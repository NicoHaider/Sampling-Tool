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


class TestAuditTriggerTamperDetection:
    """Sprint 52 / S2.7 (S-004): der Preflight bestätigte eine DB bisher nur
    über `application_id`/Trigger-NAMEN – ein entfernter oder entkernter
    Append-only-Trigger auf `audit_events` wurde akzeptiert, weil niemand
    `sqlite_master.sql` (die tatsächliche Trigger-Definition) gelesen hat.
    Der neue strukturelle Check läuft unbedingt, auch wenn `application_id`
    bereits matcht."""

    def test_preflight_detects_dropped_audit_trigger(self, tmp_path: Path) -> None:
        db_path = tmp_path / "dropped_trigger.db"
        db = Database(db_path)
        db.migrate()
        db.connect().execute("DROP TRIGGER audit_events_no_update")
        db.close()

        result = preflight_check(db_path)

        assert isinstance(result, PreflightAccepted)
        assert result.audit_triggers_tampered is True

    def test_preflight_detects_neutered_audit_trigger(self, tmp_path: Path) -> None:
        db_path = tmp_path / "neutered_trigger.db"
        db = Database(db_path)
        db.migrate()
        conn = db.connect()
        conn.execute("DROP TRIGGER audit_events_no_delete")
        conn.executescript(
            "CREATE TRIGGER audit_events_no_delete "
            "BEFORE DELETE ON audit_events "
            "BEGIN SELECT 1; END;"
        )
        db.close()

        result = preflight_check(db_path)

        assert isinstance(result, PreflightAccepted)
        assert result.audit_triggers_tampered is True

    def test_preflight_accepts_pristine_triggers(self, tmp_path: Path) -> None:
        db_path = tmp_path / "pristine.db"
        db = Database(db_path)
        db.migrate()
        db.close()

        result = preflight_check(db_path)

        assert isinstance(result, PreflightAccepted)
        assert result.audit_triggers_tampered is False

    def test_preflight_detects_when_clause_neutered_trigger(self, tmp_path: Path) -> None:
        """Review-Nachbesserung: ein `WHEN 0`-Guard lässt den RAISE(ABORT-Body
        nie feuern, enthält aber weiterhin alle drei geprüften Substrings
        ('before update on audit_events', 'raise(abort', die Append-only-
        Meldung) – ein reiner Substring-Check würde das fälschlich als intakt
        durchwinken."""
        db_path = tmp_path / "when_clause_trigger.db"
        db = Database(db_path)
        db.migrate()
        conn = db.connect()
        conn.execute("DROP TRIGGER audit_events_no_update")
        conn.executescript(
            "CREATE TRIGGER audit_events_no_update "
            "BEFORE UPDATE ON audit_events "
            "WHEN 0 "
            "BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;"
        )
        db.close()

        result = preflight_check(db_path)

        assert isinstance(result, PreflightAccepted)
        assert result.audit_triggers_tampered is True

    def test_preflight_accepts_whitespace_variant_of_raise_abort(self, tmp_path: Path) -> None:
        """Brüchigkeits-Gate für die WHEN-Fix-Gegenprobe: ein intakter Trigger
        mit harmlos abweichender Formatierung ('RAISE (ABORT' statt
        'RAISE(ABORT') muss weiterhin als NICHT getampert gelten."""
        db_path = tmp_path / "whitespace_variant.db"
        db = Database(db_path)
        db.migrate()
        conn = db.connect()
        conn.execute("DROP TRIGGER audit_events_no_delete")
        conn.executescript(
            "CREATE TRIGGER audit_events_no_delete "
            "BEFORE DELETE ON audit_events "
            "BEGIN SELECT RAISE (ABORT, 'audit_events is append-only'); END;"
        )
        db.close()

        result = preflight_check(db_path)

        assert isinstance(result, PreflightAccepted)
        assert result.audit_triggers_tampered is False


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
