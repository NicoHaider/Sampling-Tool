"""Integration: read-only Preflight-Erkennung einer Sampling-Tool-DB."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sampling_tool.persistence.database import CURRENT_SCHEMA_VERSION, Database
from sampling_tool.persistence.db_preflight import (
    PreflightAccepted,
    PreflightRejected,
    PreflightRejectionReason,
    preflight_check,
)

pytestmark = pytest.mark.integration


def _migration_sql(name: str) -> str:
    return (
        Path(__file__).resolve().parents[2]
        / "src"
        / "sampling_tool"
        / "persistence"
        / "migrations"
        / name
    ).read_text(encoding="utf-8")


def _sibling_files(path: Path) -> list[Path]:
    """Alle Dateien im selben Verzeichnis, die mit dem DB-Namen beginnen (außer ihr selbst)."""
    return sorted(p for p in path.parent.iterdir() if p != path and p.name.startswith(path.name))


class TestForeignSqliteDbRejected:
    def test_foreign_sqlite_db_rejected_and_unmodified(self, tmp_path: Path) -> None:
        db_path = tmp_path / "foreign.db"

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE unrelated (x INTEGER)")
            conn.execute("INSERT INTO unrelated (x) VALUES (1)")
            conn.commit()
        finally:
            conn.close()

        bytes_before = db_path.read_bytes()

        result = preflight_check(db_path)

        assert isinstance(result, PreflightRejected)
        assert result.reason == PreflightRejectionReason.UNKNOWN_SCHEMA

        assert db_path.read_bytes() == bytes_before
        assert _sibling_files(db_path) == []
        assert not (tmp_path / "archiv").exists()

        # sqlite_master enthält weiterhin ausschließlich die eine Fremd-Tabelle.
        verify_conn = sqlite3.connect(str(db_path))
        try:
            names = {
                r[0]
                for r in verify_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert names == {"unrelated"}
        finally:
            verify_conn.close()


class TestNonSqliteFileRejected:
    def test_non_sqlite_file_rejected(self, tmp_path: Path) -> None:
        db_path = tmp_path / "not_a_db.db"
        db_path.write_bytes(b"not a database, just text")
        bytes_before = db_path.read_bytes()

        result = preflight_check(db_path)

        assert isinstance(result, PreflightRejected)
        assert result.reason == PreflightRejectionReason.NOT_SQLITE

        assert db_path.read_bytes() == bytes_before
        assert _sibling_files(db_path) == []


class TestCorruptDbRejected:
    def test_corrupt_db_rejected(self, tmp_path: Path) -> None:
        db_path = tmp_path / "corrupt.db"

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE t (x INTEGER, y TEXT)")
            conn.executemany(
                "INSERT INTO t (x, y) VALUES (?, ?)",
                [(i, f"row-{i}" * 5) for i in range(200)],
            )
            conn.commit()
        finally:
            conn.close()

        size = db_path.stat().st_size
        db_path.write_bytes(db_path.read_bytes()[: size // 2])

        result = preflight_check(db_path)

        assert isinstance(result, PreflightRejected)
        assert result.reason == PreflightRejectionReason.CORRUPT


class TestValidCurrentDbAccepted:
    def test_valid_current_db_accepted(self, tmp_path: Path) -> None:
        db_path = tmp_path / "valid.db"
        db = Database(db_path)
        db.migrate()
        db.close()

        result = preflight_check(db_path)

        assert result == PreflightAccepted(schema_version=CURRENT_SCHEMA_VERSION)


class TestLegacyDbWithoutApplicationIdAcceptedViaSignature:
    def test_legacy_db_without_application_id_accepted_via_signature(self, tmp_path: Path) -> None:
        db_path = tmp_path / "legacy_v1.db"

        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(_migration_sql("001_initial.sql"))
        finally:
            conn.close()

        result = preflight_check(db_path)

        assert result == PreflightAccepted(schema_version=1)


class TestTooNewSchemaRejectedReadonly:
    def test_too_new_schema_rejected_readonly(self, tmp_path: Path) -> None:
        db_path = tmp_path / "too_new.db"
        db = Database(db_path)
        db.migrate()
        db.close()

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (999, CURRENT_TIMESTAMP)"
            )
            conn.commit()
        finally:
            conn.close()

        bytes_before = db_path.read_bytes()

        result = preflight_check(db_path)

        assert isinstance(result, PreflightRejected)
        assert result.reason == PreflightRejectionReason.SCHEMA_TOO_NEW

        assert db_path.read_bytes() == bytes_before
        assert _sibling_files(db_path) == []


class TestPathWithSpace:
    """Zusätzlicher Test: `as_uri()`-Percent-Encoding für Pfade mit Leerzeichen.

    Der App-Default-Installpfad enthält ein Leerzeichen
    (`~/Documents/BDO Audit Sampling/...`) – dieser Test sperrt zu, dass die
    read-only-URI-Konstruktion damit funktioniert.
    """

    def test_valid_db_in_directory_with_space_accepted(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "BDO Audit Sampling"
        target_dir.mkdir()
        db_path = target_dir / "client.db"

        db = Database(db_path)
        db.migrate()
        db.close()

        result = preflight_check(db_path)

        assert result == PreflightAccepted(schema_version=CURRENT_SCHEMA_VERSION)
