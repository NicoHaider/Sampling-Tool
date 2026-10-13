"""Eindeutige Filteranzeige im Prüfnachweis (Sprint 93).

Ein Filterwert erscheint so, wie ihn die Zelle zeigt, die er trifft, und sein
Typ ist am Text erkennbar: Text in „…“, Zahlen ohne Tausenderpunkt, leer und
fehlend unterscheidbar, `—` nur für „kein Filter".
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

import pytest

from sampling_tool.core.filter_values import decode_filter_value, encode_filter_value
from sampling_tool.core.formatting import (
    detail_filter_conditions,
    format_audit_details,
    format_filters,
)
from sampling_tool.core.models import FilterCondition, FilterOperator

EQ = FilterOperator.EQ


def _one(value: Any, operator: FilterOperator = EQ, field: str = "Konto") -> str:
    return format_filters((FilterCondition(field, operator, value),))


class TestFilterValueTypes:
    def test_text_is_quoted(self) -> None:
        assert _one("Vertrieb", field="Kostenstelle") == "Kostenstelle = „Vertrieb“"

    def test_text_that_looks_like_number_differs_from_number(self) -> None:
        as_text = _one("1.000")
        as_number = _one(1000)
        assert as_text != as_number
        assert as_text == "Konto = „1.000“"
        assert as_number == "Konto = 1000"

    def test_int_and_float_without_thousands_separator(self) -> None:
        assert _one(1000, FilterOperator.GTE, "Betrag") == "Betrag ≥ 1000"
        assert _one(1000.5, FilterOperator.LT, "Betrag") == "Betrag < 1000.5"
        assert _one(-5, FilterOperator.GT, "Betrag") == "Betrag > -5"

    def test_bool_date_datetime_unquoted(self) -> None:
        assert _one(True, field="Storno") == "Storno = Ja"
        assert _one(False, field="Storno") == "Storno = Nein"
        assert _one(date(2026, 6, 30), FilterOperator.LT, "Datum") == "Datum < 2026-06-30"
        assert _one(datetime(2026, 6, 30), FilterOperator.LT, "Datum") == "Datum < 2026-06-30"
        assert (
            _one(datetime(2026, 6, 30, 10, 5), FilterOperator.GTE, "Datum")
            == "Datum ≥ 2026-06-30 10:05:00"
        )
        assert _one(time(10, 5), field="Uhrzeit") == "Uhrzeit = 10:05:00"

    def test_empty_string_vs_none_differ(self) -> None:
        assert _one("") == "Konto = (leer)"
        assert _one(None) == "Konto = (kein Wert)"

    def test_whitespace_only_text(self) -> None:
        assert _one("   ") == "Konto = (nur Leerzeichen)"
        assert _one("\t") == "Konto = (nur Leerzeichen)"

    def test_dash_only_for_no_filter(self) -> None:
        assert format_filters([]) == "—"
        for value in ("", " ", None, "—", 0, 0.0, False, "x"):
            assert not _one(value).endswith("= —"), value

    def test_text_edges_kept_inside_quotes(self) -> None:
        assert _one(" x ") == "Konto = „ x “"

    def test_quotes_in_text_not_escaped(self) -> None:
        assert _one('a"b„c“') == 'Konto = „a"b„c““'


class TestLegacyTemporalStrings:
    """Bestandsdaten vor Sprint 93: Datumswerte liegen als ISO-Text vor.

    Bei `>`/`≥`/`<`/`≤` ist das eindeutig – die Schwellenwert-Eingabe macht aus
    jedem ISO-Text ein `datetime`, ein gespeicherter ISO-Text war also immer ein
    Datum. Bei `=`/`≠` lässt sich das nicht entscheiden; der Wert bleibt Text.
    """

    @pytest.mark.parametrize("op", ["gt", "gte", "lt", "lte"])
    def test_iso_text_with_ordering_operator_is_a_date(self, op: str) -> None:
        details = {"filters": [{"field": "Datum", "operator": op, "value": "2024-06-03T00:00:00"}]}
        (condition,) = detail_filter_conditions(details)
        assert format_audit_details(details).endswith(" 2024-06-03")
        assert "„" not in format_audit_details(details)
        assert condition[2] == "2024-06-03T00:00:00"

    def test_iso_text_with_time_keeps_time(self) -> None:
        text = _one("2024-06-03T10:05:00", FilterOperator.GTE, "Datum")
        assert text == "Datum ≥ 2024-06-03 10:05:00"

    def test_non_iso_text_with_ordering_operator_stays_text(self) -> None:
        assert _one("abc", FilterOperator.GT) == "Konto > „abc“"

    def test_iso_text_with_eq_stays_text(self) -> None:
        assert _one("2024-06-03T00:00:00") == "Konto = „2024-06-03T00:00:00“"


class TestFilterValueCodec:
    @pytest.mark.parametrize(
        "value",
        [
            datetime(2024, 6, 3),
            datetime(2024, 6, 3, 10, 5, 7, 123456),
            date(2024, 6, 3),
            time(10, 5),
        ],
    )
    def test_temporal_roundtrip(self, value: Any) -> None:
        encoded = encode_filter_value(value)
        assert isinstance(encoded, dict)
        decoded = decode_filter_value(encoded)
        assert decoded == value
        assert type(decoded) is type(value)

    @pytest.mark.parametrize("value", ["1.000", "", 1000, 1000.5, True, None])
    def test_other_values_untouched(self, value: Any) -> None:
        assert encode_filter_value(value) is value
        assert decode_filter_value(value) is value

    def test_details_filters_are_decoded(self) -> None:
        details = {
            "filters": [
                {"field": "D", "operator": "lt", "value": encode_filter_value(date(2024, 6, 3))}
            ]
        }
        assert detail_filter_conditions(details) == [("D", "lt", date(2024, 6, 3))]
        assert format_audit_details(details) == "Filter: D < 2024-06-03"

    @pytest.mark.parametrize(
        "value",
        [{"__type__": "datetime", "v": 5}, {"__type__": "unbekannt", "v": "x"}, {"v": "x"}],
    )
    def test_malformed_tags_stay_as_they_are(self, value: Any) -> None:
        assert decode_filter_value(value) is value
