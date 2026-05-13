"""Integration-Tests für `EngagementStateRepo` (Sprint 8.2).

Persistierter UI-State pro Engagement: zuletzt aktives Dataset/Sample +
Filter-Status. Genau eine Zeile pro Engagement, FK-gesichert.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import (
    EngagementState,
    EngagementStateRepo,
)


class TestGet:
    def test_get_returns_none_when_no_state_persisted(
        self, db: Database, engagement_id: int
    ) -> None:
        repo = EngagementStateRepo(db.connect())
        assert repo.get(engagement_id) is None


class TestUpsert:
    def test_upsert_inserts_first_row(self, db: Database, engagement_id: int) -> None:
        repo = EngagementStateRepo(db.connect())
        result = repo.upsert(engagement_id, None, None, filter_active=True)

        assert isinstance(result, EngagementState)
        assert result.engagement_id == engagement_id
        assert result.active_dataset_id is None
        assert result.active_sample_id is None
        assert result.filter_active is True
        assert isinstance(result.updated_at, datetime)

        roundtrip = repo.get(engagement_id)
        assert roundtrip == result

    def test_upsert_replaces_existing_row(self, db: Database, engagement_id: int) -> None:
        repo = EngagementStateRepo(db.connect())
        repo.upsert(engagement_id, None, None, filter_active=True)
        repo.upsert(engagement_id, None, None, filter_active=False)

        # Exakt eine Zeile pro Engagement.
        count = (
            db.connect()
            .execute(
                "SELECT COUNT(*) AS c FROM engagement_state WHERE engagement_id = ?",
                (engagement_id,),
            )
            .fetchone()
        )
        assert count["c"] == 1

        state = repo.get(engagement_id)
        assert state is not None
        assert state.filter_active is False

    def test_upsert_persists_boolean_as_integer(self, db: Database, engagement_id: int) -> None:
        repo = EngagementStateRepo(db.connect())
        repo.upsert(engagement_id, None, None, filter_active=True)
        raw = (
            db.connect()
            .execute(
                "SELECT filter_active FROM engagement_state WHERE engagement_id = ?",
                (engagement_id,),
            )
            .fetchone()
        )
        assert raw["filter_active"] == 1

        repo.upsert(engagement_id, None, None, filter_active=False)
        raw = (
            db.connect()
            .execute(
                "SELECT filter_active FROM engagement_state WHERE engagement_id = ?",
                (engagement_id,),
            )
            .fetchone()
        )
        assert raw["filter_active"] == 0


class TestForeignKeys:
    def test_unknown_engagement_id_is_rejected(self, db: Database) -> None:
        repo = EngagementStateRepo(db.connect())
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            repo.upsert(99999, None, None, filter_active=True)

    def test_deleted_engagement_cascades_state(self, db: Database, engagement_id: int) -> None:
        repo = EngagementStateRepo(db.connect())
        repo.upsert(engagement_id, None, None, filter_active=True)
        with db.session() as conn:
            conn.execute("DELETE FROM engagements WHERE id = ?", (engagement_id,))
        assert repo.get(engagement_id) is None


class TestClear:
    def test_clear_removes_state(self, db: Database, engagement_id: int) -> None:
        repo = EngagementStateRepo(db.connect())
        repo.upsert(engagement_id, None, None, filter_active=True)
        repo.clear(engagement_id)
        assert repo.get(engagement_id) is None

    def test_clear_is_idempotent(self, db: Database, engagement_id: int) -> None:
        repo = EngagementStateRepo(db.connect())
        repo.clear(engagement_id)  # nichts zu löschen
        repo.clear(engagement_id)
        assert repo.get(engagement_id) is None
