"""Auto-Snapshots einer Engagement-Datei.

Bei jedem Öffnen einer bestehenden Engagement-DB legt der Controller eine
Sicherheitskopie unter `<mandant>/archiv/` ab. Die SQLite-Backup-API führt
dabei auch committete, noch nicht gecheckpointete WAL-Inhalte in eine
eigenständige Snapshot-DB zusammen; Sidecar-Dateien werden nicht archiviert.

Compliance-Hintergrund: ISAE-3402 verlangt einen nachvollziehbaren
Versionsstand. Da SQLite nicht atomar versioniert, snapshoten wir pro
Session beim Öffnen (Konzept A) – das deckt den Fall „alter Stand vor
versehentlichen Änderungen" ab und bleibt trotzdem minimal-invasiv.

Sprint 88: Jeder neue Snapshot trägt seinen Grund im Namen (`+oeffnen`,
`+vor-migration`, `+vor-ueberschreiben`). Beim Öffnen entsteht nur dann eine
Kopie, wenn sich der Stand seit der jüngsten geändert hat
(`latest_snapshot_if_unchanged`), und über die Aufbewahrungsgrenze hinaus
wandern ältere „öffnen"-Kopien in den Papierkorb
(`trash_surplus_open_snapshots`). Kopien ohne Grund (vor Sprint 88) werden nie
automatisch entfernt. Nichts wird hier endgültig gelöscht – außer der eigenen,
unvollständigen Reservierung eines gescheiterten Snapshots.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import sqlite3
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Final

from sampling_tool.config import ARCHIVE_DIR_NAME, sanitize_for_path

logger = logging.getLogger(__name__)


class SnapshotReason(StrEnum):
    """Warum ein Snapshot angelegt wurde – steht als Token im Dateinamen."""

    OPEN = "oeffnen"
    PRE_MIGRATION = "vor-migration"
    PRE_OVERWRITE = "vor-ueberschreiben"


#: Trennt den Grund vom Auditor-Token. `sanitize_for_path` erzeugt nur
#: Alphanumerik, `_` und `-` – ein `+` kann also nie Teil eines Auditor-Namens
#: sein, und eine Altkopie ohne Grund wird nie als „öffnen"-Kopie gelesen.
_REASON_MARKER: Final[str] = "+"

#: Audit-Events über die Sicherung selbst. Sie ändern den Projektinhalt nicht
#: und zählen deshalb beim Vergleich mit der jüngsten Kopie nicht mit – sonst
#: wäre jedes Öffnen nach einer Sicherung eine „Änderung".
SNAPSHOT_EVENT_TYPES: Final[tuple[str, ...]] = ("backup_created", "backups_trashed")


@dataclass(frozen=True, slots=True)
class SnapshotInfo:
    """Metadaten zu einem Snapshot. `auditor_name` wird aus dem Dateinamen
    extrahiert – im Zweifel leer."""

    path: Path
    timestamp: datetime
    auditor_name: str
    size_bytes: int
    #: `None` bei Kopien aus der Zeit vor Sprint 88 – Grund nicht feststellbar.
    reason: SnapshotReason | None = None


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

    def create_snapshot(self, auditor_name: str, reason: SnapshotReason | None = None) -> Path:
        """Sichert die aktive `.db` konsistent mit Timestamp + Auditor-Tag.

        Dateiname: `{stem}_{YYYY-MM-DD}_{HH-MM-SS-ffffff}_`
        `{AuditorSanitized}[+{grund}][~{counter}].db`; ohne `reason` entsteht
        der Name wie vor Sprint 88 (wird nie automatisch aufgeräumt). Der
        optionale Kollisionszähler
        beginnt bei 2 und steht mit einem eindeutigen Marker am Ende. Die
        SQLite-Backup-API nimmt alle committeten WAL-Inhalte in die einzelne,
        konsistente Snapshot-DB auf; WAL-/SHM-Sidecars selbst werden nicht
        kopiert. Danach wird der Snapshot bestmöglich auf read-only (0o444)
        gesetzt.
        """
        if not self.engagement_db_path.exists():
            raise FileNotFoundError(f"Engagement-DB existiert nicht: {self.engagement_db_path}")

        timestamp = datetime.now()
        target, reserved_descriptor = _reserve_snapshot_target(
            archive_dir=self.archive_dir,
            stem=self.engagement_db_path.stem,
            timestamp=timestamp,
            auditor_name=auditor_name,
            suffix=self.engagement_db_path.suffix,
            reason=reason,
        )

        source: sqlite3.Connection | None = None
        destination: sqlite3.Connection | None = None
        reserved_identity: os.stat_result | None = None
        completed = False
        try:
            reserved_identity = os.fstat(reserved_descriptor)
            _verify_reserved_target(target, reserved_descriptor)
            destination = sqlite3.connect(str(target))
            _verify_reserved_target(target, reserved_descriptor)

            source_identity = self.engagement_db_path.stat()
            source = sqlite3.connect(str(self.engagement_db_path))
            current_source_identity = self.engagement_db_path.stat()
            source_was_replaced = not os.path.samestat(
                source_identity,
                current_source_identity,
            ) or (source_identity.st_size > 0 and current_source_identity.st_size == 0)
            if source_was_replaced:
                source.close()
                source = None
                if current_source_identity.st_size == 0:
                    _unlink_reserved_target(
                        self.engagement_db_path,
                        current_source_identity,
                    )
                raise sqlite3.OperationalError(
                    f"Engagement-DB wurde während des Öffnens ersetzt: {self.engagement_db_path}"
                )
            source.execute("PRAGMA query_only = ON")
            source.backup(destination)

            source.close()
            source = None
            destination.close()
            destination = None

            _verify_reserved_target(target, reserved_descriptor)
            _chmod_reserved_target_readonly(reserved_descriptor)
            _verify_reserved_target(target, reserved_descriptor)
            completed = True
        finally:
            if source is not None:
                with contextlib.suppress(sqlite3.Error):
                    source.close()
            if destination is not None:
                with contextlib.suppress(sqlite3.Error):
                    destination.close()
            if reserved_identity is None:
                with contextlib.suppress(OSError):
                    reserved_identity = os.fstat(reserved_descriptor)
            remove_incomplete = (
                not completed
                and reserved_identity is not None
                and _target_matches_identity(target, reserved_identity)
            )
            with contextlib.suppress(OSError):
                os.close(reserved_descriptor)
            if remove_incomplete and reserved_identity is not None:
                _unlink_reserved_target(target, reserved_identity)

        return target

    def list_snapshots(self) -> list[SnapshotInfo]:
        """Listet alle Snapshots im `archiv/`-Ordner, neueste zuerst."""
        archive = self.engagement_db_path.parent / ARCHIVE_DIR_NAME
        if not archive.exists():
            return []
        indexed_infos: list[tuple[SnapshotInfo, int]] = []
        for entry in archive.iterdir():
            if entry.suffix.lower() != ".db":
                continue
            try:
                entry_stat = entry.lstat()
            except OSError:
                continue
            if not stat.S_ISREG(entry_stat.st_mode):
                continue
            parsed = _parse_snapshot_components(
                entry.name,
                expected_stem=self.engagement_db_path.stem,
            )
            if parsed is None:
                continue
            timestamp, auditor, collision_counter, reason = parsed
            indexed_infos.append(
                (
                    SnapshotInfo(
                        path=entry,
                        timestamp=timestamp,
                        auditor_name=auditor,
                        size_bytes=entry_stat.st_size,
                        reason=reason,
                    ),
                    collision_counter,
                )
            )
        indexed_infos.sort(
            key=lambda item: (item[0].timestamp, item[1], item[0].path.name),
            reverse=True,
        )
        return [info for info, _counter in indexed_infos]

    def latest_snapshot_if_unchanged(self) -> Path | None:
        """Jüngste Kopie, falls sich das Projekt seitdem nicht geändert hat.

        Verglichen werden Schema-Version, `max(audit_events.id)` (ohne die
        Sicherungs-Events, `SNAPSHOT_EVENT_TYPES`) und die Engagement-Zeile.
        Jede inhaltliche Änderung der App schreibt ein Audit-Event.

        Beide Seiten werden nur lesend geöffnet. Die Kopie mit `immutable`
        (legt nichts im Archiv an). Das Original ebenso – außer ein nicht
        leerer WAL liegt daneben (App offen oder nicht sauber beendet): dann
        `mode=ro` ohne `immutable`, damit neue Events im WAL mitzählen. Ein
        read-only-Zugriff schreibt weder `.db` noch `-wal` und checkpointet
        nicht; höchstens der `-shm`-Index entsteht, wie beim folgenden Öffnen
        ohnehin.

        `None` heißt „neu sichern": keine Kopie, Änderung, oder eine Seite
        nicht lesbar bzw. ohne `audit_events` (im Zweifel sichern). Kopien
        „vor Überschreiben" sind kein Vergleichsstand – sie sichern das
        VORHERIGE Projekt am selben Pfad.
        """
        baseline = next(
            (
                info
                for info in self.list_snapshots()
                if info.reason is not SnapshotReason.PRE_OVERWRITE
            ),
            None,
        )
        if baseline is None:
            return None
        current = _read_content_state(
            self.engagement_db_path, through_wal=_has_pending_wal(self.engagement_db_path)
        )
        if current is None:
            return None
        saved = _read_content_state(baseline.path, through_wal=False)
        if saved is None or saved != current:
            return None
        return baseline.path

    def trash_surplus_open_snapshots(self, keep: int, trash: Callable[[Path], bool]) -> list[Path]:
        """Verschiebt „öffnen"-Kopien über die jüngsten `keep` hinaus in den Papierkorb.

        Nur Kopien mit Grund „öffnen" und dem Stem DIESES Projekts; „vor
        Migration", „vor Überschreiben" und Altkopien ohne Grund bleiben immer.
        `trash` verschiebt eine Datei in den Papierkorb und meldet Erfolg (die
        UI reicht `QFile.moveToTrash` herein; Tests eine Attrappe). Kopien sind
        read-only – vor dem Verschieben wird das zurückgenommen, damit kein
        Papierkorb nachfragt oder ablehnt; scheitert es, wird es wieder
        gesetzt, die Kopie bleibt liegen und es gibt eine Warnung. Nie ein
        Fallback auf Löschen. Liefert die verschobenen Pfade, älteste zuletzt.
        """
        if keep < 1:
            raise ValueError("Es muss mindestens 1 Sicherung behalten werden.")
        opens = [info for info in self.list_snapshots() if info.reason is SnapshotReason.OPEN]
        trashed: list[Path] = []
        for info in opens[keep:]:
            if _move_to_trash(info.path, trash):
                trashed.append(info.path)
        return trashed

    def restore_from_snapshot(self, snapshot_path: Path) -> Path:
        """Kopiert einen Snapshot zurück über die aktive `.db`. Aktuell
        nicht aus der UI heraus aufgerufen – wird in einer späteren
        Sprint-Version freigeschaltet (Restore-Dialog).

        Der Aufrufer muss eine aktive Connection auf dem Ziel vorher schließen.
        Erst dann entfernt der Helper stale WAL-/SHM-Sidecars, damit SQLite sie
        nicht gegen den wiederhergestellten Stand abspielt.
        """
        if not snapshot_path.exists():
            raise FileNotFoundError(f"Snapshot existiert nicht: {snapshot_path}")
        # Ziel ggf. beschreibbar machen, falls es ein alter (read-only)
        # Snapshot ist; Windows behandelt das sonst als Permission-Denied.
        if self.engagement_db_path.exists():
            with contextlib.suppress(OSError):  # pragma: no cover
                self.engagement_db_path.chmod(0o644)
        for sidecar_suffix in ("-wal", "-shm"):
            sidecar = self.engagement_db_path.with_name(
                f"{self.engagement_db_path.name}{sidecar_suffix}"
            )
            with contextlib.suppress(FileNotFoundError):
                sidecar.unlink()
        shutil.copy2(snapshot_path, self.engagement_db_path)
        with contextlib.suppress(OSError):  # pragma: no cover
            self.engagement_db_path.chmod(0o644)
        return self.engagement_db_path


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------


def _build_snapshot_name(
    *,
    stem: str,
    timestamp: datetime,
    auditor_name: str,
    suffix: str,
    collision_counter: int = 1,
    reason: SnapshotReason | None = None,
) -> str:
    date_part = timestamp.strftime("%Y-%m-%d")
    time_part = timestamp.strftime("%H-%M-%S-%f")
    auditor_token = sanitize_for_path(auditor_name) if auditor_name else "system"
    reason_token = f"{_REASON_MARKER}{reason.value}" if reason is not None else ""
    counter_token = f"~{collision_counter}" if collision_counter >= 2 else ""
    return f"{stem}_{date_part}_{time_part}_{auditor_token}{reason_token}{counter_token}{suffix}"


def _parse_snapshot_name(filename: str) -> tuple[datetime, str] | None:
    """Liest alte Sekunden- und neue Mikrosekunden-Snapshot-Namen.

    Auditor-Tokens können wiederum Underscores enthalten (z. B. aus der
    Sanitisierung von „Anna Auditorin" → `Anna_Auditorin`). Deshalb suchen
    wir nach der Zeitmarke und nehmen alles danach als Auditor-Token. Ein
    neuer Kollisionszähler steht mit dem eindeutigen Marker `~` am Ende.
    """
    parsed = _parse_snapshot_components(filename)
    if parsed is None:
        return None
    timestamp, auditor, _collision_counter, _reason = parsed
    return timestamp, auditor


def _parse_snapshot_components(
    filename: str,
    *,
    expected_stem: str | None = None,
) -> tuple[datetime, str, int, SnapshotReason | None] | None:
    """Liest Timestamp, Auditor, Kollisionszähler und Grund eines Snapshot-Namens."""
    if not filename.endswith(".db"):
        return None
    stem = filename[: -len(".db")]
    if expected_stem is not None:
        return _parse_managed_snapshot_stem(stem, expected_stem)

    parts = stem.split("_")
    for i in range(len(parts) - 1):
        date_part, time_part = parts[i], parts[i + 1]
        timestamp = _parse_snapshot_timestamp(date_part, time_part)
        if timestamp is None:
            continue
        parsed_auditor = _parse_auditor_and_counter("_".join(parts[i + 2 :]))
        if parsed_auditor is None:
            return None
        return (timestamp, *parsed_auditor)
    return None


def _parse_managed_snapshot_stem(
    snapshot_stem: str,
    expected_stem: str,
) -> tuple[datetime, str, int, SnapshotReason | None] | None:
    """Parst nur Namen mit dem exakten verwalteten DB-Stem als Präfix."""
    prefix = f"{expected_stem}_"
    if not snapshot_stem.startswith(prefix):
        return None
    snapshot_parts = snapshot_stem[len(prefix) :].split("_")
    if len(snapshot_parts) < 3:
        return None
    timestamp = _parse_snapshot_timestamp(snapshot_parts[0], snapshot_parts[1])
    if timestamp is None:
        return None
    parsed_auditor = _parse_auditor_and_counter("_".join(snapshot_parts[2:]))
    if parsed_auditor is None:
        return None
    return (timestamp, *parsed_auditor)


def _parse_auditor_and_counter(
    auditor_token: str,
) -> tuple[str, int, SnapshotReason | None] | None:
    """Trennt `~<counter>` und `+<grund>` vom sanitisierten Auditor-Token."""
    counter = 1
    if "~" in auditor_token:
        auditor_token, separator, counter_token = auditor_token.rpartition("~")
        if (
            separator != "~"
            or not auditor_token
            or "~" in auditor_token
            or not counter_token.isdigit()
            or int(counter_token) < 2
        ):
            return None
        counter = int(counter_token)
    reason: SnapshotReason | None = None
    if _REASON_MARKER in auditor_token:
        auditor_token, _marker, reason_token = auditor_token.partition(_REASON_MARKER)
        try:
            reason = SnapshotReason(reason_token)
        except ValueError:
            return None
    if not auditor_token:
        return None
    return auditor_token, counter, reason


def _parse_snapshot_timestamp(
    date_part: str,
    time_part: str,
) -> datetime | None:
    """Parst die Sekunden- oder Mikrosekunden-Zeitmarke eines Snapshots."""
    try:
        return datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H-%M-%S-%f")
    except ValueError:
        try:
            return datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H-%M-%S")
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# Vergleich + Papierkorb (Sprint 88)
# ---------------------------------------------------------------------------

_ContentState = tuple[int, int | None, tuple[tuple[object, ...], ...]]


def _has_pending_wal(db_path: Path) -> bool:
    wal = db_path.with_name(f"{db_path.name}-wal")
    try:
        return wal.stat().st_size > 0
    except OSError:
        return False


def _read_content_state(db_path: Path, *, through_wal: bool) -> _ContentState | None:
    """(Schema-Version, jüngste inhaltliche Event-ID, Engagement-Zeilen) – nur lesend.

    `None`, wenn die Datei nicht lesbar ist oder `audit_events` fehlt.
    """
    mode = "mode=ro" if through_wal else "mode=ro&immutable=1"
    try:
        conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?{mode}", uri=True)
    except (sqlite3.Error, OSError):
        return None
    try:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if not {"audit_events", "schema_version", "engagements"} <= tables:
            return None
        schema = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        placeholders = ", ".join("?" for _ in SNAPSHOT_EVENT_TYPES)
        last_event = conn.execute(
            f"SELECT MAX(id) FROM audit_events WHERE event_type NOT IN ({placeholders})",
            SNAPSHOT_EVENT_TYPES,
        ).fetchone()[0]
        engagements = tuple(
            tuple(row) for row in conn.execute("SELECT * FROM engagements ORDER BY id")
        )
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return int(schema or 0), None if last_event is None else int(last_event), engagements


def _move_to_trash(path: Path, trash: Callable[[Path], bool]) -> bool:
    """Eine Kopie in den Papierkorb – bei Fehlschlag bleibt sie read-only liegen."""
    try:
        path.chmod(0o644)
    except OSError:
        logger.warning("Could not make %s writable before trashing", path.name, exc_info=True)
    try:
        moved = trash(path)
    except Exception:
        logger.warning("Could not move snapshot %s to trash", path.name, exc_info=True)
        moved = False
    else:
        if not moved:
            logger.warning("Could not move snapshot %s to trash (refused)", path.name)
    if not moved:
        with contextlib.suppress(OSError):
            path.chmod(0o444)
    return moved


def _reserve_snapshot_target(
    *,
    archive_dir: Path,
    stem: str,
    timestamp: datetime,
    auditor_name: str,
    suffix: str,
    reason: SnapshotReason | None = None,
) -> tuple[Path, int]:
    """Reserviert atomar einen regulären, noch nicht vorhandenen Zielpfad."""
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    flags |= getattr(os, "O_NOFOLLOW", 0)
    counter = 1
    while True:
        target = archive_dir / _build_snapshot_name(
            stem=stem,
            timestamp=timestamp,
            auditor_name=auditor_name,
            suffix=suffix,
            collision_counter=counter,
            reason=reason,
        )
        try:
            os.lstat(target)
        except FileNotFoundError:
            pass
        else:
            counter += 1
            continue
        try:
            descriptor = os.open(target, flags, 0o600)
        except FileExistsError:
            counter += 1
            continue
        try:
            _verify_reserved_target(target, descriptor)
        except BaseException:
            try:
                reserved_identity = os.fstat(descriptor)
            except OSError:
                reserved_identity = None
            with contextlib.suppress(OSError):
                os.close(descriptor)
            if reserved_identity is not None:
                _unlink_reserved_target(target, reserved_identity)
            raise
        return target, descriptor


def _verify_reserved_target(target: Path, descriptor: int) -> None:
    """Prüft, dass Pfad und Descriptor dieselbe reguläre Datei bezeichnen."""
    descriptor_stat = os.fstat(descriptor)
    target_stat = os.lstat(target)
    if (
        not stat.S_ISREG(descriptor_stat.st_mode)
        or not stat.S_ISREG(target_stat.st_mode)
        or not os.path.samestat(descriptor_stat, target_stat)
    ):
        raise OSError(f"Snapshot-Ziel wurde während der Reservierung ersetzt: {target}")


def _target_matches_identity(target: Path, reserved_identity: os.stat_result) -> bool:
    """Prüft per `lstat`, ob der Pfad noch die reservierte reguläre Datei ist."""
    try:
        target_stat = os.lstat(target)
    except OSError:
        return False
    return stat.S_ISREG(target_stat.st_mode) and os.path.samestat(
        reserved_identity,
        target_stat,
    )


def _unlink_reserved_target(target: Path, reserved_identity: os.stat_result) -> None:
    """Entfernt nur das weiterhin von der Reservierungsidentität bezeichnete Ziel."""
    if not _target_matches_identity(target, reserved_identity):
        return
    with contextlib.suppress(OSError):
        target.unlink()


def _chmod_reserved_target_readonly(descriptor: int) -> None:
    """Setzt read-only nur descriptorbasiert, damit kein Ersatzpfad verfolgt wird."""
    fchmod = getattr(os, "fchmod", None)
    if fchmod is None:  # pragma: no cover - auf Plattformen ohne sichere fd-Variante
        return
    with contextlib.suppress(OSError):  # pragma: no cover - manche FS lehnen chmod ab
        fchmod(descriptor, 0o444)
