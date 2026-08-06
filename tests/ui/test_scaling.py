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

    def test_scrollbar_handle_min_size_unchanged(self) -> None:
        """Regression: `_LOGO_BOUND_RE` must NOT touch the scrollbar handle's
        `min-height`/`min-width` (Sprint 68 self-review finding) — only the
        LogoPlaceholder block's bounds may scale."""
        scaled = scale_stylesheet(_real_qss(), 1.15)
        assert "min-height: 30px;" in scaled
        assert "min-width: 30px;" in scaled


class TestLoadScaledStylesheet:
    def test_normal_matches_real_file_byte_identical(self) -> None:
        assert load_scaled_stylesheet(1.0) == _real_qss()

    def test_other_factor_differs_from_real_file(self) -> None:
        assert load_scaled_stylesheet(1.15) != _real_qss()


class TestCheckboxRadioIndicatorVisibility:
    """Sprint 69 / Bug 1: unchecked Checkboxen/Radiobuttons waren unsichtbar
    (weiß auf weiß) – `bdo_light.qss` hatte null `QCheckBox::indicator` /
    `QRadioButton::indicator`-Regeln, die generische QWidget-Regel malte den
    nativen Indikator randlos weiß über. Fix: fixe Indikator-Größe + ein
    sichtbar umrandeter `:unchecked`-Zustand, während `:checked` komplett
    unangetastet bleibt (kein Selektor matcht `:checked` – Qt rendert ihn
    also weiterhin nativ/unverändert, siehe QSS-Kommentar im Abschnitt
    "Checkboxen & Radiobuttons")."""

    def test_checkbox_indicator_has_visible_unchecked_style(self) -> None:
        qss = _real_qss()

        # 1) Beide Sub-Controls bekommen eine explizite, fixe Pixel-Größe –
        #    erst das macht aus dem Indikator überhaupt eine sichtbare
        #    Box/Kreis-Fläche (vorher: implizite, stilabhängige Größe).
        size_rule = re.search(
            r"QCheckBox::indicator\s*,\s*QRadioButton::indicator\s*\{([^}]*)\}", qss
        )
        assert size_rule is not None, "erwarte eine gemeinsame Basis-Regel für die Indikator-Größe"
        assert re.search(r"width:\s*16px", size_rule.group(1))
        assert re.search(r"height:\s*16px", size_rule.group(1))

        # 2) `:unchecked` muss klar sichtbar sein: helles Background PLUS
        #    eine echte (nicht transparente, nicht weiß-auf-weiß) Umrandung
        #    in einem der bereits im File verwendeten Palette-Grautöne.
        unchecked_rule = re.search(
            r"QCheckBox::indicator:unchecked\s*,\s*QRadioButton::indicator:unchecked\s*\{([^}]*)\}",
            qss,
        )
        assert unchecked_rule is not None, (
            "erwarte eine gemeinsame :unchecked-Regel für beide Controls"
        )
        body = unchecked_rule.group(1)
        assert re.search(r"background-color:\s*#[0-9A-Fa-f]{6}", body)
        border_match = re.search(r"border:\s*1px solid (#[0-9A-Fa-f]{6})", body)
        assert border_match is not None
        assert border_match.group(1) in {"#B0B0B0", "#D9D9D9"}

        # 3) Radiobuttons müssen wie ein Kreis aussehen (nicht wie ein
        #    Quadrat) – gerundet via border-radius, beschränkt auf
        #    `:unchecked` (ein Radius auf dem selektorlosen Basis-Fall
        #    würde – empirisch geprüft, siehe QSS-Kommentar – den nativen
        #    angehakten Punkt zum Verschwinden bringen).
        assert re.search(r"QRadioButton::indicator:unchecked\s*\{[^}]*border-radius:\s*\d+px", qss)

        # 4) Checkboxen bleiben eckig: kein border-radius in irgendeiner
        #    QCheckBox::indicator-Regel.
        checkbox_blocks = re.findall(r"QCheckBox::indicator[^{]*\{([^}]*)\}", qss)
        assert checkbox_blocks, "erwarte mindestens eine QCheckBox::indicator-Regel"
        assert not any("border-radius" in block for block in checkbox_blocks)

        # 5) 🔒 Sicherheitslinie: der angehakte Zustand bleibt komplett
        #    unangetastet – keine Regel darf `::indicator:checked` matchen,
        #    sonst würde das bestehende (native) Aussehen überschrieben.
        assert "::indicator:checked" not in qss

        # 6) Hard Constraint: keine font-size-Deklaration in den neuen
        #    Regeln (der Skalierungstest zählt jedes font-size-Vorkommen).
        indicator_section = qss[qss.index("Checkboxen & Radiobuttons") : qss.index("Splitter")]
        assert "font-size" not in indicator_section


class TestRowNumberHeaderStyle:
    """Sprint 70 / Befund B: automatische Zeilennummer visuell absetzen."""

    def test_vertical_header_background_differs_from_table_background(self) -> None:
        qss = _real_qss()
        block = re.search(r"QHeaderView::section:vertical\s*\{([^}]*)\}", qss)
        assert block is not None
        bg_match = re.search(r"background-color:\s*(#[0-9A-Fa-f]{6})", block.group(1))
        assert bg_match is not None
        assert bg_match.group(1).upper() not in {"#FFFFFF", "#FAFAFA"}

    def test_corner_label_rule_is_transparent(self) -> None:
        qss = _real_qss()
        block = re.search(r"QLabel#rowNumberCornerLabel\s*\{([^}]*)\}", qss)
        assert block is not None
        assert "background: transparent" in block.group(1)

    def test_new_rules_contain_no_font_size(self) -> None:
        qss = _real_qss()
        for selector in ("QHeaderView::section:vertical", "QLabel#rowNumberCornerLabel"):
            block = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", qss)
            assert block is not None, f"erwarte eine Regel für {selector}"
            assert "font-size" not in block.group(1)
