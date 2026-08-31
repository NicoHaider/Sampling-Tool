"""Toolbar-Builder für MainWindow (Sprint 19 / F-006)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QSizePolicy, QStyle, QToolBar, QToolButton, QWidget

if TYPE_CHECKING:
    from sampling_tool.ui.main_window import MainWindow

# Sprint 27: kompaktere Toolbar-Icons (Plattform-Default ist ~24 px). Kleinere
# Buttons → es passt mehr ins Fenster; was bei schmalem Fenster dann nicht mehr
# passt, wandert in das QToolBar-Standard-Überlauf-/„»"-Menü (Extension-Button),
# das eine QToolBar in einem QMainWindow automatisch einblendet. So bleibt jede
# Aktion erreichbar. Auf breitem Bildschirm bleibt das Layout unauffällig.
_TOOLBAR_ICON_SIZE: int = 16


def build_toolbar(window: MainWindow) -> None:
    """Baut die Haupt-Toolbar; setzt window._toolbar und
    window._action_switch_engagement. Muss NACH build_menu laufen
    (nutzt die dort erzeugten QActions)."""
    toolbar = QToolBar("Hauptaktionen", window)
    toolbar.setMovable(False)
    toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    toolbar.setIconSize(QSize(_TOOLBAR_ICON_SIZE, _TOOLBAR_ICON_SIZE))
    # "Projekt wechseln" ganz links – schneller Rückweg zum Welcome-Screen.
    style = window.style()
    window._action_switch_engagement = QAction("Projekt wechseln", window)
    if style is not None:
        window._action_switch_engagement.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_DirHomeIcon)
        )
    window._action_switch_engagement.setToolTip(
        "Projekt schließen und zum Startbildschirm zurückkehren"
    )
    window._action_switch_engagement.triggered.connect(window.close_engagement_requested.emit)
    toolbar.addAction(window._action_switch_engagement)
    toolbar.addSeparator()
    toolbar.addAction(window._action_new)
    toolbar.addAction(window._action_open)
    toolbar.addSeparator()
    toolbar.addAction(window._action_import)
    toolbar.addAction(window._action_new_sample)
    if style is not None:
        window._action_reset_sampling.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogResetButton)
        )
    toolbar.addAction(window._action_reset_sampling)
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
    spacer.setObjectName("toolbarSpacer")  # Sprint 69/6: QSS-Hook, siehe bdo_light.qss
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

    apply_icon_only_style(toolbar, window)

    window._toolbar = toolbar
    window.addToolBar(toolbar)


def icon_only_actions(window: MainWindow) -> tuple[QAction, ...]:
    """Die Aktionen, die in der Toolbar ohne Text auskommen (Sprint 81).

    Kriterium ist nicht „unwichtig", sondern **eindeutiges Symbol + vorhandener
    Tooltip**: ein Haus, ein Zurücksetzen-Pfeil, zwei Richtungspfeile, ein
    Zahnrad-Ersatz und ein Warndreieck sind ohne Beschriftung lesbar. Die
    Export-Aktionen bleiben bewusst beschriftet – „Excel-Report" und
    „HTML-Report" unterscheiden sich in Qts Standard-Pixmaps kaum.
    """
    return (
        window._action_switch_engagement,
        window._action_reset_sampling,
        window._action_undo,
        window._action_redo,
        window._action_settings,
        window._action_bug_report,
    )


def apply_icon_only_style(toolbar: QToolBar, window: MainWindow) -> None:
    """Nimmt sechs Toolbar-Buttons den Text – je Button, nicht toolbar-weit.

    Bei 1536 px logischer Breite (13-Zoll-Lenovo, Windows 125 %) lagen vier der
    zwölf Haupt-Aktionen hinter dem `»`-Überlaufmenü: Sample exportieren,
    AuditTrail-PDF, Excel-Report, HTML-Report – also die gesamte Export-Gruppe.
    Wer exportieren wollte, musste ein Menü öffnen, das aussieht wie ein
    Zeichen.

    `toolbar.setToolButtonStyle` wäre toolbar-weit und würde auch den
    Text-Aktionen die Beschriftung nehmen. Deshalb pro `QToolButton` über
    `widgetForAction` – das setzt voraus, dass die Aktion bereits in der
    Toolbar hängt.

    Ein Button ohne Icon behält seinen Text: `standardIcon` hängt am
    Plattform-Stil, und `style()` kann `None` liefern. Ohne diese Bedingung
    entstünde dort ein leerer, unbeschrifteter Knopf – schlechter als ein
    Überlaufmenü.
    """
    for action in icon_only_actions(window):
        if action.icon().isNull():
            continue
        button = toolbar.widgetForAction(action)
        if isinstance(button, QToolButton):
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
