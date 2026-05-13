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


class TestFirstRunCompleted:
    def test_default_is_false(self) -> None:
        assert AppSettings.defaults().first_run_completed is False

    def test_roundtrip_true(self) -> None:
        original = replace(AppSettings.defaults(), first_run_completed=True)
        save_settings(original)
        loaded = load_settings()
        assert loaded.first_run_completed is True

    def test_neuinstallation_first_run_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Leere QSettings + Default-Ordner existiert nicht → first_run False."""
        from sampling_tool import config
        from sampling_tool.ui import settings_store

        ghost_dir = tmp_path / "does-not-exist"
        monkeypatch.setattr(config, "ENGAGEMENTS_DIR", ghost_dir)
        monkeypatch.setattr(settings_store, "ENGAGEMENTS_DIR", ghost_dir)
        # Defaults muss frisch gebaut werden, damit der monkeypatched
        # ENGAGEMENTS_DIR in den `base` einfließt.
        loaded = load_settings()
        assert loaded.first_run_completed is False

    def test_migration_default_dir_exists_sets_flag_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Leere QSettings + Default-Pfad existiert → Migration setzt True."""
        from sampling_tool import config
        from sampling_tool.ui import settings_store

        existing = tmp_path / "existing-engagements"
        existing.mkdir()
        monkeypatch.setattr(config, "ENGAGEMENTS_DIR", existing)
        monkeypatch.setattr(settings_store, "ENGAGEMENTS_DIR", existing)
        loaded = load_settings()
        assert loaded.first_run_completed is True

    def test_migration_custom_dir_sets_flag_true(self, tmp_path: Path) -> None:
        """QSettings hat eigenen engagements_dir, kein first_run-Key →
        Bestandsuser, Flag wird True."""
        s = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG, APP_NAME)
        s.setValue("settings/engagements_dir", str(tmp_path / "custom"))
        s.sync()
        loaded = load_settings()
        assert loaded.first_run_completed is True

    def test_migration_persists_flag_to_qsettings(self, tmp_path: Path) -> None:
        """Nach Migration steht first_run_completed=True direkt in QSettings."""
        s = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG, APP_NAME)
        s.setValue("settings/engagements_dir", str(tmp_path / "custom"))
        s.sync()
        # Vor load_settings ist der Key NICHT da.
        assert not s.contains("settings/first_run_completed")
        load_settings()
        # Nach load_settings IST er da.
        fresh = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG, APP_NAME)
        assert fresh.contains("settings/first_run_completed")
        assert _to_bool(fresh.value("settings/first_run_completed")) is True


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)
