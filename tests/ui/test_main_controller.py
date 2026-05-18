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
from sampling_tool.ui.dialogs.duplicate_engagement_dialog import (
    DuplicateEngagementChoice,
    DuplicateEngagementDialog,
)
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
    rows = tuple(
        DatasetRow(row_id=i, values={"Konto": f"K{i}", "Betrag": i * 10}) for i in range(1, 6)
    )
    dataset = ds_repo.create(
        Dataset(name="Buchungen", columns=("Konto", "Betrag"), engagement_id=eng.id),
        rows,
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


def _make_stub_new_dialog(
    parent: MainWindow, target_db: Path, client_name: str
) -> NewEngagementDialog:
    """Liefert ein stub-`NewEngagementDialog`, das ohne UI-Interaktion accepted."""

    class _StubDialog(NewEngagementDialog):
        def exec(self) -> int:
            self._db_path = target_db
            return int(QDialog.DialogCode.Accepted)

        def get_engagement(self) -> Engagement:
            return Engagement(
                auditor_name="Anna",
                auditor_position="Senior",
                client_name=client_name,
                audit_type="ISAE 3402",
            )

    return _StubDialog(parent)


def _make_stub_duplicate_dialog(
    parent: MainWindow,
    db_path: Path,
    choice: DuplicateEngagementChoice,
) -> DuplicateEngagementDialog:
    """Stub des DuplicateDialogs, der ohne UI sofort das gewünschte Choice liefert."""

    class _StubDuplicate(DuplicateEngagementDialog):
        def exec(self) -> int:
            self._choice = choice
            return int(
                QDialog.DialogCode.Accepted
                if choice is not DuplicateEngagementChoice.CANCEL
                else QDialog.DialogCode.Rejected
            )

    return _StubDuplicate(db_path, parent)


def _record_duplicate(
    calls: list[Path],
    parent: MainWindow,
    db_path: Path,
    choice: DuplicateEngagementChoice,
) -> DuplicateEngagementDialog:
    """Wie `_make_stub_duplicate_dialog`, protokolliert aber den Aufruf in `calls`."""
    calls.append(db_path)
    return _make_stub_duplicate_dialog(parent, db_path, choice)


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
            dialog_factory=lambda parent, _settings, _prefill: _StubDialog(parent),
        )
        try:
            controller.handle_new_engagement()
            assert target_db.exists()
            assert window.is_workspace_visible() is True
            assert recent_store.list()[0].path == target_db.resolve()
        finally:
            controller.handle_close_engagement()

    def test_new_engagement_no_duplicate_skips_duplicate_dialog(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        tmp_path: Path,
    ) -> None:
        target_db = tmp_path / "fresh.db"
        duplicate_calls: list[Path] = []

        controller = MainController(
            window,
            recent_store=recent_store,
            dialog_factory=lambda parent, _s, _p: _make_stub_new_dialog(parent, target_db, "ACME"),
            duplicate_dialog_factory=lambda parent, db_path: _record_duplicate(
                duplicate_calls, parent, db_path, DuplicateEngagementChoice.CANCEL
            ),
        )
        try:
            controller.handle_new_engagement()
            assert target_db.exists()
            assert duplicate_calls == [], "DuplicateDialog darf nicht erscheinen"
            assert window.is_workspace_visible() is True
        finally:
            controller.handle_close_engagement()

    def test_new_engagement_with_duplicate_open_existing_opens_db(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        controller = MainController(
            window,
            recent_store=recent_store,
            dialog_factory=lambda parent, _s, _p: _make_stub_new_dialog(
                parent, populated_db, "ACME"
            ),
            duplicate_dialog_factory=lambda parent, db_path: _make_stub_duplicate_dialog(
                parent, db_path, DuplicateEngagementChoice.OPEN_EXISTING
            ),
        )
        try:
            controller.handle_new_engagement()
            assert window.is_workspace_visible() is True
            # Bestehende DB nicht überschrieben → Sample-Eintrag aus Fixture noch da.
            assert window.sidebar().datasets_widget().count() == 1
        finally:
            controller.handle_close_engagement()

    def test_new_engagement_with_duplicate_rename_reopens_new_dialog(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        tmp_path: Path,
    ) -> None:
        existing = tmp_path / "ACME.db"
        existing.touch()
        fresh = tmp_path / "ACME2.db"
        new_dialog_calls: list[Engagement | None] = []

        def _new_factory(
            parent: MainWindow,
            _settings: object,
            prefill: Engagement | None,
        ) -> NewEngagementDialog:
            new_dialog_calls.append(prefill)
            target = existing if len(new_dialog_calls) == 1 else fresh
            return _make_stub_new_dialog(parent, target, "ACME")

        # Erster Aufruf liefert RENAME, zweiter würde nicht mehr aufgerufen
        # weil der zweite NewEngagementDialog `fresh` zurückgibt (existiert nicht).
        duplicate_dialog_calls: list[Path] = []

        def _dup_factory(parent: MainWindow, db_path: Path) -> DuplicateEngagementDialog:
            duplicate_dialog_calls.append(db_path)
            return _make_stub_duplicate_dialog(parent, db_path, DuplicateEngagementChoice.RENAME)

        controller = MainController(
            window,
            recent_store=recent_store,
            dialog_factory=_new_factory,
            duplicate_dialog_factory=_dup_factory,
        )
        try:
            controller.handle_new_engagement()
            assert len(new_dialog_calls) == 2, "NewEngagementDialog muss erneut geöffnet werden"
            # Zweiter Aufruf bekommt das vorher eingegebene Engagement als Prefill.
            assert new_dialog_calls[0] is None
            assert new_dialog_calls[1] is not None
            assert new_dialog_calls[1].client_name == "ACME"
            assert duplicate_dialog_calls == [existing]
            assert fresh.exists()
            assert window.is_workspace_visible() is True
        finally:
            controller.handle_close_engagement()

    def test_new_engagement_with_duplicate_cancel_aborts(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        tmp_path: Path,
    ) -> None:
        existing = tmp_path / "blocked.db"
        existing.write_bytes(b"sentinel-bytes")
        before = existing.read_bytes()

        controller = MainController(
            window,
            recent_store=recent_store,
            dialog_factory=lambda parent, _s, _p: _make_stub_new_dialog(
                parent, existing, "Blocked"
            ),
            duplicate_dialog_factory=lambda parent, db_path: _make_stub_duplicate_dialog(
                parent, db_path, DuplicateEngagementChoice.CANCEL
            ),
        )
        try:
            controller.handle_new_engagement()
            assert window.is_workspace_visible() is False
            assert existing.read_bytes() == before, (
                "Bestehende Datei darf nicht überschrieben werden"
            )
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
        factory = lambda _p, _d, _r, _s, _am: _StubSamplingDialog(result)  # noqa: E731
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
        factory = lambda _p, _d, _r, _s, _am: _StubSamplingDialog(result)  # noqa: E731
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
        factory = lambda _p, _d, _r, _s, _am: _StubSamplingDialog(result)  # noqa: E731
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
        from sampling_tool.ui.dialogs.export_audit_pdf_dialog import (
            ExportAuditPdfDialogResult,
        )

        target = tmp_path / "trail.pdf"
        result = ExportAuditPdfDialogResult(
            output_path=target,
            date_from=None,
            date_to=None,
            event_types=set(),
            use_briefpapier=False,
            include_statistics=True,
        )
        factory = lambda *args, **kw: _StubExportDialog(result)  # noqa: E731
        controller = MainController(
            window,
            recent_store=recent_store,
            audit_pdf_dialog_factory=factory,  # type: ignore[arg-type]
        )
        try:
            controller.handle_open_engagement(populated_db)
            with patch("sampling_tool.ui.controllers.main_controller.QMessageBox.information"):
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
    rows_ab = tuple(DatasetRow(row_id=i, values={"a": i}) for i in range(1, 4))
    ds1 = ds_repo.create(
        Dataset(name="First", columns=("a",), engagement_id=eng.id),
        rows_ab,
    )
    ds2 = ds_repo.create(
        Dataset(name="Second", columns=("a",), engagement_id=eng.id),
        rows_ab,
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
        factory = lambda _p, _d, _r, _s, _am: _StubSamplingDialog(result)  # noqa: E731
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
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
        tmp_path: Path,
    ) -> None:
        from sampling_tool.ui.dialogs.export_excel_report_dialog import (
            ExportExcelReportDialogResult,
        )

        target = tmp_path / "bericht.xlsx"
        result = ExportExcelReportDialogResult(
            output_path=target,
            sheets={"Übersicht", "AuditTrail", "Samples", "Statistiken"},
        )
        factory = lambda *args, **kw: _StubExportDialog(result)  # noqa: E731
        controller = MainController(
            window,
            recent_store=recent_store,
            excel_report_dialog_factory=factory,  # type: ignore[arg-type]
        )
        try:
            controller.handle_open_engagement(populated_db)
            with patch("sampling_tool.ui.controllers.main_controller.QMessageBox.information"):
                controller.handle_export_excel_report()
            assert target.exists()
        finally:
            controller.handle_close_engagement()

    def test_handle_export_html_report_writes_file(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
        tmp_path: Path,
    ) -> None:
        from sampling_tool.ui.dialogs.export_html_report_dialog import (
            ExportHtmlReportDialogResult,
        )

        target = tmp_path / "bericht.html"
        result = ExportHtmlReportDialogResult(
            output_path=target,
            include_charts=True,
            include_audit_trail=True,
            include_samples_table=True,
        )
        factory = lambda *args, **kw: _StubExportDialog(result)  # noqa: E731
        controller = MainController(
            window,
            recent_store=recent_store,
            html_report_dialog_factory=factory,  # type: ignore[arg-type]
        )
        try:
            controller.handle_open_engagement(populated_db)
            with patch("sampling_tool.ui.controllers.main_controller.QMessageBox.information"):
                controller.handle_export_html_report()
            assert target.exists()
            content = target.read_text(encoding="utf-8")
            assert "ACME" in content
        finally:
            controller.handle_close_engagement()

    def test_refresh_views_resets_to_empty_on_close(
        self,
        controller: MainController,
        window: MainWindow,
        populated_db: Path,
    ) -> None:
        controller.handle_open_engagement(populated_db)
        controller.handle_close_engagement()
        assert window.audit_trail_view().model()._events == []


class TestUnifiedExportDialogs:
    """Sprint 6.1: Handler nutzen Dialog-Factories und filtern korrekt."""

    def test_audit_pdf_handler_filters_events_by_type(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
        tmp_path: Path,
    ) -> None:
        """Mit `event_types={"import"}` muss das PDF nur Import-Events enthalten."""
        from sampling_tool.audit.logger import AuditLogger
        from sampling_tool.persistence.database import Database
        from sampling_tool.persistence.repositories import AuditRepo, SampleRepo
        from sampling_tool.ui.dialogs.export_audit_pdf_dialog import (
            ExportAuditPdfDialogResult,
        )

        # Drei verschiedene Events in die DB schreiben.
        db = Database(populated_db)
        db.migrate()
        sample_repo = SampleRepo(db.connect())
        sample = sample_repo.list_for_dataset(1)[0]
        assert sample.id is not None
        logger_ = AuditLogger(AuditRepo(db.connect()), "tester", 1)
        logger_.log_sampling(sample, sample.id)
        logger_.log_export(sample.id, tmp_path / "x.xlsx", 2)
        db.close()

        target = tmp_path / "trail.pdf"
        result = ExportAuditPdfDialogResult(
            output_path=target,
            date_from=None,
            date_to=None,
            event_types={"sampling"},
            use_briefpapier=False,
            include_statistics=True,
        )
        factory = lambda *args, **kw: _StubExportDialog(result)  # noqa: E731
        controller = MainController(
            window,
            recent_store=recent_store,
            audit_pdf_dialog_factory=factory,  # type: ignore[arg-type]
        )
        try:
            controller.handle_open_engagement(populated_db)
            with patch(
                "sampling_tool.ui.controllers.main_controller.QMessageBox.information"
            ) as info:
                controller.handle_export_audit_pdf()
            # Info-Text enthält Anzahl der gefilterten Events.
            assert info.called
            args = info.call_args[0]
            assert "1 Events" in args[2]
        finally:
            controller.handle_close_engagement()

    def test_audit_pdf_handler_cancelled_returns_silently(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
        tmp_path: Path,
    ) -> None:
        factory = lambda *args, **kw: _StubExportDialog(None, accept=False)  # noqa: E731
        controller = MainController(
            window,
            recent_store=recent_store,
            audit_pdf_dialog_factory=factory,  # type: ignore[arg-type]
        )
        try:
            controller.handle_open_engagement(populated_db)
            controller.handle_export_audit_pdf()
            assert not list(tmp_path.glob("*.pdf"))
        finally:
            controller.handle_close_engagement()

    def test_excel_report_handler_passes_sheets_subset(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
        tmp_path: Path,
    ) -> None:
        from openpyxl import load_workbook

        from sampling_tool.ui.dialogs.export_excel_report_dialog import (
            ExportExcelReportDialogResult,
        )

        target = tmp_path / "subset.xlsx"
        result = ExportExcelReportDialogResult(
            output_path=target,
            sheets={"Übersicht"},
        )
        factory = lambda *args, **kw: _StubExportDialog(result)  # noqa: E731
        controller = MainController(
            window,
            recent_store=recent_store,
            excel_report_dialog_factory=factory,  # type: ignore[arg-type]
        )
        try:
            controller.handle_open_engagement(populated_db)
            with patch("sampling_tool.ui.controllers.main_controller.QMessageBox.information"):
                controller.handle_export_excel_report()
            assert target.exists()
            wb = load_workbook(target)
            assert len(wb.sheetnames) == 1
        finally:
            controller.handle_close_engagement()


class TestSettingsIntegration:
    """Settings beeinflussen Default-Werte beim Controller."""

    def test_init_uses_provided_settings(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        tmp_path: Path,
    ) -> None:
        from dataclasses import replace

        from sampling_tool.ui.settings_store import AppSettings

        custom_dir = tmp_path / "my-engagements"
        settings = replace(AppSettings.defaults(), engagements_dir=custom_dir)
        MainController(window, recent_store=recent_store, settings=settings)
        assert custom_dir.exists()

    def test_handle_settings_persists_new_values(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from PyQt6.QtCore import QSettings

        from sampling_tool.config import APP_NAME, APP_ORG
        from sampling_tool.ui.dialogs.settings_dialog import SettingsDialog
        from sampling_tool.ui.settings_store import AppSettings

        # QSettings in tmp_path isolieren, damit echte Prefs nicht angefasst werden.
        monkeypatch.setattr(
            "sampling_tool.ui.settings_store._qsettings",
            lambda: QSettings(
                QSettings.Format.IniFormat,
                QSettings.Scope.UserScope,
                APP_ORG,
                APP_NAME,
            ),
        )
        QSettings.setPath(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            str(tmp_path),
        )
        from dataclasses import replace

        new_settings = replace(
            AppSettings.defaults(), default_auditor_name="Updated", undo_depth=33
        )

        class _StubSettingsDialog(SettingsDialog):
            def exec(self) -> int:
                self._result = new_settings
                return int(QDialog.DialogCode.Accepted)

        controller = MainController(
            window,
            recent_store=recent_store,
            settings_dialog_factory=lambda parent, current: _StubSettingsDialog(current, parent),
        )
        controller.handle_settings()
        from sampling_tool.ui.settings_store import load_settings

        assert controller._settings.default_auditor_name == "Updated"
        loaded = load_settings()
        assert loaded.default_auditor_name == "Updated"
        assert loaded.undo_depth == 33

    def test_audit_pdf_dialog_receives_settings_defaults(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        from sampling_tool.ui.dialogs.export_audit_pdf_dialog import ExportAuditPdfDialog
        from sampling_tool.ui.settings_store import AppSettings

        captured: dict[str, object] = {}
        from dataclasses import replace

        settings = replace(
            AppSettings.defaults(),
            default_include_briefpapier=False,
            default_include_statistics=False,
        )

        def factory(  # type: ignore[no-untyped-def]
            parent,
            engagement,
            available,
            bp_available,
            default_dir,
            default_use_briefpapier,
            default_include_statistics,
        ):
            captured["default_use_briefpapier"] = default_use_briefpapier
            captured["default_include_statistics"] = default_include_statistics

            dialog = ExportAuditPdfDialog(
                engagement=engagement,
                event_types_available=available,
                briefpapier_available=bp_available,
                parent=parent,
                default_output_dir=default_dir,
                default_use_briefpapier=default_use_briefpapier,
                default_include_statistics=default_include_statistics,
            )

            def reject() -> int:
                return int(QDialog.DialogCode.Rejected)

            dialog.exec = reject  # type: ignore[method-assign]
            return dialog

        controller = MainController(
            window,
            recent_store=recent_store,
            audit_pdf_dialog_factory=factory,
            settings=settings,
        )
        try:
            controller.handle_open_engagement(populated_db)
            controller.handle_export_audit_pdf()
            assert captured["default_use_briefpapier"] is False
            assert captured["default_include_statistics"] is False
        finally:
            controller.handle_close_engagement()

    def test_reset_keeps_filter_when_setting_enabled(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from dataclasses import replace

        from PyQt6.QtWidgets import QMessageBox

        from sampling_tool.ui.settings_store import AppSettings

        settings = replace(AppSettings.defaults(), reset_keeps_filter=True)
        controller = MainController(window, recent_store=recent_store, settings=settings)
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes
        )
        try:
            controller.handle_open_engagement(populated_db)
            _open_dataset(controller, window, populated_db)
            controller.handle_sample_selected(_first_item_data(window.sidebar().samples_widget()))
            controller.handle_filter_only_sample_toggled(True)
            assert controller._filter_active_sample_id is not None
            controller.handle_reset()
            # Filter bleibt aktiv (Setting), aber Sample-Highlight ist weg.
            assert controller._sample is None
            assert controller._filter_active_sample_id is not None
        finally:
            controller.handle_close_engagement()

    def test_resolve_briefpapier_uses_setting_override(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        tmp_path: Path,
    ) -> None:
        from sampling_tool.ui.settings_store import AppSettings

        custom_pdf = tmp_path / "my_letter.pdf"
        custom_pdf.write_bytes(b"%PDF-1.4\n%\xc4\xe5\xf2\xe5\xeb\xa7\xf3\xa0\xd0\xc4\xc6\n")
        from dataclasses import replace

        settings = replace(AppSettings.defaults(), custom_briefpapier_path=custom_pdf)
        controller = MainController(window, recent_store=recent_store, settings=settings)
        cfg = controller._resolve_briefpapier()
        assert cfg is not None
        assert cfg.background_image == custom_pdf


class TestEngagementStateRestore:
    """Sprint 8.2 – aktiver Sample-State überlebt Schließen/Öffnen."""

    def test_no_state_on_first_open(
        self,
        controller: MainController,
        window: MainWindow,
        populated_db: Path,
    ) -> None:
        controller.handle_open_engagement(populated_db)
        assert controller._sample is None
        assert controller._active_sample_id is None
        assert controller._filter_active_sample_id is None

    def test_sample_selection_is_persisted(
        self,
        controller: MainController,
        window: MainWindow,
        populated_db: Path,
    ) -> None:
        controller.handle_open_engagement(populated_db)
        ds_id = _first_item_data(window.sidebar().datasets_widget())
        controller.handle_dataset_selected(ds_id)
        sample_id = _first_item_data(window.sidebar().samples_widget())
        controller.handle_sample_selected(sample_id)

        assert controller._state_repo is not None
        assert controller._engagement is not None
        assert controller._engagement.id is not None
        state = controller._state_repo.get(controller._engagement.id)
        assert state is not None
        assert state.active_dataset_id == ds_id
        assert state.active_sample_id == sample_id

    def test_restore_reapplies_sample_highlight_and_filter(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        # Session 1: Sample auswählen, Filter aktivieren, schließen.
        ctrl1 = MainController(window, recent_store=recent_store)
        try:
            ctrl1.handle_open_engagement(populated_db)
            ds_id = _first_item_data(window.sidebar().datasets_widget())
            ctrl1.handle_dataset_selected(ds_id)
            sample_id = _first_item_data(window.sidebar().samples_widget())
            ctrl1.handle_sample_filter_toggled(sample_id)
            assert window.data_table().table_model().rowCount() == 2
        finally:
            ctrl1.handle_close_engagement()

        # Session 2: gleiches Engagement erneut öffnen – State muss da sein.
        ctrl2 = MainController(window, recent_store=recent_store)
        try:
            ctrl2.handle_open_engagement(populated_db)
            assert ctrl2._sample is not None
            assert ctrl2._sample.id == sample_id
            assert ctrl2._filter_active_sample_id == sample_id
            assert window.data_table().table_model().rowCount() == 2
            highlights = window.data_table().table_model().highlighted_row_ids()
            assert highlights == frozenset({2, 4})
        finally:
            ctrl2.handle_close_engagement()

    def test_restore_without_filter(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        # Session 1: Sample auswählen ohne Filter (Default ohne Toggle).
        ctrl1 = MainController(window, recent_store=recent_store)
        try:
            ctrl1.handle_open_engagement(populated_db)
            ds_id = _first_item_data(window.sidebar().datasets_widget())
            ctrl1.handle_dataset_selected(ds_id)
            sample_id = _first_item_data(window.sidebar().samples_widget())
            ctrl1.handle_sample_selected(sample_id)
            # Filter NICHT aktiv – nur Highlight.
            assert ctrl1._filter_active_sample_id is None
            assert window.data_table().table_model().rowCount() == 5
        finally:
            ctrl1.handle_close_engagement()

        ctrl2 = MainController(window, recent_store=recent_store)
        try:
            ctrl2.handle_open_engagement(populated_db)
            assert ctrl2._sample is not None
            assert ctrl2._filter_active_sample_id is None
            # Tabelle ungefiltert, aber Highlight da.
            assert window.data_table().table_model().rowCount() == 5
            highlights = window.data_table().table_model().highlighted_row_ids()
            assert highlights == frozenset({2, 4})
        finally:
            ctrl2.handle_close_engagement()

    def test_restore_survives_deleted_sample(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        # State auf nicht-existentes Sample setzen. Dafür FK kurzzeitig
        # ausschalten – produktiv simulieren wir den Fall, dass eine
        # spätere App-Version die Sample-Tabelle anders aufräumt.
        db = Database(populated_db)
        db.migrate()
        eng = EngagementRepo(db.connect()).get()
        assert eng is not None
        assert eng.id is not None

        conn = db.connect()
        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.execute(
                "INSERT INTO engagement_state "
                "(engagement_id, active_dataset_id, active_sample_id, filter_active) "
                "VALUES (?, ?, ?, ?)",
                (eng.id, 999999, 888888, 1),
            )
        finally:
            conn.execute("PRAGMA foreign_keys = ON")
        db.close()

        # Öffnen darf nicht crashen, State wird stillschweigend ignoriert.
        controller = MainController(window, recent_store=recent_store)
        try:
            controller.handle_open_engagement(populated_db)
            assert controller._sample is None
            assert window.is_workspace_visible() is True
        finally:
            controller.handle_close_engagement()

    def test_reset_clears_persisted_sample(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from PyQt6.QtWidgets import QMessageBox

        monkeypatch.setattr(
            QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes
        )
        controller = MainController(window, recent_store=recent_store)
        try:
            controller.handle_open_engagement(populated_db)
            ds_id = _first_item_data(window.sidebar().datasets_widget())
            controller.handle_dataset_selected(ds_id)
            sample_id = _first_item_data(window.sidebar().samples_widget())
            controller.handle_sample_selected(sample_id)
            controller.handle_reset()

            assert controller._state_repo is not None
            assert controller._engagement is not None
            assert controller._engagement.id is not None
            state = controller._state_repo.get(controller._engagement.id)
            assert state is not None
            assert state.active_sample_id is None
            assert state.filter_active is False
        finally:
            controller.handle_close_engagement()


# ---------------------------------------------------------------------------
# Sprint 9.3: Advanced-Mode wird an SamplingDialog-Factory durchgereicht
# ---------------------------------------------------------------------------


class TestAdvancedModePropagation:
    def test_controller_uebergibt_advanced_mode_false_an_factory(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        from dataclasses import replace as dc_replace

        from sampling_tool.ui.settings_store import AppSettings

        received: dict[str, bool] = {}

        def fake_factory(
            _parent: MainWindow,
            _dataset: object,
            _rows: object,
            _current: object,
            advanced_mode: bool,
        ) -> _StubSamplingDialog:
            received["advanced_mode"] = advanced_mode
            return _StubSamplingDialog(None, accept=False)

        controller = MainController(
            window,
            recent_store=recent_store,
            sampling_dialog_factory=fake_factory,  # type: ignore[arg-type]
            settings=dc_replace(AppSettings.defaults(), advanced_mode=False),
        )
        try:
            _open_dataset(controller, window, populated_db)
            controller.handle_new_sampling()
            assert received["advanced_mode"] is False
        finally:
            controller.handle_close_engagement()

    def test_controller_uebergibt_advanced_mode_true_an_factory(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        from dataclasses import replace as dc_replace

        from sampling_tool.ui.settings_store import AppSettings

        received: dict[str, bool] = {}

        def fake_factory(
            _parent: MainWindow,
            _dataset: object,
            _rows: object,
            _current: object,
            advanced_mode: bool,
        ) -> _StubSamplingDialog:
            received["advanced_mode"] = advanced_mode
            return _StubSamplingDialog(None, accept=False)

        controller = MainController(
            window,
            recent_store=recent_store,
            sampling_dialog_factory=fake_factory,  # type: ignore[arg-type]
            settings=dc_replace(AppSettings.defaults(), advanced_mode=True),
        )
        try:
            _open_dataset(controller, window, populated_db)
            controller.handle_new_sampling()
            assert received["advanced_mode"] is True
        finally:
            controller.handle_close_engagement()


# ---------------------------------------------------------------------------
# Sprint 9.4: Panel-Sichtbarkeit (Dashboard / AuditTrail) wird live angewendet
# ---------------------------------------------------------------------------


class TestPanelVisibilityWiring:
    def test_init_wendet_panel_visibility_aus_settings_an(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
    ) -> None:
        from dataclasses import replace as dc_replace

        from sampling_tool.ui.settings_store import AppSettings

        settings = dc_replace(AppSettings.defaults(), show_dashboard=False, show_audit_trail=True)
        MainController(window, recent_store=recent_store, settings=settings)
        # Initialer Controller-Aufruf hat Sichtbarkeit gesetzt.
        assert window._lower_tabs.indexOf(window._dashboard_view) == -1
        assert window._lower_tabs.indexOf(window._audit_trail_view) != -1

    def test_handle_settings_wendet_neue_panel_visibility_an(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
    ) -> None:
        from dataclasses import replace as dc_replace

        from sampling_tool.ui.dialogs.settings_dialog import SettingsDialog
        from sampling_tool.ui.settings_store import AppSettings

        defaults = AppSettings.defaults()
        new_settings = dc_replace(defaults, show_dashboard=False, show_audit_trail=False)

        class _StubSettingsDialog(SettingsDialog):
            def exec(self) -> int:
                self._result = new_settings
                return int(QDialog.DialogCode.Accepted)

        controller = MainController(
            window,
            recent_store=recent_store,
            settings_dialog_factory=lambda _p, _s: _StubSettingsDialog(defaults),
            settings=defaults,
        )
        controller.handle_settings()
        # Beide Tabs sind weg.
        assert window._lower_tabs.count() == 0
        assert window._lower_tabs.isVisible() is False
