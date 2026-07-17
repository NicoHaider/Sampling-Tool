"""SQLite-Wrapper: Connection-Lifecycle, WAL-Mode, Migrations, Savepoint-Helper.

Eine `Database`-Instanz hält genau eine `sqlite3.Connection` (lazy geöffnet).
`session()` ist ein Context-Manager, der eine Transaktion öffnet und bei Erfolg
committet, bei Exception rollt zurück. Verschachtelung ist via `savepoint()`
möglich und für Repository-Methoden gedacht.

`migrate()` liest alle SQL-Dateien aus `persistence/migrations/`, sortiert nach
Versions-Präfix (`NNN_*.sql`) und führt jede neuere als die in `schema_version`
hinterlegte aus.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from sampling_tool.resources import package_resource

SCHEMA_VERSION_TABLE: Final = "schema_version"
APPLICATION_ID: Final = 0x42444F53  # "BDOS" – BDO Sampling; SQLite PRAGMA application_id
CURRENT_SCHEMA_VERSION: Final = (
    5  # muss mit jeder neuen migrations/NNN_*.sql-Datei mit hochgezogen werden
)

# ---------------------------------------------------------------------------
# Append-only-Trigger auf `audit_events` – kanonische Definition (SSOT)
#
# Der Schutz ist NUR anwendungsseitig: die beiden BEFORE-Trigger blockieren
# UPDATE/DELETE über jede sqlite3-Connection, die diese App öffnet. Die
# Projekt-`.db` liegt aber im normalen Benutzerdateisystem – ein externer
# SQLite-Editor mit Dateizugriff kann die Trigger jederzeit entfernen,
# `audit_events` ändern und die Trigger (oder entkernte No-Ops) neu anlegen
# (Sprint 52 / S2.7, S-004). `db_preflight.py` erkennt genau das anhand
# dieser Konstante (Tamper-**Erkennung**); es gibt bewusst KEINEN
# kryptografischen Manipulationsnachweis (signierte Checkpoints/Hash-Ketten
# wären dafür nötig – eigenes, hier nicht adressiertes Thema).
#
# Identisch zu migrations/001_initial.sql (dort erstmalig angelegt, seither
# von 002-005 nicht angefasst) – `TestAuditAppendOnlyTriggerCanonical` sperrt
# zu, dass diese Konstante nicht von der echten Migration abdriftet.
# ---------------------------------------------------------------------------
AUDIT_APPEND_ONLY_TRIGGERS: Final[dict[str, str]] = {
    "audit_events_no_update": (
        "CREATE TRIGGER audit_events_no_update\n"
        "BEFORE UPDATE ON audit_events\n"
        "BEGIN\n"
        "    SELECT RAISE(ABORT, 'audit_events is append-only');\n"
        "END"
    ),
    "audit_events_no_delete": (
        "CREATE TRIGGER audit_events_no_delete\n"
        "BEFORE DELETE ON audit_events\n"
        "BEGIN\n"
        "    SELECT RAISE(ABORT, 'audit_events is append-only');\n"
        "END"
    ),
}


# ---------------------------------------------------------------------------
# Datetime-Adapter / -Konverter
#
# Python 3.12+ deprecated die eingebauten naiven datetime-Adapter. Wir
# registrieren eigene, die UTC-aware speichern (ISO-8601 mit TZ) und beim
# Lesen sowohl unser ISO-Format als auch SQLites Default-Format
# ("YYYY-MM-DD HH:MM:SS", z. B. von CURRENT_TIMESTAMP) parsen.
# ---------------------------------------------------------------------------


def _adapt_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _convert_timestamp(raw: bytes) -> datetime:
    text = raw.decode()
    try:
        result = datetime.fromisoformat(text)
    except ValueError:
        # SQLite CURRENT_TIMESTAMP-Format
        result = datetime.fromisoformat(text.replace(" ", "T"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result


sqlite3.register_adapter(datetime, _adapt_datetime)
sqlite3.register_converter("TIMESTAMP", _convert_timestamp)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


class MigrationError(ValueError):
    """Schema-Zustand ist inkonsistent – `migrate()` bricht bewusst ab statt zu raten."""


def _validate_migration_sequence(applied: Sequence[int], pending: Sequence[int]) -> None:
    """Prüft Bestands- und Pending-Versionen auf Lücken/Duplikate (Sprint 45 / A-002).

    Reine, DB-/Dateisystem-freie Funktion (nur `int`-Listen) – dadurch ohne
    Fixture-Aufwand isoliert testbar. `migrate()` ruft sie mit den echten
    Werten auf, BEVOR irgendeine Migration ausgeführt wird.
    """
    applied_sorted = sorted(applied)
    if len(set(applied_sorted)) != len(applied_sorted):
        raise MigrationError(f"schema_version enthält doppelte Versionen: {applied_sorted}")

    current = applied_sorted[-1] if applied_sorted else 0

    # Zu-neu-Check VOR dem Lücken-Check (Sprint 45 / A-002, Abweichung von der
    # ursprünglich skizzierten Reihenfolge): ein Schema, dessen einzige
    # Bestandsversion weit über CURRENT_SCHEMA_VERSION liegt, ist per
    # Definition kein gapless 1..N-Verlauf – der Lücken-Check würde sonst
    # fälschlich zuerst feuern und die eigentliche Ursache ("App zu alt für
    # dieses Schema") hinter einer irreführenden Lücken-Meldung verstecken.
    if current > CURRENT_SCHEMA_VERSION:
        raise MigrationError(
            f"Schema-Version {current} ist neuer als die von dieser App unterstützte "
            f"Version {CURRENT_SCHEMA_VERSION}. Bitte die App aktualisieren."
        )

    expected_applied = list(range(1, current + 1))
    if applied_sorted != expected_applied:
        raise MigrationError(
            f"schema_version hat Lücken: erwartet {expected_applied}, gefunden {applied_sorted}"
        )

    pending_sorted = sorted(pending)
    if len(set(pending_sorted)) != len(pending_sorted):
        raise MigrationError(f"Migrations-Dateien enthalten doppelte Versionen: {pending_sorted}")

    if pending_sorted:
        expected_pending = list(range(current + 1, pending_sorted[-1] + 1))
        if pending_sorted != expected_pending:
            raise MigrationError(
                f"Migrations-Dateien haben Lücken: erwartet {expected_pending}, "
                f"gefunden {pending_sorted}"
            )


class Database:
    """Hält die SQLite-Connection und kapselt Lifecycle + Migrationen."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    # ---- Connection -----------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        """Öffnet (oder liefert die bestehende) Connection im Autocommit-Modus."""
        if self._conn is not None:
            return self._conn

        # isolation_level=None → Python öffnet keine impliziten Transaktionen.
        # Wir kontrollieren BEGIN/COMMIT/ROLLBACK selbst (siehe `session()`).
        conn = sqlite3.connect(
            str(self.db_path),
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row

        # WAL-Mode (auf :memory: ein No-Op, schadet aber nicht).
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA synchronous = NORMAL;")

        self._conn = conn
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        """Transaktion: BEGIN IMMEDIATE → COMMIT (Erfolg) bzw. ROLLBACK (Exception).

        Die Connection bleibt nach dem Block offen.
        """
        conn = self.connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")

    # ---- Migrations -----------------------------------------------------

    def schema_version(self) -> int:
        """Aktuelle Schema-Version (0, falls die Versions-Tabelle noch fehlt)."""
        conn = self.connect()
        try:
            row = conn.execute(f"SELECT MAX(version) AS v FROM {SCHEMA_VERSION_TABLE}").fetchone()
        except sqlite3.OperationalError:
            return 0
        return int(row["v"]) if row["v"] is not None else 0

    def _applied_versions(self) -> list[int]:
        """Alle in `schema_version` eingetragenen Versionen (Reihenfolge egal)."""
        conn = self.connect()
        try:
            rows = conn.execute(f"SELECT version FROM {SCHEMA_VERSION_TABLE}").fetchall()
        except sqlite3.OperationalError:
            return []
        return [int(row["version"]) for row in rows]

    def migrate(self, migrations_root: Path | None = None) -> None:
        """Wendet alle ausstehenden `NNN_*.sql`-Dateien aus `migrations/` an.

        Idempotent: bereits angewandte Versionen werden übersprungen. Jede
        Migration läuft in ihrer eigenen Transaktion (Sprint 45 / A-002) –
        schlägt eine fehl, wird NUR sie zurückgerollt (`schema_version`
        bleibt auf dem letzten erfolgreichen Stand), und die Exception
        propagiert unverändert (kein stilles Weiterlaufen zur nächsten
        Migration). Jedes Migrations-Skript ist selbst dafür verantwortlich,
        seinen Eintrag in `schema_version` zu setzen – der liegt jetzt
        innerhalb derselben Transaktion wie die DDL und ist damit atomar
        mit ihr.

        `migrations_root` ist nur für Tests gedacht (Default: das echte
        `persistence/migrations`-Verzeichnis im Paket).
        """
        conn = self.connect()
        applied = self._applied_versions()
        current = max(applied) if applied else 0

        root = (
            migrations_root
            if migrations_root is not None
            else package_resource("persistence/migrations")
        )
        pending: list[tuple[int, str]] = []
        for entry in root.iterdir():
            if not entry.name.endswith(".sql"):
                continue
            try:
                version = int(entry.name.split("_", 1)[0])
            except ValueError:
                continue
            if version > current:
                pending.append((version, entry.read_text(encoding="utf-8")))

        pending.sort(key=lambda item: item[0])
        _validate_migration_sequence(applied, [version for version, _ in pending])

        for _version, sql in pending:
            # `executescript` committet implizit und darf daher nicht in einer
            # bereits offenen Transaktion laufen (mit isolation_level=None ist
            # das ok) – die Transaktionsklammer kommt hier stattdessen explizit
            # aus dem Skript-Text selbst, damit DDL + der `schema_version`-
            # Insert atomar sind (Sprint 45 / A-002).
            wrapped_sql = f"BEGIN;\n{sql}\nCOMMIT;"
            try:
                conn.executescript(wrapped_sql)
            except Exception:
                conn.execute("ROLLBACK")
                raise

    # ---- Lifecycle ------------------------------------------------------

    def close(self) -> None:
        """Schließt die Connection (idempotent)."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# ---------------------------------------------------------------------------
# Savepoint-Helper – verschachtelbare Mini-Transaktion für Repository-Methoden.
# Funktioniert sowohl standalone als auch innerhalb einer äußeren `session()`.
# ---------------------------------------------------------------------------


@contextmanager
def savepoint(conn: sqlite3.Connection, name: str = "sp") -> Iterator[None]:
    """SQLite-SAVEPOINT als Context-Manager.

    Im Erfolgsfall RELEASE, bei Exception ROLLBACK TO + RELEASE.
    """
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
        conn.execute(f"RELEASE SAVEPOINT {name}")
        raise
    else:
        conn.execute(f"RELEASE SAVEPOINT {name}")


# ---------------------------------------------------------------------------
# Append-only-Trigger-Wiederherstellung (Sprint 52 / S2.7, S-004)
# ---------------------------------------------------------------------------


def restore_audit_append_only_triggers(conn: sqlite3.Connection) -> None:
    """Legt die kanonischen Append-only-Trigger neu an (DROP + CREATE, atomar).

    Wird vom Öffnen-Flow gerufen, wenn der Preflight eine entfernte oder
    entkernte Trigger-Definition erkannt hat (Abweichung von
    `AUDIT_APPEND_ONLY_TRIGGERS`) – stellt NUR den Schutzmechanismus wieder
    her, `audit_events`-Zeilen werden dabei nicht angefasst. Bereits vor der
    Wiederherstellung vorgenommene Änderungen lassen sich ohne
    kryptografischen Nachweis nicht rekonstruieren; ab hier greift der
    Append-only-Schutz für die weitere Arbeit wieder.

    Läuft über `savepoint()` (nicht `executescript` + eigenem BEGIN/COMMIT wie
    `migrate()`) – `executescript` committet vor seinem eigenen Skript implizit
    jede bereits offene Transaktion des Aufrufers, was hier nicht sein darf:
    diese Funktion soll ausschließlich den Trigger-Schutz reparieren, nie
    nebenbei ausstehende, vom Aufrufer noch nicht bestätigte Schreibvorgänge
    committen.
    """
    with savepoint(conn, name="restore_audit_triggers"):
        for name, create_sql in AUDIT_APPEND_ONLY_TRIGGERS.items():
            conn.execute(f"DROP TRIGGER IF EXISTS {name}")
            conn.execute(create_sql)


# ---------------------------------------------------------------------------
# Bulk-Insert-Pragmas (Sprint 10.3)
#
# Werkzeug für ISOLIERTE Bulk-Operationen, bei denen der Caller die
# Connection-Topologie kontrolliert. Setzt `synchronous=OFF` für die
# Dauer des Blocks und restored den Vor-Zustand im finally.
#
# Wird AKTUELL NICHT aus dem Production-Pfad aufgerufen: im Sprint-
# 10.3-Tooltest hat selbst ein einfacher Pragma-Wechsel innerhalb der
# `DatasetRepo.create`-Transaktion mit der parallel offenen
# MainController-Repo-Connection deadlockt (zwei Connections auf
# derselben WAL-DB). Der CM bleibt im Code als Werkzeug für offline-
# Bulk-Importe und ggf. spätere Architektur-Refactors verfügbar.
# ---------------------------------------------------------------------------


@contextmanager
def bulk_insert_pragmas(conn: sqlite3.Connection) -> Iterator[None]:
    """Temporäres `synchronous=OFF` für isolierte Bulk-Inserts.

    Nur sinnvoll, wenn auf der DB-Datei keine zweite Connection parallel
    aktiv ist – sonst kann der Pragma-Wechsel mit dem WAL-Locking
    deadlocken. Crash-Sicherheit muss der Caller über eine umliegende
    Transaktion herstellen.
    """
    prev_sync = conn.execute("PRAGMA synchronous").fetchall()[0][0]
    try:
        conn.execute("PRAGMA synchronous=OFF").fetchall()
        yield
    finally:
        # Restore darf den Hauptpfad nie crashen – defensiv via `suppress`.
        with suppress(sqlite3.Error):
            conn.execute(f"PRAGMA synchronous={int(prev_sync)}").fetchall()
