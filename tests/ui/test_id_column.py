"""Sprint 31: optionale ID-Spalte pro Dataset (QSettings-Store + Sidebar-Anzeige)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from openpyxl import Workbook
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from sampling_tool.config import APP_NAME, APP_ORG
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
from sampling_tool.ui.dataset_id_store import DatasetIdColumnStore
from sampling_tool.ui.main_window import MainWindow
from sampling_tool.ui.recent import RecentEngagementsStore
from sampling_tool.ui.widgets.sidebar import NavigationSidebar, format_sample_id_values

pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Schiebt `QSettings`-IO in tmp – wie `test_sampling_presets`."""
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    monkeypatch.setattr(
        "sampling_tool.ui.settings_store._qsettings",
        lambda: QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG, APP_NAME),
    )


def _sample(sample_id: int, size: int = 3) -> SampleResult:
    return SampleResult(
        config=SampleConfig(method=SamplingMethod.SIMPLE, size=size, seed=1),
        selected_row_ids=tuple(range(1, size + 1)),
        population_size=50,
        id=sample_id,
    )


def _legacy_label(sample: SampleResult, idx: int = 1) -> str:
    """Das bisherige Sample-Label-Format (Regressions-Referenz)."""
    return (
        f"#{idx} · {sample.config.method.value} · n={sample.actual_size} "
        f"(seed {sample.config.seed})"
    )


class TestFormatSampleIdValues:
    """Kürzungs-Logik fürs Sidebar-Label (erste N + „…“)."""

    def test_shows_all_when_within_limit(self) -> None:
        assert format_sample_id_values([1001, 1002, 1003], total=3) == "1001, 1002, 1003"

    def test_truncates_with_ellipsis_when_more_exist(self) -> None:
        assert (
            format_sample_id_values([1001, 1002, 1003], total=10, max_shown=3)
            == "1001, 1002, 1003, …"
        )

    def test_empty_values_yield_empty_string(self) -> None:
        assert format_sample_id_values([], total=0) == ""

    def test_values_stringified(self) -> None:
        assert format_sample_id_values(["B1", "B2"], total=2) == "B1, B2"


class TestIdColumnSelectionAndDisplay:
    def test_id_column_persisted_per_dataset_in_qsettings(self) -> None:
        store = DatasetIdColumnStore()
        store.set("ACME_ISAE", 7, "Belegnr")

        # Landet unter dem erwarteten projektweit-eindeutigen Key.
        raw = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG, APP_NAME)
        assert raw.value("dataset_id_columns/ACME_ISAE/7") == "Belegnr"

        # Round-Trip über den Store.
        assert store.get("ACME_ISAE", 7) == "Belegnr"
        # Nicht gesetztes Dataset → None.
        assert store.get("ACME_ISAE", 8) is None
        # Abwählen entfernt den Key wieder.
        store.set("ACME_ISAE", 7, None)
        assert store.get("ACME_ISAE", 7) is None

    def test_sidebar_shows_ids_when_enabled(self, qtbot: QtBot) -> None:
        sidebar = NavigationSidebar()
        qtbot.addWidget(sidebar)
        sample = _sample(5, size=10)
        # Controller reicht den bereits gekürzten Anzeige-String je Sample durch.
        ids_text = "1001, 1002, 1003, …"
        sidebar.set_samples(
            [sample],
            id_column="Belegnr",
            id_values_by_sample={5: ids_text},
            show_sample_id_column=True,
        )
        item = sidebar.samples_widget().item(0)
        assert item is not None
        text = item.text()
        # Legacy-Anteil bleibt, IDs werden additiv angehängt.
        assert _legacy_label(sample) in text
        assert f"IDs: {ids_text}" in text

    def test_sidebar_hides_ids_when_toggle_off(self, qtbot: QtBot) -> None:
        sidebar = NavigationSidebar()
        qtbot.addWidget(sidebar)
        sample = _sample(5)
        sidebar.set_samples(
            [sample],
            id_column="Belegnr",
            id_values_by_sample={5: "1001, 1002, 1003"},
            show_sample_id_column=False,
        )
        item = sidebar.samples_widget().item(0)
        assert item is not None
        # Toggle aus → exakt das bisherige Label, keine IDs.
        assert item.text() == _legacy_label(sample)
        assert "IDs:" not in item.text()

    def test_no_id_column_keeps_legacy_label(self, qtbot: QtBot) -> None:
        sidebar = NavigationSidebar()
        qtbot.addWidget(sidebar)
        sample = _sample(5)
        # Keine ID-Spalte gewählt → unverändertes Label (auch mit Toggle an).
        sidebar.set_samples([sample], show_sample_id_column=True)
        item = sidebar.samples_widget().item(0)
        assert item is not None
        assert item.text() == _legacy_label(sample)
        assert "IDs:" not in item.text()


def _populated_db(tmp_path: Path) -> tuple[Path, int]:
    """Engagement-DB mit einem Dataset (Spalte „Belegnr“) + einer Stichprobe."""
    db_path = tmp_path / "ACME_ISAE.db"
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
        Dataset(name="Buchungen", columns=("Belegnr", "Betrag"), engagement_id=eng.id),
        tuple(
            DatasetRow(row_id=i, values={"Belegnr": 1000 + i, "Betrag": i * 10})
            for i in range(1, 11)
        ),
    )
    assert ds.id is not None
    SampleRepo(db.connect()).create_from_result(
        SampleResult(
            config=SampleConfig(method=SamplingMethod.SIMPLE, size=5, seed=42),
            selected_row_ids=(1, 2, 3, 4, 5),
            population_size=10,
        ),
        ds.id,
        "tester",
    )
    db.close()
    return db_path, ds.id


class TestIdColumnEndToEnd:
    """Voller Controller-Pfad: gewählte ID-Spalte erscheint live in der Sidebar."""

    def test_sidebar_shows_ids_after_select_when_column_set(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        db_path, ds_id = _populated_db(tmp_path)
        win = MainWindow()
        qtbot.addWidget(win)
        ctrl = MainController(
            win, recent_store=RecentEngagementsStore(path=tmp_path / "recent.json")
        )
        ctrl.engagement.handle_open_engagement(db_path)
        DatasetIdColumnStore().set(db_path.stem, ds_id, "Belegnr")
        ctrl.selection.handle_dataset_selected(ds_id)

        item = win.sidebar().samples_widget().item(0)
        assert item is not None
        # selected_row_ids (1,2,3,4,5) → erste 3 Belegnr-Werte + „…“.
        assert "IDs: 1001, 1002, 1003, …" in item.text()
        ctrl.engagement.handle_close_engagement()

    def test_toggle_off_then_on_live_updates_sidebar(self, qtbot: QtBot, tmp_path: Path) -> None:
        db_path, ds_id = _populated_db(tmp_path)
        win = MainWindow()
        qtbot.addWidget(win)
        ctrl = MainController(
            win, recent_store=RecentEngagementsStore(path=tmp_path / "recent.json")
        )
        ctrl.engagement.handle_open_engagement(db_path)
        DatasetIdColumnStore().set(db_path.stem, ds_id, "Belegnr")
        ctrl.selection.handle_dataset_selected(ds_id)
        assert "IDs:" in _samples_item_text(win)

        # Toggle aus → live ohne Neustart.
        ctrl.session.apply_new_settings(replace(ctrl.session.settings, show_sample_id_column=False))
        assert "IDs:" not in _samples_item_text(win)

        # Wieder an → IDs zurück.
        ctrl.session.apply_new_settings(replace(ctrl.session.settings, show_sample_id_column=True))
        assert "IDs:" in _samples_item_text(win)
        ctrl.engagement.handle_close_engagement()

    def test_no_column_chosen_shows_legacy_label(self, qtbot: QtBot, tmp_path: Path) -> None:
        db_path, ds_id = _populated_db(tmp_path)
        win = MainWindow()
        qtbot.addWidget(win)
        ctrl = MainController(
            win, recent_store=RecentEngagementsStore(path=tmp_path / "recent.json")
        )
        ctrl.engagement.handle_open_engagement(db_path)
        # KEINE ID-Spalte gesetzt.
        ctrl.selection.handle_dataset_selected(ds_id)
        assert "IDs:" not in _samples_item_text(win)
        ctrl.engagement.handle_close_engagement()

    def test_active_sample_marker_survives_settings_change(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Ein Settings-/Panel-Toggle (apply_new_settings re-rendert die Sidebar)
        darf die aktive-Sample-Markierung + den Export-Button NICHT verlieren.
        """
        db_path, ds_id = _populated_db(tmp_path)
        win = MainWindow()
        qtbot.addWidget(win)
        ctrl = MainController(
            win, recent_store=RecentEngagementsStore(path=tmp_path / "recent.json")
        )
        ctrl.engagement.handle_open_engagement(db_path)
        ctrl.selection.handle_dataset_selected(ds_id)

        assert ctrl.session.db is not None
        sample_id = SampleRepo(ctrl.session.db.connect()).list_for_dataset(ds_id)[0].id
        assert sample_id is not None
        ctrl.selection.handle_sample_selected(sample_id)
        item = win.sidebar().samples_widget().item(0)
        assert item is not None
        assert item.text().startswith("●")
        assert win._action_export_sample.isEnabled() is True

        # Settings ändern → apply_new_settings baut die Sidebar-Samples neu auf.
        ctrl.session.apply_new_settings(replace(ctrl.session.settings, show_dashboard=False))

        item = win.sidebar().samples_widget().item(0)
        assert item is not None
        # Aktive-Sample-Markierung + Export-Button bleiben erhalten.
        assert item.text().startswith("●")
        assert win._action_export_sample.isEnabled() is True
        ctrl.engagement.handle_close_engagement()


def _samples_item_text(win: MainWindow) -> str:
    item = win.sidebar().samples_widget().item(0)
    assert item is not None
    return item.text()


class TestIdColumnDialog:
    """Der optionale Post-Import-Auswahl-Dialog."""

    def test_lists_columns_plus_keine_default(self, qtbot: QtBot) -> None:
        from sampling_tool.ui.dialogs.id_column_dialog import IdColumnDialog

        dialog = IdColumnDialog(["Belegnr", "Betrag"])
        qtbot.addWidget(dialog)
        # „Keine" als erster Eintrag + Default-Auswahl, dann die Spalten.
        assert dialog.selected_column() is None
        datas = [dialog._combo.itemData(i) for i in range(dialog._combo.count())]
        assert datas == [None, "Belegnr", "Betrag"]

    def test_selected_column_returns_choice(self, qtbot: QtBot) -> None:
        from sampling_tool.ui.dialogs.id_column_dialog import IdColumnDialog

        dialog = IdColumnDialog(["Belegnr", "Betrag"])
        qtbot.addWidget(dialog)
        dialog._combo.setCurrentIndex(dialog._combo.findData("Belegnr"))
        assert dialog.selected_column() == "Belegnr"

    def test_preselects_current(self, qtbot: QtBot) -> None:
        from sampling_tool.ui.dialogs.id_column_dialog import IdColumnDialog

        dialog = IdColumnDialog(["Belegnr", "Betrag"], current="Betrag")
        qtbot.addWidget(dialog)
        assert dialog.selected_column() == "Betrag"


def _make_import_xlsx(tmp_path: Path) -> Path:
    path = tmp_path / "import.xlsx"
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["Belegnr", "Betrag"])
    for i in range(1, 4):
        ws.append([1000 + i, i * 10])
    wb.save(path)
    return path


class _StubIdColumnDialog:
    DialogCode = QDialog.DialogCode

    def __init__(self, choice: str | None, accept: bool = True) -> None:
        self._choice = choice
        self._accept = accept
        self.seen_columns: list[str] = []

    def exec(self) -> int:
        return int(QDialog.DialogCode.Accepted if self._accept else QDialog.DialogCode.Rejected)

    def selected_column(self) -> str | None:
        return self._choice


class TestPostImportIdColumnWiring:
    """`handle_import_excel` bietet nach dem Import die ID-Spalten-Wahl an."""

    def _run_import(
        self,
        qtbot: QtBot,
        tmp_path: Path,
        stub: _StubIdColumnDialog,
    ) -> tuple[MainController, int]:
        db_path, _ = _populated_db(tmp_path)
        import_xlsx = _make_import_xlsx(tmp_path)
        seen: list[list[str]] = []

        def id_factory(columns: list[str], current: str | None, parent: object) -> object:
            stub.seen_columns = columns
            seen.append(columns)
            return stub

        win = MainWindow()
        qtbot.addWidget(win)
        ctrl = MainController(
            win,
            recent_store=RecentEngagementsStore(path=tmp_path / "recent.json"),
            id_column_dialog_factory=id_factory,  # type: ignore[arg-type]
        )
        ctrl.engagement.handle_open_engagement(db_path)
        with (
            patch(
                "sampling_tool.ui.controllers.workspace_controller.QFileDialog.getOpenFileName",
                return_value=(str(import_xlsx), ""),
            ),
            patch("sampling_tool.ui.controllers.workspace_controller.QMessageBox.information"),
        ):
            ctrl.workspace.handle_import_excel()
        new_ds = ctrl.session.dataset
        assert new_ds is not None
        assert new_ds.id is not None
        return ctrl, new_ds.id

    def test_accepted_choice_is_stored(self, qtbot: QtBot, tmp_path: Path) -> None:
        stub = _StubIdColumnDialog("Belegnr")
        ctrl, ds_id = self._run_import(qtbot, tmp_path, stub)
        db_stem = ctrl.session.db.db_path.stem  # type: ignore[union-attr]
        assert DatasetIdColumnStore().get(db_stem, ds_id) == "Belegnr"
        assert stub.seen_columns == ["Belegnr", "Betrag"]
        ctrl.engagement.handle_close_engagement()

    def test_cancel_stores_nothing(self, qtbot: QtBot, tmp_path: Path) -> None:
        stub = _StubIdColumnDialog("Belegnr", accept=False)
        ctrl, ds_id = self._run_import(qtbot, tmp_path, stub)
        db_stem = ctrl.session.db.db_path.stem  # type: ignore[union-attr]
        assert DatasetIdColumnStore().get(db_stem, ds_id) is None
        ctrl.engagement.handle_close_engagement()

    def test_keine_choice_stores_nothing(self, qtbot: QtBot, tmp_path: Path) -> None:
        stub = _StubIdColumnDialog(None)  # „Keine" gewählt + bestätigt.
        ctrl, ds_id = self._run_import(qtbot, tmp_path, stub)
        db_stem = ctrl.session.db.db_path.stem  # type: ignore[union-attr]
        assert DatasetIdColumnStore().get(db_stem, ds_id) is None
        ctrl.engagement.handle_close_engagement()
