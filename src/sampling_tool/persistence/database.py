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
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Final

MIGRATIONS_PACKAGE: Final = "sampling_tool.persistence.migrations"
SCHEMA_VERSION_TABLE: Final = "schema_version"


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

    def migrate(self) -> None:
        """Wendet alle ausstehenden `NNN_*.sql`-Dateien aus `migrations/` an.

        Idempotent: bereits angewandte Versionen werden übersprungen.
        Jedes Migrations-Skript ist selbst dafür verantwortlich, einen Eintrag
        in `schema_version` zu setzen.
        """
        conn = self.connect()
        current = self.schema_version()

        migrations_root = files(MIGRATIONS_PACKAGE)
        pending: list[tuple[int, str]] = []
        for entry in migrations_root.iterdir():
            if not entry.name.endswith(".sql"):
                continue
            try:
                version = int(entry.name.split("_", 1)[0])
            except ValueError:
                continue
            if version > current:
                pending.append((version, entry.read_text(encoding="utf-8")))

        for _version, sql in sorted(pending, key=lambda v: v[0]):
            # executescript committet implizit – darf nicht innerhalb einer
            # offenen Transaktion laufen. Mit isolation_level=None ist das ok.
            conn.executescript(sql)

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
