"""Read-only Preflight: erkennt eine Sampling-Tool-DB, OHNE sie zu verändern.

Prüft zusätzlich (unbedingt, auch wenn `application_id` bereits matcht), ob
die Append-only-Trigger auf `audit_events` noch intakt sind – der Schutz ist
NUR anwendungsseitig, ein externer SQLite-Editor kann sie entfernen oder
entkernen (Sprint 52 / S2.7, S-004). Das ist Tamper-**Erkennung** +
Wiederherstellung, KEIN kryptografischer Manipulationsnachweis.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from sampling_tool.persistence.database import (
    APPLICATION_ID,
    AUDIT_APPEND_ONLY_TRIGGERS,
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
# Nur die NAMEN – für den Identitäts-Fallback in `_identity_confirmed`. Ob die
# Trigger-DEFINITION den Schutz tatsächlich noch durchsetzt, prüft getrennt
# `_audit_triggers_tampered` (unbedingt, siehe `preflight_check`).
_REQUIRED_TRIGGERS: Final = frozenset(AUDIT_APPEND_ONLY_TRIGGERS)

# Operation je Trigger, aus dem kanonischen Namen abgeleitet (`..._no_<op>`)
# statt hand-dupliziert – sonst könnte dieser Mapping von `AUDIT_APPEND_ONLY_
# TRIGGERS` (der SSOT) abdriften, ohne dass ein Test es bemerkt.
_TRIGGER_OPERATIONS: Final = {
    name: name.rsplit("_", 1)[-1].upper() for name in AUDIT_APPEND_ONLY_TRIGGERS
}


class PreflightRejectionReason(StrEnum):
    """Grund, warum eine Kandidaten-Datei nicht geöffnet werden darf."""

    NOT_SQLITE = "not_sqlite"
    CORRUPT = "corrupt"
    UNKNOWN_SCHEMA = "unknown_schema"
    SCHEMA_TOO_NEW = "schema_too_new"


@dataclass(frozen=True, slots=True)
class PreflightAccepted:
    """Kandidat ist eine gültige, unterstützte Sampling-Tool-DB.

    `audit_triggers_tampered` ist `True`, wenn ein Append-only-Trigger auf
    `audit_events` fehlt oder entkernt wurde (Sprint 52 / S2.7, S-004) – der
    Aufrufer öffnet trotzdem (Variante 1), warnt aber prominent und stellt
    die kanonischen Trigger wieder her.
    """

    schema_version: int
    audit_triggers_tampered: bool = False


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


def _trigger_enforces_append_only(sql: str | None, *, operation: str) -> bool:
    """Strukturelle (nicht String-exakte) Prüfung einer Trigger-Definition.

    Bewusst kein exakter Vergleich gegen `AUDIT_APPEND_ONLY_TRIGGERS` – SQLite
    garantiert keine über Versionen hinweg identische Formatierung des
    gespeicherten `CREATE TRIGGER`-Texts. Geprüft wird, ob auf den Zeitpunkt +
    Operation + Ziel-Tabelle OHNE etwas dazwischen (insbesondere KEINE
    WHEN-Klausel – ein `WHEN 0`-Guard würde den Trigger-Body nie feuern lassen,
    obwohl Name und RAISE-Text weiterhin vorhanden wären) direkt `BEGIN` folgt,
    und ob darin ein `RAISE(ABORT`-Statement mit der Append-only-Meldung
    steckt – das genügt, um einen fehlenden oder entkernten (No-Op-Body ohne
    RAISE, oder per WHEN-Guard stummgeschalteter Body) Trigger zu erkennen,
    ohne bei harmlosem Formatierungs-Drift (z. B. Leerzeichen vor der Klammer
    in `RAISE (ABORT`) falsch anzuschlagen.
    """
    if sql is None:
        return False
    normalized = " ".join(sql.split()).casefold()
    header = f"before {operation.casefold()} on audit_events"
    header_index = normalized.find(header)
    if header_index == -1:
        return False
    after_header = normalized[header_index + len(header) :].lstrip()
    if not after_header.startswith("begin"):
        return False
    return (
        re.search(r"raise\s*\(\s*abort", normalized) is not None
        and "audit_events is append-only" in normalized
    )


def _audit_triggers_tampered(conn: sqlite3.Connection) -> bool:
    """Liest die tatsächliche Trigger-DEFINITION aus `sqlite_master.sql`.

    Ein externer SQLite-Editor kann einen Append-only-Trigger entfernen oder
    entkernen und dabei den Namen unangetastet lassen – eine reine
    Namensprüfung (wie der `_identity_confirmed`-Fallback oben) würde das
    nicht bemerken. Läuft in `preflight_check` UNBEDINGT, auch wenn
    `_identity_confirmed` bereits über `application_id` bestätigt hat.
    """
    for name, operation in _TRIGGER_OPERATIONS.items():
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
            (name,),
        ).fetchone()
        sql = row[0] if row is not None else None
        if not _trigger_enforces_append_only(sql, operation=operation):
            return True
    return False


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

        # Läuft UNBEDINGT (Sprint 52 / S2.7, S-004) – auch wenn
        # `_identity_confirmed` oben bereits über `application_id` bestätigt
        # hat, ohne die Trigger überhaupt zu betrachten.
        tampered = _audit_triggers_tampered(conn)
        return PreflightAccepted(schema_version=version, audit_triggers_tampered=tampered)
    except sqlite3.DatabaseError:
        return PreflightRejected(
            PreflightRejectionReason.CORRUPT,
            "Die ausgewählte Datei ist beschädigt und kann nicht geöffnet werden.",
        )
    finally:
        if conn is not None:
            conn.close()
