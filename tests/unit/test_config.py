"""Tests für `config.py` – insbesondere die Trennung der zwei Sanitizer-Familien."""

from __future__ import annotations

import pytest

from sampling_tool import config

pytestmark = pytest.mark.unit


class TestSanitizerFamiliesStayDistinct:
    """Sprint 60 / D.5 (Q-005): Familie A (`sanitize_for_path`, Ordner-/DB-Namen)
    und Familie B (`sanitize_export_filename_token`, Export-Dateinamen) sind
    zwei semantisch verschiedene Sanitizer – rote Linie: Export-Namen dürfen
    nie über Familie A laufen (das würde Umlaute transliterieren + kappen)."""

    def test_export_sanitizer_keeps_umlauts_path_sanitizer_transliterates(self) -> None:
        token = "Müller ä ß Prüfung"
        export_token = config.sanitize_export_filename_token(token)
        path_token = config.sanitize_for_path(token)
        assert "ä" in export_token
        assert "ß" in export_token
        assert "ä" not in path_token
        assert "ss" in path_token  # ß → ss (Familie A transliteriert)

    def test_export_sanitizer_does_not_cap_length_path_sanitizer_does(self) -> None:
        token = "X" * 150
        assert len(config.sanitize_export_filename_token(token)) == 150
        assert len(config.sanitize_for_path(token)) <= 100

    def test_export_sanitizer_replaces_forbidden_chars(self) -> None:
        assert config.sanitize_export_filename_token("a/b:c*d") == "a_b_c_d"

    def test_export_sanitizer_strips_and_collapses_double_underscores(self) -> None:
        assert config.sanitize_export_filename_token("  Rand  ") == "Rand"
        assert config.sanitize_export_filename_token("a//b") == "a_b"

    def test_export_sanitizer_empty_input_stays_empty(self) -> None:
        # Kein "or x"-Fallback hier – Aufrufer entscheiden ihren eigenen
        # Default (z. B. "sample"/"0"/"export"), analog zum bisherigen
        # `_sanitize_filename_token` in io/exporter.py.
        assert config.sanitize_export_filename_token("") == ""


class TestExcelArgb:
    """Sprint 81: EINE Umrechnung `#RRGGBB` → openpyxl-ARGB.

    Sie stand zweimal im Projekt: als privates `_to_argb` in `io/exporter.py`
    und – gar nicht – in `io/multi_report_exporter.py`, wo stattdessen vier
    `"FFE81A3B"`-Literale standen. Das war die gefährlichste Kopie des
    Marken-Rots: ein Suchen nach `#E81A3B` findet sie nicht, ein Ändern von
    `BDO_RED` wäre dort still nicht durchgeschlagen.
    """

    def test_six_digit_gets_full_alpha(self) -> None:
        assert config.excel_argb("#E81A3B") == "FFE81A3B"

    def test_hash_is_optional_and_case_is_normalised(self) -> None:
        assert config.excel_argb("e81a3b") == "FFE81A3B"

    def test_eight_digit_passes_through_unchanged(self) -> None:
        """Ein Wert mit Alpha-Kanal darf kein zweites Präfix bekommen.

        Die naive Formulierung (`f"{alpha}{value}"`) ergäbe hier
        `FFFFE81A3B` – zehn Stellen, die openpyxl kommentarlos verwirft.
        """
        assert config.excel_argb("FFE81A3B") == "FFE81A3B"

    def test_custom_alpha(self) -> None:
        assert config.excel_argb("#E81A3B", alpha="80") == "80E81A3B"

    @pytest.mark.parametrize("bad", ["", "#ABC", "#E81A3B00FF", "nope"])
    def test_unexpected_length_raises(self, bad: str) -> None:
        """Lieber laut als eine Farbe erfinden, die still verworfen wird."""
        with pytest.raises(ValueError, match="Unerwartetes Farbformat"):
            config.excel_argb(bad)


class TestMethodLabels:
    """Sprint 81: die deutschen Methodennamen stehen genau hier."""

    def test_covers_every_sampling_method(self) -> None:
        """Eine neue Methode ohne Label fiele sonst erst im UI auf – als
        englischer Enum-Wert mitten in deutschem Text."""
        from sampling_tool.core.models import SamplingMethod

        missing = [m.value for m in SamplingMethod if m.value not in config.METHOD_LABELS]
        assert not missing, f"Ohne Anzeige-Namen in config.METHOD_LABELS: {missing}"
