"""Unit-Tests für `_coerce_value` — Regressionsschutz für CLAUDE.md-Stolperfallen.

Pass-4 T-006: zwei der drei Calamine-Eigenheiten aus CLAUDE.md werden hier
direkt am `_coerce_value`-Helper getestet, statt eine vollständige xlsx-
Fixture zu basteln (die Calamine-Iteration mocken wäre invasiver als ein
Direkt-Test). Die dritte Stolperfalle (pywin32-macOS-Schutz) liegt in
`test_platform_imports.py`.
"""

from __future__ import annotations

import math
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


# ---------------------------------------------------------------------------
# Sprint 35 / WP-B: Äquivalenz-Oracle für die Coercion-Implementierung
# ---------------------------------------------------------------------------


def _reference_coerce_string(value: str) -> object:
    """Eingefrorene Referenz-Implementierung der Coercion-Semantik.

    Sprint 49 / N-006 + N-007: bewusst neu gepinnt (rote Linie im Backlog
    vorgesehen) – Ganzzahlen außerhalb des signed-64-Bit-Bereichs und
    non-finite Floats (inf/nan/Overflow) bleiben jetzt der Originalstring
    statt orjson-Crash bzw. stillem `null`-Datenverlust bei der Persistenz.
    Bewusst NICHT aus dem Importer importiert – unabhängige Zweit-
    Implementierung, damit das Oracle weiterhin Wert hat.
    """
    text = value.strip()
    if text == "":
        return None
    try:
        as_int: int | None = int(text)
    except ValueError:
        as_int = None
    if as_int is not None:
        if -(2**63) <= as_int <= 2**63 - 1:
            return as_int
        return text
    candidate = text.replace(",", ".") if "." not in text and text.count(",") == 1 else text
    try:
        as_float: float | None = float(candidate)
    except ValueError:
        as_float = None
    if as_float is not None and math.isfinite(as_float):
        return as_float
    return text


_NASTY_CORPUS = [
    "",
    " ",
    "\t\n",
    "abc",
    "Größe ß",
    "Ünïcode",
    "1",
    "+1",
    "-1",
    "007",
    "1_000",
    "1_0.5",
    "١٢٣",  # arabische Ziffern – int() akzeptiert sie
    "１２３",  # fullwidth digits
    "1.5",
    "1,5",
    "-1,5",
    "+1,5",
    "1.5.6",
    "1,5,6",
    "1,000.5",
    "1.000,5",
    ".5",
    "5.",
    "1e5",
    "1E5",
    "-1e-5",
    "e5",
    "inf",
    "Infinity",
    "-inf",
    "+inf",
    "NaN",
    "nan",
    "+nan",
    "++inf",
    "99999999999999999999",  # 20-stellig, > int64-max — Sprint 49 / N-006
    "1e999",  # Float-Overflow → inf — Sprint 49 / N-007
    "-1e999",
    "--1",
    "0x10",
    "0b101",
    "  42  ",
    "4 2",
    "€5",
    "5€",
    "-",
    "+",
    ".",
    ",",
    "_",
    "True",
    "None",
    "Buchung Nr. 17",
    "KS01",
    "2026-01-01",
    "12:30",
]


class TestCoerceStringEquivalenceOracle:
    """Sprint 35 / WP-B: Die Coercion DEFINIERT die importierten Werte/Typen
    (Byte-Identitäts-Rote-Linie). Jede Implementierungs-Optimierung muss
    exakt die historische Semantik liefern – Wert UND Typ."""

    def test_nasty_corpus_matches_reference(self) -> None:
        from sampling_tool.io.importer import _coerce_string

        for text in _NASTY_CORPUS:
            expected = _reference_coerce_string(text)
            got = _coerce_string(text)
            # repr-Vergleich statt ==: NaN != NaN (IEEE), und repr ist bei
            # -0.0 vs 0.0 sogar strenger als ==.
            assert repr(got) == repr(expected), repr(text)
            assert type(got) is type(expected), repr(text)

    def test_random_fuzz_matches_reference(self) -> None:
        """Seeded Fuzz über das kritische Alphabet (Ziffern, Vorzeichen,
        Komma/Punkt, Unterstrich, Exponent, Buchstaben, Unicode-Ziffern)."""
        import random

        from sampling_tool.io.importer import _coerce_string

        rng = random.Random(4711)
        alphabet = "0123456789+-.,_eEinfaNyz ٣５"
        for _ in range(5000):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 12)))
            expected = _reference_coerce_string(text)
            got = _coerce_string(text)
            # repr-Vergleich statt ==: NaN != NaN (IEEE), und repr ist bei
            # -0.0 vs 0.0 sogar strenger als ==.
            assert repr(got) == repr(expected), repr(text)
            assert type(got) is type(expected), repr(text)

    def test_coerce_value_type_dispatch_unchanged(self) -> None:
        """Reihenfolge-Invarianten der isinstance-Kette: bool bleibt bool
        (nicht int), date wird datetime, datetime bleibt datetime."""
        from datetime import date, datetime, time

        from sampling_tool.io.importer import _coerce_value

        assert _coerce_value(True) is True
        assert _coerce_value(False) is False
        assert type(_coerce_value(True)) is bool
        assert _coerce_value(datetime(2026, 1, 2, 3, 4)) == datetime(2026, 1, 2, 3, 4)
        assert _coerce_value(date(2026, 1, 2)) == datetime(2026, 1, 2, 0, 0, 0)
        assert type(_coerce_value(date(2026, 1, 2))) is datetime
        assert _coerce_value(time(8, 30)) == time(8, 30)
        assert _coerce_value(42.0) == 42
        assert type(_coerce_value(42.0)) is int
        assert _coerce_value(42.5) == 42.5
        assert _coerce_value(7) == 7
        assert _coerce_value(None) is None
        assert _coerce_value([1, 2]) == "[1, 2]"  # Letztes Mittel: str()


class TestCoerceSourceFidelity:
    """Sprint 49 / N-006 + N-007: explizite Vektor-Tests (nicht Oracle-
    basiert) für die pathologischen Fälle, deren Coercion-Ergebnis sich
    bewusst ändert — plus Belege, dass normale Werte byte-identisch
    bleiben (die rote Linie gilt nur für pathologische Eingaben)."""

    def test_huge_int_bleibt_string(self) -> None:
        from sampling_tool.io.importer import _coerce_string

        result = _coerce_string("99999999999999999999")
        assert result == "99999999999999999999"
        assert type(result) is str

    def test_float_overflow_bleibt_string(self) -> None:
        from sampling_tool.io.importer import _coerce_string

        for text in ("1e999", "-1e999"):
            result = _coerce_string(text)
            assert result == text
            assert type(result) is str

    def test_inf_und_nan_bleiben_string(self) -> None:
        from sampling_tool.io.importer import _coerce_string

        for text in ("inf", "-inf", "+inf", "Infinity", "nan", "NaN"):
            result = _coerce_string(text)
            assert result == text
            assert type(result) is str

    def test_int64_max_grenze_bleibt_int(self) -> None:
        from sampling_tool.io.importer import _coerce_string

        boundary = 2**63 - 1
        result = _coerce_string(str(boundary))
        assert result == boundary
        assert type(result) is int

    def test_int64_max_plus_eins_wird_string(self) -> None:
        from sampling_tool.io.importer import _coerce_string

        boundary_plus_one = 2**63
        result = _coerce_string(str(boundary_plus_one))
        assert result == str(boundary_plus_one)
        assert type(result) is str

    def test_int64_min_grenze_bleibt_int(self) -> None:
        from sampling_tool.io.importer import _coerce_string

        boundary = -(2**63)
        result = _coerce_string(str(boundary))
        assert result == boundary
        assert type(result) is int

    def test_int64_min_minus_eins_wird_string(self) -> None:
        from sampling_tool.io.importer import _coerce_string

        boundary_minus_one = -(2**63) - 1
        result = _coerce_string(str(boundary_minus_one))
        assert result == str(boundary_minus_one)
        assert type(result) is str

    def test_in_range_int_unveraendert(self) -> None:
        """Normale Werte bleiben byte-identisch — die rote Linie."""
        from sampling_tool.io.importer import _coerce_string

        result = _coerce_string("42")
        assert result == 42
        assert type(result) is int

    def test_deutsches_komma_dezimal_unveraendert(self) -> None:
        """Normale Werte bleiben byte-identisch — die rote Linie."""
        from sampling_tool.io.importer import _coerce_string

        result = _coerce_string("3,5")
        assert result == 3.5
        assert type(result) is float
