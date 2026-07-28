"""Tests für `_scaling` – UI-Skalierungsfaktor + QSS-/Pixel-Skalierung (Sprint 68 / Teil B1).

Reine Funktionen (kein Qt-Widget-Zugriff) – analog zu `test_geometry.py`
(Sprint 67) unabhängig von der Offscreen-Testplattform testbar.
"""

from __future__ import annotations

import re

import pytest

from sampling_tool.resources import package_resource
from sampling_tool.ui._scaling import (
    UI_SCALE_DEFAULT,
    UI_SCALE_LEVELS,
    load_scaled_stylesheet,
    scale_factor,
    scale_stylesheet,
    scaled_px,
)

pytestmark = pytest.mark.unit


def _real_qss() -> str:
    return package_resource("ui/styles/bdo_light.qss").read_text(encoding="utf-8")


class TestScaleFactorSsot:
    def test_scale_factor_ssot(self) -> None:
        assert scale_factor("klein") == 0.9
        assert scale_factor("normal") == 1.0
        assert scale_factor("groß") == 1.15

    def test_unknown_value_falls_back_to_normal(self) -> None:
        assert scale_factor("gigantisch") == 1.0

    def test_default_and_levels_are_consistent(self) -> None:
        assert UI_SCALE_DEFAULT == "normal"
        assert UI_SCALE_LEVELS == ("klein", "normal", "groß")
        assert scale_factor(UI_SCALE_DEFAULT) == 1.0


class TestScaledPx:
    def test_normal_is_identity(self) -> None:
        assert scaled_px(13, 1.0) == 13

    def test_klein_rounds_down(self) -> None:
        assert scaled_px(20, 0.9) == 18

    def test_gross_rounds_up(self) -> None:
        assert scaled_px(20, 1.15) == 23


class TestScaleStylesheetIdentity:
    def test_scale_stylesheet_identity_at_normal(self) -> None:
        """🔒 Sicherheitslinie: Faktor 1.0 muss das Stylesheet byte-identisch lassen."""
        original = _real_qss()
        assert scale_stylesheet(original, 1.0) == original


class TestScaleStylesheetScaling:
    def test_scale_stylesheet_scales_font_sizes(self) -> None:
        original = _real_qss()
        small = scale_stylesheet(original, 0.9)
        large = scale_stylesheet(original, 1.15)

        pattern = re.compile(r"font-size:\s*(\d+)px")
        orig_sizes = [int(v) for v in pattern.findall(original)]
        small_sizes = [int(v) for v in pattern.findall(small)]
        large_sizes = [int(v) for v in pattern.findall(large)]

        # Nichts verschluckt: gleiche Anzahl font-size-Vorkommen.
        assert len(orig_sizes) == len(small_sizes) == len(large_sizes) > 0

        # Monoton: klein < normal < groß, für JEDEN Vorkommen-Index.
        for small_v, orig_v, large_v in zip(small_sizes, orig_sizes, large_sizes, strict=True):
            assert small_v < orig_v < large_v

    def test_logo_placeholder_bounds_scale(self) -> None:
        large = scale_stylesheet(_real_qss(), 1.15)
        assert "min-width: 138px" in large
        assert "max-width: 138px" in large
        assert "min-height: 138px" in large
        assert "max-height: 138px" in large

    def test_colors_selectors_and_layout_px_unchanged(self) -> None:
        """Nur font-size + LogoPlaceholder-Grenzwerte skalieren – keine
        Farb-/Layout-/Abstands-Änderungen (Hard Constraint des Sprints)."""
        original = _real_qss()
        scaled = scale_stylesheet(original, 1.15)
        assert "#E81A3B" in scaled
        assert "QPushButton:hover" in scaled
        assert "padding: 8px 18px;" in scaled  # unverändertes Layout-px
        assert "width: 24px;" in scaled  # QComboBox::drop-down – kein font-size


class TestLoadScaledStylesheet:
    def test_normal_matches_real_file_byte_identical(self) -> None:
        assert load_scaled_stylesheet(1.0) == _real_qss()

    def test_other_factor_differs_from_real_file(self) -> None:
        assert load_scaled_stylesheet(1.15) != _real_qss()
