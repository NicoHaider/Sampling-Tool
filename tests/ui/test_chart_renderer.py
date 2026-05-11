"""Tests für `chart_renderer` – matplotlib mit `Agg`-Backend.

Wir prüfen sowohl die `QPixmap`-Variante (UI) als auch die Bytes-Variante
(HTML-Embed / Excel-Image). Wichtig ist, dass mehrfaches Rendern keine
Figure-Leaks erzeugt (matplotlib.pyplot.get_fignums sollte zwischen den
Aufrufen leer bleiben).
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import pytest
from PyQt6.QtGui import QPixmap

from sampling_tool.ui.widgets.chart_renderer import (
    render_bar_chart,
    render_bar_chart_bytes,
    render_line_chart,
    render_line_chart_bytes,
    render_pie_chart,
    render_pie_chart_bytes,
)

pytestmark = pytest.mark.ui


def test_bar_chart_returns_non_empty_pixmap(qtbot: object) -> None:
    pixmap = render_bar_chart(["A", "B", "C"], [1.0, 2.0, 3.0], "Test", width=320, height=160)
    assert isinstance(pixmap, QPixmap)
    assert not pixmap.isNull()
    assert pixmap.width() > 0
    assert pixmap.height() > 0


def test_line_chart_returns_non_empty_pixmap(qtbot: object) -> None:
    pixmap = render_line_chart(
        labels=[f"Tag {i}" for i in range(10)],
        values=[float(i) for i in range(10)],
        title="Trend",
    )
    assert isinstance(pixmap, QPixmap)
    assert not pixmap.isNull()


def test_pie_chart_returns_non_empty_pixmap(qtbot: object) -> None:
    pixmap = render_pie_chart(["simple", "cluster"], [4.0, 2.0], "Methoden")
    assert not pixmap.isNull()


def test_bar_chart_bytes_are_valid_png(qtbot: object) -> None:
    raw = render_bar_chart_bytes(["A", "B"], [10.0, 20.0])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(raw) > 100


def test_line_chart_bytes_are_valid_png(qtbot: object) -> None:
    raw = render_line_chart_bytes(["x", "y"], [1.0, 2.0])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_pie_chart_bytes_are_valid_png(qtbot: object) -> None:
    raw = render_pie_chart_bytes(["a", "b", "c"], [1.0, 2.0, 3.0])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_repeated_render_does_not_leak_figures(qtbot: object) -> None:
    """Viele Renders hintereinander dürfen keine offenen Figures hinterlassen."""
    plt.close("all")
    for _ in range(20):
        render_bar_chart(["A", "B"], [1.0, 2.0])
        render_line_chart(["A", "B"], [1.0, 2.0])
        render_pie_chart(["A", "B"], [1.0, 2.0])
    assert plt.get_fignums() == []


def test_empty_inputs_render_blank_pixmap(qtbot: object) -> None:
    """Leere Daten dürfen den Renderer nicht crashen lassen."""
    pixmap = render_bar_chart([], [], "leer")
    assert not pixmap.isNull()
    raw = render_pie_chart_bytes([], [], "leer")
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
