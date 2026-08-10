"""Tests für `ExportAuditPdfDialog` – Filter, Optionen, Validierung."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtCore import QDate, QSettings, Qt
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QScrollArea
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import AuditEvent, Engagement
from sampling_tool.io.bdo_locations import companies, locations
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import AuditRepo, EngagementRepo
from sampling_tool.ui._scaling import load_scaled_stylesheet
from sampling_tool.ui.controllers._factories import default_audit_pdf_factory
from sampling_tool.ui.controllers.export_controller import filter_audit_events
from sampling_tool.ui.controllers.main_controller import MainController
from sampling_tool.ui.dialogs._export_base import (
    HINT_NO_AUDIT_EVENTS,
    HINT_NO_EVENT_TYPES,
)
from sampling_tool.ui.dialogs.export_audit_pdf_dialog import (
    _DEFAULT_TYPES,
    ExportAuditPdfDialog,
)
from sampling_tool.ui.main_window import MainWindow
from sampling_tool.ui.recent import RecentEngagementsStore

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


def _hint_text(dialog: ExportAuditPdfDialog) -> str:
    label = dialog._target.findChild(QLabel, "exportTargetHint")
    assert label is not None
    return str(label.text())


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


class TestSelectionHint:
    """Sprint 72: „Alle abwählen" erklärt sich jetzt selbst statt den
    OK-Button stumm auszugrauen."""

    def test_hint_when_nothing_selected(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportAuditPdfDialog(
            engagement=_engagement(),
            event_types_available=["sampling", "import"],
            briefpapier_available=True,
            default_output_dir=tmp_path,
        )
        qtbot.addWidget(dialog)
        dialog._set_all_types(False)
        assert _hint_text(dialog) == HINT_NO_EVENT_TYPES
        assert _ok_enabled(dialog) is False

    def test_hint_clears_when_selection_restored(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportAuditPdfDialog(
            engagement=_engagement(),
            event_types_available=["sampling", "import"],
            briefpapier_available=True,
            default_output_dir=tmp_path,
        )
        qtbot.addWidget(dialog)
        dialog._set_all_types(False)
        assert _hint_text(dialog) == HINT_NO_EVENT_TYPES

        dialog._set_all_types(True)

        assert _hint_text(dialog) == ""
        assert _ok_enabled(dialog) is True


class TestEmptyAuditTrail:
    """Sprint 72 / §3.2 – der angeblich DAUERHAFT blockierte PDF-Dialog.

    Der Sprint-71-PR meldete, ein Projekt ohne Audit-Ereignisse könne
    dauerhaft in einen grauen OK-Button laufen, aus dem der User durch
    Anhaken nicht herauskommt. Die Messung über den ECHTEN Controller-Pfad
    widerlegt das: `handle_export_audit_pdf` reicht
    `available_types = sorted({e.event_type for e in events})` durch, das ist
    bei null Ereignissen `[]` – und genau dann greift der `_DEFAULT_TYPES`-
    Fallback und hakt ALLE sieben Typen an. `_selected_types()` ist damit nie
    leer, OK bleibt aktiv.

    Der Zustand ist also NICHT erreichbar. `HINT_NO_AUDIT_EVENTS` bleibt als
    benannter Zustand definiert, hat aber bewusst keinen Produktionspfad –
    diese Klasse ist der Nachweis dafür, damit keine tote Bedingung ohne Test
    zurückbleibt.
    """

    @pytest.fixture(autouse=True)
    def _isolated_qsettings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Echtes MainWindow → `closeEvent` würde sonst in die echten
        Benutzer-Prefs schreiben. Gleiches Muster wie
        `test_export_dir_bootstrap` – bewusst kein HOME-Umbiegen (hat in
        Sprint 67 echte Prefs korrumpiert)."""
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        monkeypatch.setattr(
            "sampling_tool.ui.main_window.QSettings",
            lambda organization, application: QSettings(
                QSettings.Format.IniFormat, QSettings.Scope.UserScope, organization, application
            ),
        )

    @pytest.fixture(autouse=True)
    def _reject_dialog(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Der Dialog ist modal – `exec()` würde headless blockieren. Geprüft
        wird der Dialog-Zustand, nicht der Export."""
        monkeypatch.setattr(
            "sampling_tool.ui.dialogs.export_audit_pdf_dialog.ExportAuditPdfDialog.exec",
            lambda _self: int(QDialog.DialogCode.Rejected),
        )

    @pytest.fixture
    def empty_db(self, tmp_path: Path) -> Path:
        """Projekt ohne jede Aktion: Engagement angelegt, sonst nichts."""
        db_path = tmp_path / "projekt" / "engagement.db"
        db_path.parent.mkdir(parents=True)
        db = Database(db_path)
        db.migrate()
        EngagementRepo(db.connect()).get_or_create(
            Engagement(
                auditor_name="Anna",
                auditor_position="Senior",
                client_name="ACME",
                audit_type="ISAE 3402",
            )
        )
        db.close()
        return db_path

    @staticmethod
    def _capture(factory: Callable[..., Any], box: list[Any]) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            dialog = factory(*args, **kwargs)
            box.append(dialog)
            return dialog

        return wrapped

    def _open_dialog(
        self, qtbot: QtBot, tmp_path: Path, empty_db: Path
    ) -> tuple[ExportAuditPdfDialog, list[AuditEvent]]:
        window = MainWindow()
        qtbot.addWidget(window)
        box: list[Any] = []
        controller = MainController(
            window,
            recent_store=RecentEngagementsStore(path=tmp_path / "recent.json"),
            audit_pdf_dialog_factory=self._capture(default_audit_pdf_factory, box),
        )
        try:
            controller.engagement.handle_open_engagement(empty_db)
            session = controller.session
            assert session.db is not None
            assert session.engagement is not None
            assert session.engagement.id is not None
            events = AuditRepo(session.db.connect()).list_for_engagement(
                session.engagement.id, limit=10_000
            )
            controller.export.handle_export_audit_pdf()
        finally:
            controller.engagement.handle_close_engagement()
        assert box, "Der AuditTrail-PDF-Dialog wurde nicht erzeugt"
        dialog = box[0]
        assert isinstance(dialog, ExportAuditPdfDialog)
        return dialog, events

    def test_fresh_project_really_has_no_audit_events(
        self, qtbot: QtBot, tmp_path: Path, empty_db: Path
    ) -> None:
        """Vorbedingung der ganzen Klasse: der Zustand „null Ereignisse" ist
        überhaupt erreichbar (auch das Öffnen selbst schreibt keinen Event)."""
        _dialog, events = self._open_dialog(qtbot, tmp_path, empty_db)
        assert events == []

    def test_fallback_fills_and_checks_all_types(
        self, qtbot: QtBot, tmp_path: Path, empty_db: Path
    ) -> None:
        """Gemessener Zustand: Liste GEFÜLLT und alles ANGEHAKT."""
        dialog, _events = self._open_dialog(qtbot, tmp_path, empty_db)
        assert dialog._types_list.count() == len(_DEFAULT_TYPES)
        assert dialog._selected_types() == set(_DEFAULT_TYPES)
        assert dialog._types_list.isEnabled() is True

    def test_ok_is_not_blocked_on_empty_audit_trail(
        self, qtbot: QtBot, tmp_path: Path, empty_db: Path
    ) -> None:
        """Der Kern des Nachweises: kein grauer Button, kein Hinweis."""
        dialog, _events = self._open_dialog(qtbot, tmp_path, empty_db)
        assert _hint_text(dialog) == ""
        assert _ok_enabled(dialog) is True

    def test_no_audit_events_hint_has_no_production_path(
        self, qtbot: QtBot, tmp_path: Path, empty_db: Path
    ) -> None:
        """`HINT_NO_AUDIT_EVENTS` ist definiert, wird aber nie angezeigt.

        Wird der Fallback je entfernt oder auf „unchecked" umgestellt, wird
        der Zustand erreichbar – dann schlägt dieser Test fehl und erzwingt,
        dass die Konstante verdrahtet (und die Liste deaktiviert) wird.
        """
        dialog, _events = self._open_dialog(qtbot, tmp_path, empty_db)
        assert _hint_text(dialog) != HINT_NO_AUDIT_EVENTS
        assert dialog._selection_hint() == ""


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

    def test_width_derived_from_content_not_hardcoded(self, qtbot: QtBot) -> None:
        """Sprint 69 / Bug 3: `setMinimumWidth(720)` war schmaler als der
        tatsächliche Inhalt (u. a. die „BDO-Gesellschaft“-Dropdown mit den
        langen offiziellen BDO-Firmennamen, z. B. „BDO Austria GmbH
        Wirtschaftsprüfungs- und Steuerberatungsgesellschaft“) – ein
        horizontaler Scrollbalken war nötig. Fix: die Mindestbreite wird aus
        `content.sizeHint()` abgeleitet (`_dialog_sizing.content_min_width`)
        und auf den verfügbaren Screen gedeckelt
        (`clamp_dialog_width_to_screen`) – nie breiter als der Screen, aber
        auch nicht mehr stur auf 720 begrenzt.

        Anders als beim Settings-Dialog
        (`test_settings_dialog_fits_content_without_hscroll`) wird hier NICHT
        geprüft, dass gar kein horizontaler Scrollbalken mehr nötig ist: der
        zweispaltige Inhalt (Aktionstypen-Liste + BDO-Firmennamen-Dropdown +
        Export-Ziel-Spalte) braucht real mehr Platz, als der virtuelle
        Offscreen-Test-Screen hergibt (kleiner als das Sprint-Zielgerät
        1280×720) – genau der in der Aufgabenstellung vorgesehene
        Tiny-Screen-Fallback (ein Rest-Scrollbalken bleibt dort akzeptiert).

        Das reale `bdo_light.qss`-Stylesheet wird explizit gesetzt (statt
        sich auf ambienten Test-Zustand zu verlassen) – macht die Messung
        repräsentativ für die echte App und unabhängig von der
        Ausführungsreihenfolge anderer Tests.
        """
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        previous_stylesheet = app.styleSheet()
        app.setStyleSheet(load_scaled_stylesheet(1.0))
        try:
            dialog = self._dialog(qtbot)
            dialog.show()
            qtbot.waitExposed(dialog)
            qtbot.wait(50)

            screen = dialog.screen()
            assert screen is not None
            assert dialog.width() <= screen.availableGeometry().width()
            assert dialog.minimumWidth() > 720
        finally:
            app.setStyleSheet(previous_stylesheet)
