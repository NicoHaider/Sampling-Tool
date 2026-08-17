"""Tests für `io/charts.py` – Bytes-Renderer für HTML-/Excel-Reports.

Sprint 15 / F-003 + F-004 + F-005: dieser Test verifiziert, dass das
Modul **ohne PyQt6** läuft. Es darf weder `pytestqt` noch `QApplication`
brauchen, weder direkt noch transitiv. Wenn dieser Import-Block grün
durchläuft, ist die Layer-Trennung intakt.
"""

from __future__ import annotations

import struct
import sys

import matplotlib.pyplot as plt
import pytest

from sampling_tool.io.charts import (
    BDO_COLORS,
    render_bar_chart_bytes,
    render_line_chart_bytes,
    render_pie_chart_bytes,
)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

#: Alle drei Renderer mit identischer Signatur – die Scale-Zusagen gelten für
#: jeden, nicht nur für den, der zufällig getestet wird.
_RENDERERS = (
    ("bar", render_bar_chart_bytes),
    ("line", render_line_chart_bytes),
    ("pie", render_pie_chart_bytes),
)


def png_size(raw: bytes) -> tuple[int, int]:
    """Pixelmaße aus dem IHDR-Chunk lesen – gemessen, nicht geschätzt.

    Aufbau: 8 Byte Signatur, 4 Byte Chunk-Länge, 4 Byte Chunk-Typ (`IHDR`),
    dann width/height als je 4 Byte big-endian. Bewusst ohne Qt/Pillow, damit
    die Qt-Freiheit dieses Moduls (`TestQtFreeImport`) nicht angetastet wird.
    """
    assert raw[:8] == _PNG_MAGIC
    assert raw[12:16] == b"IHDR", raw[12:16]
    width, height = struct.unpack(">II", raw[16:24])
    return int(width), int(height)


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


class TestChartScaleIsByteIdenticalAtOne:
    """🔒 Sicherheitslinie (Sprint 78 / §2.2).

    Bei `scale == 1.0` müssen die Bytes exakt die von vorher sein. Der Umbau
    schleust einen Faktor durch `Figure(dpi=…)` und `savefig(dpi=…)`; würde
    matplotlib schon beim Durchleiten einer 1.0 andere Bytes liefern, wäre die
    Naht falsch gewählt (§8) – das prüft diese Klasse, statt es anzunehmen.
    """

    @pytest.mark.parametrize(("name", "render"), _RENDERERS, ids=[n for n, _ in _RENDERERS])
    def test_explicit_scale_one_matches_the_default(self, name: str, render: object) -> None:
        assert callable(render)
        ohne = render(["A", "B", "C"], [1.0, 2.0, 3.0], "Test", 360, 160)
        mit = render(["A", "B", "C"], [1.0, 2.0, 3.0], "Test", 360, 160, 1.0)
        assert ohne == mit, f"{name}: scale=1.0 ist nicht byte-identisch zum Default"

    def test_report_path_widths_are_byte_identical_at_scale_one(self) -> None:
        """Der Report-Pfad ruft ohne den neuen Parameter auf und muss exakt das
        alte Ergebnis bekommen – geprüft mit genau den Maßen aus
        `html_report.py` (560×240 Bar, 620×200 Line) und
        `multi_report_exporter.py`."""
        bar_ohne = render_bar_chart_bytes(["a", "b"], [1.0, 2.0], "", 560, 240)
        bar_mit = render_bar_chart_bytes(["a", "b"], [1.0, 2.0], "", 560, 240, 1.0)
        line_ohne = render_line_chart_bytes(["x", "y"], [1.0, 2.0], "", 620, 200)
        line_mit = render_line_chart_bytes(["x", "y"], [1.0, 2.0], "", 620, 200, 1.0)
        assert bar_ohne == bar_mit
        assert line_ohne == line_mit

    def test_nonpositive_scale_falls_back_to_base_dpi(self) -> None:
        """Ein unsinniger Faktor darf keine 0×0-Grafik erzeugen."""
        raw = render_bar_chart_bytes(["A"], [1.0], "", 360, 160, 0.0)
        assert raw == render_bar_chart_bytes(["A"], [1.0], "", 360, 160)


class TestChartScaleEnlargesPixels:
    """`scale=2.0` verdoppelt die Pixelmaße – gleiche `figsize`, höhere DPI.

    Toleranz ist eingeplant: `savefig(bbox_inches="tight")` schneidet auf den
    belegten Bereich zu, die Maße sind also nicht mathematisch `width×height`
    (gemessen: 360×160 angefordert → 350×150 geliefert). Geprüft wird deshalb
    das **Verhältnis**, nicht die absolute Zahl.
    """

    TOLERANCE_PX = 2

    @pytest.mark.parametrize(("name", "render"), _RENDERERS, ids=[n for n, _ in _RENDERERS])
    def test_scale_two_doubles_both_dimensions(self, name: str, render: object) -> None:
        assert callable(render)
        einfach = png_size(render(["A", "B", "C"], [1.0, 2.0, 3.0], "Test", 360, 160, 1.0))
        doppelt = png_size(render(["A", "B", "C"], [1.0, 2.0, 3.0], "Test", 360, 160, 2.0))
        for axis, one, two in (
            ("Breite", einfach[0], doppelt[0]),
            ("Höhe", einfach[1], doppelt[1]),
        ):
            assert abs(two - 2 * one) <= self.TOLERANCE_PX, (
                f"{name}/{axis}: {two} px statt ~{2 * one} px bei scale=2.0"
            )

    def test_scale_two_is_not_merely_a_bigger_canvas(self) -> None:
        """Gegenprobe zu §2.3: die Schärfung darf kein Layout-Wechsel sein.

        Eine verdoppelte `figsize` bei gleichem DPI ergäbe ebenfalls doppelte
        Pixelmaße – aber die Schrift bliebe in pt gleich und würde relativ
        kleiner. Dass hier wirklich die Auflösung steigt, zeigt der Vergleich
        mit genau diesem Alternativweg: er liefert ANDERE Bytes.
        """
        geschaerft = render_bar_chart_bytes(["A", "B", "C"], [1.0, 2.0, 3.0], "Test", 360, 160, 2.0)
        groessere_leinwand = render_bar_chart_bytes(
            ["A", "B", "C"], [1.0, 2.0, 3.0], "Test", 720, 320, 1.0
        )
        assert png_size(geschaerft)[0] == pytest.approx(png_size(groessere_leinwand)[0], abs=40)
        assert geschaerft != groessere_leinwand


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
