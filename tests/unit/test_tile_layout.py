"""Tests für die reine Umbruch-Rechnung des Dashboards (Sprint 78 / B2).

Qt-frei und mit synthetischen Zahlen – genau dafür ist die Logik aus dem Widget
herausgezogen: `conftest.py` erzwingt `QT_QPA_PLATFORM=offscreen`, echtes
Screen-Verhalten wäre hier nicht prüfbar.
"""

from __future__ import annotations

import pytest

from sampling_tool.ui._tile_layout import tile_columns, tile_rows

pytestmark = pytest.mark.unit

# Am echten Widget gemessen (2026-08-17, Sprint 78, macOS/offscreen):
# `DashboardTile.minimumSizeHint().width()` der Chart-Kacheln = 381 px, bei
# allen drei UI-Größen. Grid-Spacing 10, Grid-Margins 0.
# Diese Zahlen sind der Bezugspunkt der Sicherheitslinie aus §2.2.
MEASURED_TILE_MIN_WIDTH = 381
MEASURED_SPACING = 10
MEASURED_MARGINS = 0
MAX_COLUMNS = 3


def _width_for(columns: int) -> int:
    """Kleinste Breite, bei der `columns` Spalten genau noch passen."""
    return MEASURED_MARGINS + columns * MEASURED_TILE_MIN_WIDTH + (columns - 1) * MEASURED_SPACING


def _columns_at(available_width: int) -> int:
    return tile_columns(
        available_width=available_width,
        tile_min_width=MEASURED_TILE_MIN_WIDTH,
        spacing=MEASURED_SPACING,
        margins=MEASURED_MARGINS,
        max_columns=MAX_COLUMNS,
    )


class TestTileColumnsSafetyLine:
    """🔒 §2.2: bei ausreichender Breite müssen es exakt 3 Spalten sein."""

    def test_reference_width_yields_exactly_three_columns(self) -> None:
        assert _columns_at(_width_for(3)) == 3

    def test_generous_width_still_caps_at_three(self) -> None:
        """Bestandsnutzer auf großen Bildschirmen sehen keinen Unterschied."""
        assert _columns_at(3000) == MAX_COLUMNS
        assert _columns_at(10_000) == MAX_COLUMNS


class TestTileColumnsBreakpoints:
    """Je Umbruchpunkt die Breite direkt darunter und direkt darüber."""

    @pytest.mark.parametrize("columns", [1, 2, 3])
    def test_exact_breakpoint_width_fits(self, columns: int) -> None:
        assert _columns_at(_width_for(columns)) == columns

    @pytest.mark.parametrize("columns", [2, 3])
    def test_one_pixel_below_breakpoint_drops_one_column(self, columns: int) -> None:
        assert _columns_at(_width_for(columns) - 1) == columns - 1

    @pytest.mark.parametrize("columns", [1, 2])
    def test_one_pixel_above_breakpoint_keeps_column_count(self, columns: int) -> None:
        """Direkt über einem Umbruchpunkt darf nicht schon die nächste Stufe greifen."""
        assert _columns_at(_width_for(columns) + 1) == columns

    def test_spacing_counts_only_between_columns(self) -> None:
        """`n` Spalten haben `n-1` Zwischenräume, nicht `n`."""
        assert tile_columns(200, 100, 10, 0, 3) == 1
        assert tile_columns(210, 100, 10, 0, 3) == 2

    def test_margins_are_subtracted_before_the_division(self) -> None:
        assert tile_columns(210, 100, 10, 0, 3) == 2
        assert tile_columns(210, 100, 10, 20, 3) == 1


class TestTileColumnsEdgeCases:
    def test_never_returns_zero_when_tile_is_wider_than_the_window(self) -> None:
        """Eine Spalte ist das Minimum – ein leeres Dashboard wäre die
        schlechtere Antwort auf ein schmales Fenster."""
        assert _columns_at(10) == 1

    def test_zero_available_width_yields_one_column(self) -> None:
        assert _columns_at(0) == 1

    def test_negative_available_width_yields_one_column(self) -> None:
        assert _columns_at(-500) == 1

    def test_margins_larger_than_window_yield_one_column(self) -> None:
        assert tile_columns(30, 100, 10, 50, 3) == 1

    def test_max_columns_below_one_is_clamped(self) -> None:
        assert tile_columns(5000, 100, 10, 0, 0) == 1

    def test_nonpositive_tile_width_falls_back_to_max_columns(self) -> None:
        """Ohne sinnvolle Kachelbreite ist die Rechnung bedeutungslos; das
        bisherige Verhalten (volle Spaltenzahl) ist die konservative Antwort –
        und vor allem kein ZeroDivisionError."""
        assert tile_columns(1000, 0, 10, 0, 3) == 3
        assert tile_columns(1000, 0, 0, 0, 3) == 3
        assert tile_columns(1000, -5, 10, 0, 3) == 3

    def test_max_columns_is_respected_below_the_natural_fit(self) -> None:
        assert tile_columns(5000, 100, 10, 0, 2) == 2


class TestTileRows:
    """Die Zeilenzahl trägt den Stretch – mit dynamischen Spalten ist ein
    festes `setRowStretch(2, 1)` falsch (§2.7)."""

    @pytest.mark.parametrize(
        ("tile_count", "columns", "expected"),
        [(6, 3, 2), (6, 2, 3), (6, 1, 6), (5, 3, 2), (4, 3, 2), (1, 3, 1)],
    )
    def test_rows_for_tile_count(self, tile_count: int, columns: int, expected: int) -> None:
        assert tile_rows(tile_count, columns) == expected

    def test_degenerate_inputs_yield_one_row(self) -> None:
        assert tile_rows(0, 3) == 1
        assert tile_rows(6, 0) == 1
        assert tile_rows(-1, -1) == 1
