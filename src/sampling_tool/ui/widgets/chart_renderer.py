"""Dünner Pixmap-Wrapper um die Bytes-Renderer aus `io.charts`.

Heavy-Lifting (matplotlib + Agg, BDO-Farbschema, Style) sitzt in
`sampling_tool.io.charts`. Hier nur die UI-Anbindung: PNG-Bytes →
`QPixmap`. Damit bleibt der `io`-Layer Qt-frei und die Bytes-Logik wird
nicht zwischen UI- und Report-Pfad dupliziert.
"""

from __future__ import annotations

from typing import Final

from PyQt6.QtGui import QImage, QPixmap

from sampling_tool.io.charts import render_bar_chart_bytes, render_line_chart_bytes

_DEFAULT_WIDTH: Final[int] = 400
_DEFAULT_HEIGHT: Final[int] = 200


def render_bar_chart(
    labels: list[str],
    values: list[float],
    title: str = "",
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
    device_pixel_ratio: float = 1.0,
) -> QPixmap:
    """Rendert ein Balkendiagramm als `QPixmap`."""
    return _bytes_to_pixmap(
        render_bar_chart_bytes(labels, values, title, width, height, device_pixel_ratio),
        device_pixel_ratio,
    )


def render_line_chart(
    labels: list[str],
    values: list[float],
    title: str = "",
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
    device_pixel_ratio: float = 1.0,
) -> QPixmap:
    """Rendert ein Liniendiagramm als `QPixmap`."""
    return _bytes_to_pixmap(
        render_line_chart_bytes(labels, values, title, width, height, device_pixel_ratio),
        device_pixel_ratio,
    )


def _bytes_to_pixmap(raw: bytes, device_pixel_ratio: float = 1.0) -> QPixmap:
    """PNG-Bytes → `QPixmap` mit gesetztem Device-Pixel-Ratio.

    Beides gehört zusammen (Sprint 78 / §2.5): ein Bild mit doppelten
    Pixelmaßen OHNE gesetztes Ratio erscheint schlicht doppelt so groß – der
    Schärfe-Fix wäre dann eine Layout-Regression. Erst das Ratio sagt Qt, dass
    die zusätzlichen Pixel Auflösung sind und keine Größe.

    Bei `1.0` ist `setDevicePixelRatio` ein No-Op und das Ergebnis unverändert
    zum Stand vor Sprint 78.
    """
    image = QImage.fromData(raw, "PNG")
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(device_pixel_ratio)
    return pixmap
