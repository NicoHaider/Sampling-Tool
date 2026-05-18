"""Unit-Tests für `_coerce_value` — Regressionsschutz für CLAUDE.md-Stolperfallen.

Pass-4 T-006: zwei der drei Calamine-Eigenheiten aus CLAUDE.md werden hier
direkt am `_coerce_value`-Helper getestet, statt eine vollständige xlsx-
Fixture zu basteln (die Calamine-Iteration mocken wäre invasiver als ein
Direkt-Test). Die dritte Stolperfalle (pywin32-macOS-Schutz) liegt in
`test_platform_imports.py`.
"""

from __future__ import annotations

from datetime import date, datetime, time

from sampling_tool.io.importer import _coerce_value


class TestCalamineEmptyStringNormalisierung:
    """CLAUDE.md-Stolperfalle: calamine liefert leere Zellen als `""`,
    muss zu `None` werden – sonst landet ein Empty-String im Dataset
    und alle nachgelagerten Filter (`row.get(field) == value`) brechen."""

    def test_empty_string_wird_None(self) -> None:
        assert _coerce_value("") is None

    def test_whitespace_only_wird_None(self) -> None:
        """Auch reine Whitespace-Zellen werden normalisiert."""
        assert _coerce_value("   ") is None

    def test_normaler_string_bleibt_erhalten(self) -> None:
        assert _coerce_value("Hallo") == "Hallo"


class TestCalamineFloatIntegerNormalisierung:
    """CLAUDE.md-Stolperfalle: Excel-Zahlen kommen IMMER als float aus
    calamine, auch wenn der User "42" eingetragen hat. Der Importer
    normalisiert ganzzahlige Floats auf int, sonst kommen alle
    Buchungs-IDs als `42.0`-Strings im PDF-Export an."""

    def test_ganzzahliger_float_wird_int(self) -> None:
        result = _coerce_value(42.0)
        assert result == 42
        assert type(result) is int

    def test_nicht_ganzzahliger_float_bleibt_float(self) -> None:
        result = _coerce_value(3.14)
        assert result == 3.14
        assert type(result) is float

    def test_negative_ganzzahl_wird_int(self) -> None:
        result = _coerce_value(-7.0)
        assert result == -7
        assert type(result) is int

    def test_null_float_wird_int(self) -> None:
        result = _coerce_value(0.0)
        assert result == 0
        assert type(result) is int


class TestCalamineDatumOhneUhrzeit:
    """CLAUDE.md-Stolperfalle: Datums-Zellen ohne Uhrzeit kommen aus
    calamine als `date`, nicht `datetime` wie bei openpyxl. Der Importer
    hebt `date` auf `datetime` mit 00:00:00 an, damit downstream-Code
    einheitlich mit `datetime` arbeitet."""

    def test_date_wird_datetime_mit_midnight(self) -> None:
        result = _coerce_value(date(2026, 5, 18))
        assert type(result) is datetime
        assert result == datetime(2026, 5, 18, 0, 0, 0)

    def test_datetime_bleibt_datetime(self) -> None:
        original = datetime(2026, 5, 18, 14, 30)
        result = _coerce_value(original)
        assert result is original

    def test_time_bleibt_time(self) -> None:
        original = time(9, 15)
        assert _coerce_value(original) == original


class TestNoneUndBool:
    def test_none_bleibt_none(self) -> None:
        assert _coerce_value(None) is None

    def test_bool_bleibt_bool_nicht_int(self) -> None:
        # bool ist subclass von int – darf nicht als int durchgereicht werden.
        result_true = _coerce_value(True)
        assert result_true is True
        assert type(result_true) is bool

        result_false = _coerce_value(False)
        assert result_false is False
        assert type(result_false) is bool
