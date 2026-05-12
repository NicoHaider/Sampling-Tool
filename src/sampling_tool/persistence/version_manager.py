"""Auto-Snapshots einer Engagement-Datei.

Bei jedem Öffnen einer bestehenden Engagement-DB legt der Controller eine
Sicherheitskopie unter `<mandant>/archiv/` ab. Der Snapshot ist ein
roher `shutil.copy2`-Klon der `.db`-Datei – ohne `.db-wal`/`.db-shm`,
weil das nur Hilfsdateien einer laufenden Session sind.

Compliance-Hintergrund: ISAE-3402 verlangt einen nachvollziehbaren
Versionsstand. Da SQLite nicht atomar versioniert, snapshoten wir pro
Session beim Öffnen (Konzept A) – das deckt den Fall „alter Stand vor
versehentlichen Änderungen" ab und bleibt trotzdem minimal-invasiv.
"""

from __future__ import annotations

import contextlib
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sampling_tool.config import ARCHIVE_DIR_NAME, sanitize_for_path


@dataclass(frozen=True, slots=True)
class SnapshotInfo:
    """Metadaten zu einem Snapshot. `auditor_name` wird aus dem Dateinamen
    extrahiert – im Zweifel leer."""

    path: Path
    timestamp: datetime
    auditor_name: str
    size_bytes: int


class EngagementVersionManager:
    """Verwaltet Snapshots einer Engagement-`.db` unter `archiv/`."""

    def __init__(self, engagement_db_path: Path) -> None:
        self.engagement_db_path = engagement_db_path

    # ---- Public API -----------------------------------------------------

    @property
    def archive_dir(self) -> Path:
        """Pfad zum `archiv/`-Unterordner (wird bei Bedarf erzeugt)."""
        path = self.engagement_db_path.parent / ARCHIVE_DIR_NAME
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create_snapshot(self, auditor_name: str) -> Path:
        """Kopiert die aktive `.db` nach `archiv/` mit Timestamp + Auditor-Tag.

        Dateiname: `{stem}_{YYYY-MM-DD}_{HH-MM-SS}_{AuditorSanitized}.db`.
        Sekundengenau, damit mehrere Snapshots pro Tag/Minute kollisionsfrei sind.
        WAL-/SHM-Hilfsdateien werden bewusst NICHT mitkopiert. Nach der
        Kopie wird die Snapshot-Datei auf read-only gesetzt (0o444), damit
        sie nicht versehentlich überschrieben wird – Windows mappt das nur
        grob auf das Read-Only-Attribut, aber besser als gar nichts.
        """
        if not self.engagement_db_path.exists():
            raise FileNotFoundError(f"Engagement-DB existiert nicht: {self.engagement_db_path}")

        timestamp = datetime.now()
        snapshot_name = _build_snapshot_name(
            stem=self.engagement_db_path.stem,
            timestamp=timestamp,
            auditor_name=auditor_name,
            suffix=self.engagement_db_path.suffix,
        )
        target = self.archive_dir / snapshot_name
        shutil.copy2(self.engagement_db_path, target)
        with contextlib.suppress(OSError):  # pragma: no cover – manche FS lehnen chmod ab
            target.chmod(0o444)
        return target

    def list_snapshots(self) -> list[SnapshotInfo]:
        """Listet alle Snapshots im `archiv/`-Ordner, neueste zuerst."""
        archive = self.engagement_db_path.parent / ARCHIVE_DIR_NAME
        if not archive.exists():
            return []
        infos: list[SnapshotInfo] = []
        for entry in archive.iterdir():
            if not entry.is_file() or entry.suffix.lower() != ".db":
                continue
            parsed = _parse_snapshot_name(entry.name)
            if parsed is None:
                continue
            timestamp, auditor = parsed
            infos.append(
                SnapshotInfo(
                    path=entry,
                    timestamp=timestamp,
                    auditor_name=auditor,
                    size_bytes=entry.stat().st_size,
                )
            )
        infos.sort(key=lambda i: i.timestamp, reverse=True)
        return infos

    def restore_from_snapshot(self, snapshot_path: Path) -> Path:
        """Kopiert einen Snapshot zurück über die aktive `.db`. Aktuell
        nicht aus der UI heraus aufgerufen – wird in einer späteren
        Sprint-Version freigeschaltet (Restore-Dialog)."""
        if not snapshot_path.exists():
            raise FileNotFoundError(f"Snapshot existiert nicht: {snapshot_path}")
        # Ziel ggf. beschreibbar machen, falls es ein alter (read-only)
        # Snapshot ist; Windows behandelt das sonst als Permission-Denied.
        if self.engagement_db_path.exists():
            with contextlib.suppress(OSError):  # pragma: no cover
                self.engagement_db_path.chmod(0o644)
        shutil.copy2(snapshot_path, self.engagement_db_path)
        with contextlib.suppress(OSError):  # pragma: no cover
            self.engagement_db_path.chmod(0o644)
        return self.engagement_db_path


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------


def _build_snapshot_name(*, stem: str, timestamp: datetime, auditor_name: str, suffix: str) -> str:
    date_part = timestamp.strftime("%Y-%m-%d")
    time_part = timestamp.strftime("%H-%M-%S")
    auditor_token = sanitize_for_path(auditor_name) if auditor_name else "system"
    return f"{stem}_{date_part}_{time_part}_{auditor_token}{suffix}"


def _parse_snapshot_name(filename: str) -> tuple[datetime, str] | None:
    """Versucht `<stem>_YYYY-MM-DD_HH-MM-SS_<auditor>.db` zurückzulesen.

    Auditor-Tokens können wiederum Underscores enthalten (z. B. aus der
    Sanitisierung von „Anna Auditorin" → `Anna_Auditorin`). Deshalb suchen
    wir nach der `YYYY-MM-DD_HH-MM-SS`-Marke und nehmen alles davor als
    Stem, alles danach als Auditor.
    """
    if not filename.endswith(".db"):
        return None
    stem = filename[: -len(".db")]
    parts = stem.split("_")
    for i in range(len(parts) - 1):
        date_part, time_part = parts[i], parts[i + 1]
        try:
            timestamp = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H-%M-%S")
        except ValueError:
            continue
        auditor = "_".join(parts[i + 2 :])
        return timestamp, auditor
    return None
