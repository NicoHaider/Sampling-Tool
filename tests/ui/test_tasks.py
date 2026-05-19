"""Tests für die konkreten Worker-Tasks (Sprint 17 / P-008).

Wir laufen die Tasks direkt (synchron im Test-Thread) – nicht über den
TaskWorker. Das deckt die Task-Logik selbst ab und prüft die Reproducibility
(Worker-Pfad == Synchron-Pfad).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from sampling_tool.core.cancellation import CancellationToken, OperationCancelled
from sampling_tool.core.models import Engagement
from sampling_tool.io.importer import ExcelImporter
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import (
    DatasetRepo,
    EngagementRepo,
)
from sampling_tool.ui.workers.task_worker import ProgressReporter, _ProgressEmitter
from sampling_tool.ui.workers.tasks import ExcelImportTask

pytestmark = pytest.mark.ui


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_test_xlsx(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Daten"
    ws.append(["Konto", "Betrag"])
    for i in range(1, 21):
        ws.append([1000 + i, i * 100])
    wb.save(path)


def _make_engagement_db(tmp_path: Path) -> tuple[Path, int]:
    db_path = tmp_path / "engagement.db"
    db = Database(db_path)
    db.migrate()
    eng = EngagementRepo(db.connect()).get_or_create(
        Engagement(
            auditor_name="A",
            client_name="C",
            auditor_position="S",
            audit_type="ISAE 3402",
        )
    )
    assert eng.id is not None
    eng_id = eng.id
    db.close()
    return db_path, eng_id


def _make_progress_reporter() -> tuple[ProgressReporter, list[tuple[int, int]]]:
    emitter = _ProgressEmitter()
    captured: list[tuple[int, int]] = []
    emitter.progress.connect(lambda c, t: captured.append((c, t)))
    return ProgressReporter(emitter), captured


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExcelImportTask:
    def test_import_persists_dataset(self, tmp_path: Path) -> None:
        xlsx = tmp_path / "src.xlsx"
        _make_test_xlsx(xlsx)
        db_path, eng_id = _make_engagement_db(tmp_path)

        task = ExcelImportTask(path=xlsx, db_path=db_path, engagement_id=eng_id, user_name="tester")
        reporter, _ticks = _make_progress_reporter()
        result = task.run(reporter, CancellationToken())
        stored = result.dataset

        assert stored.id is not None
        assert stored.row_count == 20
        assert stored.columns == ("Konto", "Betrag")
        # Persist sanity-check.
        db = Database(db_path)
        try:
            rows = DatasetRepo(db.connect()).get_all_rows(stored.id)
            assert len(rows) == 20
        finally:
            db.close()

    def test_import_emits_progress(self, tmp_path: Path) -> None:
        xlsx = tmp_path / "src.xlsx"
        _make_test_xlsx(xlsx)
        db_path, eng_id = _make_engagement_db(tmp_path)

        task = ExcelImportTask(path=xlsx, db_path=db_path, engagement_id=eng_id, user_name="tester")
        reporter, ticks = _make_progress_reporter()
        task.run(reporter, CancellationToken())
        assert ticks, "progress sollte mindestens einmal feuern (Final-Tick)"

    def test_import_cancellation_before_run_rollbacks(self, tmp_path: Path) -> None:
        xlsx = tmp_path / "src.xlsx"
        _make_test_xlsx(xlsx)
        db_path, eng_id = _make_engagement_db(tmp_path)

        token = CancellationToken()
        token.set()
        task = ExcelImportTask(path=xlsx, db_path=db_path, engagement_id=eng_id, user_name="tester")
        reporter, _ticks = _make_progress_reporter()
        with pytest.raises(OperationCancelled):
            task.run(reporter, token)

        # Kein Dataset in der DB persistiert.
        db = Database(db_path)
        try:
            datasets = DatasetRepo(db.connect()).list_for_engagement(eng_id)
            assert datasets == []
        finally:
            db.close()

    def test_import_configured_uses_sheet_and_header(self, tmp_path: Path) -> None:
        """Wenn sheet_name + header_row gesetzt sind, läuft import_file_configured."""
        xlsx = tmp_path / "configured.xlsx"
        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = "Daten"
        ws.append([None, None])
        ws.append([None, None])
        ws.append(["Konto", "Betrag"])
        ws.append([100, 999])
        wb.save(xlsx)

        db_path, eng_id = _make_engagement_db(tmp_path)
        task = ExcelImportTask(
            path=xlsx,
            db_path=db_path,
            engagement_id=eng_id,
            user_name="tester",
            sheet_name="Daten",
            header_row=2,
        )
        reporter, _ticks = _make_progress_reporter()
        result = task.run(reporter, CancellationToken())
        stored = result.dataset

        assert stored.columns == ("Konto", "Betrag")
        assert stored.row_count == 1


class TestReproducibility:
    """Sprint 17 / P-008: Worker-Pfad muss bit-genau dasselbe Dataset
    liefern wie der synchrone Pfad."""

    def test_worker_yields_same_rows_as_sync_import(self, tmp_path: Path) -> None:
        xlsx = tmp_path / "src.xlsx"
        _make_test_xlsx(xlsx)

        # Synchron
        sync = ExcelImporter().import_file(xlsx)
        sync_rows = list(sync.rows)

        # Worker-Task (direct run)
        db_path, eng_id = _make_engagement_db(tmp_path)
        task = ExcelImportTask(path=xlsx, db_path=db_path, engagement_id=eng_id, user_name="tester")
        reporter, _ticks = _make_progress_reporter()
        result = task.run(reporter, CancellationToken())
        stored = result.dataset

        # Worker-Resultat aus der DB lesen.
        db = Database(db_path)
        try:
            assert stored.id is not None
            worker_rows = DatasetRepo(db.connect()).get_all_rows(stored.id)
        finally:
            db.close()

        # Bit-genau gleich (row_id + values).
        assert len(sync_rows) == len(worker_rows)
        for s, w in zip(sync_rows, worker_rows, strict=True):
            assert s.row_id == w.row_id
            assert s.values == w.values
