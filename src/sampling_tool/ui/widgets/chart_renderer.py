"""Dünner Pixmap-Wrapper um die Bytes-Renderer aus `io.charts`.

Heavy-Lifting (matplotlib + Agg, BDO-Farbschema, Style) sitzt in
`sampling_tool.io.charts`. Hier nur die UI-Anbindung: PNG-Bytes →
`QPixmap`. Damit bleibt der `io`-Layer Qt-frei und die Bytes-Logik wird
nicht zwischen UI- und Report-Pfad dupliziert.
"""

from __future__ import annotations

from typing import Final

from PyQt6.QtGui import QImage, QPixmap

from sampling_tool.io.charts import (
    render_bar_chart_bytes,
    render_line_chart_bytes,
    render_pie_chart_bytes,
)

_DEFAULT_WIDTH: Final[int] = 400
_DEFAULT_HEIGHT: Final[int] = 200


def render_bar_chart(
    labels: list[str],
    values: list[float],
    title: str = "",
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> QPixmap:
    """Rendert ein Balkendiagramm als `QPixmap`."""
    return _bytes_to_pixmap(render_bar_chart_bytes(labels, values, title, width, height))


def render_line_chart(
    labels: list[str],
    values: list[float],
    title: str = "",
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> QPixmap:
    """Rendert ein Liniendiagramm als `QPixmap`."""
    return _bytes_to_pixmap(render_line_chart_bytes(labels, values, title, width, height))


def render_pie_chart(
    labels: list[str],
    values: list[float],
    title: str = "",
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> QPixmap:
    """Rendert ein Tortendiagramm als `QPixmap`."""
    return _bytes_to_pixmap(render_pie_chart_bytes(labels, values, title, width, height))


def _bytes_to_pixmap(raw: bytes) -> QPixmap:
    image = QImage.fromData(raw, "PNG")
    return QPixmap.fromImage(image)
