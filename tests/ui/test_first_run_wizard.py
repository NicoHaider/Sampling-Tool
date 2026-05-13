"""FirstRunWizard – Page-Aufbau, Validierung, Result-Konstruktion."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from sampling_tool.ui.dialogs.first_run_wizard import FirstRunResult, FirstRunWizard

pytestmark = pytest.mark.ui


class TestFirstRunWizard:
    def test_wizard_hat_vier_pages(self, qtbot: QtBot) -> None:
        wizard = FirstRunWizard()
        qtbot.addWidget(wizard)
        assert len(wizard.pageIds()) == 4

    def test_default_pfad_aus_config(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from sampling_tool import config

        custom_dir = tmp_path / "engagements"
        monkeypatch.setattr(config, "ENGAGEMENTS_DIR", custom_dir)
        wizard = FirstRunWizard()
        qtbot.addWidget(wizard)
        assert wizard._page_folder._line_edit.text() == str(custom_dir)

    def test_validate_page_legt_ordner_an(self, qtbot: QtBot, tmp_path: Path) -> None:
        wizard = FirstRunWizard()
        qtbot.addWidget(wizard)
        target = tmp_path / "new-subdir"
        wizard._page_folder._line_edit.setText(str(target))
        assert not target.exists()
        ok = wizard._page_folder.validatePage()
        assert ok is True
        assert target.exists()
        assert target.is_dir()

    def test_validate_page_zeigt_fehler_bei_oserror(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wizard = FirstRunWizard()
        qtbot.addWidget(wizard)

        original_mkdir = Path.mkdir

        def fake_mkdir(self: Path, *args: object, **kwargs: object) -> None:
            if "blocked" in str(self):
                raise PermissionError("denied")
            original_mkdir(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "mkdir", fake_mkdir)
        warnings: list[str] = []

        def fake_warning(*_a: object, **_kw: object) -> QMessageBox.StandardButton:
            warnings.append("called")
            return QMessageBox.StandardButton.Ok

        monkeypatch.setattr(QMessageBox, "warning", fake_warning)
        wizard._page_folder._line_edit.setText(str(tmp_path / "blocked"))
        ok = wizard._page_folder.validatePage()
        assert ok is False
        assert warnings == ["called"]

    def test_result_data_enthaelt_user_input(self, qtbot: QtBot, tmp_path: Path) -> None:
        wizard = FirstRunWizard()
        qtbot.addWidget(wizard)
        wizard._page_folder._line_edit.setText(str(tmp_path / "my-engagements"))
        wizard._page_auditor._line_edit.setText("Max Mustermann")
        # validatePage legt den Ordner an und normalisiert den Pfad
        wizard._page_folder.validatePage()
        result = wizard.result_data()
        assert isinstance(result, FirstRunResult)
        assert result.engagements_dir.endswith("my-engagements")
        assert result.default_auditor_name == "Max Mustermann"

    def test_auditor_name_optional_kann_leer_sein(self, qtbot: QtBot) -> None:
        wizard = FirstRunWizard()
        qtbot.addWidget(wizard)
        result = wizard.result_data()
        assert result.default_auditor_name == ""

    def test_auditor_name_wird_getrimmt(self, qtbot: QtBot) -> None:
        wizard = FirstRunWizard()
        qtbot.addWidget(wizard)
        wizard._page_auditor._line_edit.setText("   Mit Whitespace   ")
        result = wizard.result_data()
        assert result.default_auditor_name == "Mit Whitespace"
