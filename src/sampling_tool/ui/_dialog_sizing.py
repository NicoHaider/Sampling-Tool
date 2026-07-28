"""Dünne Qt-Anbindung: Dialoghöhe auf den verfügbaren Screen begrenzen (Sprint 67 / Teil A)."""

from __future__ import annotations

from PyQt6.QtWidgets import QDialog

from sampling_tool.ui._geometry import DEFAULT_FIT_MARGIN


def clamp_dialog_height_to_screen(dialog: QDialog, margin: int = DEFAULT_FIT_MARGIN) -> None:
    """Begrenzt die max. Höhe von `dialog` auf den verfügbaren Screen-Bereich.

    Ohne das könnte ein hoher Dialog (z. B. `SamplingDialog` mit allen
    Advanced-Feldern) auf einem 720px-hohen Bildschirm über den sichtbaren
    Bereich hinausragen, bevor der `QScrollArea`-Fallback im Inhalt greifen
    kann (der greift erst, wenn der Dialog selbst eine endliche Höhe hat).
    """
    screen = dialog.screen()
    if screen is None:
        return
    available_height = screen.availableGeometry().height()
    dialog.setMaximumHeight(max(available_height - 2 * margin, 1))
