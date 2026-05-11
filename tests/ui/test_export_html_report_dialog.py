"""Tests für `ExportHtmlReportDialog` – Inhalt-Toggles + Validierung."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QDialogButtonBox
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
