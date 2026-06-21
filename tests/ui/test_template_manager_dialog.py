"""Sprint 28 – Verwaltungsfenster für Vorlagen (`TemplateManagerDialog`).

Eigenes Fenster (Menü „Stichprobe → Vorlagen verwalten…") zum Auflisten,
Umbenennen, Löschen, Duplizieren und Bearbeiten der app-weit gespeicherten
Vorlagen – alles über die unveränderte `PresetStore`-Schicht (Sprint 23).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QInputDialog, QMessageBox
from pytestqt.qtbot import QtBot

from sampling_tool.config import APP_NAME, APP_ORG, DEFAULT_SAMPLE_SIZE
from sampling_tool.core.models import SamplingMethod, StratifyMode
from sampling_tool.core.presets import SamplingPreset
from sampling_tool.ui.dialogs.template_manager_dialog import TemplateManagerDialog
from sampling_tool.ui.preset_store import PresetStore

pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    monkeypatch.setattr(
        "sampling_tool.ui.settings_store._qsettings",
        lambda: QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG, APP_NAME),
    )


def _list_names(dialog: TemplateManagerDialog) -> list[str]:
    names: list[str] = []
    for i in range(dialog._list.count()):
        item = dialog._list.item(i)
        if item is not None:
            names.append(item.text())
    return names


def _select(dialog: TemplateManagerDialog, name: str) -> None:
    for i in range(dialog._list.count()):
        item = dialog._list.item(i)
        if item is not None and item.text() == name:
            dialog._list.setCurrentRow(i)
            return
    raise AssertionError(f"Vorlage {name!r} nicht in der Liste ({_list_names(dialog)})")


class TestTemplateManagerDialog:
    def test_lists_templates(self, qtbot: QtBot) -> None:
        store = PresetStore()
        for name in ("Gamma", "Alpha", "Beta"):
            store.save(SamplingPreset(name=name, method=SamplingMethod.SIMPLE, size=3))
        dialog = TemplateManagerDialog(store)
        qtbot.addWidget(dialog)
        # Alle Vorlagen werden gelistet (alphabetisch wie im Store).
        assert _list_names(dialog) == ["Alpha", "Beta", "Gamma"]

    def test_rename_and_delete_via_store(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = PresetStore()
        store.save(SamplingPreset(name="Alt", method=SamplingMethod.SIMPLE, size=5))
        store.save(SamplingPreset(name="Bleibt", method=SamplingMethod.SIMPLE, size=8))
        dialog = TemplateManagerDialog(store)
        qtbot.addWidget(dialog)

        # Umbenennen wirkt über den Store.
        _select(dialog, "Alt")
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Neu", True))
        dialog._on_rename()
        assert store.names() == ["Bleibt", "Neu"]
        assert _list_names(dialog) == ["Bleibt", "Neu"]

        # Löschen wirkt über den Store.
        _select(dialog, "Bleibt")
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        dialog._on_delete()
        assert store.names() == ["Neu"]
        assert _list_names(dialog) == ["Neu"]

    def test_changes_reflected_in_sampling_dropdown_after_reload(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sampling_tool.core.models import Dataset
        from sampling_tool.ui.dialogs.sampling_dialog import PRESET_PLACEHOLDER, SamplingDialog
        from sampling_tool.ui.settings_store import SamplingFeatures

        store = PresetStore()
        store.save(SamplingPreset(name="Vorher", method=SamplingMethod.SIMPLE, size=5))
        manager = TemplateManagerDialog(store)
        qtbot.addWidget(manager)
        _select(manager, "Vorher")
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Nachher", True))
        manager._on_rename()

        # Ein neu geöffneter Stichproben-Dialog spiegelt die Umbenennung im
        # Dropdown (das Dropdown lädt frisch aus dem Store).
        dataset = Dataset(name="t", columns=("A",), row_count=4)
        sampling_dialog = SamplingDialog(
            dataset,
            lambda _field: [],
            features=SamplingFeatures(),
            preset_store=PresetStore(),
        )
        qtbot.addWidget(sampling_dialog)
        combo = sampling_dialog._preset_combo
        items = [combo.itemText(i) for i in range(combo.count())]
        assert items == [PRESET_PLACEHOLDER, "Nachher"]

    def test_edit_template_persists(self, qtbot: QtBot) -> None:
        store = PresetStore()
        store.save(SamplingPreset(name="P", method=SamplingMethod.SIMPLE, size=5))
        dialog = TemplateManagerDialog(store)
        qtbot.addWidget(dialog)
        _select(dialog, "P")

        # Konfiguration ändern: Methode, Größe, Schicht-Feld, -Verteilung.
        dialog._set_edit_method(SamplingMethod.STRATIFIED)
        dialog._edit_size.setValue(12)
        dialog._edit_stratum_field.setText("Land")
        dialog._set_edit_stratify_mode(StratifyMode.EQUAL)
        dialog._on_save_edit()

        got = store.get("P")
        assert got is not None
        assert got.size == 12
        assert got.method == SamplingMethod.STRATIFIED
        assert got.stratum_field == "Land"
        assert got.stratify_mode == StratifyMode.EQUAL

    def test_duplicate_creates_copy(self, qtbot: QtBot) -> None:
        store = PresetStore()
        store.save(SamplingPreset(name="Original", method=SamplingMethod.SIMPLE, size=7))
        dialog = TemplateManagerDialog(store)
        qtbot.addWidget(dialog)
        _select(dialog, "Original")
        dialog._on_duplicate()
        names = store.names()
        # Original bleibt, eine Kopie kommt hinzu (gleiche Konfiguration).
        assert "Original" in names
        copies = [n for n in names if n != "Original"]
        assert len(copies) == 1
        copy = store.get(copies[0])
        assert copy is not None
        assert copy.size == 7


class TestCreateNewTemplate:
    """Sprint 32 – „Neue Vorlage…" legt die erste/eine neue Vorlage an.

    Da das „+" im Stichproben-Dialog entfällt, ist das Verwaltungsfenster der
    einzige Ort, an dem Vorlagen angelegt werden.
    """

    def test_new_button_creates_default_preset_via_store(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = PresetStore()
        dialog = TemplateManagerDialog(store)
        qtbot.addWidget(dialog)
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Frisch", True))
        dialog._btn_new.click()

        # Neue Default-Vorlage liegt im Store …
        got = store.get("Frisch")
        assert got is not None
        assert got.method == SamplingMethod.SIMPLE
        assert got.size == DEFAULT_SAMPLE_SIZE
        assert got.filter_field is None
        assert got.cluster_field is None
        assert got.stratum_field is None
        assert got.stratify_mode == StratifyMode.PROPORTIONAL
        # … und ist in der Liste selektiert (sofort bearbeitbar).
        assert "Frisch" in _list_names(dialog)
        assert dialog._selected_name() == "Frisch"

    def test_new_button_enabled_with_empty_list(self, qtbot: QtBot) -> None:
        # Ohne Vorlagen sind die per-Item-Aktionen aus – „Neue Vorlage…" bleibt
        # bedienbar, sonst gäbe es keinen Weg, die erste Vorlage anzulegen.
        store = PresetStore()
        dialog = TemplateManagerDialog(store)
        qtbot.addWidget(dialog)
        assert dialog._list.count() == 0
        assert dialog._btn_new.isEnabled() is True

    def test_new_template_then_editable(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = PresetStore()
        dialog = TemplateManagerDialog(store)
        qtbot.addWidget(dialog)
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Frisch", True))
        dialog._btn_new.click()

        # Direkt im rechten Formular bearbeiten + speichern.
        dialog._set_edit_method(SamplingMethod.STRATIFIED)
        dialog._edit_size.setValue(42)
        dialog._edit_stratum_field.setText("Land")
        dialog._set_edit_stratify_mode(StratifyMode.EQUAL)
        dialog._on_save_edit()

        got = store.get("Frisch")
        assert got is not None
        assert got.size == 42
        assert got.method == SamplingMethod.STRATIFIED
        assert got.stratum_field == "Land"
        assert got.stratify_mode == StratifyMode.EQUAL

    def test_new_name_collision_confirms_overwrite(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = PresetStore()
        store.save(SamplingPreset(name="Da", method=SamplingMethod.SIMPLE, size=5))
        dialog = TemplateManagerDialog(store)
        qtbot.addWidget(dialog)
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Da", True))
        asked: list[bool] = []

        def _question(*a: object, **k: object) -> QMessageBox.StandardButton:
            asked.append(True)
            return QMessageBox.StandardButton.Yes

        monkeypatch.setattr(QMessageBox, "question", _question)
        dialog._btn_new.click()

        # Die vorhandene Überschreib-Bestätigung wurde genutzt …
        assert asked == [True]
        # … und die Default-Vorlage hat die alte ersetzt (kein Duplikat).
        got = store.get("Da")
        assert got is not None
        assert got.size == DEFAULT_SAMPLE_SIZE
        assert len(store.list()) == 1
