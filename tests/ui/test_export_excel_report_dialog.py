"""Tests für `ExportExcelReportDialog` – Sheet-Selektion + Validierung."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialogButtonBox, QLabel
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import Engagement
from sampling_tool.ui.dialogs._export_base import HINT_NO_SHEETS
from sampling_tool.ui.dialogs.export_excel_report_dialog import (
    AVAILABLE_SHEETS,
    ExportExcelReportDialog,
)

pytestmark = pytest.mark.ui


def _engagement() -> Engagement:
    return Engagement(
        auditor_name="Anna",
        client_name="ACME GmbH",
        auditor_position="Senior",
        audit_type="ISAE 3402",
        id=1,
    )


def _ok_enabled(dialog: ExportExcelReportDialog) -> bool:
    box = dialog.findChild(QDialogButtonBox)
    assert box is not None
    btn = box.button(QDialogButtonBox.StandardButton.Ok)
    assert btn is not None
    return bool(btn.isEnabled())


def _hint_text(dialog: ExportExcelReportDialog) -> str:
    label = dialog._target.findChild(QLabel, "exportTargetHint")
    assert label is not None
    return str(label.text())


class TestSelectionHint:
    """Sprint 72: alle Blätter abwählen erklärt sich jetzt selbst."""

    def test_hint_when_nothing_selected(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportExcelReportDialog(_engagement(), default_output_dir=tmp_path)
        qtbot.addWidget(dialog)
        dialog._set_all_sheets(False)
        assert _hint_text(dialog) == HINT_NO_SHEETS
        assert _ok_enabled(dialog) is False

    def test_hint_clears_when_selection_restored(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportExcelReportDialog(_engagement(), default_output_dir=tmp_path)
        qtbot.addWidget(dialog)
        dialog._set_all_sheets(False)
        assert _hint_text(dialog) == HINT_NO_SHEETS

        dialog._select_only_overview()

        assert _hint_text(dialog) == ""
        assert _ok_enabled(dialog) is True


class TestExportExcelReportDialog:
    def test_default_all_sheets_checked(self, qtbot: QtBot) -> None:
        dialog = ExportExcelReportDialog(_engagement())
        qtbot.addWidget(dialog)
        assert dialog._selected_sheets() == set(AVAILABLE_SHEETS)

    def test_only_overview_button(self, qtbot: QtBot) -> None:
        dialog = ExportExcelReportDialog(_engagement())
        qtbot.addWidget(dialog)
        dialog._select_only_overview()
        assert dialog._selected_sheets() == {"Übersicht"}

    def test_ok_disabled_when_no_sheet_selected(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportExcelReportDialog(_engagement(), default_output_dir=tmp_path)
        qtbot.addWidget(dialog)
        assert _ok_enabled(dialog) is True
        dialog._set_all_sheets(False)
        assert _ok_enabled(dialog) is False

    def test_ok_disabled_without_output_dir(self, qtbot: QtBot) -> None:
        dialog = ExportExcelReportDialog(_engagement())
        qtbot.addWidget(dialog)
        assert _ok_enabled(dialog) is False

    def test_get_result_returns_filled_dataclass(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportExcelReportDialog(_engagement(), default_output_dir=tmp_path)
        qtbot.addWidget(dialog)
        # AuditTrail-Sheet abwählen.
        for i in range(dialog._sheet_list.count()):
            item = dialog._sheet_list.item(i)
            assert item is not None
            if item.text() == "AuditTrail":
                item.setCheckState(Qt.CheckState.Unchecked)
        dialog._on_accept()
        result = dialog.get_result()
        assert result is not None
        assert result.output_path.parent == tmp_path
        assert result.output_path.suffix == ".xlsx"
        assert "report" in result.output_path.name
        assert "AuditTrail" not in result.sheets
        assert {"Übersicht", "Samples", "Statistiken"} == result.sheets
