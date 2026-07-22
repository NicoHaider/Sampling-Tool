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
