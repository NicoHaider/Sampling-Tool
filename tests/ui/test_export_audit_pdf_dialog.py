"""Tests für `ExportAuditPdfDialog` – Filter, Optionen, Validierung."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialogButtonBox
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import Engagement
from sampling_tool.ui.dialogs.export_audit_pdf_dialog import (
    ExportAuditPdfDialog,
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


def _ok_enabled(dialog: ExportAuditPdfDialog) -> bool:
    box = dialog.findChild(QDialogButtonBox)
    assert box is not None
    btn = box.button(QDialogButtonBox.StandardButton.Ok)
    assert btn is not None
    return bool(btn.isEnabled())


class TestExportAuditPdfDialog:
    def test_default_all_types_checked(self, qtbot: QtBot) -> None:
        dialog = ExportAuditPdfDialog(
            engagement=_engagement(),
            event_types_available=["sampling", "import", "export"],
            briefpapier_available=True,
        )
        qtbot.addWidget(dialog)
        assert dialog._selected_types() == {"sampling", "import", "export"}

    def test_falls_back_to_default_types_when_empty(self, qtbot: QtBot) -> None:
        dialog = ExportAuditPdfDialog(
            engagement=_engagement(),
            event_types_available=[],
            briefpapier_available=True,
        )
        qtbot.addWidget(dialog)
        assert {"sampling", "reset", "import", "export"}.issubset(dialog._selected_types())

    def test_briefpapier_disabled_when_unavailable(self, qtbot: QtBot) -> None:
        dialog = ExportAuditPdfDialog(
            engagement=_engagement(),
            event_types_available=["sampling"],
            briefpapier_available=False,
        )
        qtbot.addWidget(dialog)
        assert dialog._cb_briefpapier.isEnabled() is False
        assert dialog._cb_briefpapier.isChecked() is False
        assert "nicht konfiguriert" in dialog._cb_briefpapier.toolTip()

    def test_briefpapier_enabled_when_available(self, qtbot: QtBot) -> None:
        dialog = ExportAuditPdfDialog(
            engagement=_engagement(),
            event_types_available=["sampling"],
            briefpapier_available=True,
        )
        qtbot.addWidget(dialog)
        assert dialog._cb_briefpapier.isEnabled() is True
        assert dialog._cb_briefpapier.isChecked() is True

    def test_ok_disabled_without_output_dir(self, qtbot: QtBot) -> None:
        dialog = ExportAuditPdfDialog(
            engagement=_engagement(),
            event_types_available=["sampling"],
            briefpapier_available=True,
        )
        qtbot.addWidget(dialog)
        assert _ok_enabled(dialog) is False

    def test_ok_disabled_when_no_event_types_selected(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportAuditPdfDialog(
            engagement=_engagement(),
            event_types_available=["sampling", "import"],
            briefpapier_available=True,
            default_output_dir=tmp_path,
        )
        qtbot.addWidget(dialog)
        assert _ok_enabled(dialog) is True
        dialog._set_all_types(False)
        assert _ok_enabled(dialog) is False

    def test_date_range_enables_qdateedit(self, qtbot: QtBot) -> None:
        dialog = ExportAuditPdfDialog(
            engagement=_engagement(),
            event_types_available=["sampling"],
            briefpapier_available=True,
        )
        qtbot.addWidget(dialog)
        assert dialog._from_date.isEnabled() is False
        dialog._from_check.setChecked(True)
        assert dialog._from_date.isEnabled() is True

    def test_get_result_returns_full_dataclass(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportAuditPdfDialog(
            engagement=_engagement(),
            event_types_available=["sampling", "import"],
            briefpapier_available=True,
            default_output_dir=tmp_path,
        )
        qtbot.addWidget(dialog)
        # Bis-Datum aktivieren und gezielt setzen.
        dialog._to_check.setChecked(True)
        # 2. Eintrag (import) abwählen.
        item = dialog._types_list.item(1)
        assert item is not None
        item.setCheckState(Qt.CheckState.Unchecked)
        dialog._cb_statistics.setChecked(False)

        dialog._on_accept()
        result = dialog.get_result()
        assert result is not None
        assert result.output_path.parent == tmp_path
        assert result.output_path.suffix == ".pdf"
        assert "audit_trail" in result.output_path.name
        assert result.event_types == {"sampling"}
        assert result.date_from is None
        assert isinstance(result.date_to, date)
        assert result.use_briefpapier is True
        assert result.include_statistics is False
