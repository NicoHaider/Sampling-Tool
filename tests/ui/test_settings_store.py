"""Tests für `settings_store`: save/load-Roundtrip via `QSettings`."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings

from sampling_tool.config import APP_NAME, APP_ORG
from sampling_tool.ui.settings_store import (
    DEFAULT_LOG_LEVEL,
    DEFAULT_UNDO_DEPTH,
    AppSettings,
    load_settings,
    save_settings,
)

pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Schiebt `QSettings`-IO in einen tmp-Pfad, damit echte Prefs nicht
    angefasst werden."""
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path),
    )
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    # Zwingt unseren Code in das tmp-INI; vorhandene QSettings()-Aufrufe
    # picken Format/Pfad automatisch auf.
    monkeypatch.setattr(
        "sampling_tool.ui.settings_store._qsettings",
        lambda: QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            APP_ORG,
            APP_NAME,
        ),
    )


class TestDefaults:
    def test_defaults_have_sensible_values(self) -> None:
        d = AppSettings.defaults()
        assert d.default_auditor_name == ""
        assert d.undo_depth == DEFAULT_UNDO_DEPTH
        assert d.log_level == DEFAULT_LOG_LEVEL
        assert d.reset_keeps_filter is False
        assert d.default_include_briefpapier is True
        assert d.default_include_statistics is True
        assert d.custom_briefpapier_path is None

    def test_load_returns_defaults_when_empty(self) -> None:
        loaded = load_settings()
        assert loaded.default_auditor_name == ""
        assert loaded.log_level == DEFAULT_LOG_LEVEL


class TestRoundtrip:
    def test_save_then_load_returns_same_values(self, tmp_path: Path) -> None:
        custom_path = tmp_path / "letter.pdf"
        original = replace(
            AppSettings.defaults(),
            default_auditor_name="Anna",
            engagements_dir=tmp_path / "engagements",
            reset_keeps_filter=True,
            custom_briefpapier_path=custom_path,
            undo_depth=42,
            snapshot_retention_days=7,
            log_level="DEBUG",
        )
        save_settings(original)
        loaded = load_settings()

        assert loaded.default_auditor_name == "Anna"
        assert loaded.engagements_dir == tmp_path / "engagements"
        assert loaded.reset_keeps_filter is True
        assert loaded.custom_briefpapier_path == custom_path
        assert loaded.undo_depth == 42
        assert loaded.snapshot_retention_days == 7
        assert loaded.log_level == "DEBUG"

    def test_save_none_custom_briefpapier_roundtrips(self) -> None:
        original = replace(AppSettings.defaults(), custom_briefpapier_path=None)
        save_settings(original)
        loaded = load_settings()
        assert loaded.custom_briefpapier_path is None

    def test_invalid_log_level_falls_back_to_default(self) -> None:
        # Direkt in QSettings einen unbekannten Wert ablegen.
        s = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG, APP_NAME)
        s.setValue("settings/log_level", "TRACE")
        s.sync()
        loaded = load_settings()
        assert loaded.log_level == DEFAULT_LOG_LEVEL

    def test_invalid_undo_depth_falls_back_to_default(self) -> None:
        s = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG, APP_NAME)
        s.setValue("settings/undo_depth", "not-a-number")
        s.sync()
        loaded = load_settings()
        assert loaded.undo_depth == DEFAULT_UNDO_DEPTH


class TestAdvancedMode:
    def test_advanced_mode_default_is_false(self) -> None:
        assert AppSettings.defaults().advanced_mode is False

    def test_advanced_mode_roundtrips_true(self) -> None:
        original = replace(AppSettings.defaults(), advanced_mode=True)
        save_settings(original)
        loaded = load_settings()
        assert loaded.advanced_mode is True

    def test_advanced_mode_missing_key_defaults_to_false(self) -> None:
        # QSettings ohne advanced_mode-Key → load_settings liefert False.
        loaded = load_settings()
        assert loaded.advanced_mode is False


class TestPanelVisibilityFlags:
    def test_show_dashboard_default_is_true(self) -> None:
        assert AppSettings.defaults().show_dashboard is True

    def test_show_audit_trail_default_is_true(self) -> None:
        assert AppSettings.defaults().show_audit_trail is True

    def test_show_dashboard_roundtrips_false(self) -> None:
        original = replace(AppSettings.defaults(), show_dashboard=False)
        save_settings(original)
        loaded = load_settings()
        assert loaded.show_dashboard is False
        # andere Panel-Flag bleibt davon unberührt
        assert loaded.show_audit_trail is True

    def test_show_audit_trail_roundtrips_false(self) -> None:
        original = replace(AppSettings.defaults(), show_audit_trail=False)
        save_settings(original)
        loaded = load_settings()
        assert loaded.show_audit_trail is False
        assert loaded.show_dashboard is True

    def test_panel_flags_missing_keys_default_to_true(self) -> None:
        # QSettings ohne show_*-Keys → load_settings liefert True / True.
        loaded = load_settings()
        assert loaded.show_dashboard is True
        assert loaded.show_audit_trail is True
