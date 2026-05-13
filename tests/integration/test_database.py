"""Integration: Database-Lifecycle, Migrationen, Sessions."""

from __future__ import annotations

from pathlib import Path

import pytest

from sampling_tool.persistence.database import Database


class TestSchemaVersion:
    def test_zero_before_migration(self) -> None:
        db = Database(Path(":memory:"))
        try:
            assert db.schema_version() == 0
        finally:
            db.close()

    def test_latest_after_migration(self, db: Database) -> None:
        # Fixture migriert bereits.
        assert db.schema_version() == 2

    def test_migration_is_idempotent(self, db: Database) -> None:
        db.migrate()  # erneut – darf nichts ändern
        db.migrate()
        assert db.schema_version() == 2


class TestMigrationsApply:
    def test_all_expected_tables_exist(self, db: Database) -> None:
        rows = (
            db.connect()
            .execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            .fetchall()
        )
        names = {r["name"] for r in rows}

        expected = {
            "schema_version",
            "engagements",
            "datasets",
            "dataset_rows",
            "samples",
            "sample_rows",
            "audit_events",
            "undo_snapshots",
            "engagement_state",
        }
        assert expected.issubset(names)

    def test_audit_triggers_exist(self, db: Database) -> None:
        rows = (
            db.connect().execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
        )
        names = {r["name"] for r in rows}
        assert {"audit_events_no_update", "audit_events_no_delete"}.issubset(names)

    def test_foreign_keys_pragma_enabled(self, db: Database) -> None:
        result = db.connect().execute("PRAGMA foreign_keys").fetchone()
        assert result[0] == 1


class TestSession:
    def test_commit_on_success(self, db: Database, engagement_id: int) -> None:
        with db.session() as conn:
            conn.execute(
                "INSERT INTO datasets "
                "(engagement_id, name, row_count, columns_json) "
                "VALUES (?, ?, ?, ?)",
                (engagement_id, "X", 0, "[]"),
            )

        rows = db.connect().execute("SELECT COUNT(*) AS c FROM datasets").fetchone()
        assert rows["c"] == 1

    def test_rollback_on_exception(self, db: Database, engagement_id: int) -> None:
        with pytest.raises(RuntimeError, match="boom"), db.session() as conn:  # noqa: PT012
            conn.execute(
                "INSERT INTO datasets "
                "(engagement_id, name, row_count, columns_json) "
                "VALUES (?, ?, ?, ?)",
                (engagement_id, "Wird zurückgerollt", 0, "[]"),
            )
            raise RuntimeError("boom")

        rows = db.connect().execute("SELECT COUNT(*) AS c FROM datasets").fetchone()
        assert rows["c"] == 0


class TestMigrationV1ToV2:
    """Regression: bestehende Sprint-7-DBs (schema_version=1) müssen ohne
    Datenverlust auf v2 hochgezogen werden, sobald sie das erste Mal von der
    Sprint-8.2-App geöffnet werden."""

    def test_v1_db_is_upgraded_in_place(self, tmp_path: Path) -> None:
        db_path = tmp_path / "legacy.db"

        # Schritt 1: Sprint-7-Stand simulieren – nur Migration 001 anwenden.
        legacy = Database(db_path)
        try:
            conn = legacy.connect()
            v1_sql = (
                Path(__file__).resolve().parents[2]
                / "src"
                / "sampling_tool"
                / "persistence"
                / "migrations"
                / "001_initial.sql"
            ).read_text(encoding="utf-8")
            conn.executescript(v1_sql)
            with legacy.session() as c:
                c.execute(
                    "INSERT INTO engagements (auditor_name, client_name) VALUES (?, ?)",
                    ("Anna", "ACME"),
                )
            assert legacy.schema_version() == 1
        finally:
            legacy.close()

        # Schritt 2: dieselbe DB-Datei normal öffnen (wie der Controller).
        upgraded = Database(db_path)
        try:
            upgraded.migrate()
            assert upgraded.schema_version() == 2

            # Bestehende Daten überleben.
            row = (
                upgraded.connect()
                .execute("SELECT auditor_name, client_name FROM engagements")
                .fetchone()
            )
            assert row["auditor_name"] == "Anna"
            assert row["client_name"] == "ACME"

            # Neue Tabelle ist da und leer.
            count = (
                upgraded.connect().execute("SELECT COUNT(*) AS c FROM engagement_state").fetchone()
            )
            assert count["c"] == 0
        finally:
            upgraded.close()


class TestPersistenceAcrossConnections:
    def test_file_database_survives_close(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        first = Database(db_path)
        first.migrate()
        with first.session() as conn:
            conn.execute(
                "INSERT INTO engagements (auditor_name, client_name) VALUES (?, ?)",
                ("Anna", "ACME"),
            )
        first.close()

        second = Database(db_path)
        try:
            row = second.connect().execute("SELECT auditor_name FROM engagements").fetchone()
            assert row["auditor_name"] == "Anna"
        finally:
            second.close()
