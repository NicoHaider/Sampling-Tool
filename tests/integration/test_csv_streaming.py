"""Sprint 96: CSV-Import streamt und behält Zeilenumbrüche in Feldern.

Kern ist `TestCsvEquivalenceOracle`: Für „saubere" CSV-Dateien (kein
Zeilenumbruch in Anführungszeichen, keines der Zeichen, an denen
`str.splitlines()` zusätzlich trennt) muss der gestreamte Import
byte-identisch zur eingefrorenen Referenz des Stands vor Sprint 96 sein –
auf dem Auto-Pfad, dem konfigurierten Pfad und in der Vorschau.
"""

from __future__ import annotations

import builtins
import csv
import io
import random
import tracemalloc
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import sampling_tool.io.importer as importer_module
from sampling_tool.core.cancellation import CancellationToken, OperationCancelled
from sampling_tool.core.models import DatasetRow
from sampling_tool.io.importer import (
    DataImportError,
    ExcelImporter,
    ImportStats,
    _coerce_value,
    _detect_header_with_confidence,
    _encoding_warning,
    _generic_columns,
    _header_row_number,
    _is_blank,
    _normalize_columns,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# Sprint 97 / D: byte-genaue Kopie der CSVs aus dem gitignorten `testdaten/csv/`,
# damit der Oracle-Teil auch in CI läuft. Fehlt eine Datei, schlägt der Test fehl.
TESTDATEN_DIR = REPO_ROOT / "tests" / "fixtures" / "csv"
TESTDATEN_CSV = [
    TESTDATEN_DIR / name
    for name in (
        "01_basis_gequotet.csv",
        "01_basis_komma.csv",
        "01_basis_semikolon_dezimalkomma.csv",
        "01_basis_utf8.csv",
        "01_basis_utf8_bom.csv",
    )
]

# Zeichen, an denen `str.splitlines()` trennt, die aber kein CSV-Zeilenende sind.
SPLITLINES_ONLY_CHARS = ("\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")

Outcome = tuple[Any, ...]


# ---------------------------------------------------------------------------
# Eingefrorene Referenz: CSV-Pfad des Importers auf `728c9ad` (vor Sprint 96).
# NICHT pflegen und NICHT an neues Verhalten anpassen – die Kopie ist das
# Orakel. Weicht der Importer für eine saubere Datei ab, ist der Importer
# falsch, nicht die Referenz.
# ---------------------------------------------------------------------------

_REF_CSV_ENCODINGS = ("utf-8", "utf-8-sig", "cp1252", "latin-1")


def _ref_read_csv_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"

    last_error: Exception | None = None
    for encoding in _REF_CSV_ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError as e:
            last_error = e
    raise DataImportError(
        f"CSV '{path.name}' konnte mit keinem unterstützten Encoding gelesen werden "
        f"({', '.join(_REF_CSV_ENCODINGS)}). Letzter Fehler: {last_error}"
    )


def _ref_csv_reader_rows(text: str, *, suffix: str = "") -> tuple[list[list[Any]], str | None]:
    sample = text[:8192] or text
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        fallback_warning: str | None = None
    except csv.Error:
        if suffix == ".tsv":
            dialect = csv.excel_tab
            fallback_warning = "Trennzeichen: Tab (aus Dateiendung '.tsv')."
        else:
            dialect = csv.excel
            fallback_warning = "Trennzeichen: Komma (Standard, Erkennung nicht eindeutig)."
    rows = [list(row) for row in csv.reader(text.splitlines(), dialect=dialect)]
    return rows, fallback_warning


def _ref_parse_csv(
    text: str, *, suffix: str = ""
) -> tuple[list[str], list[list[Any]], int, list[str], int]:
    all_rows, delimiter_warning = _ref_csv_reader_rows(text, suffix=suffix)

    leading = 0
    while all_rows and _is_blank(all_rows[0]):
        all_rows.pop(0)
        leading += 1

    while all_rows and _is_blank(all_rows[-1]):
        all_rows.pop()

    if not all_rows:
        return [], [], leading, [], leading

    header_row = list(all_rows[0])
    columns, warnings = _normalize_columns(header_row)
    if delimiter_warning is not None:
        warnings = [*warnings, delimiter_warning]

    data_rows: list[list[Any]] = []
    skipped = leading
    for raw in all_rows[1:]:
        if _is_blank(raw):
            skipped += 1
            continue
        data_rows.append(list(raw))

    return columns, data_rows, skipped, warnings, leading


def _ref_rows(columns: list[str], data_rows: list[list[Any]]) -> list[DatasetRow]:
    """`_csv_row_generator` (ohne Limits/Progress/Cancel – im Korpus nicht berührt)."""
    return [
        DatasetRow(
            row_id=idx,
            values={
                col: _coerce_value(raw[i] if i < len(raw) else None)
                for i, col in enumerate(columns)
            },
        )
        for idx, raw in enumerate(data_rows, start=1)
    ]


def _ref_import_csv(path: Path) -> Outcome:
    text, encoding = _ref_read_csv_text(path)
    columns, data_rows, skipped, warnings, leading = _ref_parse_csv(
        text, suffix=path.suffix.lower()
    )
    if not columns:
        return ("error", f"CSV-Datei '{path.name}' enthält keine Daten.")
    encoding_warning = _encoding_warning(encoding)
    if encoding_warning is not None:
        warnings = [*warnings, encoding_warning]
    stats = ImportStats(skipped_rows=skipped, rows_above_header=leading, warnings=list(warnings))
    rows = _ref_rows(columns, data_rows)
    stats.processed_count = len(rows)
    return _describe(path.stem, columns, _header_row_number(leading), str(path), rows, stats)


def _ref_import_csv_configured(path: Path, header_row: int | None) -> Outcome:
    text, encoding = _ref_read_csv_text(path)
    raw_rows, delimiter_warning = _ref_csv_reader_rows(text, suffix=path.suffix.lower())

    warnings: list[str] = []
    if header_row is None:
        width = max((len(r) for r in raw_rows if not _is_blank(r)), default=0)
        columns = _generic_columns(width)
        body = raw_rows
        leading_skipped = 0
    else:
        if header_row >= len(raw_rows):
            return (
                "error",
                f"Header-Zeile {header_row + 1} liegt jenseits der Daten in "
                f"'{path.name}' (max. {len(raw_rows)} Zeilen).",
            )
        columns, warnings = _normalize_columns(list(raw_rows[header_row]))
        body = raw_rows[header_row + 1 :]
        leading_skipped = header_row

    if not columns:
        return ("error", f"CSV-Datei '{path.name}' enthält keine Daten.")

    while body and _is_blank(body[-1]):
        body = body[:-1]

    data_rows: list[list[Any]] = []
    skipped = leading_skipped
    for raw in body:
        if _is_blank(raw):
            skipped += 1
            continue
        data_rows.append(list(raw))

    if delimiter_warning is not None:
        warnings = [*warnings, delimiter_warning]
    encoding_warning = _encoding_warning(encoding)
    if encoding_warning is not None:
        warnings = [*warnings, encoding_warning]

    stats = ImportStats(
        skipped_rows=skipped, rows_above_header=leading_skipped, warnings=list(warnings)
    )
    rows = _ref_rows(columns, data_rows)
    stats.processed_count = len(rows)
    return _describe(path.stem, columns, _header_row_number(header_row), str(path), rows, stats)


def _ref_preview_csv(path: Path, max_rows: int = 20) -> Outcome:
    text, _enc = _ref_read_csv_text(path)
    rows, _delim_warning = _ref_csv_reader_rows(text, suffix=path.suffix.lower())
    raw_rows = [tuple(_coerce_value(c) for c in row) for row in rows[:max_rows]]
    detected, confidence = _detect_header_with_confidence(raw_rows)
    return (path.name, repr(tuple(raw_rows)), detected, confidence)


# ---------------------------------------------------------------------------
# Vergleichs-Helfer
# ---------------------------------------------------------------------------


def _describe(
    name: str,
    columns: list[str] | tuple[str, ...],
    header_row: int,
    source_file: str,
    rows: list[DatasetRow],
    stats: ImportStats,
) -> Outcome:
    """Vollständiges Ergebnis; Werte über `repr` – erfasst Typen und ist NaN-sicher."""
    return (
        "ok",
        name,
        tuple(columns),
        header_row,
        source_file,
        tuple((r.row_id, repr(r.values)) for r in rows),
        stats.skipped_rows,
        stats.rows_above_header,
        stats.processed_count,
        tuple(stats.warnings),
    )


def _consume(build: Any) -> Outcome:
    """Führt einen Import aus und verbraucht die Zeilen vollständig.

    Fachliche Fehler werden NUR beim Aufruf akzeptiert (wie in der Referenz) –
    ein Fehler erst beim Verbrauch würde hier als Ausnahme durchschlagen.
    """
    try:
        result = build()
    except DataImportError as exc:
        return ("error", str(exc))
    rows = list(result.rows)
    ds = result.dataset
    assert ds.source_sheet is None
    return _describe(ds.name, ds.columns, ds.header_row, ds.source_file, rows, result.stats)


def _new_import_csv(path: Path) -> Outcome:
    return _consume(lambda: ExcelImporter().import_file(path))


def _new_import_csv_configured(path: Path, header_row: int | None) -> Outcome:
    return _consume(lambda: ExcelImporter().import_file_configured(path, None, header_row))


def _new_preview_csv(path: Path, max_rows: int = 20) -> Outcome:
    preview = ExcelImporter().preview_csv(path, max_rows)
    return (preview.sheet_name, repr(preview.rows), preview.detected_header_row, preview.confidence)


def _is_clean(path: Path) -> bool:
    """Definition „saubere CSV" (Sprint 96 §2.5), mit dem Dialekt der Referenz."""
    text, _enc = _ref_read_csv_text(path)
    if any(ch in text for ch in SPLITLINES_ONLY_CHARS):
        return False
    sample = text[:8192]
    try:
        dialect: Any = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if path.suffix.lower() == ".tsv" else csv.excel
    reader = csv.reader(io.StringIO(text, newline=""), dialect=dialect)
    return not any("\n" in cell or "\r" in cell for row in reader for cell in row)


def _assert_all_paths_identical(path: Path) -> None:
    assert _new_import_csv(path) == _ref_import_csv(path), "Auto-Pfad"
    for header_row in (0, 2, 999, None):
        assert _new_import_csv_configured(path, header_row) == _ref_import_csv_configured(
            path, header_row
        ), f"konfiguriert, header_row={header_row}"
    assert _new_preview_csv(path) == _ref_preview_csv(path), "Vorschau"
    assert _new_preview_csv(path, 3) == _ref_preview_csv(path, 3), "Vorschau max_rows=3"


# ---------------------------------------------------------------------------
# Korpus
# ---------------------------------------------------------------------------


def _corpus() -> dict[str, bytes]:
    """Saubere CSV-Dateien (Name → Bytes); Name enthält die Endung."""
    basis = (
        "Konto;Betrag;Datum;Text\n"
        "4711;1234,56;2024-01-31;Miete\n"
        "4712;-17,5;31.12.2023;Büro\n"
        "4713;0;2024-02-29T08:15:00;Reise\n"
    )
    return {
        "komma.csv": b"Konto,Betrag,Text\n1,2.5,a\n2,3.5,b\n3,4.5,c\n",
        "semikolon.csv": basis.encode("utf-8"),
        "tab.csv": b"Konto\tBetrag\tText\n1\t2.5\ta\n2\t3.5\tb\n3\t4.5\tc\n",
        "pipe.csv": b"Konto|Betrag|Text\n1|2.5|a\n2|3.5|b\n3|4.5|c\n",
        "tab_ohne_erkennung.tsv": b"Spalte\nwert eins\nwert zwei\n",
        "komma_ohne_erkennung.csv": b"Spalte\nwert eins\nwert zwei\n",
        "utf8.csv": basis.encode("utf-8"),
        "utf8_bom.csv": b"\xef\xbb\xbf" + basis.encode("utf-8"),
        "utf8_bom_crlf.csv": b"\xef\xbb\xbf" + basis.replace("\n", "\r\n").encode("utf-8"),
        "nur_cr.csv": basis.replace("\n", "\r").encode("utf-8"),
        "cp1252_euro.csv": "Text;Betrag\n€ Gebühr;12,50\nÄnderung;3\n".encode("cp1252"),
        # 0x81 ist in cp1252 undefiniert → latin-1.
        "latin1.csv": b"Text;Wert\nKl\xe4ger\x81;1\nStra\xdfe;2\n",
        "leerzeilen_vorne_mitte_hinten.csv": (b"\n\n;;\nKonto;Betrag\n1;2\n\n;;\n3;4\n\n\n;\n"),
        "nur_trennzeichen.csv": b";;;\n;;;\n",
        "ungleich_lang.csv": b"a,b,c\n1\n1,2\n1,2,3,4,5\n,,\n6,7,8\n",
        "trenner_in_quotes.csv": b'Name;Text\n1;"a;b;c"\n2;"x;y"\n',
        "doppelte_quotes.csv": b'Name,Text\n1,"Er sagte ""Hallo"""\n2,"""quoted"""\n',
        "leer.csv": b"",
        "nur_leerzeilen.csv": b"\n\n\r\n\n",
        "nur_kopfzeile.csv": b"Konto;Betrag;Text\n",
        "nur_kopfzeile_ohne_umbruch.csv": b"Konto;Betrag;Text",
        "dezimalkomma.csv": b"Konto;Betrag\n1;1,5\n2;1.234,56\n3;-0,01\n4;1,2,3\n",
        "datumsstrings.csv": b"Datum,Zeit\n2024-01-31,08:15\n31.12.2023,23:59:59\n",
        "doppelte_spalten.csv": b"A;A;;B\n1;2;3;4\n",
        "grosse_zahlen.csv": b"A,B\n99999999999999999999,1e999\ninf,nan\n",
        "titelzeilen.csv": b"Bericht Q1\n\nKonto;Betrag\n1;2\n3;4\n",
        "kein_umbruch_am_ende.csv": b"A;B\n1;2\n3;4",
        "lange_datei.csv": (
            "Nr;Wert;Text\n" + "".join(f"{i};{i * 1.5};Zeile {i} – ä\n" for i in range(3000))
        ).encode("utf-8"),
    }


def _write_corpus(tmp_path: Path) -> list[Path]:
    paths = []
    for name, data in _corpus().items():
        path = tmp_path / name
        path.write_bytes(data)
        paths.append(path)
    return paths


_FUZZ_CELLS = (
    "",
    " ",
    "0",
    "42",
    "-7",
    "1,5",
    "2.5",
    "1e5",
    "1.234,56",
    "2024-01-31",
    "31.12.2023",
    "08:15",
    "Müller",
    "Straße",
    "€ 12",
    "a b",
    'Er sagte "Hallo"',
    "x;y",
    "x,y",
    "x|y",
    "x\ty",
    "99999999999999999999",
    "nan",
    "  Text  ",
)


def _fuzz_file(rng: random.Random) -> tuple[str, bytes]:
    """Eine zufällige, saubere CSV (keine Umbrüche in Feldern, keine Sonder-Trenner)."""
    delimiter = rng.choice(",;\t|")
    lineterminator = rng.choice(("\n", "\n", "\r\n", "\r"))
    n_cols = rng.randint(1, 6)
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter, lineterminator=lineterminator)
    lines: list[str] = []
    for line_no in range(rng.randint(0, 25)):
        roll = rng.random()
        if roll < 0.08:
            lines.append(lineterminator)  # Leerzeile
            continue
        if roll < 0.12:
            lines.append(delimiter * rng.randint(1, 4) + lineterminator)  # nur Trenner
            continue
        width = n_cols if rng.random() < 0.85 else rng.randint(1, n_cols + 2)
        if line_no == 0 and rng.random() < 0.7:
            cells = [f"Spalte{rng.choice('ABCÄ')}{i}" for i in range(width)]
        else:
            cells = [rng.choice(_FUZZ_CELLS) for _ in range(width)]
        buf.seek(0)
        buf.truncate()
        writer.writerow(cells)
        lines.append(buf.getvalue())
    text = "".join(lines)
    if text and rng.random() < 0.2:
        text = text[: -len(lineterminator)]  # letzte Zeile ohne Umbruch
    encoding = rng.choice(("utf-8", "utf-8", "utf-8-sig", "cp1252"))
    suffix = rng.choice((".csv", ".csv", ".tsv"))
    return suffix, text.encode(encoding)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCsvEquivalenceOracle:
    """Gestreamter Import == eingefrorene Referenz für saubere Dateien."""

    @pytest.mark.parametrize("path", TESTDATEN_CSV, ids=lambda p: p.name)
    def test_testdaten_csv(self, path: Path) -> None:
        if _is_clean(path):
            _assert_all_paths_identical(path)
            return
        # Nicht sauber (Zeilenumbruch in Anführungszeichen): einzige erlaubte
        # Abweichung ist der erhaltene Umbruch (Sprint 96 §2.4 Punkt 1).
        new = _new_import_csv(path)
        ref = _ref_import_csv(path)
        assert new != ref
        assert _strip_line_breaks(new) == ref

    def test_testdaten_korpus_vorhanden(self) -> None:
        assert [p.name for p in TESTDATEN_CSV if not p.is_file()] == []
        assert sorted(TESTDATEN_DIR.glob("*.csv")) == sorted(TESTDATEN_CSV)
        assert sum(_is_clean(p) for p in TESTDATEN_CSV) >= 4

    @pytest.mark.parametrize("name", sorted(_corpus()))
    def test_generierter_korpus(self, tmp_path: Path, name: str) -> None:
        path = tmp_path / name
        path.write_bytes(_corpus()[name])
        assert _is_clean(path)
        _assert_all_paths_identical(path)

    def test_seeded_fuzz_clean_files(self, tmp_path: Path) -> None:
        rng = random.Random(20261026)
        for i in range(300):
            suffix, data = _fuzz_file(rng)
            path = tmp_path / f"fuzz_{i:03d}{suffix}"
            path.write_bytes(data)
            assert _is_clean(path), data
            assert _new_import_csv(path) == _ref_import_csv(path), data
            header_row = rng.choice((None, 0, 1, 2, 40))
            assert _new_import_csv_configured(path, header_row) == _ref_import_csv_configured(
                path, header_row
            ), (header_row, data)
            assert _new_preview_csv(path) == _ref_preview_csv(path), data


def _strip_line_breaks(outcome: Outcome) -> Outcome:
    """Entfernt CR/LF aus den Zellwerten (Zeilen-Tupel an Position 5)."""
    rows = tuple(
        (row_id, values_repr.replace("\\r", "").replace("\\n", ""))
        for row_id, values_repr in outcome[5]
    )
    return (*outcome[:5], rows, *outcome[6:])


def _rows(path: Path) -> list[DatasetRow]:
    return list(ExcelImporter().import_file(path).rows)


@pytest.mark.integration
class TestQuotedNewlinePreserved:
    """Zeilenumbrüche in Anführungszeichen bleiben unverändert erhalten."""

    def test_lf_inside_quotes_kept(self, tmp_path: Path) -> None:
        path = tmp_path / "lf.csv"
        path.write_bytes(b'Nr;Text\n1;"Zeile eins\nZeile zwei"\n2;x\n')
        rows = _rows(path)
        assert rows[0].values["Text"] == "Zeile eins\nZeile zwei"
        assert len(rows) == 2

    def test_crlf_inside_quotes_kept(self, tmp_path: Path) -> None:
        path = tmp_path / "crlf.csv"
        path.write_bytes(b'Nr,Text\r\n1,"Zeile eins\r\nZeile zwei"\r\n2,x\r\n3,y\r\n')
        rows = _rows(path)
        assert rows[0].values["Text"] == "Zeile eins\r\nZeile zwei"
        assert [r.values["Nr"] for r in rows] == [1, 2, 3]

    def test_preview_shows_multiline_field_as_one_cell(self, tmp_path: Path) -> None:
        path = tmp_path / "vorschau.csv"
        path.write_bytes(b'Nr;Text\n1;"Zeile eins\nZeile zwei"\n2;x\n')
        preview = ExcelImporter().preview_csv(path)
        assert preview.rows == (("Nr", "Text"), (1, "Zeile eins\nZeile zwei"), (2, "x"))

    def test_record_count_with_multiline_fields(self, tmp_path: Path) -> None:
        path = tmp_path / "drei.csv"
        # Bytes statt `write_text`: unter Windows würde `\n` sonst zu `\r\n`.
        path.write_bytes(
            b'Nr;Buchungstext;Betrag\n1;Miete;100\n2;"Teil 1\nTeil 2\nTeil 3";200\n3;Reise;300\n'
        )
        result = ExcelImporter().import_file(path)
        rows = list(result.rows)
        assert len(rows) == 3
        assert rows[1].values == {"Nr": 2, "Buchungstext": "Teil 1\nTeil 2\nTeil 3", "Betrag": 200}
        assert rows[2].values == {"Nr": 3, "Buchungstext": "Reise", "Betrag": 300}
        assert result.stats.skipped_rows == 0


@pytest.mark.integration
class TestNoSplitOnUnicodeLineSeparators:
    """`\\v`, `\\f`, `\\x1c`–`\\x1e`, `\\x85`, U+2028/2029 beenden keinen Datensatz."""

    @pytest.mark.parametrize("char", SPLITLINES_ONLY_CHARS, ids=lambda c: f"U+{ord(c):04X}")
    def test_char_bleibt_im_wert(self, tmp_path: Path, char: str) -> None:
        path = tmp_path / "sonderzeichen.csv"
        path.write_text(f"Nr;Text\n1;a{char}b\n2;c\n3;d\n", encoding="utf-8")
        rows = _rows(path)
        assert [r.values["Nr"] for r in rows] == [1, 2, 3]
        assert rows[0].values["Text"] == f"a{char}b"


@pytest.mark.integration
class TestEncodingDecisionUnchanged:
    """Encoding-Wahl wie bisher, obwohl die Datei nur noch blockweise gelesen wird."""

    @pytest.mark.parametrize("block_size", [7, 64 * 1024])
    def test_late_invalid_utf8_byte_falls_back_like_today(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, block_size: int
    ) -> None:
        monkeypatch.setattr(importer_module, "_CSV_SCAN_BLOCK_SIZE", block_size)
        body = "".join(f"{i};Grüße aus Köln {i}\n" for i in range(5000))
        path = tmp_path / "spaet.csv"
        path.write_bytes(("Nr;Text\n" + body).encode("utf-8") + b"5000;Preis \x80 5\n")
        assert _new_import_csv(path) == _ref_import_csv(path)
        warnings = ExcelImporter().import_file(path).stats.warnings
        assert warnings == [_encoding_warning("cp1252")]

    @pytest.mark.parametrize("block_size", [1, 2, 7, 64 * 1024])
    def test_multibyte_char_across_block_boundary_stays_utf8(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, block_size: int
    ) -> None:
        monkeypatch.setattr(importer_module, "_CSV_SCAN_BLOCK_SIZE", block_size)
        path = tmp_path / "grenze.csv"
        path.write_text("Text;Wert\nÄ€😀ü;1\nßß;2\n", encoding="utf-8")
        assert _new_import_csv(path) == _ref_import_csv(path)
        assert ExcelImporter().import_file(path).stats.warnings == []

    def test_bom_detected(self, tmp_path: Path) -> None:
        path = tmp_path / "bom.csv"
        path.write_bytes(b"\xef\xbb\xbfKonto;Text\n1;\xc3\xa4\n")
        outcome = _new_import_csv(path)
        assert outcome == _ref_import_csv(path)
        assert outcome[2] == ("Konto", "Text")  # kein BOM-Präfix in der ersten Spalte
        assert outcome[-1] == ()

    def test_cp1252_before_latin1(self, tmp_path: Path) -> None:
        path = tmp_path / "euro.csv"
        path.write_bytes("Text;Betrag\n€ Gebühr;12,50\n".encode("cp1252"))
        outcome = _new_import_csv(path)
        assert outcome == _ref_import_csv(path)
        assert "€ Gebühr" in outcome[5][0][1]
        assert outcome[-1] == (_encoding_warning("cp1252"),)


class _CountingTextFile:
    """Proxy um ein Text-Dateiobjekt: zählt gelesene Zeilen, merkt sich `closed`."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.lines_read = 0

    def __iter__(self) -> Iterator[str]:
        return self

    def __next__(self) -> str:
        line: str = next(self._inner)
        self.lines_read += 1
        return line

    def __enter__(self) -> _CountingTextFile:
        return self

    def __exit__(self, *exc: object) -> None:
        self._inner.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@pytest.fixture
def opened_text_files(monkeypatch: pytest.MonkeyPatch) -> list[_CountingTextFile]:
    """Protokolliert alle Text-Dateien, die der Importer öffnet."""
    handles: list[_CountingTextFile] = []

    def _tracking_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        # Der Importer schließt das Handle selbst – genau das prüfen die Tests.
        handle = builtins.open(file, mode, *args, **kwargs)  # noqa: SIM115
        if "b" in mode:
            return handle
        proxy = _CountingTextFile(handle)
        handles.append(proxy)
        return proxy

    monkeypatch.setattr(importer_module, "open", _tracking_open, raising=False)
    return handles


def _write_big_csv(path: Path, n_rows: int) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("Nr;Betrag;Text;Datum\n")
        for i in range(n_rows):
            fh.write(f"{i};{i * 1.25:.2f};Buchung {i} – Köln;2024-01-{i % 28 + 1:02d}\n")


def _import_peak_bytes(path: Path) -> int:
    tracemalloc.start()
    try:
        result = ExcelImporter().import_file(path)
        for _row in result.rows:
            pass
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak


@pytest.mark.integration
@pytest.mark.slow
class TestStreamingMemory:
    def test_peak_memory_independent_of_file_size(self, tmp_path: Path) -> None:
        small, large = tmp_path / "klein.csv", tmp_path / "gross.csv"
        _write_big_csv(small, 20_000)
        _write_big_csv(large, 200_000)
        peak_small = _import_peak_bytes(small)
        peak_large = _import_peak_bytes(large)
        assert peak_large <= 1.5 * peak_small, (peak_small, peak_large)

    def test_file_closed_after_cancel(
        self, tmp_path: Path, opened_text_files: list[_CountingTextFile]
    ) -> None:
        path = tmp_path / "abbruch.csv"
        _write_big_csv(path, 10_000)
        token = CancellationToken()
        result = ExcelImporter(cancellation=token).import_file(path)
        consumed: list[DatasetRow] = []

        def _consume_and_cancel() -> None:
            for row in result.rows:
                consumed.append(row)
                if len(consumed) == 1500:
                    token.set()

        with pytest.raises(OperationCancelled):
            _consume_and_cancel()
        assert len(consumed) < 10_000
        assert opened_text_files
        assert all(handle.closed for handle in opened_text_files)
        # Unter Windows schlägt das bei offener Datei fehl (Sperre).
        path.rename(tmp_path / "abbruch_umbenannt.csv")

    def test_file_closed_when_rows_iterator_closed(
        self, tmp_path: Path, opened_text_files: list[_CountingTextFile]
    ) -> None:
        path = tmp_path / "close.csv"
        _write_big_csv(path, 3000)
        rows = ExcelImporter().import_file(path).rows
        next(rows)
        assert not all(handle.closed for handle in opened_text_files)
        rows.close()  # type: ignore[attr-defined]
        assert all(handle.closed for handle in opened_text_files)

    def test_unconsumed_import_holds_no_open_file(
        self, tmp_path: Path, opened_text_files: list[_CountingTextFile]
    ) -> None:
        path = tmp_path / "offen.csv"
        _write_big_csv(path, 100)
        ExcelImporter().import_file_configured(path, None, None)
        ExcelImporter().preview_csv(path)
        assert opened_text_files
        assert all(handle.closed for handle in opened_text_files)

    def test_row_limit_enforced_while_reading(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        opened_text_files: list[_CountingTextFile],
    ) -> None:
        path = tmp_path / "limit.csv"
        _write_big_csv(path, 10_000)
        monkeypatch.setattr(importer_module, "MAX_IMPORT_ROWS", 50)
        result = ExcelImporter().import_file(path)
        with pytest.raises(DataImportError, match="Sicherheitslimit"):
            list(result.rows)
        data_pass = opened_text_files[-1]
        assert data_pass.closed
        # Der Reader holt intern höchstens ein paar Zeilen voraus – weit weg von 10 000.
        assert data_pass.lines_read < 100

    def test_row_limit_counts_blank_lines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "leer.csv"
        path.write_text("A;B\n1;2\n" + "\n" * 500 + "3;4\n", encoding="utf-8")
        monkeypatch.setattr(importer_module, "MAX_IMPORT_ROWS", 100)
        result = ExcelImporter().import_file(path)
        with pytest.raises(DataImportError, match="Sicherheitslimit"):
            list(result.rows)
