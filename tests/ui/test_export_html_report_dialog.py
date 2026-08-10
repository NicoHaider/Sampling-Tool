"""Tests für `ExportHtmlReportDialog` – Inhalt-Toggles + Validierung."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QDialogButtonBox, QLabel
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import Engagement
from sampling_tool.ui.dialogs.export_html_report_dialog import ExportHtmlReportDialog

pytestmark = pytest.mark.ui


def _engagement() -> Engagement:
    return Engagement(
        auditor_name="Anna",
        client_name="ACME GmbH",
        auditor_position="Senior",
        audit_type="ISAE 3402",
        id=1,
    )


def _ok_enabled(dialog: ExportHtmlReportDialog) -> bool:
    box = dialog.findChild(QDialogButtonBox)
    assert box is not None
    btn = box.button(QDialogButtonBox.StandardButton.Ok)
    assert btn is not None
    return bool(btn.isEnabled())


def _hint_text(dialog: ExportHtmlReportDialog) -> str:
    label = dialog._target.findChild(QLabel, "exportTargetHint")
    assert label is not None
    return str(label.text())


class TestSelectionHint:
    """Sprint 72: dieser Dialog ist der einzige OHNE Auswahl-Bedingung.

    Bewusst festgenagelt: kommt später eine dazu (z. B. „mindestens ein
    Inhaltsblock"), fällt dieser Test auf und erzwingt einen Hinweistext,
    statt wieder still einen grauen Button zu erzeugen.
    """

    def test_html_dialog_has_no_selection_hint(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportHtmlReportDialog(_engagement(), default_output_dir=tmp_path)
        qtbot.addWidget(dialog)
        assert dialog._selection_hint() == ""

        # Alle drei Inhalts-Toggles aus → weiterhin kein Hinweis, OK bleibt aktiv
        # (ein Report ohne Zusatzblöcke ist ein gültiges Ergebnis).
        dialog._cb_charts.setChecked(False)
        dialog._cb_audit_trail.setChecked(False)
        dialog._cb_samples.setChecked(False)

        assert _hint_text(dialog) == ""
        assert _ok_enabled(dialog) is True


class TestExportHtmlReportDialog:
    def test_defaults_all_options_on(self, qtbot: QtBot) -> None:
        dialog = ExportHtmlReportDialog(_engagement())
        qtbot.addWidget(dialog)
        assert dialog._cb_charts.isChecked() is True
        assert dialog._cb_audit_trail.isChecked() is True
        assert dialog._cb_samples.isChecked() is True

    def test_ok_disabled_without_output_dir(self, qtbot: QtBot) -> None:
        dialog = ExportHtmlReportDialog(_engagement())
        qtbot.addWidget(dialog)
        assert _ok_enabled(dialog) is False

    def test_ok_enabled_when_path_set(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportHtmlReportDialog(_engagement(), default_output_dir=tmp_path)
        qtbot.addWidget(dialog)
        assert _ok_enabled(dialog) is True

    def test_get_result_reflects_unchecked_toggles(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportHtmlReportDialog(_engagement(), default_output_dir=tmp_path)
        qtbot.addWidget(dialog)
        dialog._cb_charts.setChecked(False)
        dialog._cb_audit_trail.setChecked(False)
        dialog._on_accept()
        result = dialog.get_result()
        assert result is not None
        assert result.output_path.parent == tmp_path
        assert result.output_path.suffix == ".html"
        assert result.include_charts is False
        assert result.include_audit_trail is False
        assert result.include_samples_table is True
