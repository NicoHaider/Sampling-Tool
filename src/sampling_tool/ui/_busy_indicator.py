"""Sichtbares „bitte warten" ohne Pixmap-Cursor (Sprint 91 / A).

Qt baut `WaitCursor`/`BusyCursor` auf macOS aus einer Pixmap und wandelt sie
über `QImage::toCGImage()` um; dabei kann ein ungültiger Farbraum an
`CGImageCreate` landen (SIGTRAP in `QGuiApplication::setOverrideCursor`, siehe
zwei Absturzberichte vom 28.09.2026 beim Klick auf OK im Stichproben-Dialog).
`setOverrideCursor` ist deshalb über alle Plattformen hinweg tabu (siehe
`tests/unit/test_no_pixmap_cursor.py`) – dieser Kontextmanager deaktiviert
stattdessen das betroffene Widget für die Dauer der kurzen synchronen Arbeit.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from PyQt6.QtWidgets import QWidget


@contextmanager
def busy_indicator(widget: QWidget | None) -> Iterator[None]:
    """Deaktiviert `widget` für die Dauer des `with`-Blocks, stellt danach wieder her.

    Nimmt `None` entgegen (analog zu `_dialog_buttons.mark_secondary`), damit
    der Aufrufer für einen optionalen Button keine eigene Guard-Zeile
    schreiben muss.
    """
    if widget is None:
        yield
        return
    was_enabled = widget.isEnabled()
    widget.setEnabled(False)
    try:
        yield
    finally:
        widget.setEnabled(was_enabled)
