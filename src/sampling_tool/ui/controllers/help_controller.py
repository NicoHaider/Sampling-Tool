"""HelpController – Bug-Report, About, Settings, Hotkeys, Handbuch.

Sprint 13 / F-001: aus dem MainController-God-Object zerlegt.
Nimmt die nicht-mutierenden Hilfs- und Settings-Aktionen.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from PyQt6.QtWidgets import QMessageBox

from sampling_tool.resources import doc_resource
from sampling_tool.ui._scaling import scale_factor
from sampling_tool.ui.controllers._factories import ControllerFactories
from sampling_tool.ui.controllers.workspace_session import WorkspaceSession
from sampling_tool.ui.dialogs.about_dialog import AboutDialog
from sampling_tool.ui.dialogs.bug_report_dialog import BugReportDialog
from sampling_tool.ui.dialogs.template_manager_dialog import TemplateManagerDialog
from sampling_tool.ui.dialogs.user_guide_dialog import UserGuideDialog
from sampling_tool.ui.preset_store import PresetStore
from sampling_tool.ui.settings_store import PANEL_AUDIT_TRAIL, PANEL_DASHBOARD, save_settings

logger = logging.getLogger(__name__)

USER_GUIDE_FILE = "USER_GUIDE.md"


class HelpController:
    """Help-Pfade ohne Engagement-State-Mutation."""

    def __init__(self, session: WorkspaceSession, factories: ControllerFactories) -> None:
        self.session = session
        self._factories = factories
        # Nicht-modal: das Handbuch bleibt offen, während weitergearbeitet wird.
        self._user_guide: UserGuideDialog | None = None

    def handle_user_guide(self) -> None:
        """Handbuch öffnen (Sprint 89 / F) – ein Fenster, bei erneutem Aufruf nach vorn."""
        if self._user_guide is not None:
            self._user_guide.show()
            self._user_guide.raise_()
            self._user_guide.activateWindow()
            return
        path = doc_resource(USER_GUIDE_FILE)
        try:
            markdown = path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("User guide not found at %s", path, exc_info=True)
            QMessageBox.information(
                self.session.window,
                "Handbuch nicht verfügbar",
                "Das Handbuch ist in dieser Installation nicht enthalten. Bitte wenden "
                "Sie sich an die Ansprechperson für das Sampling-Tool.",
            )
            return
        self._user_guide = UserGuideDialog(markdown, self.session.window)
        self._user_guide.show()

    def handle_bug_report(self) -> None:
        """Bug-Report-Dialog öffnen (mailto-Fallback)."""
        BugReportDialog(self.session.window).exec()

    def handle_about(self) -> None:
        """About-Dialog öffnen."""
        factor = scale_factor(self.session.settings.ui_scale)
        AboutDialog(self.session.window, ui_scale_factor=factor).exec()

    def handle_settings(self) -> None:
        """Settings-Dialog öffnen und auf OK persistieren."""
        dialog = self._factories.settings(self.session.window, self.session.settings)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        new_settings = dialog.get_settings()
        if new_settings is None:
            return
        save_settings(new_settings)
        # `apply_new_settings` legt Engagement-Dir an + setzt Panel-Visibility.
        self.session.apply_new_settings(new_settings)
        # Sprint 22: Settings-Dialog kann show_dashboard/show_audit_trail
        # geändert haben → „Ansicht"-Menü-Checks nachziehen.
        self.session.sync_view_menu()

    def handle_feature_toggled(self, feature: str, enabled: bool) -> None:
        """Einzel-Toggle einer Advanced-Funktion aus dem „Ansicht"-Menü (Sprint 22).

        Persistiert den app-weiten Toggle. Kein Live-UI-Refresh nötig: die
        Funktionen leben im modalen Stichproben-Dialog, der bei jedem Öffnen
        frisch aus den (aufgelösten) Settings aufgebaut wird. Das Häkchen hält
        die `QAction` selbst.
        """
        new_settings = self.session.settings.with_feature_toggle(feature, enabled)
        save_settings(new_settings)
        self.session.settings = new_settings

    def handle_panel_toggled(self, panel: str, enabled: bool) -> None:
        """Panel-Toggle (Dashboard/Audit-Trail) aus dem „Ansicht"-Menü (Sprint 22).

        Mappt auf die bestehenden `show_dashboard`/`show_audit_trail`-Flags,
        persistiert und wendet die Panel-Sichtbarkeit sofort live an.
        """
        if panel == PANEL_DASHBOARD:
            new_settings = replace(self.session.settings, show_dashboard=enabled)
        elif panel == PANEL_AUDIT_TRAIL:
            new_settings = replace(self.session.settings, show_audit_trail=enabled)
        else:
            return
        save_settings(new_settings)
        self.session.apply_new_settings(new_settings)

    def handle_manage_templates(self) -> None:
        """Vorlagen-Verwaltungsfenster öffnen (Sprint 28, einziger Einstiegspunkt).

        Vorlagen liegen app-weit (`PresetStore`/QSettings, Sprint 23) – das
        Fenster braucht kein offenes Projekt. Bewusst genau **eine** Stelle,
        damit später ein Passwort-Gate davorgeschaltet werden kann (jetzt noch
        keins).
        """
        factor = scale_factor(self.session.settings.ui_scale)
        TemplateManagerDialog(PresetStore(), self.session.window, ui_scale_factor=factor).exec()

    def handle_hotkeys(self) -> None:
        """Statisches Info-Fenster mit Tastatur-Shortcuts."""
        QMessageBox.information(
            self.session.window,
            "Tastatur-Shortcuts",
            (
                "<table cellpadding='6'>"
                "<tr><td><b>Cmd/Ctrl+Z</b></td><td>Rückgängig</td></tr>"
                "<tr><td><b>Cmd/Ctrl+Shift+Z</b></td><td>Wiederherstellen</td></tr>"
                "<tr><td><b>Cmd/Ctrl+N</b></td><td>Neues Projekt</td></tr>"
                "<tr><td><b>Cmd/Ctrl+O</b></td><td>Projekt öffnen</td></tr>"
                "<tr><td><b>Cmd/Ctrl+I</b></td><td>Datei importieren</td></tr>"
                "<tr><td><b>Cmd/Ctrl+S</b></td><td>Speichern (passiert automatisch)</td></tr>"
                "<tr><td><b>Cmd/Ctrl+W</b></td><td>Projekt schließen</td></tr>"
                "<tr><td><b>Cmd/Ctrl+,</b></td><td>Einstellungen</td></tr>"
                "<tr><td><b>F1 (macOS: Cmd+?)</b></td><td>Handbuch</td></tr>"
                "<tr><td><b>Cmd/Ctrl+Q</b></td><td>Beenden</td></tr>"
                "</table>"
            ),
        )
