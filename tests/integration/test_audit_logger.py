"""Integration: AuditLogger – High-Level-Wrapper um AuditRepo."""

from __future__ import annotations

from pathlib import Path

import pytest

from sampling_tool.audit.logger import AuditLogger
from sampling_tool.core.models import (
    Dataset,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import AuditRepo


@pytest.fixture
def logger(db: Database, engagement_id: int) -> AuditLogger:
    return AuditLogger(
        AuditRepo(db.connect()),
        user_name="anna",
        engagement_id=engagement_id,
    )


def _make_sample_result(size: int = 5, population: int = 100) -> SampleResult:
    cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=size, seed=42)
    return SampleResult(
        config=cfg,
        selected_row_ids=tuple(range(1, size + 1)),
        population_size=population,
    )


class TestLogSampling:
    def test_writes_event_with_size_seed_percent(
        self, engagement_id: int, logger: AuditLogger, sample_id: int
    ) -> None:
        sample = _make_sample_result(size=10, population=100)
        evt = logger.log_sampling(sample, sample_id=sample_id)

        assert evt.event_type == "sampling"
        assert evt.sample_id == sample_id
        assert evt.sample_size == 10
        assert evt.total_count == 100
        assert evt.sample_percent is not None
        assert abs(evt.sample_percent - 10.0) < 1e-9
        assert evt.seed == 42
        assert evt.user_name == "anna"
        assert evt.engagement_id == engagement_id

    def test_handles_empty_population_gracefully(self, logger: AuditLogger, sample_id: int) -> None:
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=1, seed=1)
        empty = SampleResult(config=cfg, selected_row_ids=(), population_size=0)
        evt = logger.log_sampling(empty, sample_id=sample_id)
        assert evt.sample_percent == 0.0


class TestLogImport:
    def test_writes_event_with_file_and_columns(
        self, logger: AuditLogger, engagement_id: int
    ) -> None:
        ds = Dataset(
            name="Dataset X",
            columns=("a", "b"),
            row_count=1,
            source_file="/tmp/x.xlsx",
            engagement_id=engagement_id,
            id=7,
        )
        evt = logger.log_import(ds)
        assert evt.event_type == "import"
        assert evt.import_file == "/tmp/x.xlsx"
        assert evt.total_count == 1
        assert evt.details["columns"] == ["a", "b"]
        assert evt.details["dataset_id"] == 7


class TestLogExport:
    def test_writes_event_with_export_file(self, logger: AuditLogger, sample_id: int) -> None:
        evt = logger.log_export(
            sample_id=sample_id,
            export_file=Path("/tmp/out.xlsx"),
            row_count=25,
        )
        assert evt.event_type == "export"
        assert evt.sample_id == sample_id
        assert evt.export_file == "/tmp/out.xlsx"
        assert evt.sample_size == 25


class TestLogUndoRedoReset:
    def test_log_undo(self, logger: AuditLogger, sample_id: int) -> None:
        evt = logger.log_undo(sample_id=sample_id)
        assert evt.event_type == "undo"
        assert evt.sample_id == sample_id

    def test_log_redo(self, logger: AuditLogger, sample_id: int) -> None:
        evt = logger.log_redo(sample_id=sample_id)
        assert evt.event_type == "redo"
        assert evt.sample_id == sample_id

    def test_log_reset(self, logger: AuditLogger) -> None:
        evt = logger.log_reset(dataset_id=99)
        assert evt.event_type == "reset"
        assert evt.details["dataset_id"] == 99


class TestLogCorrection:
    def test_correction_links_to_original(self, logger: AuditLogger, sample_id: int) -> None:
        original = logger.log_sampling(_make_sample_result(), sample_id=sample_id)
        assert original.id is not None

        correction = logger.log_correction(original.id, reason="Falscher Seed")
        assert correction.event_type == "correction"
        assert correction.corrects_event_id == original.id
        assert correction.details["reason"] == "Falscher Seed"


class TestLoggerRoundtripViaRepo:
    def test_events_visible_via_list_for_engagement(
        self,
        db: Database,
        logger: AuditLogger,
        engagement_id: int,
        sample_id: int,
    ) -> None:
        logger.log_undo(sample_id=sample_id)
        logger.log_redo(sample_id=sample_id)
        logger.log_reset(dataset_id=2)

        repo = AuditRepo(db.connect())
        listed = repo.list_for_engagement(engagement_id)
        types = [e.event_type for e in listed]
        # Reihenfolge nach timestamp DESC – aber gleiche Sekunde möglich,
        # daher per id-Tiebreaker: zuletzt eingefügt = reset oben.
        assert "reset" in types
        assert "undo" in types
        assert "redo" in types
