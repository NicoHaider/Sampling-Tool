"""SamplingDialog – Method-Switching, Validierung, Seed-Würfel, Resample."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from PyQt6.QtWidgets import QDialogButtonBox
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import (
    Dataset,
    SampleConfig,
    SampleResult,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.ui.dialogs.sampling_dialog import NO_FILTER_LABEL, SamplingDialog

pytestmark = pytest.mark.ui


def _make_dataset() -> tuple[Dataset, Callable[[str], list[Any]]]:
    """Sprint 19 / P-005: Dataset (Metadaten) + distinct-values-Provider."""
    distinct: dict[str, list[Any]] = {
        "Land": ["AUT", "CHE", "DEU"],
        "Konto": [f"K{i:03d}" for i in range(1, 13)],
        "Betrag": [i * 10 for i in range(1, 13)],
    }
    dataset = Dataset(name="t", columns=("Land", "Konto", "Betrag"), row_count=12)
    return dataset, lambda field: distinct.get(field, [])


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
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=True)
        qtbot.addWidget(dialog)
        assert dialog._radio_simple.isChecked()
        assert dialog._cluster_field.isEnabled() is False
        assert dialog._stratum_field.isEnabled() is False

    def test_switching_to_cluster_enables_cluster_field(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=True)
        qtbot.addWidget(dialog)
        dialog._radio_cluster.setChecked(True)
        assert dialog._cluster_field.isEnabled() is True
        assert dialog._stratum_field.isEnabled() is False

    def test_switching_to_stratified_enables_stratum_and_mode(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=True)
        qtbot.addWidget(dialog)
        dialog._radio_stratified.setChecked(True)
        assert dialog._stratum_field.isEnabled() is True
        assert dialog._radio_proportional.isEnabled() is True
        assert dialog._radio_equal.isEnabled() is True

    def test_filter_field_change_populates_values(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=True)
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Land")
        assert dialog._filter_value.isEnabled() is True
        assert dialog._filter_value.count() == 3
        items = {dialog._filter_value.itemText(i) for i in range(dialog._filter_value.count())}
        assert items == {"AUT", "DEU", "CHE"}

    def test_no_filter_disables_value_combo(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=True)
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Land")
        dialog._filter_field.setCurrentText(NO_FILTER_LABEL)
        assert dialog._filter_value.isEnabled() is False

    def test_dice_button_changes_seed(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=True)
        qtbot.addWidget(dialog)
        dialog._seed_spin.setValue(7)
        dialog._reroll_seed()
        assert dialog._seed_spin.value() != 7

    def test_validation_blocks_cluster_without_field(self, qtbot: QtBot) -> None:
        ds = Dataset(name="leer", columns=())
        dialog = SamplingDialog(ds, advanced_mode=True)
        qtbot.addWidget(dialog)
        assert _ok_enabled(dialog) is False

    def test_simple_get_result_returns_correct_config(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=True)
        qtbot.addWidget(dialog)
        dialog._size_spin.setValue(5)
        dialog._seed_spin.setValue(42)
        dialog._filter_field.setCurrentText("Land")
        dialog._filter_value.setCurrentIndex(0)
        dialog.accept()
        result = dialog.get_result()
        assert result is not None
        assert result.config.method == SamplingMethod.SIMPLE
        assert result.config.size == 5
        assert result.config.seed == 42
        assert result.config.filter_field == "Land"
        assert result.from_sample_only is False

    def test_resample_checkbox_updates_size_hint(self, qtbot: QtBot) -> None:
        # Sprint 9.6: kein hartes Capping mehr – Hint-Label kommuniziert
        # die zulässige Obergrenze, Validierung beim Accept fängt
        # Überschreitungen ab.
        ds, provider = _make_dataset()
        dialog = SamplingDialog(
            ds, provider, current_sample=_make_sample((1, 3, 5, 7)), advanced_mode=True
        )
        qtbot.addWidget(dialog)
        dialog._resample_checkbox.setChecked(True)
        assert "4" in dialog._lbl_size_hint.text()
        dialog._resample_checkbox.setChecked(False)
        assert "12" in dialog._lbl_size_hint.text()

    def test_resample_disabled_when_no_current_sample(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), current_sample=None, advanced_mode=True)
        qtbot.addWidget(dialog)
        assert dialog._resample_checkbox.isEnabled() is False

    def test_stratified_proportional_default(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=True)
        qtbot.addWidget(dialog)
        dialog._radio_stratified.setChecked(True)
        dialog._stratum_field.setCurrentText("Land")
        dialog._size_spin.setValue(6)
        dialog.accept()
        result = dialog.get_result()
        assert result is not None
        assert result.config.method == SamplingMethod.STRATIFIED
        assert result.config.stratify_mode == StratifyMode.PROPORTIONAL
        assert result.config.stratum_field == "Land"

    def test_cancel_returns_none(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=True)
        qtbot.addWidget(dialog)
        dialog.reject()
        assert dialog.get_result() is None


class TestSamplingDialogSimpleMode:
    """Sprint 9.3 + 9.6: Simple-Mode versteckt Methoden + method-spezifische
    Felder, behält aber Resample-Filter und Seed-Widget."""

    def test_simple_mode_does_not_create_method_radios(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=False)
        qtbot.addWidget(dialog)
        assert not hasattr(dialog, "_radio_cluster")
        assert not hasattr(dialog, "_radio_stratified")

    def test_simple_mode_creates_seed_widget(self, qtbot: QtBot) -> None:
        # Sprint 9.6 (Korrektur zu 9.3): Seed-Widget wandert in den Common-
        # Block. Reproduzierbarkeits-Transparenz auch im Default-Modus.
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=False)
        qtbot.addWidget(dialog)
        assert hasattr(dialog, "_seed_spin")
        assert hasattr(dialog, "_seed_dice")

    def test_simple_mode_does_not_create_method_specific_fields(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=False)
        qtbot.addWidget(dialog)
        assert not hasattr(dialog, "_cluster_field")
        assert not hasattr(dialog, "_stratum_field")
        assert not hasattr(dialog, "_filter_field")

    def test_simple_mode_keeps_from_sample_only_filter(self, qtbot: QtBot) -> None:
        # `_resample_checkbox` IST der from_sample_only-Filter – muss bleiben.
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=False)
        qtbot.addWidget(dialog)
        assert hasattr(dialog, "_resample_checkbox")

    def test_simple_mode_zeigt_mode_hint(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=False)
        qtbot.addWidget(dialog)
        assert hasattr(dialog, "_mode_hint")

    def test_advanced_mode_kein_mode_hint(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=True)
        qtbot.addWidget(dialog)
        assert not hasattr(dialog, "_mode_hint")

    def test_simple_mode_seed_ist_vorbefuellt(self, qtbot: QtBot) -> None:
        # Sprint 9.6: Seed wird beim Öffnen mit Zufalls-Wert gefüllt.
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=False)
        qtbot.addWidget(dialog)
        seed = dialog._seed_spin.value()
        assert seed > 0

    def test_simple_mode_seed_landet_im_config(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=False)
        qtbot.addWidget(dialog)
        dialog._seed_spin.setValue(424242)
        dialog._size_spin.setValue(5)
        dialog.accept()
        result = dialog.get_result()
        assert result is not None
        assert result.config.method == SamplingMethod.SIMPLE
        assert result.config.size == 5
        assert result.config.seed == 424242

    def test_simple_mode_wuerfel_aendert_seed(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=False)
        qtbot.addWidget(dialog)
        seed_before = dialog._seed_spin.value()
        # Mit 31-Bit-Range ist eine Kollision astronomisch unwahrscheinlich,
        # aber zur Sicherheit ein kleiner Retry-Loop.
        for _ in range(5):
            dialog._seed_dice.click()
            if dialog._seed_spin.value() != seed_before:
                break
        assert dialog._seed_spin.value() != seed_before

    def test_simple_mode_neuer_dialog_neuer_seed(self, qtbot: QtBot) -> None:
        # Sanity: zwei frische Dialoge liefern verschiedene Default-Seeds.
        seeds: set[int] = set()
        for _ in range(5):
            dialog = SamplingDialog(*_make_dataset(), advanced_mode=False)
            qtbot.addWidget(dialog)
            seeds.add(dialog._seed_spin.value())
        assert len(seeds) >= 4


class TestSamplingDialogSizeHint:
    """Sprint 9.6: Hint-Label unter Größe-SpinBox + Accept-Validierung."""

    def test_hint_zeigt_dataset_groesse_im_default(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=False)
        qtbot.addWidget(dialog)
        assert hasattr(dialog, "_lbl_size_hint")
        # Dataset hat 12 Zeilen.
        assert "12" in dialog._lbl_size_hint.text()
        assert "max." in dialog._lbl_size_hint.text().lower()

    def test_hint_updatet_bei_filter_toggle(self, qtbot: QtBot) -> None:
        ds, provider = _make_dataset()
        dialog = SamplingDialog(
            ds,
            provider,
            current_sample=_make_sample((1, 2, 3, 4, 5)),
            advanced_mode=False,
        )
        qtbot.addWidget(dialog)
        dialog._resample_checkbox.setChecked(True)
        assert "5" in dialog._lbl_size_hint.text()
        dialog._resample_checkbox.setChecked(False)
        assert "12" in dialog._lbl_size_hint.text()

    def test_size_zu_gross_zeigt_messagebox(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        warnings: list[tuple[str, str]] = []

        def fake_warning(*args: object, **_kwargs: object) -> int:
            # args: (parent, title, text, ...)
            warnings.append((str(args[1]), str(args[2])))
            return 0

        from PyQt6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "warning", fake_warning)

        dialog = SamplingDialog(*_make_dataset(), advanced_mode=False)
        qtbot.addWidget(dialog)
        # Dataset hat 12 Zeilen; 1000 muss fehlschlagen.
        dialog._size_spin.setValue(1000)
        dialog.accept()

        assert len(warnings) == 1
        title, text = warnings[0]
        assert "groß" in title.lower() or "groß" in text.lower()
        # Dialog wurde nicht akzeptiert.
        assert dialog.result() != int(dialog.DialogCode.Accepted)
        assert dialog.get_result() is None

    def test_size_unter_minimum_zeigt_messagebox(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        warnings: list[tuple[str, str]] = []

        def fake_warning(*args: object, **_kwargs: object) -> int:
            warnings.append((str(args[1]), str(args[2])))
            return 0

        from PyQt6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "warning", fake_warning)

        dialog = SamplingDialog(*_make_dataset(), advanced_mode=False)
        qtbot.addWidget(dialog)
        # MIN_SAMPLE_SIZE ist 1; setRange erlaubt eigentlich kein 0 –
        # wir setzen den Range temporär runter, um den Validierungs-Pfad zu
        # treffen.
        dialog._size_spin.setMinimum(0)
        dialog._size_spin.setValue(0)
        dialog.accept()

        assert len(warnings) == 1
        assert dialog.result() != int(dialog.DialogCode.Accepted)

    def test_size_spin_hat_kein_hartes_cap(self, qtbot: QtBot) -> None:
        # Sprint 9.6: Widget cappt nicht mehr still – Validierung beim Accept
        # übernimmt. Sanity-Check: setValue oberhalb des Datasets bleibt
        # erhalten.
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=False)
        qtbot.addWidget(dialog)
        dialog._size_spin.setValue(9999)
        assert dialog._size_spin.value() == 9999


class TestSamplingDialogDistinctProvider:
    """Sprint 19 / P-005: Filter-Werte kommen über den Provider-Callback."""

    def test_advanced_filter_values_use_provider(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=True)
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Land")
        items = {dialog._filter_value.itemText(i) for i in range(dialog._filter_value.count())}
        assert items == {"AUT", "CHE", "DEU"}

    def test_provider_called_with_selected_field(self, qtbot: QtBot) -> None:
        seen: list[str] = []
        dataset, _ = _make_dataset()

        def provider(field: str) -> list[Any]:
            seen.append(field)
            return ["x", "y"]

        dialog = SamplingDialog(dataset, provider, advanced_mode=True)
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Konto")
        assert "Konto" in seen

    def test_no_provider_yields_empty_value_combo(self, qtbot: QtBot) -> None:
        dataset, _ = _make_dataset()
        dialog = SamplingDialog(dataset, None, advanced_mode=True)
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Land")
        assert dialog._filter_value.count() == 0
