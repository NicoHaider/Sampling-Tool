"""Tests für `SettingsDialog`: Tabs laden, Reset, Result-Konstruktion."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QDialog, QMessageBox
from pytestqt.qtbot import QtBot

from sampling_tool.ui.dialogs.settings_dialog import SettingsDialog
from sampling_tool.ui.settings_store import AppSettings

pytestmark = pytest.mark.ui


@pytest.fixture
def defaults() -> AppSettings:
    return AppSettings.defaults()


class TestSettingsDialog:
    def test_dialog_constructs_with_defaults(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        assert dialog._auditor_name.text() == ""
        assert dialog._radio_placeholder.isChecked()
        assert dialog._reset_keeps_filter.isChecked() is False
        assert dialog._default_briefpapier.isChecked() is True

    def test_dialog_loads_current_values(self, qtbot: QtBot, tmp_path: Path) -> None:
        custom = tmp_path / "custom.pdf"
        custom.write_bytes(b"%PDF-1.4\n")
        current = replace(
            AppSettings.defaults(),
            default_auditor_name="Bob",
            custom_briefpapier_path=custom,
            undo_depth=11,
            log_level="DEBUG",
        )
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        assert dialog._auditor_name.text() == "Bob"
        assert dialog._radio_custom.isChecked()
        assert dialog._custom_briefpapier.text() == str(custom)
        assert dialog._undo_depth.value() == 11
        assert dialog._log_level.currentText() == "DEBUG"

    def test_get_settings_returns_none_before_accept(
        self, qtbot: QtBot, defaults: AppSettings
    ) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        assert dialog.get_settings() is None

    def test_accept_produces_result_with_form_values(
        self, qtbot: QtBot, defaults: AppSettings, tmp_path: Path
    ) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        dialog._auditor_name.setText("Carla")
        dialog._engagements_dir.setText(str(tmp_path / "eng"))
        dialog._reset_keeps_filter.setChecked(True)
        dialog._undo_depth.setValue(30)
        idx = dialog._log_level.findText("DEBUG")
        dialog._log_level.setCurrentIndex(idx)

        dialog._on_accept()
        result = dialog.get_settings()
        assert result is not None
        assert result.default_auditor_name == "Carla"
        assert result.engagements_dir == tmp_path / "eng"
        assert result.reset_keeps_filter is True
        assert result.undo_depth == 30
        assert result.log_level == "DEBUG"

    def test_accept_with_empty_engagements_dir_does_not_close(
        self, qtbot: QtBot, defaults: AppSettings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        dialog._engagements_dir.setText("")
        called: list[bool] = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *_a, **_k: called.append(True))

        dialog._on_accept()
        assert called == [True]
        assert dialog.get_settings() is None

    def test_reset_button_restores_defaults(
        self, qtbot: QtBot, defaults: AppSettings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        current = replace(
            defaults,
            default_auditor_name="Z",
            undo_depth=99,
            reset_keeps_filter=True,
        )
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes
        )
        dialog._on_reset_defaults()
        assert dialog._auditor_name.text() == ""
        assert dialog._undo_depth.value() == defaults.undo_depth
        assert dialog._reset_keeps_filter.isChecked() is False

    def test_custom_radio_disables_when_placeholder_selected(
        self, qtbot: QtBot, defaults: AppSettings
    ) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        dialog._radio_placeholder.setChecked(True)
        dialog._on_accept()
        # leerer Pfad bei Placeholder-Modus → custom_briefpapier_path None.
        assert dialog.get_settings() is not None
        assert dialog.get_settings().custom_briefpapier_path is None  # type: ignore[union-attr]

    def test_cancel_keeps_result_none(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        dialog.reject()
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert dialog.get_settings() is None


class TestAdvancedModeToggle:
    def test_checkbox_shows_initial_value(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        assert dialog._chk_advanced_mode.isChecked() is False

    def test_checkbox_prefilled_when_enabled(self, qtbot: QtBot, defaults: AppSettings) -> None:
        current = replace(defaults, advanced_mode=True)
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        assert dialog._chk_advanced_mode.isChecked() is True

    def test_ok_propagates_advanced_mode(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        dialog._chk_advanced_mode.setChecked(True)
        dialog._on_accept()
        result = dialog.get_settings()
        assert result is not None
        assert result.advanced_mode is True

    def test_reset_to_defaults_unchecks_advanced(
        self, qtbot: QtBot, defaults: AppSettings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        current = replace(defaults, advanced_mode=True)
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes
        )
        dialog._on_reset_defaults()
        assert dialog._chk_advanced_mode.isChecked() is False


class TestPanelVisibilityToggle:
    def test_dialog_zeigt_panel_checkboxen_mit_defaults(
        self, qtbot: QtBot, defaults: AppSettings
    ) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        assert dialog._chk_show_dashboard.isChecked() is True
        assert dialog._chk_show_audit_trail.isChecked() is True

    def test_dialog_prefilled_panel_flags(self, qtbot: QtBot, defaults: AppSettings) -> None:
        current = replace(defaults, show_dashboard=False, show_audit_trail=True)
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        assert dialog._chk_show_dashboard.isChecked() is False
        assert dialog._chk_show_audit_trail.isChecked() is True

    def test_ok_propagates_panel_flags(self, qtbot: QtBot, defaults: AppSettings) -> None:
        dialog = SettingsDialog(defaults)
        qtbot.addWidget(dialog)
        dialog._chk_show_dashboard.setChecked(False)
        dialog._chk_show_audit_trail.setChecked(False)
        dialog._on_accept()
        result = dialog.get_settings()
        assert result is not None
        assert result.show_dashboard is False
        assert result.show_audit_trail is False

    def test_reset_to_defaults_restores_panel_flags(
        self, qtbot: QtBot, defaults: AppSettings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        current = replace(defaults, show_dashboard=False, show_audit_trail=False)
        dialog = SettingsDialog(current)
        qtbot.addWidget(dialog)
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes
        )
        dialog._on_reset_defaults()
        assert dialog._chk_show_dashboard.isChecked() is True
        assert dialog._chk_show_audit_trail.isChecked() is True
