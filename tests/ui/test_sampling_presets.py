"""Sprint 23 – Sampling-Presets: Store (QSettings) + Dialog-Integration.

Drei Ebenen:
1. `PresetStore` – app-weite CRUD-Persistenz via QSettings (JSON).
2. `SamplingDialog.current_settings_as_preset` / `apply_preset` – Preset aus
   den aktuellen Dialog-Einstellungen bilden bzw. wieder einspielen, inkl.
   Spalten-Validierung beim Anwenden auf eine andere Population.
3. Reproduzierbarkeit – ein angewendetes Preset zieht identisch zur manuellen
   Einstellung; das Anwenden zieht selbst NICHT.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from sampling_tool.config import APP_NAME, APP_ORG
from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    SamplingMethod,
    StratifyMode,
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
    """Schiebt `QSettings`-IO in tmp – wie `test_feature_toggles`."""
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


# ---------------------------------------------------------------------------
# 1. PresetStore (QSettings)
# ---------------------------------------------------------------------------


class TestPresetStore:
    def test_persists_app_wide(self) -> None:
        store = PresetStore()
        store.save(SamplingPreset(name="A", method=SamplingMethod.SIMPLE, size=5))
        # Frischer Store (anderer Instanz) sieht das Preset → nicht an ein
        # Engagement gebunden, app-weit persistiert.
        assert "A" in PresetStore().names()
        assert PresetStore().get("A") is not None

    def test_overwrite_same_name_keeps_count(self) -> None:
        store = PresetStore()
        store.save(SamplingPreset(name="A", method=SamplingMethod.SIMPLE, size=5))
        store.save(SamplingPreset(name="A", method=SamplingMethod.SIMPLE, size=9))
        presets = store.list()
        assert len(presets) == 1
        got = store.get("A")
        assert got is not None
        assert got.size == 9

    def test_rename_changes_only_name(self) -> None:
        store = PresetStore()
        store.save(SamplingPreset(name="A", method=SamplingMethod.SIMPLE, size=5))
        assert store.rename("A", "B") is True
        assert store.names() == ["B"]
        got = store.get("B")
        assert got is not None
        assert got.size == 5

    def test_rename_missing_returns_false(self) -> None:
        store = PresetStore()
        assert store.rename("ghost", "x") is False

    def test_delete_removes_preset(self) -> None:
        store = PresetStore()
        store.save(SamplingPreset(name="A", method=SamplingMethod.SIMPLE, size=5))
        store.delete("A")
        assert store.names() == []

    def test_list_sorted_case_insensitive(self) -> None:
        store = PresetStore()
        for name in ("zeta", "Alpha", "mike"):
            store.save(SamplingPreset(name=name, method=SamplingMethod.SIMPLE, size=2))
        assert store.names() == ["Alpha", "mike", "zeta"]


# ---------------------------------------------------------------------------
# 2. Dialog: current_settings_as_preset / apply_preset
# ---------------------------------------------------------------------------


class TestSamplingPresets:
    def test_save_and_apply_roundtrip(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_ALL)
        qtbot.addWidget(dialog)
        dialog._size_spin.setValue(8)
        dialog._filter_field.setCurrentText("Land")
        dialog._filter_value.setCurrentIndex(0)  # AUT
        preset = dialog.current_settings_as_preset("Standard")

        # Einstellungen verändern …
        dialog._size_spin.setValue(2)
        dialog._filter_field.setCurrentText(NO_FILTER_LABEL)

        # … und das Preset wieder anwenden.
        result = dialog.apply_preset(preset)
        assert result.skipped_filters == ()
        cfg = dialog._build_config()
        assert cfg.method == SamplingMethod.SIMPLE
        assert cfg.size == 8
        assert cfg.filter_field == "Land"
        assert cfg.filter_value == preset.filter_value == "AUT"

    def test_preset_excludes_seed(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_ALL)
        qtbot.addWidget(dialog)
        dialog._seed_spin.setValue(555)
        preset = dialog.current_settings_as_preset("p")
        assert not hasattr(preset, "seed")
        # Ein fremdes Preset anwenden lässt den aktuellen Seed unberührt.
        dialog.apply_preset(SamplingPreset(name="x", method=SamplingMethod.SIMPLE, size=3))
        assert dialog._seed_spin.value() == 555

    def test_apply_stratified_preset_sets_method_and_mode(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_ALL)
        qtbot.addWidget(dialog)
        preset = SamplingPreset(
            name="Schicht",
            method=SamplingMethod.STRATIFIED,
            size=6,
            stratum_field="Land",
            stratify_mode=StratifyMode.EQUAL,
        )
        dialog.apply_preset(preset)
        cfg = dialog._build_config()
        assert cfg.method == SamplingMethod.STRATIFIED
        assert cfg.stratum_field == "Land"
        assert cfg.stratify_mode == StratifyMode.EQUAL

    def test_apply_skips_missing_columns(self, qtbot: QtBot) -> None:
        # Population OHNE die Filter-Spalte „Land".
        dataset = Dataset(name="t", columns=("Konto", "Betrag"), row_count=10)
        dialog = SamplingDialog(dataset, lambda field: [], current_sample=None, features=_ALL)
        qtbot.addWidget(dialog)
        preset = SamplingPreset(
            name="p",
            method=SamplingMethod.SIMPLE,
            size=4,
            filter_field="Land",
            filter_value="AUT",
        )
        result = dialog.apply_preset(preset)
        # Der Filter auf die fehlende Spalte wird gemeldet …
        assert "Land" in result.skipped_filters
        # … die übrigen Einstellungen sind trotzdem gesetzt (kein Crash) …
        assert dialog._size_spin.value() == 4
        # … und der Filter selbst ist neutralisiert.
        assert dialog._filter_field.currentText() == NO_FILTER_LABEL
        assert dialog._build_config().filter_field is None

    def test_apply_skips_missing_filter_value(self, qtbot: QtBot) -> None:
        # Spalte „Land" existiert, aber der Preset-Wert „AUT" kommt in dieser
        # Population NICHT vor. Statt still auf einen anderen Wert zu fallen,
        # wird der Filter übersprungen und gemeldet (kein stiller Fehlschlag).
        dataset = Dataset(name="t", columns=("Land", "Betrag"), row_count=10)
        dialog = SamplingDialog(
            dataset,
            lambda field: ["CHE", "DEU"] if field == "Land" else [],
            features=_ALL,
        )
        qtbot.addWidget(dialog)
        preset = SamplingPreset(
            name="p",
            method=SamplingMethod.SIMPLE,
            size=2,
            filter_field="Land",
            filter_value="AUT",
        )
        result = dialog.apply_preset(preset)
        assert "Land" in result.skipped_filters
        assert dialog._filter_field.currentText() == NO_FILTER_LABEL
        assert dialog._build_config().filter_field is None


# ---------------------------------------------------------------------------
# 3. Reproduzierbarkeit (Pflicht §5)
# ---------------------------------------------------------------------------


def _rows() -> list[DatasetRow]:
    return [
        DatasetRow(
            row_id=i,
            values={"Land": ["AUT", "CHE", "DEU"][i % 3], "Konto": f"K{i:03d}", "Betrag": i * 10},
        )
        for i in range(1, 13)
    ]


class TestPresetSamplingNeutrality:
    def test_preset_then_draw_equals_manual_then_draw(self, qtbot: QtBot) -> None:
        seed = 4711
        # (a) Manuell konfigurieren und ziehen.
        manual_dialog = SamplingDialog(*_make_dataset(), features=_ALL)
        qtbot.addWidget(manual_dialog)
        manual_dialog._size_spin.setValue(2)
        manual_dialog._seed_spin.setValue(seed)
        manual_dialog._filter_field.setCurrentText("Land")
        manual_dialog._filter_value.setCurrentIndex(0)  # AUT
        manual_dialog.accept()
        manual_result = manual_dialog.get_result()
        assert manual_result is not None
        manual_config = manual_result.config

        # (b) Dieselben Werte als Preset anwenden, gleichen Seed setzen, ziehen.
        preset = SamplingPreset.from_config("AUT", manual_config)
        preset_dialog = SamplingDialog(*_make_dataset(), features=_ALL)
        qtbot.addWidget(preset_dialog)
        preset_dialog.apply_preset(preset)
        preset_dialog._seed_spin.setValue(seed)
        preset_dialog.accept()
        preset_result = preset_dialog.get_result()
        assert preset_result is not None
        preset_config = preset_result.config

        # Konfiguration identisch (bis auf eine eventuelle Beschreibung) …
        assert preset_config == manual_config
        # … und die tatsächliche Ziehung identisch.
        rows = _rows()
        a = create_sampler(manual_config).sample(list(rows), population_size=len(rows))
        b = create_sampler(preset_config).sample(list(rows), population_size=len(rows))
        assert a.selected_row_ids == b.selected_row_ids

    def test_apply_preset_does_not_draw(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), features=_ALL)
        qtbot.addWidget(dialog)
        dialog.apply_preset(SamplingPreset(name="p", method=SamplingMethod.SIMPLE, size=3))
        # Anwenden setzt nur Parameter – es zieht NICHT (kein Result).
        assert dialog.get_result() is None


# Die UI-Bedienung der Vorlagen (Chips + „+" im Stichproben-Dialog,
# Verwaltungsfenster) ist seit Sprint 28 in tests/ui/test_template_chips.py und
# tests/ui/test_template_manager_dialog.py abgedeckt. `apply_preset` /
# `current_settings_as_preset` (oben) bleiben die unveränderte Sprint-23-Mechanik.
