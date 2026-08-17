"""Tests für die App-Entry-Helper (Wizard-Trigger, Settings-Merge)."""

from __future__ import annotations

import inspect
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


class TestHighDpiRoundingPolicy:
    """Die DPI-Rundungspolitik und – vor allem – ihre Reihenfolge (Sprint 78 / §2.6).

    Gemessen mit Qt 6.11.0: ohne explizite Zeile liefert
    `QGuiApplication.highDpiScaleFactorRoundingPolicy()` bereits `PassThrough`.
    Die Zeile ändert also NICHTS am Erscheinungsbild – sie schreibt den heutigen
    Default fest, damit eine künftige Qt-Version ihn nicht unbemerkt kippt.
    `Round` würde aus einer Windows-Skalierung von 125 % ein 100 % machen und
    Fenster wie Schriften auf jedem Bestandsrechner schrumpfen lassen.
    """

    def _main_source_lines(self) -> list[str]:
        import sampling_tool.__main__ as entry

        return inspect.getsource(entry.main).splitlines()

    def _index_of(self, needle: str) -> int:
        for index, line in enumerate(self._main_source_lines()):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if needle in stripped:
                return index
        raise AssertionError(f"{needle!r} kommt in main() nicht vor")

    def test_policy_is_set_before_the_qapplication_is_created(self) -> None:
        """Nach `QApplication(...)` gesetzt bleibt die Policy wirkungslos.

        Deshalb ist die Reihenfolge festgenagelt: die Zeile darf nicht unter die
        `QApplication`-Zeile rutschen.
        """
        policy_line = self._index_of("setHighDpiScaleFactorRoundingPolicy")
        app_line = self._index_of("QApplication(sys.argv)")
        assert policy_line < app_line, (
            f"Policy-Zeile steht in Zeile {policy_line}, QApplication in {app_line} – "
            "die Policy wirkt so nicht mehr."
        )

    def test_policy_is_pass_through(self) -> None:
        """PassThrough ist der gemessene Qt-6.11-Default und der gewünschte Wert:
        125 % Windows-Skalierung bleiben 1.25 statt auf 1.0 gerundet zu werden."""
        source = "\n".join(self._main_source_lines())
        assert "Qt.HighDpiScaleFactorRoundingPolicy.PassThrough" in source

    def test_documented_default_still_matches_this_qt_version(self) -> None:
        """Positiv-Kontrolle für die Begründung: sollte ein künftiges Qt den
        Default ändern, wird dieser Test rot – und die Behauptung „ändert nichts"
        muss dann neu geprüft werden, statt still falsch zu werden."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QGuiApplication

        assert (
            QGuiApplication.highDpiScaleFactorRoundingPolicy()
            == Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
