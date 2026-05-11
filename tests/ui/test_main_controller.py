"""MainController – Glue-Logik mit echter SQLite-Datei und Excel-Fixture."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from openpyxl import Workbook
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QListWidget
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    Engagement,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import (
    DatasetRepo,
    EngagementRepo,
    SampleRepo,
)
from sampling_tool.ui.controllers.main_controller import MainController
from sampling_tool.ui.dialogs.new_engagement_dialog import NewEngagementDialog
from sampling_tool.ui.main_window import MainWindow
from sampling_tool.ui.recent import RecentEngagementsStore

pytestmark = pytest.mark.ui


@pytest.fixture
def recent_store(tmp_path: Path) -> RecentEngagementsStore:
    return RecentEngagementsStore(path=tmp_path / "recent.json")


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    return win


@pytest.fixture
def controller(
    window: MainWindow, recent_store: RecentEngagementsStore
) -> Iterator[MainController]:
    ctrl = MainController(window, recent_store=recent_store)
    yield ctrl
    ctrl.handle_close_engagement()


@pytest.fixture
def populated_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "engagement.db"
    db = Database(db_path)
    db.migrate()
    eng_repo = EngagementRepo(db.connect())
    eng = eng_repo.get_or_create(
        Engagement(
            auditor_name="Anna",
            client_name="ACME",
            auditor_position="Senior",
            audit_type="ISAE 3402",
        )
    )
    assert eng.id is not None
    ds_repo = DatasetRepo(db.connect())
    dataset = ds_repo.create(
        Dataset(
            name="Buchungen",
            columns=("Konto", "Betrag"),
            rows=tuple(
                DatasetRow(row_id=i, values={"Konto": f"K{i}", "Betrag": i * 10})
                for i in range(1, 6)
            ),
            engagement_id=eng.id,
        )
    )
    assert dataset.id is not None
    SampleRepo(db.connect()).create_from_result(
        SampleResult(
            config=SampleConfig(method=SamplingMethod.SIMPLE, size=2, seed=42),
            selected_row_ids=(2, 4),
            population_size=5,
        ),
        dataset.id,
        "tester",
    )
    db.close()
    return db_path


@pytest.fixture
def import_xlsx(tmp_path: Path) -> Path:
    path = tmp_path / "import.xlsx"
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["Konto", "Betrag"])
    for i in range(1, 4):
        ws.append([f"K{i}", i * 100])
    wb.save(path)
    return path


def _first_item_data(list_widget: QListWidget) -> int:
    item = list_widget.item(0)
    assert item is not None
    value = item.data(int(Qt.ItemDataRole.UserRole))
    assert isinstance(value, int)
    return value


class TestMainController:
    def test_open_engagement_loads_into_workspace(
        self,
        controller: MainController,
        window: MainWindow,
        populated_db: Path,
    ) -> None:
        controller.handle_open_engagement(populated_db)
        assert window.is_workspace_visible() is True
        assert window.sidebar().datasets_widget().count() == 1

    def test_open_engagement_missing_db_shows_welcome(
        self,
        controller: MainController,
        window: MainWindow,
        tmp_path: Path,
    ) -> None:
        ghost = tmp_path / "ghost.db"
        with patch("sampling_tool.ui.controllers.main_controller.QMessageBox.warning") as warning:
            controller.handle_open_engagement(ghost)
        assert warning.called
        assert window.is_workspace_visible() is False

    def test_dataset_selected_shows_table_and_samples(
        self,
        controller: MainController,
        window: MainWindow,
        populated_db: Path,
    ) -> None:
        controller.handle_open_engagement(populated_db)
        controller.handle_dataset_selected(_first_item_data(window.sidebar().datasets_widget()))
        assert window.data_table().table_model().rowCount() == 5
        assert window.sidebar().samples_widget().count() == 1

    def test_sample_selected_highlights_rows(
        self,
        controller: MainController,
        window: MainWindow,
        populated_db: Path,
    ) -> None:
        controller.handle_open_engagement(populated_db)
        controller.handle_dataset_selected(_first_item_data(window.sidebar().datasets_widget()))
        controller.handle_sample_selected(_first_item_data(window.sidebar().samples_widget()))
        highlights = window.data_table().table_model().highlighted_row_ids()
        assert highlights == frozenset({2, 4})

    def test_sample_filter_toggle_filters_and_unfilters(
        self,
        controller: MainController,
        window: MainWindow,
        populated_db: Path,
    ) -> None:
        controller.handle_open_engagement(populated_db)
        controller.handle_dataset_selected(_first_item_data(window.sidebar().datasets_widget()))
        sample_id = _first_item_data(window.sidebar().samples_widget())

        controller.handle_sample_filter_toggled(sample_id)
        assert window.data_table().table_model().rowCount() == 2

        controller.handle_sample_filter_toggled(sample_id)
        assert window.data_table().table_model().rowCount() == 5

    def test_close_engagement_returns_to_welcome(
        self,
        controller: MainController,
        window: MainWindow,
        populated_db: Path,
    ) -> None:
        controller.handle_open_engagement(populated_db)
        controller.handle_close_engagement()
        assert window.is_workspace_visible() is False
        assert window.data_table().table_model().rowCount() == 0

    def test_new_engagement_creates_db_via_dialog(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        tmp_path: Path,
    ) -> None:
        target_db = tmp_path / "new.db"

        class _StubDialog(NewEngagementDialog):
            def exec(self) -> int:
                self._db_path = target_db
                return int(QDialog.DialogCode.Accepted)

            def get_engagement(self) -> Engagement:
                return Engagement(
                    auditor_name="Anna",
                    auditor_position="Senior",
                    client_name="ACME",
                    audit_type="ISAE 3402",
                )

        controller = MainController(
            window,
            recent_store=recent_store,
            dialog_factory=lambda parent: _StubDialog(parent),
        )
        try:
            controller.handle_new_engagement()
            assert target_db.exists()
            assert window.is_workspace_visible() is True
            assert recent_store.list()[0].path == target_db.resolve()
        finally:
            controller.handle_close_engagement()

    def test_import_excel_persists_dataset_and_logs_audit(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
        import_xlsx: Path,
    ) -> None:
        controller = MainController(window, recent_store=recent_store)
        try:
            controller.handle_open_engagement(populated_db)
            with (
                patch(
                    "sampling_tool.ui.controllers.main_controller.QFileDialog.getOpenFileName",
                    return_value=(str(import_xlsx), ""),
                ),
                patch("sampling_tool.ui.controllers.main_controller.QMessageBox.information"),
            ):
                controller.handle_import_excel()

            assert window.sidebar().datasets_widget().count() == 2
            assert window.data_table().table_model().rowCount() == 3
        finally:
            controller.handle_close_engagement()
