"""Tests für `ExportAuditPdfDialog` – Filter, Optionen, Validierung."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import QDialogButtonBox
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import AuditEvent, Engagement
from sampling_tool.ui.controllers.export_controller import filter_audit_events
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

    def test_date_group_absent_when_filter_off(self, qtbot: QtBot) -> None:
        # Sprint 27: Default (Toggle aus) → kein Datumsschritt, Felder fehlen.
        dialog = ExportAuditPdfDialog(
            engagement=_engagement(),
            event_types_available=["sampling"],
            briefpapier_available=True,
        )
        qtbot.addWidget(dialog)
        assert not hasattr(dialog, "_from_date")
        assert not hasattr(dialog, "_to_date")

    def test_date_fields_present_and_enabled_when_filter_on(self, qtbot: QtBot) -> None:
        # Sprint 27: Toggle an → von/bis sind DIREKT editierbar (Bug-Fix).
        dialog = ExportAuditPdfDialog(
            engagement=_engagement(),
            event_types_available=["sampling"],
            briefpapier_available=True,
            offer_date_filter=True,
        )
        qtbot.addWidget(dialog)
        assert dialog._from_date.isEnabled() is True
        assert dialog._to_date.isEnabled() is True

    def test_result_dates_none_when_filter_off(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportAuditPdfDialog(
            engagement=_engagement(),
            event_types_available=["sampling"],
            briefpapier_available=True,
            default_output_dir=tmp_path,
        )
        qtbot.addWidget(dialog)
        dialog._on_accept()
        result = dialog.get_result()
        assert result is not None
        assert result.date_from is None
        assert result.date_to is None

    def test_get_result_returns_full_dataclass(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportAuditPdfDialog(
            engagement=_engagement(),
            event_types_available=["sampling", "import"],
            briefpapier_available=True,
            default_output_dir=tmp_path,
            offer_date_filter=True,
        )
        qtbot.addWidget(dialog)
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
        assert isinstance(result.date_from, date)
        assert isinstance(result.date_to, date)
        assert result.use_briefpapier is True
        assert result.include_statistics is False


def _event(event_type: str, day: int) -> AuditEvent:
    return AuditEvent(
        event_type=event_type,
        engagement_id=1,
        timestamp=datetime(2024, 6, day, 12, 0, tzinfo=UTC),
    )


class TestAuditExportDateFilter:
    """Sprint 27: Datumsfilter im Audit-Export – toggelbar, Default aus."""

    def test_date_filter_default_off(self) -> None:
        from sampling_tool.ui.settings_store import AppSettings

        assert AppSettings.defaults().audit_export_offer_date_filter is False

    def test_date_filter_off_exports_all(self) -> None:
        # Toggle aus → date_from/date_to None → alle Events, kein Datumsschritt.
        events = [_event("sampling", 1), _event("import", 10), _event("export", 20)]
        filtered = filter_audit_events(events, set(), date_from=None, date_to=None)
        assert filtered == events

    def test_date_filter_on_restricts_range(self) -> None:
        events = [_event("sampling", 1), _event("import", 10), _event("export", 20)]
        filtered = filter_audit_events(
            events,
            set(),
            date_from=date(2024, 6, 5),
            date_to=date(2024, 6, 15),
        )
        assert [e.event_type for e in filtered] == ["import"]

    def test_date_inputs_accept_values(self, qtbot: QtBot, tmp_path: Path) -> None:
        # Regression gegen den Bug: die von/bis-Eingaben lassen sich setzen
        # und werden ausgelesen.
        dialog = ExportAuditPdfDialog(
            engagement=_engagement(),
            event_types_available=["sampling"],
            briefpapier_available=True,
            default_output_dir=tmp_path,
            offer_date_filter=True,
        )
        qtbot.addWidget(dialog)
        dialog._from_date.setDate(QDate(2024, 1, 2))
        dialog._to_date.setDate(QDate(2024, 3, 4))
        dialog._on_accept()
        result = dialog.get_result()
        assert result is not None
        assert result.date_from == date(2024, 1, 2)
        assert result.date_to == date(2024, 3, 4)
