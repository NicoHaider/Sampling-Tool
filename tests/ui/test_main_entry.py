"""Tests für die App-Entry-Helper (Wizard-Trigger, Settings-Merge)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QWizard
from pytestqt.qtbot import QtBot

from sampling_tool.__main__ import run_first_run_wizard
from sampling_tool.config import APP_NAME, APP_ORG
from sampling_tool.ui.dialogs.first_run_wizard import FirstRunWizard
from sampling_tool.ui.settings_store import AppSettings

pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path: Path) -> None:
    """Schiebt QSettings-IO in ein tmp-Ini, damit echte Prefs unangetastet bleiben."""
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    _ = APP_ORG, APP_NAME  # nur Imports halten


class TestRunFirstRunWizard:
    def test_accepted_merged_user_input(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Bei Accept fließen Folder + Auditor in das neue AppSettings."""

        def fake_exec(self: FirstRunWizard) -> int:
            self._page_folder._line_edit.setText(str(tmp_path / "chosen"))
            self._page_auditor._line_edit.setText("Anna Auditorin")
            self._page_folder.validatePage()
            return int(QWizard.DialogCode.Accepted)

        monkeypatch.setattr(FirstRunWizard, "exec", fake_exec)
        initial = AppSettings.defaults()
        out = run_first_run_wizard(initial)
        assert out.first_run_completed is True
        assert str(out.engagements_dir).endswith("chosen")
        assert out.default_auditor_name == "Anna Auditorin"

    def test_rejected_keeps_defaults_but_sets_flag(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bei Cancel bleibt initial unverändert, aber first_run_completed=True."""
        monkeypatch.setattr(FirstRunWizard, "exec", lambda _self: int(QWizard.DialogCode.Rejected))
        initial = replace(AppSettings.defaults(), default_auditor_name="prev-user")
        out = run_first_run_wizard(initial)
        assert out.first_run_completed is True
        assert out.engagements_dir == initial.engagements_dir
        assert out.default_auditor_name == "prev-user"
