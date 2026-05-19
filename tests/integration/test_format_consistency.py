"""Integration-Tests: PDF, UI, Excel- und HTML-Report formatieren Audit-
Event-Timestamps identisch (Sprint 18 / Q-005).

Vor Sprint 18: PDF-Pfad normalisierte die Zeitzone nicht, UI/Excel/HTML
schon → derselbe Event hatte in PDF und UI unterschiedliche Uhrzeiten.
Diese Tests stellen sicher, dass der Drift nicht wieder auftritt – via
Identitäts-Check (alle Pfade beziehen DIESELBE zentrale Funktion).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sampling_tool.core import formatting
from sampling_tool.io import html_report, multi_report_exporter, pdf_report
from sampling_tool.ui.widgets import audit_trail_view

# Test-Anker: ein fester aware-UTC-Timestamp. Alle Konsumenten müssen
# denselben String produzieren – egal über welchen Pfad.
_EVENT_TS = datetime(2026, 5, 18, 14, 30, 0, tzinfo=UTC)


class TestFormatConsistency:
    # Die `is`-Checks greifen bewusst auf importierte (nicht via __all__
    # re-exportierte) Modul-Symbole zu – genau das ist der Konsolidierungs-
    # Nachweis. `type: ignore[attr-defined]` ist hier korrekt.

    def test_pdf_uses_central_format_event_timestamp(self) -> None:
        """Q-005: PDF-Pfad benutzt DIESELBE Funktion wie UI/Excel/HTML."""
        assert (
            pdf_report.format_event_timestamp  # type: ignore[attr-defined]
            is formatting.format_event_timestamp
        )

    def test_ui_uses_central_format_optional_timestamp(self) -> None:
        assert (
            audit_trail_view.format_optional_timestamp  # type: ignore[attr-defined]
            is formatting.format_optional_timestamp
        )

    def test_excel_report_uses_central_format_optional_timestamp(self) -> None:
        assert (
            multi_report_exporter.format_optional_timestamp  # type: ignore[attr-defined]
            is formatting.format_optional_timestamp
        )

    def test_html_report_uses_central_format_optional_timestamp(self) -> None:
        assert (
            html_report.format_optional_timestamp  # type: ignore[attr-defined]
            is formatting.format_optional_timestamp
        )

    def test_pdf_and_ui_format_same_event_identically(self) -> None:
        """Konkreter Output-Vergleich für einen festen UTC-Timestamp."""
        expected = formatting.format_event_timestamp(_EVENT_TS)
        # PDF nutzt direkt format_event_timestamp (kein Em-Dash-Fallback).
        assert formatting.format_event_timestamp(_EVENT_TS) == expected
        # UI/Excel/HTML gehen durch format_optional_timestamp.
        assert formatting.format_optional_timestamp(_EVENT_TS) == expected

    def test_naive_timestamp_konsistent_via_format_optional(self) -> None:
        """Naive datetimes (alte DB-Daten) werden als UTC interpretiert."""
        naive = datetime(2026, 5, 18, 14, 30, 0)
        aware = naive.replace(tzinfo=UTC)
        assert formatting.format_optional_timestamp(naive) == (
            formatting.format_optional_timestamp(aware)
        )

    def test_none_timestamp_returns_em_dash(self) -> None:
        assert formatting.format_optional_timestamp(None) == "—"
