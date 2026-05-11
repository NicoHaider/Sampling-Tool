"""matplotlib-Wrapper für Mini-Charts in Dashboard, HTML-Report und Excel.

Charts werden in einem `Agg`-Backend gerendert (kein Display nötig) und
können als `QPixmap` (für die UI) oder als rohe PNG-Bytes (für HTML-Embed
und Excel-Bilder) abgerufen werden. Das BDO-Farbschema kommt aus
`config.py` und sorgt für konsistente Optik über alle Report-Layer.

WICHTIG: `matplotlib.use('Agg')` MUSS vor dem `pyplot`-Import laufen, sonst
versucht matplotlib unter macOS/Linux ohne `DISPLAY` ein interaktives
Backend zu laden und crasht.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, Final

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from PyQt6.QtGui import QImage, QPixmap

from sampling_tool.config import BDO_DARK_GREY, BDO_GREY, BDO_LIGHT_GREY, BDO_RED

BDO_COLORS: Final[list[str]] = [
    BDO_RED,
    BDO_DARK_GREY,
    BDO_GREY,
    "#FF8E9E",
    BDO_LIGHT_GREY,
]

_DPI: Final[int] = 100
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
    fig = _make_figure(width, height)
    ax = fig.add_subplot(111)
    if labels:
        colors = [BDO_COLORS[i % len(BDO_COLORS)] for i in range(len(labels))]
        ax.bar(labels, values, color=colors)
    _style_axes(ax, title)
    return _figure_to_pixmap(fig)


def render_line_chart(
    labels: list[str],
    values: list[float],
    title: str = "",
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> QPixmap:
    """Rendert ein Liniendiagramm als `QPixmap`."""
    fig = _make_figure(width, height)
    ax = fig.add_subplot(111)
    if labels:
        ax.plot(labels, values, color=BDO_RED, marker="o", linewidth=2.0)
        ax.fill_between(range(len(labels)), values, alpha=0.15, color=BDO_RED)
    _style_axes(ax, title)
    if len(labels) > 8:
        for label in ax.get_xticklabels():
            label.set_rotation(45)
            label.set_horizontalalignment("right")
    return _figure_to_pixmap(fig)


def render_pie_chart(
    labels: list[str],
    values: list[float],
    title: str = "",
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> QPixmap:
    """Rendert ein Tortendiagramm als `QPixmap`."""
    fig = _make_figure(width, height)
    ax = fig.add_subplot(111)
    if labels and sum(values) > 0:
        colors = [BDO_COLORS[i % len(BDO_COLORS)] for i in range(len(labels))]
        ax.pie(
            values,
            labels=labels,
            colors=colors,
            autopct="%1.0f%%",
            startangle=90,
            textprops={"fontsize": 8, "color": BDO_DARK_GREY},
            wedgeprops={"linewidth": 1, "edgecolor": "white"},
        )
        ax.axis("equal")
    if title:
        ax.set_title(title, color=BDO_DARK_GREY, fontsize=10, fontweight="bold")
    return _figure_to_pixmap(fig)


def render_bar_chart_bytes(
    labels: list[str],
    values: list[float],
    title: str = "",
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> bytes:
    """Wie `render_bar_chart`, gibt aber PNG-Bytes zurück (für HTML/Excel)."""
    fig = _make_figure(width, height)
    ax = fig.add_subplot(111)
    if labels:
        colors = [BDO_COLORS[i % len(BDO_COLORS)] for i in range(len(labels))]
        ax.bar(labels, values, color=colors)
    _style_axes(ax, title)
    return _figure_to_bytes(fig)


def render_line_chart_bytes(
    labels: list[str],
    values: list[float],
    title: str = "",
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> bytes:
    """Wie `render_line_chart`, gibt aber PNG-Bytes zurück."""
    fig = _make_figure(width, height)
    ax = fig.add_subplot(111)
    if labels:
        ax.plot(labels, values, color=BDO_RED, marker="o", linewidth=2.0)
        ax.fill_between(range(len(labels)), values, alpha=0.15, color=BDO_RED)
    _style_axes(ax, title)
    if len(labels) > 8:
        for label in ax.get_xticklabels():
            label.set_rotation(45)
            label.set_horizontalalignment("right")
    return _figure_to_bytes(fig)


def render_pie_chart_bytes(
    labels: list[str],
    values: list[float],
    title: str = "",
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> bytes:
    """Wie `render_pie_chart`, gibt aber PNG-Bytes zurück."""
    fig = _make_figure(width, height)
    ax = fig.add_subplot(111)
    if labels and sum(values) > 0:
        colors = [BDO_COLORS[i % len(BDO_COLORS)] for i in range(len(labels))]
        ax.pie(
            values,
            labels=labels,
            colors=colors,
            autopct="%1.0f%%",
            startangle=90,
            textprops={"fontsize": 8, "color": BDO_DARK_GREY},
            wedgeprops={"linewidth": 1, "edgecolor": "white"},
        )
        ax.axis("equal")
    if title:
        ax.set_title(title, color=BDO_DARK_GREY, fontsize=10, fontweight="bold")
    return _figure_to_bytes(fig)


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _make_figure(width: int, height: int) -> Figure:
    fig = Figure(figsize=(width / _DPI, height / _DPI), dpi=_DPI)
    fig.patch.set_alpha(0.0)
    return fig


def _style_axes(ax: Any, title: str) -> None:
    """Einheitliches Styling für Bar-/Line-Charts."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(BDO_LIGHT_GREY)
    ax.spines["bottom"].set_color(BDO_LIGHT_GREY)
    ax.tick_params(axis="both", colors=BDO_GREY, labelsize=8)
    ax.grid(axis="y", linestyle=":", color=BDO_LIGHT_GREY, alpha=0.6)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, color=BDO_DARK_GREY, fontsize=10, fontweight="bold")


def _figure_to_bytes(fig: Figure) -> bytes:
    """Speichert die Figure in einen PNG-Buffer und schließt sie sauber."""
    try:
        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=_DPI, transparent=True, bbox_inches="tight")
        return buf.getvalue()
    finally:
        plt.close(fig)


def _figure_to_pixmap(fig: Figure) -> QPixmap:
    """Rendert die Figure und packt sie in ein `QPixmap` (kein File-Roundtrip)."""
    raw = _figure_to_bytes(fig)
    image = QImage.fromData(raw, "PNG")
    return QPixmap.fromImage(image)
