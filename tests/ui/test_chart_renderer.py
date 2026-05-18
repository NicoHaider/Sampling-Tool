"""Tests für `ui/widgets/chart_renderer` – dünner QPixmap-Wrapper.

Die Bytes-Logik selbst sitzt seit Sprint 15 in `io/charts.py` und wird
dort in `tests/unit/test_io_charts.py` separat (Qt-frei) getestet.
Hier nur die UI-Anbindung: PNG → QPixmap, kein Figure-Leak.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import pytest
from PyQt6.QtGui import QPixmap

from sampling_tool.ui.widgets.chart_renderer import (
    render_bar_chart,
    render_line_chart,
    render_pie_chart,
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
