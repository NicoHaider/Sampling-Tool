"""HelpController – Bug-Report, About, Settings, Hotkeys.

Sprint 13 / F-001: aus dem MainController-God-Object zerlegt.
Nimmt die nicht-mutierenden Hilfs- und Settings-Aktionen.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox

from sampling_tool.ui.controllers._factories import ControllerFactories
from sampling_tool.ui.controllers.workspace_session import WorkspaceSession
from sampling_tool.ui.dialogs.about_dialog import AboutDialog
from sampling_tool.ui.dialogs.bug_report_dialog import BugReportDialog
from sampling_tool.ui.settings_store import save_settings


class HelpController:
    """Help-Pfade ohne Engagement-State-Mutation."""

    def __init__(self, session: WorkspaceSession, factories: ControllerFactories) -> None:
        self.session = session
        self._factories = factories

    def handle_bug_report(self) -> None:
        """Bug-Report-Dialog öffnen (mailto-Fallback)."""
        BugReportDialog(self.session.window).exec()

    def handle_about(self) -> None:
        """About-Dialog öffnen."""
        AboutDialog(self.session.window).exec()

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

    def handle_hotkeys(self) -> None:
        """Statisches Info-Fenster mit Tastatur-Shortcuts."""
        QMessageBox.information(
            self.session.window,
            "Tastatur-Shortcuts",
            (
                "<table cellpadding='6'>"
                "<tr><td><b>Cmd/Ctrl+Z</b></td><td>Rückgängig</td></tr>"
                "<tr><td><b>Cmd/Ctrl+Shift+Z</b></td><td>Wiederherstellen</td></tr>"
                "<tr><td><b>Cmd/Ctrl+N</b></td><td>Neues Engagement</td></tr>"
                "<tr><td><b>Cmd/Ctrl+O</b></td><td>Engagement öffnen</td></tr>"
                "<tr><td><b>Cmd/Ctrl+I</b></td><td>Datei importieren</td></tr>"
                "<tr><td><b>Cmd/Ctrl+W</b></td><td>Engagement schließen</td></tr>"
                "<tr><td><b>Cmd/Ctrl+,</b></td><td>Einstellungen</td></tr>"
                "<tr><td><b>Cmd/Ctrl+Q</b></td><td>Beenden</td></tr>"
                "</table>"
            ),
        )
