"""SamplingDialog – Method-Switching, Validierung, Seed-Würfel, Resample."""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QDialogButtonBox
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    SampleConfig,
    SampleResult,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.ui.dialogs.sampling_dialog import NO_FILTER_LABEL, SamplingDialog

pytestmark = pytest.mark.ui


def _make_dataset() -> Dataset:
    rows = tuple(
        DatasetRow(
            row_id=i,
            values={
                "Land": ["AUT", "DEU", "CHE"][i % 3],
                "Konto": f"K{i:03d}",
                "Betrag": i * 10,
            },
        )
        for i in range(1, 13)
    )
    return Dataset(name="t", columns=("Land", "Konto", "Betrag"), rows=rows)


def _make_sample(row_ids: tuple[int, ...]) -> SampleResult:
    return SampleResult(
        config=SampleConfig(method=SamplingMethod.SIMPLE, size=len(row_ids), seed=1),
        selected_row_ids=row_ids,
        population_size=12,
        id=1,
    )


def _ok_enabled(dialog: SamplingDialog) -> bool:
    box = dialog.findChild(QDialogButtonBox)
    assert box is not None
    btn = box.button(QDialogButtonBox.StandardButton.Ok)
    assert btn is not None
    return bool(btn.isEnabled())


class TestSamplingDialog:
    def test_default_method_is_simple(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(_make_dataset())
        qtbot.addWidget(dialog)
        assert dialog._radio_simple.isChecked()
        assert dialog._cluster_field.isEnabled() is False
        assert dialog._stratum_field.isEnabled() is False

    def test_switching_to_cluster_enables_cluster_field(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(_make_dataset())
        qtbot.addWidget(dialog)
        dialog._radio_cluster.setChecked(True)
        assert dialog._cluster_field.isEnabled() is True
        assert dialog._stratum_field.isEnabled() is False

    def test_switching_to_stratified_enables_stratum_and_mode(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(_make_dataset())
        qtbot.addWidget(dialog)
        dialog._radio_stratified.setChecked(True)
        assert dialog._stratum_field.isEnabled() is True
        assert dialog._radio_proportional.isEnabled() is True
        assert dialog._radio_equal.isEnabled() is True

    def test_filter_field_change_populates_values(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(_make_dataset())
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Land")
        assert dialog._filter_value.isEnabled() is True
        assert dialog._filter_value.count() == 3
        items = {dialog._filter_value.itemText(i) for i in range(dialog._filter_value.count())}
        assert items == {"AUT", "DEU", "CHE"}

    def test_no_filter_disables_value_combo(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(_make_dataset())
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Land")
        dialog._filter_field.setCurrentText(NO_FILTER_LABEL)
        assert dialog._filter_value.isEnabled() is False

    def test_dice_button_changes_seed(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(_make_dataset())
        qtbot.addWidget(dialog)
        dialog._seed_spin.setValue(7)
        dialog._reroll_seed()
        assert dialog._seed_spin.value() != 7

    def test_validation_blocks_cluster_without_field(self, qtbot: QtBot) -> None:
        ds = Dataset(name="leer", columns=(), rows=())
        dialog = SamplingDialog(ds)
        qtbot.addWidget(dialog)
        assert _ok_enabled(dialog) is False

    def test_simple_get_result_returns_correct_config(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(_make_dataset())
        qtbot.addWidget(dialog)
        dialog._size_spin.setValue(5)
        dialog._seed_spin.setValue(42)
        dialog._filter_field.setCurrentText("Land")
        dialog._filter_value.setCurrentIndex(0)
        dialog._on_accept()
        result = dialog.get_result()
        assert result is not None
        assert result.config.method == SamplingMethod.SIMPLE
        assert result.config.size == 5
        assert result.config.seed == 42
        assert result.config.filter_field == "Land"
        assert result.from_sample_only is False

    def test_resample_checkbox_limits_size_to_current_sample(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(_make_dataset(), current_sample=_make_sample((1, 3, 5, 7)))
        qtbot.addWidget(dialog)
        dialog._size_spin.setValue(10)
        dialog._resample_checkbox.setChecked(True)
        assert dialog._size_spin.maximum() == 4
        assert dialog._size_spin.value() <= 4

    def test_resample_disabled_when_no_current_sample(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(_make_dataset(), current_sample=None)
        qtbot.addWidget(dialog)
        assert dialog._resample_checkbox.isEnabled() is False

    def test_stratified_proportional_default(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(_make_dataset())
        qtbot.addWidget(dialog)
        dialog._radio_stratified.setChecked(True)
        dialog._stratum_field.setCurrentText("Land")
        dialog._size_spin.setValue(6)
        dialog._on_accept()
        result = dialog.get_result()
        assert result is not None
        assert result.config.method == SamplingMethod.STRATIFIED
        assert result.config.stratify_mode == StratifyMode.PROPORTIONAL
        assert result.config.stratum_field == "Land"

    def test_cancel_returns_none(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(_make_dataset())
        qtbot.addWidget(dialog)
        dialog.reject()
        assert dialog.get_result() is None
