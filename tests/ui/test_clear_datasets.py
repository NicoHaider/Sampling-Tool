"""Sprint 31 Teil A: „Datensätze aus Ansicht entfernen" – reiner Ansichts-Reset.

Audit-safe: leert nur die Ansicht (Tabelle + Sidebar-Listen), die Projekt-DB
(`datasets`/`dataset_rows`/Audit-Events) bleibt unangetastet. Das Projekt bleibt
offen; ein erneutes Öffnen/Reload zeigt die Datensätze wieder.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from sampling_tool.config import APP_NAME, APP_ORG
from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    Engagement,
    SampleConfig,
    SampleResult,
    SamplingMethod,
    Snapshot,
    UndoStack,
)
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import (
    DatasetRepo,
    EngagementRepo,
    SampleRepo,
)
from sampling_tool.ui.controllers.main_controller import MainController
from sampling_tool.ui.main_window import MainWindow
from sampling_tool.ui.recent import RecentEngagementsStore

pytestmark = pytest.mark.ui

_QUESTION = "sampling_tool.ui.controllers.workspace_controller.QMessageBox.question"


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """QSettings-IO nach tmp – schützt echte Prefs (load_settings + ID-Store)."""
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    monkeypatch.setattr(
        "sampling_tool.ui.settings_store._qsettings",
        lambda: QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG, APP_NAME),
    )


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    return win


@pytest.fixture
def populated_db(tmp_path: Path) -> tuple[Path, int, int]:
    """Engagement-DB mit einem Dataset (5 Zeilen) + einer Stichprobe."""
    db_path = tmp_path / "engagement.db"
    db = Database(db_path)
    db.migrate()
    eng = EngagementRepo(db.connect()).get_or_create(
        Engagement(
            auditor_name="Anna",
            client_name="ACME",
            auditor_position="Senior",
            audit_type="ISAE 3402",
        )
    )
    assert eng.id is not None
    ds = DatasetRepo(db.connect()).create(
        Dataset(name="Buchungen", columns=("Konto", "Betrag"), engagement_id=eng.id),
        tuple(
            DatasetRow(row_id=i, values={"Konto": f"K{i}", "Betrag": i * 10}) for i in range(1, 6)
        ),
    )
    assert ds.id is not None
    SampleRepo(db.connect()).create_from_result(
        SampleResult(
            config=SampleConfig(method=SamplingMethod.SIMPLE, size=2, seed=42),
            selected_row_ids=(2, 4),
            population_size=5,
        ),
        ds.id,
        "tester",
    )
    db.close()
    return db_path, eng.id, ds.id


class TestClearLoadedDatasets:
    def _open_and_select(
        self, window: MainWindow, tmp_path: Path, populated_db: tuple[Path, int, int]
    ) -> MainController:
        db_path, _eng_id, ds_id = populated_db
        ctrl = MainController(
            window, recent_store=RecentEngagementsStore(path=tmp_path / "recent.json")
        )
        ctrl.handle_open_engagement(db_path)
        ctrl.selection.handle_dataset_selected(ds_id)  # Dataset in die Tabelle laden.
        return ctrl

    def test_clear_empties_sidebar_and_table(
        self, window: MainWindow, tmp_path: Path, populated_db: tuple[Path, int, int]
    ) -> None:
        ctrl = self._open_and_select(window, tmp_path, populated_db)
        assert window.sidebar().datasets_widget().count() == 1
        assert window.sidebar().samples_widget().count() == 1
        assert window.data_table().table_model().rowCount() == 5

        with patch(_QUESTION, return_value=QMessageBox.StandardButton.Yes):
            ctrl.workspace.handle_clear_loaded_datasets()

        assert window.sidebar().datasets_widget().count() == 0
        assert window.sidebar().samples_widget().count() == 0
        assert window.data_table().table_model().rowCount() == 0
        ctrl.handle_close_engagement()

    def test_clear_does_not_touch_db(
        self, window: MainWindow, tmp_path: Path, populated_db: tuple[Path, int, int]
    ) -> None:
        _db_path, eng_id, ds_id = populated_db
        ctrl = self._open_and_select(window, tmp_path, populated_db)

        with patch(_QUESTION, return_value=QMessageBox.StandardButton.Yes):
            ctrl.workspace.handle_clear_loaded_datasets()

        assert ctrl.session.db is not None
        repo = DatasetRepo(ctrl.session.db.connect())
        # Datasets + Rows in der DB unverändert (kein Delete).
        datasets = repo.list_for_engagement(eng_id)
        assert len(datasets) == 1
        assert len(repo.get_all_rows(ds_id)) == 5
        # Erneutes reload_datasets zeigt sie wieder in der Sidebar.
        ctrl.session.reload_datasets()
        assert window.sidebar().datasets_widget().count() == 1
        ctrl.handle_close_engagement()

    def test_clear_keeps_project_open(
        self, window: MainWindow, tmp_path: Path, populated_db: tuple[Path, int, int]
    ) -> None:
        ctrl = self._open_and_select(window, tmp_path, populated_db)

        with patch(_QUESTION, return_value=QMessageBox.StandardButton.Yes):
            ctrl.workspace.handle_clear_loaded_datasets()

        # Kein Wechsel zum Welcome-Screen; Engagement bleibt geladen.
        assert window.is_workspace_visible() is True
        assert ctrl.session.has_engagement() is True
        ctrl.handle_close_engagement()

    def test_clear_cancelled_is_noop(
        self, window: MainWindow, tmp_path: Path, populated_db: tuple[Path, int, int]
    ) -> None:
        ctrl = self._open_and_select(window, tmp_path, populated_db)

        with patch(_QUESTION, return_value=QMessageBox.StandardButton.No):
            ctrl.workspace.handle_clear_loaded_datasets()

        # Abbruch → nichts geleert.
        assert window.sidebar().datasets_widget().count() == 1
        assert window.data_table().table_model().rowCount() == 5
        ctrl.handle_close_engagement()

    def test_menu_action_emits_signal(
        self, window: MainWindow, tmp_path: Path, populated_db: tuple[Path, int, int]
    ) -> None:
        # Die Menü-Action ist verdrahtet und feuert das Fenster-Signal.
        ctrl = self._open_and_select(window, tmp_path, populated_db)
        with patch(_QUESTION, return_value=QMessageBox.StandardButton.Yes):
            window._action_clear_datasets.trigger()
        assert window.sidebar().datasets_widget().count() == 0
        ctrl.handle_close_engagement()

    def test_undo_snapshot_after_clear_applies_empty_state(
        self, window: MainWindow, tmp_path: Path, populated_db: tuple[Path, int, int]
    ) -> None:
        """Nach dem Ansichts-Reset darf ein Undo-Snapshot KEIN Sample-Highlight
        ohne sichtbares Dataset erzeugen (kein inkonsistenter persistierter State).
        """
        _db_path, _eng_id, ds_id = populated_db
        ctrl = self._open_and_select(window, tmp_path, populated_db)
        # Echte Sample-ID merken (überlebt das Ansicht-Leeren, da kein DB-Delete).
        assert ctrl.session.db is not None
        real_sample_id = SampleRepo(ctrl.session.db.connect()).list_for_dataset(ds_id)[0].id
        assert real_sample_id is not None

        with patch(_QUESTION, return_value=QMessageBox.StandardButton.Yes):
            ctrl.workspace.handle_clear_loaded_datasets()
        assert ctrl.session.dataset is None

        # Snapshot mit EXISTIERENDER Sample-ID → ohne Guard würde das Sample
        # restauriert (Highlight ohne Dataset). Mit Guard: leerer State.
        snap = Snapshot(
            stack_type=UndoStack.UNDO,
            position=0,
            sample_id=real_sample_id,
            highlighted_rows=(2, 4),
            visible_rows=(2, 4),
        )
        ctrl.workspace._apply_snapshot(snap)
        assert ctrl.session.sample is None
        assert ctrl.session.active_sample_id is None
        assert ctrl.session.filter_active_sample_id is None
        ctrl.handle_close_engagement()
