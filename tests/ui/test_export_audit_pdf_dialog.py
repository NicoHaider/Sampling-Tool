"""Tests für `ExportAuditPdfDialog` – Filter, Optionen, Validierung."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import QDialogButtonBox, QScrollArea
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import AuditEvent, Engagement
from sampling_tool.io.bdo_locations import companies, locations
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


class TestBdoCompanyLocationDropdowns:
    """Sprint 33: zwei UNABHÄNGIGE Dropdowns (Gesellschaft + Standort), die sich
    nicht gegenseitig filtern – jede Gesellschaft ist mit jedem Standort
    kombinierbar."""

    def _dialog(
        self,
        qtbot: QtBot,
        *,
        company_key: str | None = None,
        location_key: str | None = None,
    ) -> ExportAuditPdfDialog:
        dialog = ExportAuditPdfDialog(
            engagement=_engagement(),
            event_types_available=["sampling"],
            briefpapier_available=True,
            default_company_key=company_key,
            default_location_key=location_key,
        )
        qtbot.addWidget(dialog)
        return dialog

    def test_beide_dropdowns_voll_befuellt(self, qtbot: QtBot) -> None:
        dialog = self._dialog(qtbot)
        assert dialog._company_combo.count() == len(companies())
        assert dialog._location_combo.count() == len(locations())

    def test_dropdowns_sind_unabhaengig(self, qtbot: QtBot) -> None:
        dialog = self._dialog(qtbot)
        location_count_before = dialog._location_combo.count()
        # Gesellschaft wechseln → Standort-Dropdown bleibt unverändert vollständig.
        idx = dialog._company_combo.findData("consulting_gmbh")
        assert idx >= 0
        dialog._company_combo.setCurrentIndex(idx)
        assert dialog._location_combo.count() == location_count_before
        assert dialog._location_combo.count() == len(locations())

    def test_vorauswahl_aus_keys(self, qtbot: QtBot) -> None:
        dialog = self._dialog(qtbot, company_key="consulting_gmbh", location_key="linz")
        assert dialog._company_combo.currentData() == "consulting_gmbh"
        assert dialog._location_combo.currentData() == "linz"

    def test_unbekannte_keys_fallen_auf_default(self, qtbot: QtBot) -> None:
        dialog = self._dialog(qtbot, company_key=None, location_key="atlantis")
        assert dialog._company_combo.currentData() == "austria_gmbh"
        assert dialog._location_combo.currentData() == "wien"

    def test_result_enthaelt_gewaehlte_keys(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportAuditPdfDialog(
            engagement=_engagement(),
            event_types_available=["sampling"],
            briefpapier_available=True,
            default_output_dir=tmp_path,
            default_company_key="austria_gmbh",
            default_location_key="wien",
        )
        qtbot.addWidget(dialog)
        dialog._company_combo.setCurrentIndex(dialog._company_combo.findData("consulting_gmbh"))
        dialog._location_combo.setCurrentIndex(dialog._location_combo.findData("linz"))
        dialog._on_accept()
        result = dialog.get_result()
        assert result is not None
        assert result.company_key == "consulting_gmbh"
        assert result.location_key == "linz"


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


class TestScrollFallback:
    """Sprint 67 / Teil A: Inhalt scrollt, OK/Abbrechen bleiben immer sichtbar."""

    def _dialog(self, qtbot: QtBot) -> ExportAuditPdfDialog:
        dialog = ExportAuditPdfDialog(
            engagement=_engagement(),
            event_types_available=["sampling"],
            briefpapier_available=True,
        )
        qtbot.addWidget(dialog)
        return dialog

    def test_scroll_area_wraps_content_buttons_stay_outside(self, qtbot: QtBot) -> None:
        dialog = self._dialog(qtbot)
        scroll_areas = dialog.findChildren(QScrollArea)
        assert scroll_areas
        for scroll in scroll_areas:
            assert not scroll.isAncestorOf(dialog._buttons)

    def test_height_is_clamped_to_available_screen(self, qtbot: QtBot) -> None:
        dialog = self._dialog(qtbot)
        screen = dialog.screen()
        assert screen is not None
        assert dialog.maximumHeight() <= screen.availableGeometry().height()
