"""SamplingDialog – Method-Switching, Validierung, Seed-Würfel, Resample."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import pytest
from PyQt6.QtWidgets import QDialogButtonBox, QLineEdit
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import (
    Dataset,
    FilterOperator,
    SampleConfig,
    SampleResult,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.core.presets import SamplingPreset
from sampling_tool.ui.dialogs.sampling_dialog import (
    NO_FILTER_LABEL,
    SamplingDialog,
    _parse_filter_threshold,
)
from sampling_tool.ui.settings_store import SamplingFeatures

pytestmark = pytest.mark.ui

# Sprint 22: der Dialog bekommt seine Sichtbarkeit pro Funktion aufgelöst
# (vorher ein einzelnes `advanced_mode`-Flag). `_ALL` entspricht dem alten
# Advanced-Mode (alles sichtbar), `_NONE` dem alten Simple-Mode.
_ALL = SamplingFeatures(show_filter=True, show_cluster=True, show_stratified=True)
_NONE = SamplingFeatures()


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
        dialog = SamplingDialog(*_make_dataset(), features=_ALL)
        qtbot.addWidget(dialog)
        assert dialog._radio_simple.isChecked()
        assert dialog._cluster_field.isEnabled() is False
        assert dialog._stratum_field.isEnabled() is False

    def test_switching_to_cluster_enables_cluster_field(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_ALL)
        qtbot.addWidget(dialog)
        dialog._radio_cluster.setChecked(True)
        assert dialog._cluster_field.isEnabled() is True
        assert dialog._stratum_field.isEnabled() is False

    def test_switching_to_stratified_enables_stratum_and_mode(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_ALL)
        qtbot.addWidget(dialog)
        dialog._radio_stratified.setChecked(True)
        assert dialog._stratum_field.isEnabled() is True
        assert dialog._radio_proportional.isEnabled() is True
        assert dialog._radio_equal.isEnabled() is True

    def test_filter_field_change_populates_values(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_ALL)
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Land")
        assert dialog._filter_value.isEnabled() is True
        assert dialog._filter_value.count() == 3
        items = {dialog._filter_value.itemText(i) for i in range(dialog._filter_value.count())}
        assert items == {"AUT", "DEU", "CHE"}

    def test_no_filter_disables_value_combo(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_ALL)
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Land")
        dialog._filter_field.setCurrentText(NO_FILTER_LABEL)
        assert dialog._filter_value.isEnabled() is False

    def test_validation_blocks_cluster_without_field(self, qtbot: QtBot) -> None:
        ds = Dataset(name="leer", columns=())
        dialog = SamplingDialog(ds, features=_ALL)
        qtbot.addWidget(dialog)
        assert _ok_enabled(dialog) is False

    def test_simple_get_result_returns_correct_config(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_ALL)
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
            ds, provider, current_sample=_make_sample((1, 3, 5, 7)), features=_ALL
        )
        qtbot.addWidget(dialog)
        dialog._resample_checkbox.setChecked(True)
        assert "4" in dialog._lbl_size_hint.text()
        dialog._resample_checkbox.setChecked(False)
        assert "12" in dialog._lbl_size_hint.text()

    def test_resample_disabled_when_no_current_sample(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), current_sample=None, features=_ALL)
        qtbot.addWidget(dialog)
        assert dialog._resample_checkbox.isEnabled() is False

    def test_stratified_proportional_default(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_ALL)
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
        dialog = SamplingDialog(*_make_dataset(), features=_ALL)
        qtbot.addWidget(dialog)
        dialog.reject()
        assert dialog.get_result() is None


class TestSamplingDialogSimpleMode:
    """Sprint 9.3 + 9.6: Simple-Mode versteckt Methoden + method-spezifische
    Felder, behält aber Resample-Filter und Seed-Widget."""

    def test_simple_mode_does_not_create_method_radios(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_NONE)
        qtbot.addWidget(dialog)
        assert not hasattr(dialog, "_radio_cluster")
        assert not hasattr(dialog, "_radio_stratified")

    def test_simple_mode_creates_seed_widget(self, qtbot: QtBot) -> None:
        # Sprint 9.6 (Korrektur zu 9.3): Seed-Widget wandert in den Common-
        # Block. Reproduzierbarkeits-Transparenz auch im Default-Modus.
        # Sprint 27: schreibgeschützt, kein Würfel-Button mehr.
        dialog = SamplingDialog(*_make_dataset(), features=_NONE)
        qtbot.addWidget(dialog)
        assert hasattr(dialog, "_seed_spin")
        assert not hasattr(dialog, "_seed_dice")

    def test_simple_mode_does_not_create_method_specific_fields(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_NONE)
        qtbot.addWidget(dialog)
        assert not hasattr(dialog, "_cluster_field")
        assert not hasattr(dialog, "_stratum_field")
        assert not hasattr(dialog, "_filter_field")

    def test_simple_mode_keeps_from_sample_only_filter(self, qtbot: QtBot) -> None:
        # `_resample_checkbox` IST der from_sample_only-Filter – muss bleiben.
        dialog = SamplingDialog(*_make_dataset(), features=_NONE)
        qtbot.addWidget(dialog)
        assert hasattr(dialog, "_resample_checkbox")

    def test_simple_mode_zeigt_mode_hint(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_NONE)
        qtbot.addWidget(dialog)
        assert hasattr(dialog, "_mode_hint")

    def test_advanced_mode_kein_mode_hint(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_ALL)
        qtbot.addWidget(dialog)
        assert not hasattr(dialog, "_mode_hint")

    def test_simple_mode_seed_ist_vorbefuellt(self, qtbot: QtBot) -> None:
        # Sprint 9.6: Seed wird beim Öffnen mit Zufalls-Wert gefüllt.
        dialog = SamplingDialog(*_make_dataset(), features=_NONE)
        qtbot.addWidget(dialog)
        seed = dialog._seed_spin.value()
        assert seed > 0

    def test_simple_mode_seed_landet_im_config(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_NONE)
        qtbot.addWidget(dialog)
        dialog._seed_spin.setValue(424242)
        dialog._size_spin.setValue(5)
        dialog.accept()
        result = dialog.get_result()
        assert result is not None
        assert result.config.method == SamplingMethod.SIMPLE
        assert result.config.size == 5
        assert result.config.seed == 424242

    def test_simple_mode_neuer_dialog_neuer_seed(self, qtbot: QtBot) -> None:
        # Sanity: zwei frische Dialoge liefern verschiedene Default-Seeds.
        seeds: set[int] = set()
        for _ in range(5):
            dialog = SamplingDialog(*_make_dataset(), features=_NONE)
            qtbot.addWidget(dialog)
            seeds.add(dialog._seed_spin.value())
        assert len(seeds) >= 4


class TestSeedLock:
    """Sprint 27: Seed im Haupt-Dialog schreibgeschützt, kein Würfel."""

    def test_main_seed_field_readonly(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_NONE)
        qtbot.addWidget(dialog)
        assert dialog._seed_spin.isReadOnly() is True
        assert not hasattr(dialog, "_seed_dice")

    def test_main_seed_field_readonly_in_advanced(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_ALL)
        qtbot.addWidget(dialog)
        assert dialog._seed_spin.isReadOnly() is True

    def test_set_initial_seed_still_lands_in_config(self, qtbot: QtBot) -> None:
        # Programmatisch (set_initial_seed) bleibt der Seed setzbar und wandert
        # unverändert in die SampleConfig – der RNG-/Zieh-Pfad ist unberührt.
        dialog = SamplingDialog(*_make_dataset(), features=_NONE)
        qtbot.addWidget(dialog)
        dialog.set_initial_seed(98765)
        dialog._size_spin.setValue(3)
        dialog.accept()
        result = dialog.get_result()
        assert result is not None
        assert result.config.seed == 98765


class TestSamplingDialogSizeHint:
    """Sprint 9.6: Hint-Label unter Größe-SpinBox + Accept-Validierung."""

    def test_hint_zeigt_dataset_groesse_im_default(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_NONE)
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
            features=_NONE,
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

        dialog = SamplingDialog(*_make_dataset(), features=_NONE)
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

        dialog = SamplingDialog(*_make_dataset(), features=_NONE)
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
        dialog = SamplingDialog(*_make_dataset(), features=_NONE)
        qtbot.addWidget(dialog)
        dialog._size_spin.setValue(9999)
        assert dialog._size_spin.value() == 9999


class TestSamplingDialogDistinctProvider:
    """Sprint 19 / P-005: Filter-Werte kommen über den Provider-Callback."""

    def test_advanced_filter_values_use_provider(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_ALL)
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

        dialog = SamplingDialog(dataset, provider, features=_ALL)
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Konto")
        assert "Konto" in seen

    def test_no_provider_yields_empty_value_combo(self, qtbot: QtBot) -> None:
        dataset, _ = _make_dataset()
        dialog = SamplingDialog(dataset, None, features=_ALL)
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Land")
        assert dialog._filter_value.count() == 0


class TestSamplingDialogGranularFeatures:
    """Sprint 22: jede Advanced-Funktion ist einzeln schaltbar.

    Der Dialog rendert genau die Funktionen, die in `SamplingFeatures` aktiv
    sind. Die „Methode"-Gruppe erscheint, sobald Cluster ODER Geschichtet an
    ist, und zeigt nur die freigeschalteten Radios.
    """

    def test_only_filter_shows_filter_row_and_no_method_box(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=SamplingFeatures(show_filter=True))
        qtbot.addWidget(dialog)
        assert hasattr(dialog, "_filter_field")
        # Keine Methodenwahl, keine method-spezifischen Felder.
        assert not hasattr(dialog, "_radio_simple")
        assert not hasattr(dialog, "_radio_cluster")
        assert not hasattr(dialog, "_cluster_field")
        assert not hasattr(dialog, "_stratum_field")

    def test_only_filter_has_no_mode_hint(self, qtbot: QtBot) -> None:
        # Sobald irgendeine Advanced-Funktion an ist, ist der Simple-Hinweis weg.
        dialog = SamplingDialog(*_make_dataset(), features=SamplingFeatures(show_filter=True))
        qtbot.addWidget(dialog)
        assert not hasattr(dialog, "_mode_hint")

    def test_only_filter_builds_simple_config_without_filter(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=SamplingFeatures(show_filter=True))
        qtbot.addWidget(dialog)
        dialog._size_spin.setValue(3)
        dialog.accept()
        result = dialog.get_result()
        assert result is not None
        assert result.config.method == SamplingMethod.SIMPLE
        assert result.config.filter_field is None

    def test_only_filter_selected_value_lands_in_config(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=SamplingFeatures(show_filter=True))
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Land")
        dialog._filter_value.setCurrentIndex(0)
        dialog._size_spin.setValue(1)
        dialog.accept()
        result = dialog.get_result()
        assert result is not None
        assert result.config.filter_field == "Land"

    def test_only_cluster_shows_method_box_with_cluster_radio(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=SamplingFeatures(show_cluster=True))
        qtbot.addWidget(dialog)
        assert hasattr(dialog, "_radio_simple")
        assert hasattr(dialog, "_radio_cluster")
        assert hasattr(dialog, "_cluster_field")
        # Geschichtet bleibt aus – Radio + Felder existieren nicht.
        assert not hasattr(dialog, "_radio_stratified")
        assert not hasattr(dialog, "_stratum_field")
        # Filter ist nicht freigeschaltet.
        assert not hasattr(dialog, "_filter_field")

    def test_only_cluster_can_draw_cluster_sample(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=SamplingFeatures(show_cluster=True))
        qtbot.addWidget(dialog)
        dialog._radio_cluster.setChecked(True)
        assert dialog._cluster_field.isEnabled() is True
        dialog._cluster_field.setCurrentText("Land")
        dialog._size_spin.setValue(1)
        dialog.accept()
        result = dialog.get_result()
        assert result is not None
        assert result.config.method == SamplingMethod.CLUSTER
        assert result.config.cluster_field == "Land"

    def test_only_stratified_shows_method_box_with_stratified_radio(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=SamplingFeatures(show_stratified=True))
        qtbot.addWidget(dialog)
        assert hasattr(dialog, "_radio_simple")
        assert hasattr(dialog, "_radio_stratified")
        assert hasattr(dialog, "_stratum_field")
        assert hasattr(dialog, "_radio_proportional")
        assert hasattr(dialog, "_radio_equal")
        # Cluster bleibt aus.
        assert not hasattr(dialog, "_radio_cluster")
        assert not hasattr(dialog, "_cluster_field")

    def test_only_stratified_can_draw_stratified_sample(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=SamplingFeatures(show_stratified=True))
        qtbot.addWidget(dialog)
        dialog._radio_stratified.setChecked(True)
        assert dialog._stratum_field.isEnabled() is True
        dialog._stratum_field.setCurrentText("Land")
        dialog._size_spin.setValue(6)
        dialog.accept()
        result = dialog.get_result()
        assert result is not None
        assert result.config.method == SamplingMethod.STRATIFIED
        assert result.config.stratum_field == "Land"

    def test_cluster_and_stratified_show_all_three_radios(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(
            *_make_dataset(),
            features=SamplingFeatures(show_cluster=True, show_stratified=True),
        )
        qtbot.addWidget(dialog)
        assert hasattr(dialog, "_radio_simple")
        assert hasattr(dialog, "_radio_cluster")
        assert hasattr(dialog, "_radio_stratified")
        # Filter aber weiterhin aus.
        assert not hasattr(dialog, "_filter_field")

    def test_all_off_is_pure_simple_mode(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_NONE)
        qtbot.addWidget(dialog)
        assert hasattr(dialog, "_mode_hint")
        assert not hasattr(dialog, "_radio_simple")
        assert not hasattr(dialog, "_filter_field")
        dialog._size_spin.setValue(2)
        dialog.accept()
        result = dialog.get_result()
        assert result is not None
        assert result.config.method == SamplingMethod.SIMPLE
        assert result.config.filter_field is None
        assert result.config.cluster_field is None
        assert result.config.stratum_field is None


class TestFilterDistinctValuesCache:
    """Sprint 34 / WP5: distinct-Werte werden pro Dialog-Instanz memoisiert.

    Der Provider (`DatasetRepo.distinct_values`) ist ein Full-Table-Scan pro
    Aufruf; das Filter-Feld-Combo feuert `currentTextChanged` auch bei
    Pfeiltasten-Navigation pro Tastendruck. Der Dialog ist modal – das
    Dataset kann sich während seiner Lebensdauer nicht ändern, also darf
    jede Spalte höchstens EINEN Provider-Call auslösen.
    """

    def test_repeated_field_visits_hit_provider_once_per_column(self, qtbot: QtBot) -> None:
        dataset, provider = _make_dataset()
        calls: list[str] = []

        def counting(field: str) -> list[Any]:
            calls.append(field)
            return provider(field)

        dialog = SamplingDialog(dataset, counting, features=SamplingFeatures(show_filter=True))
        qtbot.addWidget(dialog)

        for field in ("Land", "Konto", "Land", "Konto", "Land"):
            dialog._filter_field.setCurrentText(field)
        assert calls == ["Land", "Konto"]  # vorher: 5 Full-Table-Scans, einer pro Wechsel

    def test_cached_values_fill_combo_identically(self, qtbot: QtBot) -> None:
        dataset, provider = _make_dataset()
        dialog = SamplingDialog(dataset, provider, features=SamplingFeatures(show_filter=True))
        qtbot.addWidget(dialog)

        dialog._filter_field.setCurrentText("Land")
        first = [dialog._filter_value.itemData(i) for i in range(dialog._filter_value.count())]
        dialog._filter_field.setCurrentText("Konto")
        dialog._filter_field.setCurrentText("Land")
        second = [dialog._filter_value.itemData(i) for i in range(dialog._filter_value.count())]
        assert first == second == ["AUT", "CHE", "DEU"]


# ---------------------------------------------------------------------------
# Sprint 36: Filter-Operatoren + Schwellenwert-Feld + Match-Preview
# ---------------------------------------------------------------------------

_FILTER = SamplingFeatures(show_filter=True)


def _select_operator(dialog: SamplingDialog, operator: FilterOperator) -> None:
    """Wählt den Operator im Combo per userData-Match."""
    combo = dialog._filter_operator
    for i in range(combo.count()):
        if combo.itemData(i) == operator:
            combo.setCurrentIndex(i)
            return
    raise AssertionError(f"Operator {operator} nicht im Combo gefunden")


def _make_match_provider() -> tuple[
    Callable[[str, FilterOperator, Any, bool], int],
    list[tuple[str, FilterOperator, Any, bool]],
]:
    """Zähl-Fake für den Match-Count-Provider: liefert 3 (restrict) bzw. 7."""
    calls: list[tuple[str, FilterOperator, Any, bool]] = []

    def provider(field: str, operator: FilterOperator, value: Any, restrict: bool) -> int:
        calls.append((field, operator, value, restrict))
        return 3 if restrict else 7

    return provider, calls


class TestFilterOperatorUI:
    """Operator-Combo, Zwei-Modus-Wertfeld, Preview-Timing, Decision-Table."""

    def test_operator_switch_toggles_value_widget(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_FILTER)
        qtbot.addWidget(dialog)
        # Default EQ → distinct-Dropdown-Seite.
        assert dialog._filter_value_stack.currentWidget() is dialog._filter_value
        # Ordering-Op → Textfeld-Seite.
        _select_operator(dialog, FilterOperator.GT)
        assert dialog._filter_value_stack.currentWidget() is dialog._filter_value_text
        assert isinstance(dialog._filter_value_stack.currentWidget(), QLineEdit)
        # Zurück zu NE (EQ/NE) → wieder Dropdown-Seite.
        _select_operator(dialog, FilterOperator.NE)
        assert dialog._filter_value_stack.currentWidget() is dialog._filter_value

    def test_operator_combo_has_six_items(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_FILTER)
        qtbot.addWidget(dialog)
        ops = {dialog._filter_operator.itemData(i) for i in range(dialog._filter_operator.count())}
        assert ops == set(FilterOperator)
        assert dialog._filter_operator.currentData() == FilterOperator.EQ

    def test_preview_reacts_on_editing_finished_not_per_keystroke(self, qtbot: QtBot) -> None:
        ds, dist = _make_dataset()
        match_provider, calls = _make_match_provider()
        dialog = SamplingDialog(
            ds, dist, features=_FILTER, filter_match_count_provider=match_provider
        )
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Betrag")  # EQ-Modus: ein Provider-Call
        _select_operator(dialog, FilterOperator.GT)  # Textfeld leer → kein Call
        before = len(calls)
        # Tastendruck-für-Tastendruck: textChanged feuert, editingFinished nicht.
        for partial in ("1", "10", "100"):
            dialog._filter_value_text.setText(partial)
        assert len(calls) == before  # kein Full-Table-Scan pro Zeichen
        dialog._filter_value_text.editingFinished.emit()
        assert len(calls) == before + 1  # ein Scan bei editingFinished
        assert calls[-1] == ("Betrag", FilterOperator.GT, 100, False)

    def test_size_hint_decision_table(self, qtbot: QtBot) -> None:
        ds, dist = _make_dataset()
        match_provider, calls = _make_match_provider()
        dialog = SamplingDialog(
            ds,
            dist,
            current_sample=_make_sample((1, 3, 5, 7)),
            features=_FILTER,
            filter_match_count_provider=match_provider,
        )
        qtbot.addWidget(dialog)

        # F=nein, R=nein → Datasetgröße.
        assert dialog._effective_max_sample_size() == 12
        # F=nein, R=ja → Größe des bestehenden Samples.
        dialog._resample_checkbox.setChecked(True)
        assert dialog._effective_max_sample_size() == 4
        dialog._resample_checkbox.setChecked(False)
        assert calls == []  # ohne aktiven Filter kein Provider-Aufruf

        # Filter aktivieren (EQ / distinct-Wert).
        dialog._filter_field.setCurrentText("Betrag")
        dialog._filter_value.setCurrentIndex(0)
        # F=ja, R=nein → Provider(..., False) == 7.
        assert dialog._effective_max_sample_size() == 7
        assert "7" in dialog._lbl_size_hint.text()
        # F=ja, R=ja → Provider(..., True) == 3.
        dialog._resample_checkbox.setChecked(True)
        assert dialog._effective_max_sample_size() == 3
        assert "3" in dialog._lbl_size_hint.text()

    def test_provider_none_falls_back_to_dataset_size(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_FILTER)  # kein Provider
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Betrag")
        dialog._filter_value.setCurrentIndex(0)
        # Aktiver Filter, aber Provider None → kein Crash, Datasetgröße.
        assert dialog._effective_max_sample_size() == 12

    def test_match_count_is_memoized(self, qtbot: QtBot) -> None:
        ds, dist = _make_dataset()
        match_provider, calls = _make_match_provider()
        dialog = SamplingDialog(
            ds,
            dist,
            current_sample=_make_sample((1, 3, 5, 7)),
            features=_FILTER,
            filter_match_count_provider=match_provider,
        )
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Betrag")  # 1. Call (…, False)
        dialog._filter_value.setCurrentIndex(0)
        # Resample hin und her: nur zwei distinkte restrict-Kombis.
        for checked in (True, False, True, False):
            dialog._resample_checkbox.setChecked(checked)
        assert len(calls) == 2

    def test_parse_filter_threshold_order(self) -> None:
        assert _parse_filter_threshold("1000") == 1000
        assert type(_parse_filter_threshold("1000")) is int
        assert _parse_filter_threshold("1.5") == 1.5
        assert type(_parse_filter_threshold("1.5")) is float
        assert _parse_filter_threshold("2024-01-01") == date(2024, 1, 1)
        assert type(_parse_filter_threshold("2024-01-01")) is date
        assert _parse_filter_threshold("2024-01-01T10:00") == datetime(2024, 1, 1, 10, 0)
        assert type(_parse_filter_threshold("2024-01-01T10:00")) is datetime
        assert _parse_filter_threshold("abc") == "abc"
        assert type(_parse_filter_threshold("abc")) is str

    def test_build_config_eq_mode(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_FILTER)
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Land")
        dialog._filter_value.setCurrentIndex(0)  # "AUT"
        cfg = dialog._build_config()
        assert cfg.filter_operator == FilterOperator.EQ
        assert cfg.filter_field == "Land"
        assert cfg.filter_value == "AUT"

    def test_build_config_ordering_mode(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_FILTER)
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Betrag")
        _select_operator(dialog, FilterOperator.GTE)
        dialog._filter_value_text.setText("1000")
        cfg = dialog._build_config()
        assert cfg.filter_operator == FilterOperator.GTE
        assert cfg.filter_field == "Betrag"
        assert cfg.filter_value == 1000
        assert type(cfg.filter_value) is int

    def test_build_config_no_filter_is_bit_identical(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_FILTER)
        qtbot.addWidget(dialog)
        cfg = dialog._build_config()
        assert cfg.filter_field is None
        assert cfg.filter_value is None

    def test_validation_blocks_empty_threshold(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_FILTER)
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Betrag")
        _select_operator(dialog, FilterOperator.GT)
        # Leerer Schwellenwert → OK gesperrt.
        assert _ok_enabled(dialog) is False
        dialog._filter_value_text.setText("500")
        assert _ok_enabled(dialog) is True

    def test_apply_preset_ordering_operator(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_FILTER)
        qtbot.addWidget(dialog)
        preset = SamplingPreset(
            name="p",
            method=SamplingMethod.SIMPLE,
            size=3,
            filter_field="Betrag",
            filter_value=1000,
            filter_operator=FilterOperator.GT,
        )
        dialog.apply_preset(preset)
        assert dialog._filter_operator.currentData() == FilterOperator.GT
        assert dialog._filter_value_stack.currentWidget() is dialog._filter_value_text
        assert dialog._filter_value_text.text() == "1000"
        assert dialog._filter_field.currentText() == "Betrag"

    def test_apply_preset_eq_operator_uses_dropdown(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_FILTER)
        qtbot.addWidget(dialog)
        preset = SamplingPreset(
            name="p",
            method=SamplingMethod.SIMPLE,
            size=3,
            filter_field="Land",
            filter_value="AUT",
            filter_operator=FilterOperator.EQ,
        )
        dialog.apply_preset(preset)
        assert dialog._filter_operator.currentData() == FilterOperator.EQ
        assert dialog._filter_value_stack.currentWidget() is dialog._filter_value
        assert dialog._filter_field.currentText() == "Land"
        assert dialog._filter_value.currentText() == "AUT"

    def test_preview_value_agrees_with_build_config(self, qtbot: QtBot) -> None:
        # Struktureller Gleichlauf: der Wert, den der Preview zählt, ist exakt
        # der, den die Ziehung nutzt – für beide Modi (EQ-Dropdown + Ordering).
        dialog = SamplingDialog(*_make_dataset(), features=_FILTER)
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Land")
        dialog._filter_value.setCurrentIndex(0)  # EQ / "AUT"
        assert dialog._active_filter_query()[2] == dialog._build_config().filter_value
        dialog._filter_field.setCurrentText("Betrag")
        _select_operator(dialog, FilterOperator.LT)  # Ordering / Schwellenwert
        dialog._filter_value_text.setText("500")
        assert dialog._active_filter_query()[2] == dialog._build_config().filter_value == 500

    def test_apply_preset_refreshes_size_hint(self, qtbot: QtBot) -> None:
        # Ordering-Preset: der Schwellenwert wird per setText gesetzt (kein
        # editingFinished) → nur das explizite _update_size_hint in apply_preset
        # hält den „max. N verfügbar"-Hinweis aktuell.
        ds, dist = _make_dataset()
        match_provider, calls = _make_match_provider()
        dialog = SamplingDialog(
            ds, dist, features=_FILTER, filter_match_count_provider=match_provider
        )
        qtbot.addWidget(dialog)
        preset = SamplingPreset(
            name="p",
            method=SamplingMethod.SIMPLE,
            size=3,
            filter_field="Betrag",
            filter_value=1000,
            filter_operator=FilterOperator.GT,
        )
        dialog.apply_preset(preset)
        assert ("Betrag", FilterOperator.GT, 1000, False) in calls
        assert "7" in dialog._lbl_size_hint.text()

    def test_manual_threshold_edit_resets_preset_dropdown(self, qtbot: QtBot) -> None:
        # editingFinished am Schwellenwert-Feld = manuelle Filteränderung →
        # Vorlagen-Dropdown zurück auf den Platzhalter.
        dialog = SamplingDialog(*_make_dataset(), features=_FILTER)
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Betrag")
        _select_operator(dialog, FilterOperator.GT)
        dialog._preset_combo.setCurrentIndex(0)
        # Simuliere eine gemerkte Vorlage im Dropdown.
        dialog._preset_combo.addItem("Vorlage X", userData="Vorlage X")
        dialog._preset_combo.setCurrentIndex(dialog._preset_combo.count() - 1)
        dialog._filter_value_text.setText("42")
        dialog._filter_value_text.editingFinished.emit()
        assert dialog._preset_combo.currentIndex() == 0
