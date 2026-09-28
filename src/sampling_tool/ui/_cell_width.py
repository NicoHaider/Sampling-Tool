"""Breite, die eine Tabellenzelle für einen Text braucht (Sprint 89 / E1, E3).

Gemessen wie Qt es in `sizeHintForColumn` selbst tut: über den Stil (inkl.
Stylesheet-Padding und der Ränder des Plattform-Stils) und die polierte
Schrift. Schriftbreite + feste Zugabe reichte unter macOS nicht.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem, QTableView


def cell_width(table: QTableView, text: str) -> int:
    """Benötigte Spaltenbreite in px für `text` in einer Zelle von `table`."""
    # Ohne Polieren gilt noch die Schrift von vor dem Stylesheet.
    table.ensurePolished()
    option = QStyleOptionViewItem()
    option.initFrom(table)
    option.font = table.font()
    option.text = text
    option.features = QStyleOptionViewItem.ViewItemFeature.HasDisplay
    style = table.style()
    if style is None:
        return table.fontMetrics().horizontalAdvance(text)
    size = style.sizeFromContents(QStyle.ContentsType.CT_ItemViewItem, option, QSize(), table)
    return size.width() + (1 if table.showGrid() else 0)
