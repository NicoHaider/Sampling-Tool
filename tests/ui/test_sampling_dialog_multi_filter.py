"""Stichproben-Dialog mit bis zu fünf Filterzeilen, UND-verknüpft (Sprint 92 / A7)."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QFormLayout, QLabel
from pytestqt.qtbot import QtBot

from sampling_tool.config import MAX_FILTERS
from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    Engagement,
    FilterCondition,
    FilterOperator,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.core.presets import SamplingPreset
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import DatasetRepo, EngagementRepo
from sampling_tool.ui.controllers._factories import default_sampling_factory
from sampling_tool.ui.controllers.main_controller import MainController
from sampling_tool.ui.dialogs.sampling_dialog import (
    FILTER_ROW_BUTTON_NAME,
    NO_FILTER_LABEL,
    SamplingDialog,
)
from sampling_tool.ui.main_window import MainWindow
from sampling_tool.ui.recent import RecentEngagementsStore
from sampling_tool.ui.settings_store import AppSettings, SamplingFeatures
from tests._styling_policy import stylesheet_text

pytestmark = pytest.mark.ui

_FILTER = SamplingFeatures(show_filter=True)

_KOSTENSTELLEN = ("Vertrieb", "Einkauf", "Verwaltung")


def _rows() -> tuple[DatasetRow, ...]:
    """60 Zeilen: Kostenstelle reihum, Betrag 100..6000."""
    return tuple(
        DatasetRow(
            row_id=i,
            values={"Kostenstelle": _KOSTENSTELLEN[i % 3], "Betrag": i * 100},
        )
        for i in range(1, 61)
    )


def _dialog(
    qtbot: QtBot,
    count: Callable[[tuple[FilterCondition, ...], bool], int] | None = None,
) -> SamplingDialog:
    rows = _rows()
    dataset = Dataset(name="Buchungen", columns=("Kostenstelle", "Betrag"), row_count=len(rows))

    def distinct(column: str) -> Sequence[Any]:
        return sorted({r.get(column) for r in rows})

    dialog = SamplingDialog(dataset, distinct, features=_FILTER, filter_match_count_provider=count)
    qtbot.addWidget(dialog)
    return dialog


def _set_condition(
    dialog: SamplingDialog, index: int, field: str, operator: FilterOperator, value: Any
) -> None:
    row = dialog._filter_rows[index]
    row.field.setCurrentText(field)
    for i in range(row.operator.count()):
        if row.operator.itemData(i) == operator:
            row.operator.setCurrentIndex(i)
    if operator in (FilterOperator.EQ, FilterOperator.NE):
        row.value.setCurrentText(str(value))
    else:
        row.value_text.setText(str(value))
        row.value_text.editingFinished.emit()


def _form_label(dialog: SamplingDialog, index: int) -> str:
    form: QFormLayout = dialog._form
    label = form.labelForField(dialog._filter_rows[index].widget)
    assert isinstance(label, QLabel)
    return label.text()


class TestSamplingDialogMultiFilter:
    def test_add_button_hidden_until_first_filter_chosen(self, qtbot: QtBot) -> None:
        dialog = _dialog(qtbot)
        add = dialog._filter_rows[0].add_button
        assert add.isHidden()
        dialog._filter_rows[0].field.setCurrentText("Kostenstelle")
        assert not add.isHidden()
        assert add.toolTip() == "Weiteren Filter hinzufügen"
        assert add.text() == "+"

    def test_add_row_moves_plus_to_new_last_row(self, qtbot: QtBot) -> None:
        dialog = _dialog(qtbot)
        dialog._filter_rows[0].field.setCurrentText("Kostenstelle")
        dialog._filter_rows[0].add_button.click()
        assert len(dialog._filter_rows) == 2
        first, second = dialog._filter_rows
        assert first.add_button.isHidden()
        assert not second.add_button.isHidden()
        assert second.remove_button is not None
        assert second.remove_button.toolTip() == "Filter entfernen"
        assert first.remove_button is None
        assert second.field.currentText() == NO_FILTER_LABEL

    def test_label_und_from_second_row(self, qtbot: QtBot) -> None:
        dialog = _dialog(qtbot)
        dialog._filter_rows[0].field.setCurrentText("Kostenstelle")
        dialog._filter_rows[0].add_button.click()
        assert _form_label(dialog, 0) == "Filter (optional)"
        assert _form_label(dialog, 1) == "und"

    def test_maximum_five_rows(self, qtbot: QtBot) -> None:
        dialog = _dialog(qtbot)
        dialog._filter_rows[0].field.setCurrentText("Kostenstelle")
        for _ in range(MAX_FILTERS - 1):
            dialog._filter_rows[-1].add_button.click()
        assert len(dialog._filter_rows) == MAX_FILTERS == 5
        assert all(row.add_button.isHidden() for row in dialog._filter_rows)

    def test_remove_row(self, qtbot: QtBot) -> None:
        dialog = _dialog(qtbot)
        _set_condition(dialog, 0, "Kostenstelle", FilterOperator.EQ, "Vertrieb")
        dialog._filter_rows[0].add_button.click()
        _set_condition(dialog, 1, "Betrag", FilterOperator.GTE, 1000)
        removed = dialog._filter_rows[1]
        assert removed.remove_button is not None
        removed.remove_button.click()
        assert len(dialog._filter_rows) == 1
        assert not dialog._filter_rows[0].add_button.isHidden()
        assert dialog._build_config().filters == (
            FilterCondition("Kostenstelle", FilterOperator.EQ, "Vertrieb"),
        )

    def test_first_row_back_to_no_filter_keeps_following_rows(self, qtbot: QtBot) -> None:
        dialog = _dialog(qtbot)
        _set_condition(dialog, 0, "Kostenstelle", FilterOperator.EQ, "Vertrieb")
        dialog._filter_rows[0].add_button.click()
        _set_condition(dialog, 1, "Betrag", FilterOperator.GTE, 1000)
        dialog._filter_rows[0].field.setCurrentText(NO_FILTER_LABEL)
        assert len(dialog._filter_rows) == 2
        assert dialog._build_config().filters == (
            FilterCondition("Betrag", FilterOperator.GTE, 1000),
        )

    def test_build_config_collects_all_rows_in_order(self, qtbot: QtBot) -> None:
        dialog = _dialog(qtbot)
        _set_condition(dialog, 0, "Kostenstelle", FilterOperator.EQ, "Vertrieb")
        dialog._filter_rows[0].add_button.click()
        _set_condition(dialog, 1, "Betrag", FilterOperator.GTE, 1000)
        dialog._filter_rows[1].add_button.click()
        _set_condition(dialog, 2, "Betrag", FilterOperator.LT, 5000)
        assert dialog._build_config().filters == (
            FilterCondition("Kostenstelle", FilterOperator.EQ, "Vertrieb"),
            FilterCondition("Betrag", FilterOperator.GTE, 1000),
            FilterCondition("Betrag", FilterOperator.LT, 5000),
        )

    def test_incomplete_row_blocks_ok(self, qtbot: QtBot) -> None:
        dialog = _dialog(qtbot)
        dialog._size_spin.setValue(1)
        _set_condition(dialog, 0, "Kostenstelle", FilterOperator.EQ, "Vertrieb")
        dialog._filter_rows[0].add_button.click()
        second = dialog._filter_rows[1]
        second.field.setCurrentText("Betrag")
        for i in range(second.operator.count()):
            if second.operator.itemData(i) == FilterOperator.GT:
                second.operator.setCurrentIndex(i)
        dialog.accept()
        assert dialog.get_result() is None
        assert "Schwellenwert" in dialog._inline_errors[second.error_key].text()
        assert dialog._inline_errors["filter"].text() == ""
        second.value_text.setText("1000")
        dialog.accept()
        assert dialog.get_result() is not None

    def test_rows_with_no_filter_are_ignored(self, qtbot: QtBot) -> None:
        dialog = _dialog(qtbot)
        dialog._size_spin.setValue(1)
        _set_condition(dialog, 0, "Kostenstelle", FilterOperator.EQ, "Vertrieb")
        dialog._filter_rows[0].add_button.click()
        dialog.accept()
        result = dialog.get_result()
        assert result is not None
        assert len(result.config.filters) == 1

    def test_preset_with_two_filters_fills_two_rows(self, qtbot: QtBot) -> None:
        dialog = _dialog(qtbot)
        conds = (
            FilterCondition("Kostenstelle", FilterOperator.EQ, "Vertrieb"),
            FilterCondition("Betrag", FilterOperator.GTE, 1000),
        )
        applied = dialog.apply_preset(
            SamplingPreset(name="p", method=SamplingMethod.SIMPLE, size=3, filters=conds)
        )
        assert applied.skipped_filters == ()
        assert len(dialog._filter_rows) == 2
        assert dialog._build_config().filters == conds
        # Eine weitere Vorlage ohne Filter räumt die Zusatzzeilen weg.
        dialog.apply_preset(SamplingPreset(name="q", method=SamplingMethod.SIMPLE, size=3))
        assert len(dialog._filter_rows) == 1
        assert dialog._build_config().filters == ()

    def test_preset_reports_each_skipped_column(self, qtbot: QtBot) -> None:
        dialog = _dialog(qtbot)
        conds = (
            FilterCondition("Fehlt", FilterOperator.EQ, "x"),
            FilterCondition("Betrag", FilterOperator.GTE, 1000),
            FilterCondition("Kostenstelle", FilterOperator.EQ, "gibt es nicht"),
        )
        applied = dialog.apply_preset(
            SamplingPreset(name="p", method=SamplingMethod.SIMPLE, size=3, filters=conds)
        )
        assert applied.skipped_filters == ("Fehlt", "Kostenstelle")
        assert dialog._build_config().filters == (
            FilterCondition("Betrag", FilterOperator.GTE, 1000),
        )

    def test_match_count_cache_distinguishes_condition_sets(self, qtbot: QtBot) -> None:
        calls: list[tuple[tuple[FilterCondition, ...], bool]] = []

        def count(filters: tuple[FilterCondition, ...], restrict: bool) -> int:
            calls.append((filters, restrict))
            return 10 * len(filters)

        dialog = _dialog(qtbot, count)
        _set_condition(dialog, 0, "Kostenstelle", FilterOperator.EQ, "Vertrieb")
        assert dialog._lbl_size_hint.text() == "max. 10 verfügbar"
        dialog._filter_rows[0].add_button.click()
        _set_condition(dialog, 1, "Betrag", FilterOperator.GTE, 1000)
        assert dialog._lbl_size_hint.text() == "max. 20 verfügbar"
        assert calls[-1] == (
            (
                FilterCondition("Kostenstelle", FilterOperator.EQ, "Vertrieb"),
                FilterCondition("Betrag", FilterOperator.GTE, 1000),
            ),
            False,
        )


# ---------------------------------------------------------------------------
# „max. N verfügbar" gegen den echten Zähler des Controllers
# ---------------------------------------------------------------------------


@pytest.fixture
def buchungen_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "buchungen.db"
    db = Database(db_path)
    db.migrate()
    eng = EngagementRepo(db.connect()).get_or_create(
        Engagement(
            auditor_name="Anna", client_name="ACME", auditor_position="S", audit_type="ISAE 3402"
        )
    )
    assert eng.id is not None
    DatasetRepo(db.connect()).create(
        Dataset(name="Buchungen", columns=("Kostenstelle", "Betrag"), engagement_id=eng.id),
        _rows(),
    )
    db.close()
    return db_path


def _expected(*conds: FilterCondition) -> int:
    from sampling_tool.core.sampling import matches_all

    return sum(1 for r in _rows() if matches_all(r, conds))


class TestSamplingDialogMultiFilterRealCount:
    """Der Hinweis rechnet mit ALLEN aktiven Bedingungen – geprüft gegen den
    Zähler, den der Controller dem Dialog mitgibt (kein Fake)."""

    def test_size_hint_follows_every_change(
        self, qtbot: QtBot, tmp_path: Path, buchungen_db: Path
    ) -> None:
        hints: list[str] = []
        vertrieb = FilterCondition("Kostenstelle", FilterOperator.EQ, "Vertrieb")
        ab_1000 = FilterCondition("Betrag", FilterOperator.GTE, 1000)
        unter_5000 = FilterCondition("Betrag", FilterOperator.LT, 5000)

        def drive(dialog: SamplingDialog) -> int:
            hints.append(dialog._lbl_size_hint.text())
            _set_condition(dialog, 0, "Kostenstelle", FilterOperator.EQ, "Vertrieb")
            hints.append(dialog._lbl_size_hint.text())
            dialog._filter_rows[0].add_button.click()
            hints.append(dialog._lbl_size_hint.text())
            _set_condition(dialog, 1, "Betrag", FilterOperator.GTE, 1000)
            hints.append(dialog._lbl_size_hint.text())
            dialog._filter_rows[1].add_button.click()
            _set_condition(dialog, 2, "Betrag", FilterOperator.LT, 5000)
            hints.append(dialog._lbl_size_hint.text())
            remove = dialog._filter_rows[1].remove_button
            assert remove is not None
            remove.click()
            hints.append(dialog._lbl_size_hint.text())
            return int(QDialog.DialogCode.Rejected)

        def factory(*args: Any, **kwargs: Any) -> SamplingDialog:
            dialog = default_sampling_factory(*args, **kwargs)
            dialog.exec = lambda: drive(dialog)  # type: ignore[method-assign]
            return dialog

        window = MainWindow()
        qtbot.addWidget(window)
        settings = dataclasses.replace(AppSettings.defaults(), show_filter_feature=True)
        controller = MainController(
            window,
            recent_store=RecentEngagementsStore(path=tmp_path / "recent.json"),
            sampling_dialog_factory=factory,
            settings=settings,
        )
        try:
            controller.engagement.handle_open_engagement(buchungen_db)
            item = window.sidebar().datasets_widget().item(0)
            assert item is not None
            controller.selection.handle_dataset_selected(item.data(int(Qt.ItemDataRole.UserRole)))
            controller.workspace.handle_new_sampling()
        finally:
            controller.engagement.handle_close_engagement()

        def hint(n: int) -> str:
            return f"max. {n:,} verfügbar".replace(",", ".")

        assert hints == [
            hint(60),
            hint(_expected(vertrieb)),
            hint(_expected(vertrieb)),
            hint(_expected(vertrieb, ab_1000)),
            hint(_expected(vertrieb, ab_1000, unter_5000)),
            hint(_expected(vertrieb, unter_5000)),
        ]
        assert _expected(vertrieb, ab_1000, unter_5000) < _expected(vertrieb, ab_1000)

    def test_drawn_rows_meet_all_conditions(
        self, qtbot: QtBot, tmp_path: Path, buchungen_db: Path
    ) -> None:
        def drive(dialog: SamplingDialog) -> int:
            dialog._size_spin.setValue(5)
            _set_condition(dialog, 0, "Kostenstelle", FilterOperator.EQ, "Vertrieb")
            dialog._filter_rows[0].add_button.click()
            _set_condition(dialog, 1, "Betrag", FilterOperator.GTE, 1000)
            dialog.accept()
            return int(dialog.result())

        def factory(*args: Any, **kwargs: Any) -> SamplingDialog:
            dialog = default_sampling_factory(*args, **kwargs)
            dialog.exec = lambda: drive(dialog)  # type: ignore[method-assign]
            return dialog

        window = MainWindow()
        qtbot.addWidget(window)
        settings = dataclasses.replace(AppSettings.defaults(), show_filter_feature=True)
        controller = MainController(
            window,
            recent_store=RecentEngagementsStore(path=tmp_path / "recent.json"),
            sampling_dialog_factory=factory,
            settings=settings,
        )
        try:
            controller.engagement.handle_open_engagement(buchungen_db)
            item = window.sidebar().datasets_widget().item(0)
            assert item is not None
            controller.selection.handle_dataset_selected(item.data(int(Qt.ItemDataRole.UserRole)))
            controller.workspace.handle_new_sampling()
            sample = controller.session.sample
            assert sample is not None
        finally:
            controller.engagement.handle_close_engagement()
        by_id = {r.row_id: r for r in _rows()}
        assert len(sample.selected_row_ids) == 5
        for row_id in sample.selected_row_ids:
            values = by_id[row_id].values
            assert values["Kostenstelle"] == "Vertrieb"
            assert values["Betrag"] >= 1000
        assert sample.population_size == _expected(
            FilterCondition("Kostenstelle", FilterOperator.EQ, "Vertrieb"),
            FilterCondition("Betrag", FilterOperator.GTE, 1000),
        )
        assert isinstance(sample.config, SampleConfig)
        assert isinstance(sample, SampleResult)


class TestFilterRowButtonStyle:
    """Die „+"/„×"-Knöpfe sind quadratisch und heben sich beim Hover sichtbar ab."""

    def test_square_symbol_buttons(self, qtbot: QtBot) -> None:
        dialog = _dialog(qtbot)
        dialog._filter_rows[0].field.setCurrentText("Kostenstelle")
        dialog._filter_rows[0].add_button.click()
        second = dialog._filter_rows[1]
        assert second.remove_button is not None
        for button in (second.add_button, second.remove_button):
            assert button.objectName() == FILTER_ROW_BUTTON_NAME
            assert button.width() == button.height()
        assert second.remove_button.text() == "×"

    def test_stylesheet_has_hover_rule(self) -> None:
        qss = stylesheet_text()
        assert re.search(rf"QToolButton#{FILTER_ROW_BUTTON_NAME}:hover\s*\{{[^}}]*background", qss)
