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


# ---------------------------------------------------------------------------
# Sprint-5: Sampling-Flow, Reset, Undo/Redo, Export
# ---------------------------------------------------------------------------


class _StubSamplingDialog:
    """Mini-Stub statt `SamplingDialog`. Liefert ein vordefiniertes Result."""

    DialogCode = QDialog.DialogCode

    def __init__(self, result_obj: object, accept: bool = True) -> None:
        self._result = result_obj
        self._accept = accept

    def exec(self) -> int:
        return int(QDialog.DialogCode.Accepted if self._accept else QDialog.DialogCode.Rejected)

    def get_result(self) -> object:
        return self._result


class _StubExportDialog:
    DialogCode = QDialog.DialogCode

    def __init__(self, result_obj: object, accept: bool = True) -> None:
        self._result = result_obj
        self._accept = accept

    def exec(self) -> int:
        return int(QDialog.DialogCode.Accepted if self._accept else QDialog.DialogCode.Rejected)

    def get_result(self) -> object:
        return self._result


def _open_dataset(controller: MainController, window: MainWindow, db_path: Path) -> int:
    controller.handle_open_engagement(db_path)
    ds_id = _first_item_data(window.sidebar().datasets_widget())
    controller.handle_dataset_selected(ds_id)
    return ds_id


class TestSamplingFlow:
    def test_new_sampling_creates_sample_and_highlights(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        from sampling_tool.core.models import SampleConfig, SamplingMethod
        from sampling_tool.ui.dialogs.sampling_dialog import SamplingDialogResult

        result = SamplingDialogResult(
            config=SampleConfig(method=SamplingMethod.SIMPLE, size=2, seed=7),
            from_sample_only=False,
        )
        factory = lambda _p, _d, _s: _StubSamplingDialog(result)  # noqa: E731
        controller = MainController(
            window,
            recent_store=recent_store,
            sampling_dialog_factory=factory,  # type: ignore[arg-type]
        )
        try:
            _open_dataset(controller, window, populated_db)
            samples_before = window.sidebar().samples_widget().count()
            controller.handle_new_sampling()
            samples_after = window.sidebar().samples_widget().count()
            assert samples_after == samples_before + 1
            highlighted = window.data_table().table_model().highlighted_row_ids()
            assert len(highlighted) == 2
        finally:
            controller.handle_close_engagement()

    def test_reset_clears_highlight_with_confirmation(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        controller = MainController(window, recent_store=recent_store)
        try:
            _open_dataset(controller, window, populated_db)
            controller.handle_sample_selected(_first_item_data(window.sidebar().samples_widget()))
            with patch(
                "sampling_tool.ui.controllers.main_controller.QMessageBox.question",
                return_value=__import__(
                    "PyQt6.QtWidgets", fromlist=["QMessageBox"]
                ).QMessageBox.StandardButton.Yes,
            ):
                controller.handle_reset()
            assert window.data_table().table_model().highlighted_row_ids() == frozenset()
        finally:
            controller.handle_close_engagement()

    def test_reset_cancelled_keeps_highlight(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        controller = MainController(window, recent_store=recent_store)
        try:
            _open_dataset(controller, window, populated_db)
            controller.handle_sample_selected(_first_item_data(window.sidebar().samples_widget()))
            from PyQt6.QtWidgets import QMessageBox

            with patch(
                "sampling_tool.ui.controllers.main_controller.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ):
                controller.handle_reset()
            # Highlight unverändert
            assert len(window.data_table().table_model().highlighted_row_ids()) == 2
        finally:
            controller.handle_close_engagement()

    def test_undo_redo_round_trip(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        from sampling_tool.core.models import SampleConfig, SamplingMethod
        from sampling_tool.ui.dialogs.sampling_dialog import SamplingDialogResult

        result = SamplingDialogResult(
            config=SampleConfig(method=SamplingMethod.SIMPLE, size=3, seed=11),
            from_sample_only=False,
        )
        factory = lambda _p, _d, _s: _StubSamplingDialog(result)  # noqa: E731
        controller = MainController(
            window,
            recent_store=recent_store,
            sampling_dialog_factory=factory,  # type: ignore[arg-type]
        )
        try:
            _open_dataset(controller, window, populated_db)
            controller.handle_new_sampling()
            after_sampling = window.data_table().table_model().highlighted_row_ids()
            assert len(after_sampling) == 3

            controller.handle_undo()
            # Vorheriger Zustand: kein Sample (vor dem ersten Sampling-Push gab es nichts).
            assert window.data_table().table_model().highlighted_row_ids() == frozenset()

            controller.handle_redo()
            assert window.data_table().table_model().highlighted_row_ids() == after_sampling
        finally:
            controller.handle_close_engagement()

    def test_resample_filters_to_current_sample(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        from sampling_tool.core.models import SampleConfig, SamplingMethod
        from sampling_tool.ui.dialogs.sampling_dialog import SamplingDialogResult

        result = SamplingDialogResult(
            config=SampleConfig(method=SamplingMethod.SIMPLE, size=1, seed=3),
            from_sample_only=True,
        )
        factory = lambda _p, _d, _s: _StubSamplingDialog(result)  # noqa: E731
        controller = MainController(
            window,
            recent_store=recent_store,
            sampling_dialog_factory=factory,  # type: ignore[arg-type]
        )
        try:
            _open_dataset(controller, window, populated_db)
            # Vorhandenes Sample auswählen (row_ids 2,4 aus dem Fixture)
            controller.handle_sample_selected(_first_item_data(window.sidebar().samples_widget()))
            controller.handle_new_sampling()
            new_highlight = window.data_table().table_model().highlighted_row_ids()
            assert new_highlight  # mindestens eine
            # Die neue Auswahl darf nur row_ids aus dem Vorsample enthalten.
            assert new_highlight.issubset({2, 4})
        finally:
            controller.handle_close_engagement()

    def test_export_sample_calls_excel_exporter(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
        tmp_path: Path,
    ) -> None:
        from sampling_tool.ui.dialogs.export_sample_dialog import ExportSampleDialogResult

        export_result = ExportSampleDialogResult(
            columns=["Konto", "Betrag"],
            custom_name="testname",
            custom_id="42",
            output_dir=tmp_path,
        )
        factory = lambda *args, **kw: _StubExportDialog(export_result)  # noqa: E731
        controller = MainController(
            window,
            recent_store=recent_store,
            export_dialog_factory=factory,  # type: ignore[arg-type]
        )
        try:
            _open_dataset(controller, window, populated_db)
            controller.handle_sample_selected(_first_item_data(window.sidebar().samples_widget()))
            with patch("sampling_tool.ui.controllers.main_controller.QMessageBox.information"):
                controller.handle_export_sample()
            files = list(tmp_path.glob("testname_ID42_BDO_sampling_*.xlsx"))
            assert len(files) == 1
        finally:
            controller.handle_close_engagement()

    def test_export_audit_pdf_writes_file(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
        tmp_path: Path,
    ) -> None:
        controller = MainController(window, recent_store=recent_store)
        try:
            controller.handle_open_engagement(populated_db)
            target = tmp_path / "trail.pdf"
            with (
                patch(
                    "sampling_tool.ui.controllers.main_controller.QFileDialog.getSaveFileName",
                    return_value=(str(target), ""),
                ),
                patch("sampling_tool.ui.controllers.main_controller.QMessageBox.information"),
            ):
                controller.handle_export_audit_pdf()
            assert target.exists()
            assert target.stat().st_size > 0
        finally:
            controller.handle_close_engagement()

    def test_undo_redo_state_after_open_engagement(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        controller = MainController(window, recent_store=recent_store)
        try:
            controller.handle_open_engagement(populated_db)
            # Frisches Engagement: weder Undo noch Redo verfügbar.
            assert window._action_undo.isEnabled() is False
            assert window._action_redo.isEnabled() is False
        finally:
            controller.handle_close_engagement()


# ---------------------------------------------------------------------------
# Sprint-5.5: Dataset-Klick + Highlight-Persistenz + Versionierung
# ---------------------------------------------------------------------------


def _two_dataset_db(tmp_path: Path) -> tuple[Path, int, int, int]:
    """Engagement mit zwei Datasets und einem Sample am ersten."""
    db_path = tmp_path / "two.db"
    db = Database(db_path)
    db.migrate()
    eng = EngagementRepo(db.connect()).get_or_create(
        Engagement(auditor_name="Anna", client_name="ACME", audit_type="ISAE 3402")
    )
    assert eng.id is not None
    ds_repo = DatasetRepo(db.connect())
    ds1 = ds_repo.create(
        Dataset(
            name="First",
            columns=("a",),
            rows=tuple(DatasetRow(row_id=i, values={"a": i}) for i in range(1, 4)),
            engagement_id=eng.id,
        )
    )
    ds2 = ds_repo.create(
        Dataset(
            name="Second",
            columns=("a",),
            rows=tuple(DatasetRow(row_id=i, values={"a": i}) for i in range(1, 4)),
            engagement_id=eng.id,
        )
    )
    assert ds1.id is not None
    assert ds2.id is not None
    sample_id = SampleRepo(db.connect()).create_from_result(
        SampleResult(
            config=SampleConfig(method=SamplingMethod.SIMPLE, size=2, seed=1),
            selected_row_ids=(1, 3),
            population_size=3,
        ),
        ds1.id,
        "test",
    )
    db.close()
    return db_path, ds1.id, ds2.id, sample_id


class TestDatasetClickPreservesHighlight:
    def test_clicking_same_dataset_keeps_highlight(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        tmp_path: Path,
    ) -> None:
        db_path, ds1_id, _ds2_id, sample_id = _two_dataset_db(tmp_path)
        controller = MainController(window, recent_store=recent_store)
        try:
            controller.handle_open_engagement(db_path)
            controller.handle_dataset_selected(ds1_id)
            controller.handle_sample_selected(sample_id)
            before = window.data_table().table_model().highlighted_row_ids()
            controller.handle_dataset_selected(ds1_id)  # gleicher Klick
            after = window.data_table().table_model().highlighted_row_ids()
            assert before == after
            assert before == frozenset({1, 3})
        finally:
            controller.handle_close_engagement()

    def test_clicking_other_dataset_clears_highlight_when_sample_unrelated(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        tmp_path: Path,
    ) -> None:
        db_path, ds1_id, ds2_id, sample_id = _two_dataset_db(tmp_path)
        controller = MainController(window, recent_store=recent_store)
        try:
            controller.handle_open_engagement(db_path)
            controller.handle_dataset_selected(ds1_id)
            controller.handle_sample_selected(sample_id)
            controller.handle_dataset_selected(ds2_id)  # anderes Dataset
            assert window.data_table().table_model().highlighted_row_ids() == frozenset()
        finally:
            controller.handle_close_engagement()

    def test_clicking_other_dataset_reapplies_highlight_when_sample_belongs(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        tmp_path: Path,
    ) -> None:
        db_path, ds1_id, ds2_id, sample_id = _two_dataset_db(tmp_path)
        controller = MainController(window, recent_store=recent_store)
        try:
            controller.handle_open_engagement(db_path)
            controller.handle_dataset_selected(ds1_id)
            controller.handle_sample_selected(sample_id)
            # Wechsel auf ds2 → Highlight verschwindet
            controller.handle_dataset_selected(ds2_id)
            assert window.data_table().table_model().highlighted_row_ids() == frozenset()
            # Zurück zu ds1 → Highlight kommt wieder (Sample gehört wieder dazu)
            controller.handle_dataset_selected(ds1_id)
            assert window.data_table().table_model().highlighted_row_ids() == frozenset({1, 3})
        finally:
            controller.handle_close_engagement()

    def test_open_engagement_creates_snapshot(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        tmp_path: Path,
    ) -> None:
        from sampling_tool.config import ARCHIVE_DIR_NAME

        db_path, _ds1, _ds2, _s = _two_dataset_db(tmp_path)
        controller = MainController(window, recent_store=recent_store)
        try:
            controller.handle_open_engagement(db_path)
            archive = db_path.parent / ARCHIVE_DIR_NAME
            snaps = list(archive.glob("*.db"))
            assert len(snaps) == 1
        finally:
            controller.handle_close_engagement()


class TestFilterAndSwitchEngagement:
    """Sprint 5.6: Auto-Filter, Reset-Filter, Engagement schließen mit Bestätigung."""

    def test_new_sampling_activates_filter_and_checkbox(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        from sampling_tool.core.models import SampleConfig, SamplingMethod
        from sampling_tool.ui.dialogs.sampling_dialog import SamplingDialogResult

        result = SamplingDialogResult(
            config=SampleConfig(method=SamplingMethod.SIMPLE, size=2, seed=7),
            from_sample_only=False,
        )
        factory = lambda _p, _d, _s: _StubSamplingDialog(result)  # noqa: E731
        controller = MainController(
            window,
            recent_store=recent_store,
            sampling_dialog_factory=factory,  # type: ignore[arg-type]
        )
        try:
            _open_dataset(controller, window, populated_db)
            controller.handle_new_sampling()
            # Tabelle ist auf die gezogenen Zeilen reduziert.
            assert window.data_table().table_model().rowCount() == 2
            # Sidebar-Checkbox ist an.
            assert window.sidebar().is_filter_only_sample() is True
            # Statusbar-Suffix sichtbar.
            assert "gefiltert" in window._status_sample.text()
        finally:
            controller.handle_close_engagement()

    def test_reset_deactivates_filter(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        from PyQt6.QtWidgets import QMessageBox

        controller = MainController(window, recent_store=recent_store)
        try:
            _open_dataset(controller, window, populated_db)
            controller.handle_sample_selected(_first_item_data(window.sidebar().samples_widget()))
            # Filter manuell aktivieren
            controller.handle_filter_only_sample_toggled(True)
            assert window.sidebar().is_filter_only_sample() is True

            with patch(
                "sampling_tool.ui.controllers.main_controller.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                controller.handle_reset()
            assert window.sidebar().is_filter_only_sample() is False
            # Tabelle zeigt wieder alle 5 Zeilen.
            assert window.data_table().table_model().rowCount() == 5
        finally:
            controller.handle_close_engagement()

    def test_filter_only_sample_toggle_filters_and_unfilters(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        controller = MainController(window, recent_store=recent_store)
        try:
            _open_dataset(controller, window, populated_db)
            controller.handle_sample_selected(_first_item_data(window.sidebar().samples_widget()))
            controller.handle_filter_only_sample_toggled(True)
            assert window.data_table().table_model().rowCount() == 2
            controller.handle_filter_only_sample_toggled(False)
            assert window.data_table().table_model().rowCount() == 5
        finally:
            controller.handle_close_engagement()

    def test_filter_checkbox_disabled_without_sample(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        controller = MainController(window, recent_store=recent_store)
        try:
            _open_dataset(controller, window, populated_db)
            # Frisches Dataset ohne aktives Sample → Checkbox disabled.
            assert window.sidebar().filter_checkbox().isEnabled() is False
            controller.handle_sample_selected(_first_item_data(window.sidebar().samples_widget()))
            # Sample aktiv → Checkbox enabled.
            assert window.sidebar().filter_checkbox().isEnabled() is True
        finally:
            controller.handle_close_engagement()

    def test_close_request_confirmed_returns_to_welcome(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        from PyQt6.QtWidgets import QMessageBox

        controller = MainController(window, recent_store=recent_store)
        try:
            controller.handle_open_engagement(populated_db)
            with patch(
                "sampling_tool.ui.controllers.main_controller.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                controller.handle_close_engagement_requested()
            assert window.is_workspace_visible() is False
        finally:
            controller.handle_close_engagement()

    def test_close_request_cancelled_stays_in_workspace(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        from PyQt6.QtWidgets import QMessageBox

        controller = MainController(window, recent_store=recent_store)
        try:
            controller.handle_open_engagement(populated_db)
            with patch(
                "sampling_tool.ui.controllers.main_controller.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ):
                controller.handle_close_engagement_requested()
            assert window.is_workspace_visible() is True
        finally:
            controller.handle_close_engagement()

    def test_close_request_noop_when_no_engagement(
        self,
        controller: MainController,
        window: MainWindow,
    ) -> None:
        # Ohne offenes Engagement darf kein Dialog erscheinen.
        with patch("sampling_tool.ui.controllers.main_controller.QMessageBox.question") as question:
            controller.handle_close_engagement_requested()
        assert question.called is False
        assert window.is_workspace_visible() is False


class TestEngagementsDirSetup:
    def test_engagements_dir_is_created_on_init(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
    ) -> None:
        from sampling_tool.config import ENGAGEMENTS_DIR

        MainController(window, recent_store=recent_store)
        assert ENGAGEMENTS_DIR.exists()


class TestSanitizeForPath:
    def test_replaces_spaces_with_underscore(self) -> None:
        from sampling_tool.config import sanitize_for_path

        assert sanitize_for_path("A1 Telekom Austria AG") == "A1_Telekom_Austria_AG"

    def test_transliterates_umlauts(self) -> None:
        from sampling_tool.config import sanitize_for_path

        assert sanitize_for_path("Müller & Söhne GmbH") == "Mueller__Soehne_GmbH"

    def test_strips_special_chars_keeps_dash(self) -> None:
        from sampling_tool.config import sanitize_for_path

        assert sanitize_for_path("Foo-Bar/Baz?") == "Foo-BarBaz"

    def test_empty_falls_back(self) -> None:
        from sampling_tool.config import sanitize_for_path

        assert sanitize_for_path("?!") == "engagement"


# ---------------------------------------------------------------------------
# Sprint-6: Reports + Refresh-Logik
# ---------------------------------------------------------------------------


class TestSprint6Reports:
    def test_audit_trail_view_populated_after_open(
        self,
        controller: MainController,
        window: MainWindow,
        populated_db: Path,
    ) -> None:
        controller.handle_open_engagement(populated_db)
        events = window.audit_trail_view().model()._events
        # populated_db enthält noch keine Events (Sample wurde direkt
        # eingefügt, kein Logger). Aber das Modell muss gesetzt sein.
        assert isinstance(events, list)

    def test_dashboard_view_populated_after_open(
        self,
        controller: MainController,
        window: MainWindow,
        populated_db: Path,
    ) -> None:
        controller.handle_open_engagement(populated_db)
        # Dashboard sollte aus dem Empty-State raus sein, da Datasets vorhanden sind.
        dashboard = window.dashboard_view()
        assert dashboard._stack.currentWidget() is not dashboard._empty_label

    def test_audit_event_double_clicked_selects_sample(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
        import_xlsx: Path,
    ) -> None:
        """Nach einem Import sollte ein Doppelklick aufs Import-Event nichts brechen."""
        controller = MainController(window, recent_store=recent_store)
        try:
            controller.handle_open_engagement(populated_db)
            # Trigger eine Aktion mit Sample-Bezug.
            ds_id = _first_item_data(window.sidebar().datasets_widget())
            controller.handle_dataset_selected(ds_id)
            sample_id = _first_item_data(window.sidebar().samples_widget())

            # Manuell einen Sample-Event ins Audit-Log schreiben.
            from sampling_tool.audit.logger import AuditLogger
            from sampling_tool.persistence.database import Database
            from sampling_tool.persistence.repositories import AuditRepo, SampleRepo

            db = Database(populated_db)
            db.migrate()
            sample = SampleRepo(db.connect()).get_by_id(sample_id)
            assert sample is not None
            logger_ = AuditLogger(AuditRepo(db.connect()), "tester", 1)
            evt = logger_.log_sampling(sample, sample_id)
            db.close()

            controller._refresh_audit_trail()
            assert evt.id is not None
            controller.handle_audit_event_double_clicked(evt.id)
            # Sample sollte jetzt hervorgehoben sein.
            highlights = window.data_table().table_model().highlighted_row_ids()
            assert sample_id in {s for s in [sample_id]}  # smoke
            assert highlights
        finally:
            controller.handle_close_engagement()

    def test_handle_export_excel_report_writes_file(
        self,
        controller: MainController,
        window: MainWindow,
        populated_db: Path,
        tmp_path: Path,
    ) -> None:
        controller.handle_open_engagement(populated_db)
        target = tmp_path / "bericht.xlsx"
        with (
            patch(
                "sampling_tool.ui.controllers.main_controller.QFileDialog.getSaveFileName",
                return_value=(str(target), ""),
            ),
            patch("sampling_tool.ui.controllers.main_controller.QMessageBox.information"),
        ):
            controller.handle_export_excel_report()
        assert target.exists()

    def test_handle_export_html_report_writes_file(
        self,
        controller: MainController,
        window: MainWindow,
        populated_db: Path,
        tmp_path: Path,
    ) -> None:
        controller.handle_open_engagement(populated_db)
        target = tmp_path / "bericht.html"
        with (
            patch(
                "sampling_tool.ui.controllers.main_controller.QFileDialog.getSaveFileName",
                return_value=(str(target), ""),
            ),
            patch("sampling_tool.ui.controllers.main_controller.QMessageBox.information"),
        ):
            controller.handle_export_html_report()
        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert "ACME" in content

    def test_refresh_views_resets_to_empty_on_close(
        self,
        controller: MainController,
        window: MainWindow,
        populated_db: Path,
    ) -> None:
        controller.handle_open_engagement(populated_db)
        controller.handle_close_engagement()
        assert window.audit_trail_view().model()._events == []
