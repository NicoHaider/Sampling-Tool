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


class TestDevicePixelRatio:
    """Schärfe-Fix (Sprint 78 / §2.5): mehr Pixel UND gesetztes Ratio.

    Beides gehört zusammen. Ein Bild mit doppelten Pixelmaßen ohne gesetztes
    Ratio erscheint schlicht doppelt so groß – der Fix wäre dann eine
    Layout-Regression statt einer Schärfung.
    """

    TOLERANCE_PX = 2

    def test_default_ratio_is_one_and_unchanged(self, qtbot: object) -> None:
        """🔒 Sicherheitslinie §2.2: ohne Parameter alles wie bisher."""
        pixmap = render_bar_chart(["A", "B"], [1.0, 2.0], "Test", 360, 160)
        assert pixmap.devicePixelRatio() == 1.0

    def test_explicit_ratio_one_matches_the_default(self, qtbot: object) -> None:
        ohne = render_bar_chart(["A", "B"], [1.0, 2.0], "Test", 360, 160)
        mit = render_bar_chart(["A", "B"], [1.0, 2.0], "Test", 360, 160, 1.0)
        assert (mit.width(), mit.height()) == (ohne.width(), ohne.height())
        assert mit.devicePixelRatio() == ohne.devicePixelRatio()

    def test_ratio_two_doubles_raw_pixels(self, qtbot: object) -> None:
        einfach = render_bar_chart(["A", "B"], [1.0, 2.0], "Test", 360, 160, 1.0)
        doppelt = render_bar_chart(["A", "B"], [1.0, 2.0], "Test", 360, 160, 2.0)
        assert abs(doppelt.width() - 2 * einfach.width()) <= self.TOLERANCE_PX
        assert abs(doppelt.height() - 2 * einfach.height()) <= self.TOLERANCE_PX

    def test_ratio_two_sets_the_pixmap_ratio(self, qtbot: object) -> None:
        pixmap = render_bar_chart(["A", "B"], [1.0, 2.0], "Test", 360, 160, 2.0)
        assert pixmap.devicePixelRatio() == 2.0

    def test_layout_size_stays_the_same(self, qtbot: object) -> None:
        """Der eigentliche Beweis, dass es eine Schärfung und kein Wachstum ist:
        die geräteunabhängige (Layout-)Größe bleibt gleich."""
        einfach = render_bar_chart(["A", "B"], [1.0, 2.0], "Test", 360, 160, 1.0)
        doppelt = render_bar_chart(["A", "B"], [1.0, 2.0], "Test", 360, 160, 2.0)
        assert doppelt.deviceIndependentSize().width() == pytest.approx(
            einfach.deviceIndependentSize().width(), abs=self.TOLERANCE_PX
        )
        assert doppelt.deviceIndependentSize().height() == pytest.approx(
            einfach.deviceIndependentSize().height(), abs=self.TOLERANCE_PX
        )

    def test_all_three_renderers_carry_the_ratio(self, qtbot: object) -> None:
        for render in (render_bar_chart, render_line_chart, render_pie_chart):
            pixmap = render(["A", "B"], [1.0, 2.0], "Test", 360, 160, 2.0)
            assert pixmap.devicePixelRatio() == 2.0, render.__name__
            assert not pixmap.isNull(), render.__name__
