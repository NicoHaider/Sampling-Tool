"""Menü-Builder für MainWindow (Sprint 19 / F-006)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QStyle

from sampling_tool.ui.recent import RecentEntry

if TYPE_CHECKING:
    from sampling_tool.ui.main_window import MainWindow

# Max. Recent-Einträge im Datei-Menü (vorher in main_window.py).
_MAX_RECENT_IN_MENU: int = 5


def build_menu(window: MainWindow) -> None:
    """Baut Menübar + alle QActions; setzt window._file_menu / _recent_menu /
    _help_menu / alle window._action_*."""
    menu_bar = window.menuBar()
    if menu_bar is None:
        return

    # ---- File ----
    file_menu = menu_bar.addMenu("&Datei")
    assert file_menu is not None
    window._file_menu = file_menu

    window._action_new = QAction("Neues Engagement…", window)
    window._action_new.setShortcut(QKeySequence.StandardKey.New)
    window._action_new.triggered.connect(window.new_engagement_requested.emit)
    file_menu.addAction(window._action_new)

    window._action_open = QAction("Engagement öffnen…", window)
    window._action_open.setShortcut(QKeySequence.StandardKey.Open)
    window._action_open.triggered.connect(window._on_open_clicked)
    file_menu.addAction(window._action_open)

    recent_menu = file_menu.addMenu("Zuletzt geöffnet")
    assert recent_menu is not None
    window._recent_menu = recent_menu
    window._recent_menu.setEnabled(False)

    file_menu.addSeparator()
    style = window.style()
    window._action_close = QAction("Engagement schließen", window)
    window._action_close.setShortcut(QKeySequence.StandardKey.Close)
    if style is not None:
        window._action_close.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DirHomeIcon))
    window._action_close.setToolTip("Engagement schließen und zum Startbildschirm zurückkehren")
    window._action_close.triggered.connect(window.close_engagement_requested.emit)
    file_menu.addAction(window._action_close)

    file_menu.addSeparator()
    window._action_settings = QAction("Einstellungen…", window)
    window._action_settings.setShortcut(QKeySequence.StandardKey.Preferences)
    # PreferencesRole sorgt auf Mac dafür, dass die Action zusätzlich
    # ins App-Menü gezogen wird (Cmd+,). Die gleiche Instanz bleibt im
    # Datei-Menü sichtbar – Pattern wie beim Bug-Report-Button.
    window._action_settings.setMenuRole(QAction.MenuRole.PreferencesRole)
    window._action_settings.setToolTip("Einstellungen öffnen")
    window._action_settings.setStatusTip("Öffnet den Einstellungen-Dialog")
    window._action_settings.triggered.connect(window.settings_requested.emit)
    file_menu.addAction(window._action_settings)

    file_menu.addSeparator()
    action_quit = QAction("Beenden", window)
    action_quit.setShortcut(QKeySequence.StandardKey.Quit)
    action_quit.triggered.connect(window.close)
    file_menu.addAction(action_quit)

    # ---- Edit ----
    edit_menu = menu_bar.addMenu("&Bearbeiten")
    assert edit_menu is not None

    window._action_import = QAction("Datei importieren…", window)
    window._action_import.setShortcut(QKeySequence("Ctrl+I"))
    window._action_import.triggered.connect(window.import_excel_requested.emit)
    edit_menu.addAction(window._action_import)

    window._action_export_sample = QAction("Sample exportieren…", window)
    window._action_export_sample.triggered.connect(window.export_sample_requested.emit)
    edit_menu.addAction(window._action_export_sample)

    window._action_export_pdf = QAction("AuditTrail-PDF…", window)
    window._action_export_pdf.triggered.connect(window.export_audit_pdf_requested.emit)
    edit_menu.addAction(window._action_export_pdf)

    window._action_excel_report = QAction("Excel-Report exportieren…", window)
    window._action_excel_report.triggered.connect(window.export_excel_report_requested.emit)
    edit_menu.addAction(window._action_excel_report)

    window._action_html_report = QAction("HTML-Report generieren…", window)
    window._action_html_report.triggered.connect(window.export_html_report_requested.emit)
    edit_menu.addAction(window._action_html_report)

    # ---- Sample ----
    sample_menu = menu_bar.addMenu("&Stichprobe")
    assert sample_menu is not None

    window._action_new_sample = QAction("Neue Stichprobe…", window)
    window._action_new_sample.triggered.connect(window.new_sample_requested.emit)
    sample_menu.addAction(window._action_new_sample)

    window._action_reset_sample = QAction("Auswahl zurücksetzen", window)
    window._action_reset_sample.triggered.connect(window.reset_sample_requested.emit)
    sample_menu.addAction(window._action_reset_sample)

    sample_menu.addSeparator()
    style = window.style()
    window._action_undo = QAction("Rückgängig", window)
    window._action_undo.setShortcut(QKeySequence.StandardKey.Undo)
    window._action_undo.setToolTip("Letzte Aktion rückgängig machen (Cmd+Z)")
    if style is not None:
        window._action_undo.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
    window._action_undo.triggered.connect(window.undo_requested.emit)
    sample_menu.addAction(window._action_undo)

    window._action_redo = QAction("Wiederherstellen", window)
    window._action_redo.setShortcut(QKeySequence.StandardKey.Redo)
    window._action_redo.setToolTip("Letzte rückgängig gemachte Aktion wiederholen (Cmd+Shift+Z)")
    if style is not None:
        window._action_redo.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
    window._action_redo.triggered.connect(window.redo_requested.emit)
    sample_menu.addAction(window._action_redo)

    # ---- Help ----
    help_menu = menu_bar.addMenu("&Hilfe")
    assert help_menu is not None
    window._help_menu = help_menu

    window._action_hotkeys = QAction("Tastatur-Shortcuts…", window)
    window._action_hotkeys.triggered.connect(window.hotkeys_requested.emit)
    help_menu.addAction(window._action_hotkeys)

    window._action_bug_report = QAction("Bug melden…", window)
    window._action_bug_report.setToolTip("Fehler melden oder Feedback senden")
    window._action_bug_report.setStatusTip("Öffnet den Bug-Report-Dialog")
    if style is not None:
        window._action_bug_report.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical)
        )
    window._action_bug_report.triggered.connect(window.bug_report_requested.emit)
    help_menu.addAction(window._action_bug_report)

    window._action_about = QAction("Über…", window)
    window._action_about.setMenuRole(QAction.MenuRole.AboutRole)
    window._action_about.triggered.connect(window.about_requested.emit)
    help_menu.addAction(window._action_about)

    # Sprint-4-Initial: alle workspace-only Aktionen disabled.
    window._set_workspace_actions_enabled(False)


def rebuild_recent_menu(window: MainWindow, entries: list[RecentEntry]) -> None:
    """Befüllt das File→Recent-Submenü neu."""
    menu = window._recent_menu
    menu.clear()
    if not entries:
        menu.setEnabled(False)
        return
    menu.setEnabled(True)
    for entry in entries:
        label = f"{entry.client_name} — {entry.path.name}"
        action = QAction(label, window)
        action.triggered.connect(
            lambda _checked=False, p=entry.path: window.open_engagement_requested.emit(p)
        )
        menu.addAction(action)
