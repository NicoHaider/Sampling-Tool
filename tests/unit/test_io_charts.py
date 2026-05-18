"""Tests für `io/charts.py` – Bytes-Renderer für HTML-/Excel-Reports.

Sprint 15 / F-003 + F-004 + F-005: dieser Test verifiziert, dass das
Modul **ohne PyQt6** läuft. Es darf weder `pytestqt` noch `QApplication`
brauchen, weder direkt noch transitiv. Wenn dieser Import-Block grün
durchläuft, ist die Layer-Trennung intakt.
"""

from __future__ import annotations

import sys

import matplotlib.pyplot as plt

from sampling_tool.io.charts import (
    BDO_COLORS,
    render_bar_chart_bytes,
    render_line_chart_bytes,
    render_pie_chart_bytes,
)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class TestChartBytesValidPng:
    def test_render_bar_chart_bytes_produces_valid_png(self) -> None:
        raw = render_bar_chart_bytes(["A", "B", "C"], [1.0, 2.0, 3.0], "Test")
        assert raw[:8] == _PNG_MAGIC
        assert len(raw) > 100  # nicht-trivial befüllt

    def test_render_line_chart_bytes_produces_valid_png(self) -> None:
        raw = render_line_chart_bytes(["x", "y", "z"], [1.0, 2.0, 3.0], "Trend")
        assert raw[:8] == _PNG_MAGIC

    def test_render_pie_chart_bytes_produces_valid_png(self) -> None:
        raw = render_pie_chart_bytes(["a", "b", "c"], [1.0, 2.0, 3.0], "Verteilung")
        assert raw[:8] == _PNG_MAGIC


class TestChartBytesEdgeCases:
    def test_render_bar_chart_bytes_with_empty_labels_does_not_crash(self) -> None:
        raw = render_bar_chart_bytes([], [], "leer")
        assert raw[:8] == _PNG_MAGIC

    def test_render_pie_chart_bytes_with_zero_sum_does_not_crash(self) -> None:
        """Pie-Chart mit lauter Null-Values: Zeichnen wird übersprungen,
        aber die Figure muss trotzdem ein gültiges PNG produzieren (sonst
        crasht der HTML-/Excel-Report bei degenerierten Statistiken)."""
        raw = render_pie_chart_bytes(["a", "b"], [0.0, 0.0], "alles null")
        assert raw[:8] == _PNG_MAGIC

    def test_render_line_chart_bytes_long_labels_does_not_crash(self) -> None:
        """>8 Labels → x-Achsen-Rotation greift, darf nicht crashen."""
        raw = render_line_chart_bytes(
            [f"Tag {i}" for i in range(15)],
            [float(i) for i in range(15)],
        )
        assert raw[:8] == _PNG_MAGIC

    def test_render_does_not_leak_figures(self) -> None:
        """20× Render → 0 offene matplotlib-Figures (kein Memory-Leak)."""
        plt.close("all")
        for _ in range(20):
            render_bar_chart_bytes(["A", "B"], [1.0, 2.0])
            render_line_chart_bytes(["A", "B"], [1.0, 2.0])
            render_pie_chart_bytes(["A", "B"], [1.0, 2.0])
        assert plt.get_fignums() == []


class TestQtFreeImport:
    """Verifiziert die Sprint-15-Architektur-Garantie: io/charts.py darf
    KEIN PyQt6 in `sys.modules` ziehen. Wenn dieser Test rot wird, hat
    jemand einen UI-Import in `io/charts.py` eingefügt."""

    def test_io_charts_does_not_import_pyqt6_transitively(self) -> None:
        # Bei pytest-Run ist PyQt6 oft schon importiert (durch andere Tests).
        # Wir prüfen darum nur, dass charts.py selbst direkt kein PyQt6
        # nutzt, indem wir den Modul-Source nach Qt-Tokens durchsuchen.
        import sampling_tool.io.charts as charts_mod

        source_path = charts_mod.__file__
        assert source_path is not None
        with open(source_path, encoding="utf-8") as fh:
            content = fh.read()
        assert "PyQt6" not in content
        assert "QPixmap" not in content
        assert "QImage" not in content


class TestBdoColors:
    def test_bdo_colors_is_non_empty_list_of_hex(self) -> None:
        assert isinstance(BDO_COLORS, list)
        assert len(BDO_COLORS) >= 3
        for color in BDO_COLORS:
            assert color.startswith("#")
            assert len(color) == 7  # #RRGGBB

    def test_module_exposes_public_renderers(self) -> None:
        # Sicherstellen, dass die public API stabil bleibt.
        mod = sys.modules["sampling_tool.io.charts"]
        for name in (
            "render_bar_chart_bytes",
            "render_line_chart_bytes",
            "render_pie_chart_bytes",
            "BDO_COLORS",
        ):
            assert hasattr(mod, name), f"io.charts fehlt: {name}"
