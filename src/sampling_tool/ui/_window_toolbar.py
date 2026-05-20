"""Toolbar-Builder für MainWindow (Sprint 19 / F-006)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QSizePolicy, QStyle, QToolBar, QWidget

if TYPE_CHECKING:
    from sampling_tool.ui.main_window import MainWindow


def build_toolbar(window: MainWindow) -> None:
    """Baut die Haupt-Toolbar; setzt window._toolbar und
    window._action_switch_engagement. Muss NACH build_menu laufen
    (nutzt die dort erzeugten QActions)."""
    toolbar = QToolBar("Hauptaktionen", window)
    toolbar.setMovable(False)
    toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    # "Engagement wechseln" ganz links – schneller Rückweg zum Welcome-Screen.
    style = window.style()
    window._action_switch_engagement = QAction("Engagement wechseln", window)
    if style is not None:
        window._action_switch_engagement.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_DirHomeIcon)
        )
    window._action_switch_engagement.setToolTip(
        "Engagement schließen und zum Startbildschirm zurückkehren"
    )
    window._action_switch_engagement.triggered.connect(window.close_engagement_requested.emit)
    toolbar.addAction(window._action_switch_engagement)
    toolbar.addSeparator()
    toolbar.addAction(window._action_new)
    toolbar.addAction(window._action_open)
    toolbar.addSeparator()
    toolbar.addAction(window._action_import)
    toolbar.addAction(window._action_new_sample)
    toolbar.addSeparator()
    toolbar.addAction(window._action_undo)
    toolbar.addAction(window._action_redo)
    toolbar.addSeparator()
    toolbar.addAction(window._action_export_sample)
    toolbar.addAction(window._action_export_pdf)
    toolbar.addSeparator()
    if style is not None:
        window._action_excel_report.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        )
        window._action_html_report.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon)
        )
    toolbar.addAction(window._action_excel_report)
    toolbar.addAction(window._action_html_report)

    # Sekundäre Aktionen – rechts abgesetzt via Expanding-Spacer, damit die
    # Settings-/Bug-Report-Buttons optisch nicht mit den Haupt-Aktionen
    # konkurrieren. Reihenfolge rechts: Einstellungen (häufiger genutzt),
    # dann Bug-Report.
    spacer = QWidget()
    spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    toolbar.addWidget(spacer)
    if style is not None and window._action_settings.icon().isNull():
        # Qt-Standard-Pixmaps haben kein Zahnrad – SP_FileDialogContentsView
        # liefert ein neutrales Listen-Icon. SP_FileDialogDetailedView ist
        # bereits für den Excel-Report belegt, daher die andere Variante.
        window._action_settings.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        )
    shortcut_text = window._action_settings.shortcut().toString(
        QKeySequence.SequenceFormat.NativeText
    )
    window._action_settings.setToolTip(f"Einstellungen öffnen ({shortcut_text})")
    toolbar.addAction(window._action_settings)
    toolbar.addAction(window._action_bug_report)

    window._toolbar = toolbar
    window.addToolBar(toolbar)
