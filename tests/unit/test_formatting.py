"""Unit-Tests für `core.formatting` (Sprint 18 / Q-005).

Zentrale Timestamp-Formatierung – stellt sicher, dass PDF, UI, Excel- und
HTML-Report denselben Event mit IDENTISCHEM Datums-/Zeit-String anzeigen.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from sampling_tool.core.formatting import (
    ensure_utc,
    format_event_timestamp,
    format_optional_timestamp,
)


class TestFormatEventTimestamp:
    def test_naive_datetime_wird_als_utc_interpretiert(self) -> None:
        """Naive datetimes (alte DB-Daten ohne TZ) gelten als UTC."""
        # Wir prüfen Konsistenz: derselbe Wert als naive und als aware-UTC
        # muss gleich formatiert werden.
        naive = datetime(2026, 5, 18, 14, 30, 0)
        aware_utc = naive.replace(tzinfo=UTC)
        assert format_event_timestamp(naive) == format_event_timestamp(aware_utc)

    def test_aware_utc_wird_in_lokale_zone_konvertiert(self) -> None:
        """UTC-Timestamps werden für die Anzeige in lokale TZ umgerechnet."""
        # Wir setzen einen UTC-Wert + lokale TZ kontrolliert.
        utc_dt = datetime(2026, 5, 18, 14, 30, 0, tzinfo=UTC)
        local_dt = utc_dt.astimezone()
        expected = local_dt.strftime("%Y-%m-%d %H:%M:%S")
        assert format_event_timestamp(utc_dt) == expected

    def test_aware_andere_tz_wird_zu_lokal_konvertiert(self) -> None:
        """Eingehende non-UTC-aware datetimes werden auch zur lokalen TZ."""
        tokyo = timezone(timedelta(hours=9))
        dt = datetime(2026, 5, 18, 23, 30, 0, tzinfo=tokyo)
        expected = dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        assert format_event_timestamp(dt) == expected

    def test_format_string_ist_yyyy_mm_dd_hhmmss(self) -> None:
        dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        out = format_event_timestamp(dt)
        # 19 Zeichen: 'YYYY-MM-DD HH:MM:SS'
        assert len(out) == 19
        assert out[4] == "-"
        assert out[7] == "-"
        assert out[10] == " "
        assert out[13] == ":"
        assert out[16] == ":"


class TestFormatOptionalTimestamp:
    def test_none_liefert_dash(self) -> None:
        assert format_optional_timestamp(None) == "—"

    def test_datetime_wird_via_format_event_timestamp_formatiert(self) -> None:
        dt = datetime(2026, 5, 18, 14, 30, 0, tzinfo=UTC)
        assert format_optional_timestamp(dt) == format_event_timestamp(dt)


class TestEnsureUtc:
    def test_naive_bekommt_utc_tz(self) -> None:
        naive = datetime(2026, 5, 18, 14, 30, 0)
        out = ensure_utc(naive)
        assert out.tzinfo == UTC

    def test_aware_bleibt_unveraendert(self) -> None:
        tokyo = timezone(timedelta(hours=9))
        aware = datetime(2026, 5, 18, 14, 30, 0, tzinfo=tokyo)
        out = ensure_utc(aware)
        assert out.tzinfo == tokyo
        assert out == aware
