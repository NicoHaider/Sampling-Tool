"""`format_int` – Tausenderpunkte für deutsche Locale (Sprint 91 / C)."""

from __future__ import annotations

import pytest

from sampling_tool.ui._number_format import format_int


class TestFormatInt:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0, "0"),
            (5, "5"),
            (999, "999"),
            (1000, "1.000"),
            (12345, "12.345"),
            (500_000, "500.000"),
            (1_234_567, "1.234.567"),
        ],
    )
    def test_formats_with_german_thousands_separator(self, value: int, expected: str) -> None:
        assert format_int(value) == expected
