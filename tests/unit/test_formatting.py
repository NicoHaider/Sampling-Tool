"""Unit-Tests für `core.formatting` (Sprint 18 / Q-005).

Zentrale Timestamp-Formatierung – stellt sicher, dass PDF, UI, Excel- und
HTML-Report denselben Event mit IDENTISCHEM Datums-/Zeit-String anzeigen.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone

import pytest

from sampling_tool.core.formatting import (
    ensure_utc,
    format_audit_details,
    format_cell_value,
    format_event_timestamp,
    format_header_row,
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


class TestFormatAuditDetails:
    def test_empty_dict_returns_dash(self) -> None:
        assert format_audit_details({}) == "—"

    def test_joins_multiple_keys_compactly(self) -> None:
        result = format_audit_details({"filter_operator": "gte", "parent_sample_id": 17})
        assert result == "Filter-Operator: ≥ · Parent-Sample-ID: 17"

    def test_bool_value_renders_german(self) -> None:
        assert format_audit_details({"flag": True}) == "flag: ja"
        assert format_audit_details({"flag": False}) == "flag: nein"


@pytest.mark.unit
class TestFormatCellValue:
    """Sprint 82 / Befund A: Zellwerte ungerundet, Floats nie in Exponent-Schreibweise."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (13134.97, "13134.97"),
            (20630.27, "20630.27"),
            (-5438.12, "-5438.12"),
            (1234567.89, "1234567.89"),
            (1e16, "10000000000000000"),
            (1.5e-7, "0.00000015"),
            (1234.0, "1234"),
            (0.1, "0.1"),
            # Das Vorzeichen steht so in der Quelle (nur CSV-Text „-0.0" landet hier).
            (-0.0, "-0"),
            (123456789012345678.0, "123456789012345680"),
            (float("nan"), "nan"),
            (float("inf"), "inf"),
            (float("-inf"), "-inf"),
        ],
    )
    def test_float_is_exact_fixed_point(self, value: float, expected: str) -> None:
        assert format_cell_value(value) == expected

    @pytest.mark.parametrize(
        "value",
        [13134.97, 20630.27, -5438.12, 1234567.89, 1e16, 1.5e-7, 1234.0, 1e22, 1e300, 5e-324],
    )
    def test_finite_float_never_exponent_and_lossless(self, value: float) -> None:
        text = format_cell_value(value)
        assert "e" not in text.lower()
        assert float(text) == value

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, ""),
            (True, "Ja"),
            (False, "Nein"),
            (datetime(2026, 1, 2, 3, 4, 5), "2026-01-02 03:04:05"),
            (datetime(2026, 5, 11), "2026-05-11"),
            (date(2026, 5, 11), "2026-05-11"),
            (time(9, 15, 30), "09:15:30"),
            (42, "42"),
            ("Kasse", "Kasse"),
        ],
    )
    def test_non_float_values_keep_previous_rendering(self, value: object, expected: str) -> None:
        assert format_cell_value(value) == expected


class TestFormatHeaderRow:
    """Sprint 83 / B: Kopfzeile 1-basiert wie im Import-Dialog, 0 = keine."""

    def test_zeilennummer(self) -> None:
        assert format_header_row(5) == "Zeile 5"

    def test_keine_kopfzeile(self) -> None:
        assert format_header_row(0) == "keine (Spaltennamen generiert)"

    def test_nicht_erfasst(self) -> None:
        assert format_header_row(None) == "—"


@pytest.mark.unit
class TestAuditDetailsReadable:
    """Sprint 83 / D: deutsche Schlüssel, übersetzte Werte, keine Python-Rohdaten.
    In der DB bleiben die Rohschlüssel – übersetzt wird nur beim Rendern."""

    def test_keys_are_german(self) -> None:
        result = format_audit_details({"size_requested": 5, "stratum_field": "Land"})
        assert result == "Angeforderte Größe: 5 · Schicht-Feld: Land"

    @pytest.mark.parametrize(
        ("details", "expected"),
        [
            ({"method": "simple"}, "Methode: Einfach"),
            ({"method": "stratified"}, "Methode: Geschichtet"),
            ({"stratify_mode": "proportional"}, "Schichtungsmodus: Proportional"),
            ({"stratify_mode": "equal"}, "Schichtungsmodus: Gleich"),
            ({"filter_operator": "lte"}, "Filter-Operator: ≤"),
            ({"parent_relation": "restrict"}, "Ableitung: eingeschränkt"),
            ({"parent_relation": "supplement"}, "Ableitung: Nachstichprobe"),
            ({"header_row": 5}, "Kopfzeile: Zeile 5"),
            ({"header_row": 0}, "Kopfzeile: keine (Spaltennamen generiert)"),
            ({"restored": "empty"}, "Wiederhergestellt: leerer Zustand (keine Stichprobe)"),
        ],
    )
    def test_values_are_translated(self, details: dict[str, object], expected: str) -> None:
        assert format_audit_details(details) == expected

    def test_list_joined_without_python_repr(self) -> None:
        result = format_audit_details({"columns": ["BuchungsID", "Belegart"]})
        assert result == "Spalten: BuchungsID, Belegart"
        assert "[" not in result
        assert "'" not in result

    def test_tuple_joined_like_list(self) -> None:
        assert format_audit_details({"columns": ("a", "b")}) == "Spalten: a, b"

    def test_none_entries_are_dropped(self) -> None:
        result = format_audit_details({"filter_field": None, "method": "simple"})
        assert result == "Methode: Einfach"

    def test_only_none_entries_render_dash(self) -> None:
        assert format_audit_details({"filter_field": None}) == "—"

    def test_unknown_key_appears_raw(self) -> None:
        assert format_audit_details({"mystery_key": 1}) == "mystery_key: 1"

    def test_unknown_value_of_translated_key_appears_raw(self) -> None:
        assert format_audit_details({"method": "systematic"}) == "Methode: systematic"

    def test_key_order_follows_dict(self) -> None:
        result = format_audit_details({"seed_hint": 1, "method": "simple", "dataset_id": 3})
        assert result == "seed_hint: 1 · Methode: Einfach · Datensatz-ID: 3"
