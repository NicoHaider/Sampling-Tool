"""Read-only Preflight: erkennt eine Sampling-Tool-DB, OHNE sie zu verändern."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from sampling_tool.persistence.database import (
    APPLICATION_ID,
    CURRENT_SCHEMA_VERSION,
    SCHEMA_VERSION_TABLE,
)

_SQLITE_HEADER_MAGIC: Final = b"SQLite format 3\x00"

_REQUIRED_TABLES: Final = frozenset(
    {
        SCHEMA_VERSION_TABLE,
        "engagements",
        "datasets",
        "dataset_rows",
        "samples",
        "sample_rows",
        "audit_events",
        "undo_snapshots",
    }
)
_REQUIRED_TRIGGERS: Final = frozenset({"audit_events_no_update", "audit_events_no_delete"})


class PreflightRejectionReason(StrEnum):
    """Grund, warum eine Kandidaten-Datei nicht geöffnet werden darf."""

    NOT_SQLITE = "not_sqlite"
    CORRUPT = "corrupt"
    UNKNOWN_SCHEMA = "unknown_schema"
    SCHEMA_TOO_NEW = "schema_too_new"


@dataclass(frozen=True, slots=True)
class PreflightAccepted:
    """Kandidat ist eine gültige, unterstützte Sampling-Tool-DB."""

    schema_version: int


@dataclass(frozen=True, slots=True)
class PreflightRejected:
    """Kandidat ist unsicher – Snapshot/Migration dürfen NICHT starten."""

    reason: PreflightRejectionReason
    message: str  # deutsch, endnutzertauglich – direkt für s.error(...) nutzbar


PreflightResult = PreflightAccepted | PreflightRejected


def _has_sqlite_header(db_path: Path) -> bool:
    try:
        with db_path.open("rb") as f:
            header = f.read(16)
    except OSError:
        return False
    return header == _SQLITE_HEADER_MAGIC


def _identity_confirmed(conn: sqlite3.Connection) -> bool:
    row = conn.execute("PRAGMA application_id").fetchone()
    if row is not None and row[0] == APPLICATION_ID:
        return True

    master_rows = conn.execute(
        "SELECT type, name FROM sqlite_master WHERE type IN ('table', 'trigger')"
    ).fetchall()
    tables = {r["name"] for r in master_rows if r["type"] == "table"}
    triggers = {r["name"] for r in master_rows if r["type"] == "trigger"}
    return _REQUIRED_TABLES.issubset(tables) and _REQUIRED_TRIGGERS.issubset(triggers)


def _read_schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(f"SELECT MAX(version) AS v FROM {SCHEMA_VERSION_TABLE}").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row["v"]) if row["v"] is not None else 0


def preflight_check(db_path: Path) -> PreflightResult:
    """Prüft, ob `db_path` sicher snapshot- und migrierbar ist – rein lesend.

    Schreibt unter keinen Umständen auf das Kandidaten-File oder legt Sidecar-
    Dateien daneben an (kein WAL/SHM, kein `archiv/`). Erst nach erfolgreicher
    Prüfung darf der Aufrufer (Task 3) den regulären Snapshot+Migrate-Pfad
    anstoßen.
    """
    if not _has_sqlite_header(db_path):
        return PreflightRejected(
            PreflightRejectionReason.NOT_SQLITE,
            "Die ausgewählte Datei ist keine gültige Datenbank-Datei.",
        )

    # `mode=ro` allein reicht NICHT: Ist die Kandidaten-Datei WAL-mode-getaggt
    # (jede von `Database.connect()` erzeugte DB ist das dauerhaft, weil
    # `journal_mode=WAL` im Datei-Header steht), erzeugt SQLite beim bloßen
    # read-only Öffnen + Query-Ausführen trotzdem `-wal`/`-shm`-Sidecar-Dateien
    # daneben – auch wenn nichts in die Haupt-Datei geschrieben wird. Das würde
    # das "Kandidat-Verzeichnis bleibt bei Ablehnung unverändert"-Invariant
    # verletzen. `immutable=1` sagt SQLite explizit, dass die Datei nicht
    # verändert werden kann und WAL/SHM komplett zu überspringen ist – direktes
    # Lesen aus der Haupt-Datei, keine Sidecars. Empirisch verifiziert: `mode=ro`
    # allein legt `x.db-shm`/`x.db-wal` neben einer WAL-mode-Datei an,
    # `mode=ro&immutable=1` legt nichts an und liest trotzdem korrekt (inkl.
    # `PRAGMA application_id` und Tabelleninhalt). `.resolve().as_uri()` statt
    # manuellem String-Bau, weil es Leerzeichen/Sonderzeichen plattformüber-
    # greifend korrekt prozent-encoded (Default-Installpfad enthält ein
    # Leerzeichen: `~/Documents/BDO Audit Sampling/...`; Zielplattform auch
    # Windows mit Laufwerksbuchstaben-Pfaden).
    uri = f"{db_path.resolve().as_uri()}?mode=ro&immutable=1"
    conn: sqlite3.Connection | None = None
    try:
        # `connect()` selbst gehört mit in dieses try: eine TOCTOU-Lücke
        # zwischen dem Header-Read oben und hier (Datei wird währenddessen
        # gelöscht, Rechte entzogen o. Ä.) lässt `sqlite3.connect` mit
        # `sqlite3.OperationalError` (Subklasse von `DatabaseError`)
        # scheitern – auch das muss als `CORRUPT` beantwortet werden statt
        # unbehandelt durchzuschlagen.
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row

        # Kein eigenes try/except hier: ein `sqlite3.DatabaseError` (u. a.
        # `OperationalError`, z. B. "database disk image is malformed") aus
        # `quick_check` läuft absichtlich zum äußeren Handler durch – der
        # fängt jeden `DatabaseError` aus Schritt 3-5 identisch als CORRUPT ab.
        quick_check_rows = conn.execute("PRAGMA quick_check").fetchall()

        if [tuple(r) for r in quick_check_rows] != [("ok",)]:
            return PreflightRejected(
                PreflightRejectionReason.CORRUPT,
                "Die ausgewählte Datei ist beschädigt und kann nicht geöffnet werden.",
            )

        if not _identity_confirmed(conn):
            return PreflightRejected(
                PreflightRejectionReason.UNKNOWN_SCHEMA,
                "Die ausgewählte Datei enthält kein Sampling-Tool-Projekt.",
            )

        version = _read_schema_version(conn)
        if version > CURRENT_SCHEMA_VERSION:
            return PreflightRejected(
                PreflightRejectionReason.SCHEMA_TOO_NEW,
                "Diese Datei wurde mit einer neueren Version des Tools erstellt. "
                "Bitte aktualisieren Sie die App, um sie zu öffnen.",
            )

        return PreflightAccepted(schema_version=version)
    except sqlite3.DatabaseError:
        return PreflightRejected(
            PreflightRejectionReason.CORRUPT,
            "Die ausgewählte Datei ist beschädigt und kann nicht geöffnet werden.",
        )
    finally:
        if conn is not None:
            conn.close()
