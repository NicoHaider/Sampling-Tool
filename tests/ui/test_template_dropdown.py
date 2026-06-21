"""Sprint 32 – Vorlagen als Dropdown statt Chips, „+" entfernt.

Die Sprint-28-Chip-Leiste + das „+" im Stichproben-Dialog sind durch ein
kompaktes `QComboBox`-Dropdown ersetzt: ein neutraler Platzhalter-Eintrag plus
je gespeicherter Vorlage ein Eintrag. Auswahl wendet die Vorlage an
(`apply_preset`: setzt nur Parameter, zieht NICHT). Speichern/Anlegen passiert
ab jetzt ausschließlich im Verwaltungsfenster. Die Sprint-23-Mechanik
(`PresetStore`, `apply_preset`, `current_settings_as_preset`) bleibt unverändert.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QMessageBox, QPushButton
from pytestqt.qtbot import QtBot

from sampling_tool.config import APP_NAME, APP_ORG
from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    SamplingMethod,
)
from sampling_tool.core.presets import SamplingPreset
from sampling_tool.core.sampling import create_sampler
from sampling_tool.ui.dialogs.sampling_dialog import (
    NO_FILTER_LABEL,
    PRESET_PLACEHOLDER,
    SamplingDialog,
)
from sampling_tool.ui.preset_store import PresetStore
from sampling_tool.ui.settings_store import SamplingFeatures

pytestmark = pytest.mark.ui

_ALL = SamplingFeatures(show_filter=True, show_cluster=True, show_stratified=True)


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Schiebt `QSettings`-IO in tmp – wie `test_sampling_presets`."""
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    monkeypatch.setattr(
        "sampling_tool.ui.settings_store._qsettings",
        lambda: QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG, APP_NAME),
    )


def _make_dataset() -> tuple[Dataset, Any]:
    distinct: dict[str, list[Any]] = {
        "Land": ["AUT", "CHE", "DEU"],
        "Konto": [f"K{i:03d}" for i in range(1, 13)],
        "Betrag": [i * 10 for i in range(1, 13)],
    }
    dataset = Dataset(name="t", columns=("Land", "Konto", "Betrag"), row_count=12)
    return dataset, lambda field: distinct.get(field, [])


def _combo_items(dialog: SamplingDialog) -> list[str]:
    combo = dialog._preset_combo
    return [combo.itemText(i) for i in range(combo.count())]


def _select_preset(dialog: SamplingDialog, name: str) -> None:
    """Simuliert die Nutzer-Auswahl einer Vorlage im Dropdown.

    Setzt den Index und feuert `activated` (das Signal, das auch ein echter
    Klick im Dropdown auslöst) – `currentIndexChanged` allein würde Anwenden
    nicht triggern.
    """
    combo = dialog._preset_combo
    idx = combo.findData(name)
    if idx < 0:
        raise AssertionError(f"Keine Vorlage {name!r} im Dropdown ({_combo_items(dialog)})")
    combo.setCurrentIndex(idx)
    combo.activated.emit(idx)


# ---------------------------------------------------------------------------
# TestPresetDropdown (§4)
# ---------------------------------------------------------------------------


class TestPresetDropdown:
    def test_dropdown_lists_all_presets_plus_placeholder(self, qtbot: QtBot) -> None:
        store = PresetStore()
        store.save(SamplingPreset(name="Alpha", method=SamplingMethod.SIMPLE, size=5))
        store.save(SamplingPreset(name="Beta", method=SamplingMethod.SIMPLE, size=9))
        dialog = SamplingDialog(*_make_dataset(), features=_ALL, preset_store=store)
        qtbot.addWidget(dialog)
        # Platzhalter zuerst, dann je Vorlage genau ein Eintrag.
        assert _combo_items(dialog) == [PRESET_PLACEHOLDER, "Alpha", "Beta"]
        # Beim Öffnen steht das Dropdown auf dem Platzhalter (keine Vorlage aktiv).
        assert dialog._preset_combo.currentIndex() == 0

    def test_empty_store_shows_only_placeholder(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_ALL, preset_store=PresetStore())
        qtbot.addWidget(dialog)
        # Leere-Liste-Fall: nur der Platzhalter, Dropdown bleibt benutzbar.
        assert _combo_items(dialog) == [PRESET_PLACEHOLDER]
        assert dialog._preset_combo.isEnabled()

    def test_selecting_preset_applies_without_drawing(self, qtbot: QtBot) -> None:
        store = PresetStore()
        store.save(
            SamplingPreset(
                name="Gross",
                method=SamplingMethod.SIMPLE,
                size=9,
                filter_field="Land",
                filter_value="AUT",
            )
        )
        dialog = SamplingDialog(*_make_dataset(), features=_ALL, preset_store=store)
        qtbot.addWidget(dialog)
        seed_before = dialog._seed_spin.value()
        # Andere Einstellungen vorlegen …
        dialog._size_spin.setValue(2)
        dialog._filter_field.setCurrentText(NO_FILTER_LABEL)
        # … dann die Vorlage im Dropdown wählen (= apply_preset).
        _select_preset(dialog, "Gross")
        cfg = dialog._build_config()
        assert cfg.method == SamplingMethod.SIMPLE
        assert cfg.size == 9
        assert cfg.filter_field == "Land"
        assert cfg.filter_value == "AUT"
        # Anwenden zieht NICHT – kein Ergebnis …
        assert dialog.get_result() is None
        # … und lässt den Seed in Ruhe (Reproduzierbarkeits-Neutralität).
        assert dialog._seed_spin.value() == seed_before

    def test_manual_change_resets_dropdown_to_placeholder(self, qtbot: QtBot) -> None:
        store = PresetStore()
        store.save(SamplingPreset(name="Alpha", method=SamplingMethod.SIMPLE, size=9))
        dialog = SamplingDialog(*_make_dataset(), features=_ALL, preset_store=store)
        qtbot.addWidget(dialog)

        # Größen-Änderung hebt die Auswahl auf.
        _select_preset(dialog, "Alpha")
        assert dialog._preset_combo.currentText() == "Alpha"
        dialog._size_spin.setValue(3)
        assert dialog._preset_combo.currentIndex() == 0
        assert dialog._preset_combo.currentText() == PRESET_PLACEHOLDER

        # Methoden-Änderung hebt die Auswahl auf.
        _select_preset(dialog, "Alpha")
        assert dialog._preset_combo.currentText() == "Alpha"
        dialog._radio_cluster.setChecked(True)
        assert dialog._preset_combo.currentIndex() == 0

        # Filter-Änderung hebt die Auswahl auf.
        _select_preset(dialog, "Alpha")
        assert dialog._preset_combo.currentText() == "Alpha"
        dialog._filter_field.setCurrentText("Land")
        assert dialog._preset_combo.currentIndex() == 0

    def test_selecting_placeholder_is_noop(self, qtbot: QtBot) -> None:
        # Der Platzhalter (Index 0, kein `userData`) darf nichts anwenden und
        # nicht crashen – auch wenn er nach einer Auswahl erneut gewählt wird.
        store = PresetStore()
        store.save(SamplingPreset(name="Alpha", method=SamplingMethod.SIMPLE, size=9))
        dialog = SamplingDialog(*_make_dataset(), features=_ALL, preset_store=store)
        qtbot.addWidget(dialog)
        dialog._size_spin.setValue(3)
        combo = dialog._preset_combo
        combo.setCurrentIndex(0)
        combo.activated.emit(0)
        assert dialog._size_spin.value() == 3  # unverändert – nichts angewandt
        assert dialog.get_result() is None  # und nichts gezogen

    def test_selecting_deleted_preset_recovers(self, qtbot: QtBot) -> None:
        # Vorlage wird (im Verwaltungsfenster) entfernt, während der Dialog offen
        # ist – die Auswahl des veralteten Eintrags lädt das Dropdown neu statt
        # zu crashen.
        store = PresetStore()
        store.save(SamplingPreset(name="Weg", method=SamplingMethod.SIMPLE, size=9))
        dialog = SamplingDialog(*_make_dataset(), features=_ALL, preset_store=store)
        qtbot.addWidget(dialog)
        combo = dialog._preset_combo
        idx = combo.findData("Weg")
        assert idx >= 0
        store.delete("Weg")
        combo.setCurrentIndex(idx)
        combo.activated.emit(idx)
        # Dropdown frisch geladen (nur noch der Platzhalter), kein Ergebnis.
        assert _combo_items(dialog) == [PRESET_PLACEHOLDER]
        assert dialog.get_result() is None

    def test_skipped_filter_reports_information(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Population OHNE die Filter-Spalte „Land".
        store = PresetStore()
        store.save(
            SamplingPreset(
                name="MitFilter",
                method=SamplingMethod.SIMPLE,
                size=4,
                filter_field="Land",
                filter_value="AUT",
            )
        )
        dataset = Dataset(name="t", columns=("Konto", "Betrag"), row_count=10)
        dialog = SamplingDialog(
            dataset, lambda field: [], current_sample=None, features=_ALL, preset_store=store
        )
        qtbot.addWidget(dialog)
        infos: list[tuple[str, str]] = []

        def _info(_parent: object, title: str, text: str, *a: object, **k: object) -> int:
            infos.append((title, text))
            return 0

        monkeypatch.setattr(QMessageBox, "information", _info)
        _select_preset(dialog, "MitFilter")
        # Übersprungene Filter werden gemeldet …
        assert len(infos) == 1
        assert "Land" in infos[0][1]
        # … der Rest ist trotzdem angewandt …
        assert dialog._size_spin.value() == 4
        # … und der Filter selbst ist neutralisiert (kein Crash).
        assert dialog._filter_field.currentText() == NO_FILTER_LABEL
        assert dialog._build_config().filter_field is None
        # Die (teilweise) angewandte Vorlage bleibt im Dropdown ausgewählt –
        # die filter-bedingte Widget-Änderung räumt die Auswahl nicht weg
        # (`_applying_preset`-Guard).
        assert dialog._preset_combo.currentText() == "MitFilter"

    def test_no_add_button_present(self, qtbot: QtBot) -> None:
        # Regression gegen Sprint 28: Das „+"-Speichern ist aus dem Dialog raus.
        store = PresetStore()
        store.save(SamplingPreset(name="X", method=SamplingMethod.SIMPLE, size=3))
        dialog = SamplingDialog(*_make_dataset(), features=_ALL, preset_store=store)
        qtbot.addWidget(dialog)
        assert not hasattr(dialog, "_btn_add_preset")
        assert all(btn.text() != "+" for btn in dialog.findChildren(QPushButton))


# ---------------------------------------------------------------------------
# TestDropdownApplySamplingNeutrality (§5 – Reproduzierbarkeit)
# ---------------------------------------------------------------------------


def _rows() -> list[DatasetRow]:
    return [
        DatasetRow(
            row_id=i,
            values={"Land": ["AUT", "CHE", "DEU"][i % 3], "Konto": f"K{i:03d}", "Betrag": i * 10},
        )
        for i in range(1, 13)
    ]


class TestDropdownApplySamplingNeutrality:
    def test_dropdown_apply_then_draw_equals_manual_then_draw(self, qtbot: QtBot) -> None:
        seed = 4711
        # (a) Manuell konfigurieren und ziehen.
        manual = SamplingDialog(*_make_dataset(), features=_ALL)
        qtbot.addWidget(manual)
        manual._size_spin.setValue(2)
        manual._seed_spin.setValue(seed)
        manual._filter_field.setCurrentText("Land")
        manual._filter_value.setCurrentIndex(0)  # AUT
        manual.accept()
        manual_result = manual.get_result()
        assert manual_result is not None
        manual_config = manual_result.config

        # (b) Dieselben Werte als Vorlage per Dropdown anwenden, gleichen Seed, ziehen.
        store = PresetStore()
        store.save(SamplingPreset.from_config("AUT", manual_config))
        combo_dialog = SamplingDialog(*_make_dataset(), features=_ALL, preset_store=store)
        qtbot.addWidget(combo_dialog)
        _select_preset(combo_dialog, "AUT")
        combo_dialog._seed_spin.setValue(seed)
        combo_dialog.accept()
        combo_result = combo_dialog.get_result()
        assert combo_result is not None

        assert combo_result.config == manual_config
        rows = _rows()
        a = create_sampler(manual_config).sample(list(rows), population_size=len(rows))
        b = create_sampler(combo_result.config).sample(list(rows), population_size=len(rows))
        assert a.selected_row_ids == b.selected_row_ids


# ---------------------------------------------------------------------------
# TestTemplatesPersistAppWide (§4 – Vorlagen app-weit, nicht in Projekt-DB)
# ---------------------------------------------------------------------------


class TestTemplatesPersistAppWide:
    def test_templates_persist_across_store_instances(self, qtbot: QtBot) -> None:
        # Vorlage aus den aktuellen Dialog-Einstellungen bilden und speichern.
        store = PresetStore()
        dialog = SamplingDialog(*_make_dataset(), features=_ALL, preset_store=store)
        qtbot.addWidget(dialog)
        dialog._size_spin.setValue(6)
        store.save(dialog.current_settings_as_preset("AppWeit"))

        # Ein FRISCHER Store (andere Instanz, kein Projekt-Kontext) sieht es →
        # app-weit persistiert, nicht an ein Projekt/eine DB gebunden.
        assert "AppWeit" in PresetStore().names()
        # Und ein neu geöffneter Dialog zeigt es im Dropdown.
        dialog2 = SamplingDialog(*_make_dataset(), features=_ALL, preset_store=PresetStore())
        qtbot.addWidget(dialog2)
        assert "AppWeit" in _combo_items(dialog2)
