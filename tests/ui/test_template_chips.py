"""Sprint 28 – Vorlagen als Chips + „+" im Stichproben-Bereich.

Die Sprint-23-Combobox + Buttons (Anwenden/Umbenennen/Löschen) im
Stichproben-Dialog sind durch eine Chip-Leiste (ein Chip je Vorlage,
Klick → `apply_preset`) plus genau ein „+" (aktuelle Einstellungen als neue
Vorlage speichern) ersetzt. Die Sprint-23-Mechanik (`PresetStore`,
`apply_preset`, `current_settings_as_preset`) bleibt unverändert wiederverwendet.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QInputDialog, QMessageBox, QPushButton
from pytestqt.qtbot import QtBot

from sampling_tool.config import APP_NAME, APP_ORG
from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    SamplingMethod,
)
from sampling_tool.core.presets import SamplingPreset
from sampling_tool.core.sampling import create_sampler
from sampling_tool.ui.dialogs.sampling_dialog import NO_FILTER_LABEL, SamplingDialog
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


def _chip_named(dialog: SamplingDialog, name: str) -> QPushButton:
    for chip in dialog._preset_chips:
        if chip.text() == name:
            return chip
    raise AssertionError(f"Kein Chip mit Namen {name!r} (vorhanden: {_chip_names(dialog)})")


def _chip_names(dialog: SamplingDialog) -> list[str]:
    return [chip.text() for chip in dialog._preset_chips]


# ---------------------------------------------------------------------------
# TestTemplateChips (§4)
# ---------------------------------------------------------------------------


class TestTemplateChips:
    def test_chips_list_saved_templates(self, qtbot: QtBot) -> None:
        store = PresetStore()
        store.save(SamplingPreset(name="Alpha", method=SamplingMethod.SIMPLE, size=5))
        store.save(SamplingPreset(name="Beta", method=SamplingMethod.SIMPLE, size=9))
        dialog = SamplingDialog(*_make_dataset(), features=_ALL, preset_store=store)
        qtbot.addWidget(dialog)
        # Pro gespeicherter Vorlage genau ein Chip mit korrektem Namen.
        assert _chip_names(dialog) == ["Alpha", "Beta"]

    def test_chip_click_applies_template(self, qtbot: QtBot) -> None:
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
        # Andere Einstellungen vorlegen …
        dialog._size_spin.setValue(2)
        dialog._filter_field.setCurrentText(NO_FILTER_LABEL)
        # … dann den Chip klicken (= apply_preset).
        _chip_named(dialog, "Gross").click()
        cfg = dialog._build_config()
        assert cfg.method == SamplingMethod.SIMPLE
        assert cfg.size == 9
        assert cfg.filter_field == "Land"
        assert cfg.filter_value == "AUT"
        # Anwenden zieht NICHT – kein Ergebnis.
        assert dialog.get_result() is None

    def test_plus_saves_current_as_new_template(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = PresetStore()
        dialog = SamplingDialog(*_make_dataset(), features=_ALL, preset_store=store)
        qtbot.addWidget(dialog)
        dialog._size_spin.setValue(7)
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Meine Vorlage", True))
        dialog._btn_add_preset.click()
        # Liegt im Store …
        got = store.get("Meine Vorlage")
        assert got is not None
        assert got.size == 7
        # … und erscheint als Chip.
        assert "Meine Vorlage" in _chip_names(dialog)

    def test_plus_overwrite_prompts_confirmation(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = PresetStore()
        store.save(SamplingPreset(name="X", method=SamplingMethod.SIMPLE, size=3))
        dialog = SamplingDialog(*_make_dataset(), features=_ALL, preset_store=store)
        qtbot.addWidget(dialog)
        dialog._size_spin.setValue(11)
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("X", True))
        asked: list[bool] = []

        def _question(*a: object, **k: object) -> QMessageBox.StandardButton:
            asked.append(True)
            return QMessageBox.StandardButton.Yes

        monkeypatch.setattr(QMessageBox, "question", _question)
        dialog._btn_add_preset.click()
        assert asked == [True]  # Überschreiben wurde bestätigt-abgefragt.
        got = store.get("X")
        assert got is not None
        assert got.size == 11
        assert len(store.list()) == 1

    def test_chip_apply_surfaces_skipped_filters(
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
        _chip_named(dialog, "MitFilter").click()
        # Übersprungene Filter werden gemeldet …
        assert len(infos) == 1
        assert "Land" in infos[0][1]
        # … der Rest ist trotzdem angewandt …
        assert dialog._size_spin.value() == 4
        # … und der Filter selbst ist neutralisiert (kein Crash).
        assert dialog._filter_field.currentText() == NO_FILTER_LABEL
        assert dialog._build_config().filter_field is None


# ---------------------------------------------------------------------------
# TestChipApplySamplingNeutrality (§5 – Reproduzierbarkeit)
# ---------------------------------------------------------------------------


def _rows() -> list[DatasetRow]:
    return [
        DatasetRow(
            row_id=i,
            values={"Land": ["AUT", "CHE", "DEU"][i % 3], "Konto": f"K{i:03d}", "Betrag": i * 10},
        )
        for i in range(1, 13)
    ]


class TestChipApplySamplingNeutrality:
    def test_chip_apply_then_draw_equals_manual_then_draw(self, qtbot: QtBot) -> None:
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

        # (b) Dieselben Werte als Vorlage per Chip anwenden, gleichen Seed, ziehen.
        store = PresetStore()
        store.save(SamplingPreset.from_config("AUT", manual_config))
        chip_dialog = SamplingDialog(*_make_dataset(), features=_ALL, preset_store=store)
        qtbot.addWidget(chip_dialog)
        _chip_named(chip_dialog, "AUT").click()
        chip_dialog._seed_spin.setValue(seed)
        chip_dialog.accept()
        chip_result = chip_dialog.get_result()
        assert chip_result is not None

        assert chip_result.config == manual_config
        rows = _rows()
        a = create_sampler(manual_config).sample(list(rows), population_size=len(rows))
        b = create_sampler(chip_result.config).sample(list(rows), population_size=len(rows))
        assert a.selected_row_ids == b.selected_row_ids

    def test_plus_save_does_not_draw(self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
        store = PresetStore()
        dialog = SamplingDialog(*_make_dataset(), features=_ALL, preset_store=store)
        qtbot.addWidget(dialog)
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Neu", True))
        dialog._btn_add_preset.click()
        # „+" (Speichern) löst keine Ziehung aus.
        assert dialog.get_result() is None
        assert store.get("Neu") is not None


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
        # Und ein neu geöffneter Dialog zeigt es als Chip.
        dialog2 = SamplingDialog(*_make_dataset(), features=_ALL, preset_store=PresetStore())
        qtbot.addWidget(dialog2)
        assert "AppWeit" in _chip_names(dialog2)
