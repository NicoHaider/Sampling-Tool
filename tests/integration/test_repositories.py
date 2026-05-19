"""Integration: alle vier Repositories + Append-Only-Trigger."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from sampling_tool.core.cancellation import CancellationToken, OperationCancelled
from sampling_tool.core.models import (
    AuditEvent,
    Dataset,
    DatasetRow,
    Engagement,
    SampleConfig,
    SampleResult,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import (
    AuditRepo,
    DatasetRepo,
    EngagementRepo,
    SampleRepo,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_rows() -> tuple[DatasetRow, ...]:
    return tuple(
        DatasetRow(row_id=i, values={"Col1": f"V{i}", "Country": ["AUT", "GER"][i % 2]})
        for i in range(1, 11)
    )


def _sample_dataset(engagement_id: int) -> Dataset:
    return Dataset(
        name="Buchungssätze 2026",
        columns=("Col1", "Country"),
        row_count=10,
        source_file="/tmp/test.xlsx",
        engagement_id=engagement_id,
    )


# ===========================================================================
# EngagementRepo
# ===========================================================================


class TestEngagementRepo:
    def test_get_returns_none_initially(self, db: Database) -> None:
        repo = EngagementRepo(db.connect())
        assert repo.get() is None

    def test_get_or_create_inserts(self, db: Database) -> None:
        repo = EngagementRepo(db.connect())
        eng = repo.get_or_create(Engagement(auditor_name="Anna", client_name="ACME"))
        assert eng.id is not None
        assert eng.auditor_name == "Anna"

    def test_get_or_create_is_idempotent(self, db: Database) -> None:
        repo = EngagementRepo(db.connect())
        first = repo.get_or_create(Engagement(auditor_name="A", client_name="X"))
        second = repo.get_or_create(Engagement(auditor_name="B", client_name="Y"))
        assert first.id == second.id
        assert second.auditor_name == "A"  # zweiter Aufruf hat NICHT überschrieben

    def test_update_metadata(self, db: Database, engagement_id: int) -> None:
        repo = EngagementRepo(db.connect())
        updated = repo.update_metadata(
            engagement_id, auditor_name="Berta", audit_type="ISAE 3402 Typ I"
        )
        assert updated.auditor_name == "Berta"
        assert updated.audit_type == "ISAE 3402 Typ I"
        # Felder, die nicht übergeben wurden, bleiben:
        assert updated.client_name == "ACME GmbH"

    def test_update_unknown_engagement_raises(self, db: Database) -> None:
        repo = EngagementRepo(db.connect())
        with pytest.raises(LookupError):
            repo.update_metadata(99999, auditor_name="X")


# ===========================================================================
# DatasetRepo
# ===========================================================================


class TestDatasetRepo:
    def test_create_persists_dataset_and_rows(self, db: Database, engagement_id: int) -> None:
        repo = DatasetRepo(db.connect())
        ds = repo.create(_sample_dataset(engagement_id), _sample_rows())
        assert ds.id is not None
        assert ds.row_count == 10

        roundtrip = repo.get_by_id(ds.id)
        assert roundtrip is not None
        assert roundtrip.name == "Buchungssätze 2026"
        assert roundtrip.row_count == 10
        assert roundtrip.columns == ("Col1", "Country")

        rows = repo.get_all_rows(ds.id)
        assert len(rows) == 10
        assert rows[0].values["Country"] == "GER"  # row_id=1, 1%2=1

    def test_get_by_id_unknown_returns_none(self, db: Database) -> None:
        assert DatasetRepo(db.connect()).get_by_id(42) is None

    def test_create_without_engagement_id_raises(self, db: Database) -> None:
        repo = DatasetRepo(db.connect())
        ds = Dataset(name="X", columns=("a",))
        with pytest.raises(ValueError, match="engagement_id"):
            repo.create(ds, ())

    def test_list_for_engagement_excludes_rows(self, db: Database, engagement_id: int) -> None:
        repo = DatasetRepo(db.connect())
        repo.create(_sample_dataset(engagement_id), _sample_rows())
        listed = repo.list_for_engagement(engagement_id)
        assert len(listed) == 1
        # Übersicht hat row_count, aber keine Rows-Materialisierung
        assert listed[0].row_count == 10

    def test_delete_cascades_rows(self, db: Database, engagement_id: int) -> None:
        repo = DatasetRepo(db.connect())
        ds = repo.create(_sample_dataset(engagement_id), _sample_rows())
        assert ds.id is not None
        repo.delete(ds.id)

        rows_left = (
            db.connect()
            .execute(
                "SELECT COUNT(*) AS c FROM dataset_rows WHERE dataset_id = ?",
                (ds.id,),
            )
            .fetchone()
        )
        assert rows_left["c"] == 0

    # ---- Sprint 17: progress + cancellation ----------------------------

    def test_create_invokes_progress_callback(self, db: Database, engagement_id: int) -> None:
        """`progress(current, total)` wird mindestens einmal aufgerufen."""
        repo = DatasetRepo(db.connect())
        ticks: list[tuple[int, int]] = []
        repo.create(
            _sample_dataset(engagement_id),
            _sample_rows(),
            progress=lambda c, t: ticks.append((c, t)),
        )
        assert ticks, "progress sollte mind. 1× gefeuert haben"
        # Letzter Tick = vollständig.
        assert ticks[-1] == (10, 10)

    def test_create_respects_cancellation_token(self, db: Database, engagement_id: int) -> None:
        """Token vor Start gesetzt → OperationCancelled, kein Dataset."""
        repo = DatasetRepo(db.connect())
        token = CancellationToken()
        token.set()
        with pytest.raises(OperationCancelled):
            repo.create(
                _sample_dataset(engagement_id),
                _sample_rows(),
                cancellation=token,
            )
        # Rollback: kein Dataset in der DB.
        listed = repo.list_for_engagement(engagement_id)
        assert listed == []

    def test_create_without_progress_runs_to_completion(
        self, db: Database, engagement_id: int
    ) -> None:
        # Sanity – Default-Verhalten unverändert.
        repo = DatasetRepo(db.connect())
        ds = repo.create(_sample_dataset(engagement_id), _sample_rows())
        assert ds.row_count == 10

    def test_create_is_atomic_on_failure(self, db: Database, engagement_id: int) -> None:
        repo = DatasetRepo(db.connect())
        # ein Row mit nicht-serialisierbarem Wert lässt INSERT auf dataset_rows
        # scheitern → Dataset darf nicht zurückbleiben.
        bad = Dataset(name="bad", columns=("a",), engagement_id=engagement_id)
        bad_rows = (DatasetRow(row_id=1, values={"a": object()}),)
        with pytest.raises(TypeError):
            repo.create(bad, bad_rows)
        count = (
            db.connect().execute("SELECT COUNT(*) AS c FROM datasets WHERE name = 'bad'").fetchone()
        )
        assert count["c"] == 0

    def test_get_rows_by_ids_leere_eingabe(self, db: Database, engagement_id: int) -> None:
        repo = DatasetRepo(db.connect())
        ds = repo.create(_sample_dataset(engagement_id), _sample_rows())
        assert ds.id is not None
        assert repo.get_rows_by_ids(ds.id, []) == []

    def test_get_rows_by_ids_behält_reihenfolge(self, db: Database, engagement_id: int) -> None:
        repo = DatasetRepo(db.connect())
        ds = repo.create(_sample_dataset(engagement_id), _sample_rows())
        assert ds.id is not None
        rows = repo.get_rows_by_ids(ds.id, [5, 1, 3])
        assert [r.row_id for r in rows] == [5, 1, 3]

    def test_get_rows_by_ids_ignoriert_stale(self, db: Database, engagement_id: int) -> None:
        repo = DatasetRepo(db.connect())
        ds = repo.create(_sample_dataset(engagement_id), _sample_rows())
        assert ds.id is not None
        rows = repo.get_rows_by_ids(ds.id, [1, 99999, 3])
        # 99999 stillschweigend übersprungen, Reihenfolge bleibt
        assert [r.row_id for r in rows] == [1, 3]

    def test_get_rows_by_ids_chunking_bei_grossen_listen(
        self, db: Database, engagement_id: int
    ) -> None:
        repo = DatasetRepo(db.connect())
        many_rows = tuple(
            DatasetRow(row_id=i, values={"Col1": f"V{i}", "Country": "AUT"}) for i in range(1, 2001)
        )
        ds = repo.create(
            Dataset(
                name="Big",
                columns=("Col1", "Country"),
                row_count=2000,
                engagement_id=engagement_id,
            ),
            many_rows,
        )
        assert ds.id is not None
        # > SQLITE_VAR_LIMIT (900) → mehrere Chunks
        ids = list(range(1, 2001))
        rows = repo.get_rows_by_ids(ds.id, ids)
        assert [r.row_id for r in rows] == ids

    def test_iter_row_ids_lazy_und_sortiert(self, db: Database, engagement_id: int) -> None:
        from collections.abc import Iterator as _Iter

        repo = DatasetRepo(db.connect())
        ds = repo.create(_sample_dataset(engagement_id), _sample_rows())
        assert ds.id is not None
        iterator = repo.iter_row_ids(ds.id)
        assert isinstance(iterator, _Iter)
        assert not isinstance(iterator, list)
        ids = list(iterator)
        assert ids == list(range(1, 11))

    def test_datetime_values_roundtrip(self, db: Database, engagement_id: int) -> None:
        from datetime import date, datetime, time

        repo = DatasetRepo(db.connect())
        ds = Dataset(
            name="dt-test",
            columns=("Datum", "Uhrzeit", "Tag"),
            engagement_id=engagement_id,
        )
        rows = (
            DatasetRow(
                row_id=1,
                values={
                    "Datum": datetime(2026, 5, 11, 14, 30, 0),
                    "Uhrzeit": time(8, 15, 30),
                    "Tag": date(2026, 5, 11),
                },
            ),
        )
        created = repo.create(ds, rows)
        assert created.id is not None
        loaded_rows = repo.get_all_rows(created.id)
        first = loaded_rows[0].values
        assert first["Datum"] == datetime(2026, 5, 11, 14, 30, 0)
        assert first["Uhrzeit"] == time(8, 15, 30)
        assert first["Tag"] == date(2026, 5, 11)


# ===========================================================================
# SampleRepo
# ===========================================================================


def _persist_dataset(db: Database, engagement_id: int) -> int:
    ds = DatasetRepo(db.connect()).create(_sample_dataset(engagement_id), _sample_rows())
    assert ds.id is not None
    return ds.id


def _make_result() -> SampleResult:
    cfg = SampleConfig(
        method=SamplingMethod.STRATIFIED,
        size=4,
        seed=42,
        stratum_field="Country",
        stratify_mode=StratifyMode.PROPORTIONAL,
        filter_field="Country",
        filter_value="AUT",
    )
    return SampleResult(
        config=cfg,
        selected_row_ids=(1, 3, 5, 7),
        population_size=10,
    )


class TestSampleRepo:
    def test_create_returns_int_id(self, db: Database, engagement_id: int) -> None:
        dataset_id = _persist_dataset(db, engagement_id)
        repo = SampleRepo(db.connect())
        sid = repo.create_from_result(_make_result(), dataset_id, "anna")
        assert isinstance(sid, int)

    def test_roundtrip_preserves_config_and_rows(self, db: Database, engagement_id: int) -> None:
        dataset_id = _persist_dataset(db, engagement_id)
        repo = SampleRepo(db.connect())
        sid = repo.create_from_result(_make_result(), dataset_id, "anna")

        loaded = repo.get_by_id(sid)
        assert loaded is not None
        assert loaded.selected_row_ids == (1, 3, 5, 7)
        assert loaded.population_size == 10
        assert loaded.config.method == SamplingMethod.STRATIFIED
        assert loaded.config.stratum_field == "Country"
        assert loaded.config.filter_value == "AUT"
        assert loaded.created_by == "anna"

    def test_list_for_dataset(self, db: Database, engagement_id: int) -> None:
        dataset_id = _persist_dataset(db, engagement_id)
        repo = SampleRepo(db.connect())
        repo.create_from_result(_make_result(), dataset_id, "anna")
        repo.create_from_result(_make_result(), dataset_id, "berta")

        listed = repo.list_for_dataset(dataset_id)
        assert len(listed) == 2
        creators = {s.created_by for s in listed}
        assert creators == {"anna", "berta"}

    def test_get_by_id_unknown_returns_none(self, db: Database) -> None:
        assert SampleRepo(db.connect()).get_by_id(99999) is None


# ===========================================================================
# AuditRepo
# ===========================================================================


class TestAuditRepo:
    def test_log_inserts_event_with_id(self, db: Database, engagement_id: int) -> None:
        repo = AuditRepo(db.connect())
        event = AuditEvent(
            event_type="import",
            engagement_id=engagement_id,
            user_name="anna",
            details={"source": "test.xlsx"},
        )
        logged = repo.log(event)
        assert logged.id is not None

    def test_log_requires_engagement_id(self, db: Database) -> None:
        repo = AuditRepo(db.connect())
        with pytest.raises(ValueError, match="engagement_id"):
            repo.log(AuditEvent(event_type="x"))

    def test_list_for_engagement_orders_newest_first(
        self, db: Database, engagement_id: int
    ) -> None:
        repo = AuditRepo(db.connect())
        for label in ("a", "b", "c"):
            repo.log(
                AuditEvent(
                    event_type="sampling",
                    engagement_id=engagement_id,
                    details={"label": label},
                )
            )
        listed = repo.list_for_engagement(engagement_id)
        assert len(listed) == 3
        assert listed[0].details["label"] == "c"
        assert listed[-1].details["label"] == "a"

    def test_correct_writes_correction_event(self, db: Database, engagement_id: int) -> None:
        repo = AuditRepo(db.connect())
        original = repo.log(
            AuditEvent(
                event_type="sampling",
                engagement_id=engagement_id,
                seed=123,
            )
        )
        assert original.id is not None

        correction = repo.correct(
            original.id,
            AuditEvent(
                event_type="ignored-because-overwritten",
                engagement_id=engagement_id,
                details={"reason": "Seed war falsch"},
            ),
        )
        assert correction.event_type == "correction"
        assert correction.corrects_event_id == original.id

    def test_update_blocked_by_trigger(self, db: Database, engagement_id: int) -> None:
        repo = AuditRepo(db.connect())
        evt = repo.log(AuditEvent(event_type="x", engagement_id=engagement_id))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.connect().execute(
                "UPDATE audit_events SET event_type = 'tampered' WHERE id = ?",
                (evt.id,),
            )

    def test_delete_blocked_by_trigger(self, db: Database, engagement_id: int) -> None:
        repo = AuditRepo(db.connect())
        evt = repo.log(AuditEvent(event_type="x", engagement_id=engagement_id))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.connect().execute("DELETE FROM audit_events WHERE id = ?", (evt.id,))

    def test_details_roundtrip_json(self, db: Database, engagement_id: int) -> None:
        repo = AuditRepo(db.connect())
        details: dict[str, Any] = {"nested": {"k": [1, 2, 3]}, "flag": True}
        evt = repo.log(
            AuditEvent(
                event_type="x",
                engagement_id=engagement_id,
                details=details,
            )
        )
        loaded = repo.list_for_engagement(engagement_id)[0]
        assert loaded.details == details
        assert loaded.id == evt.id
