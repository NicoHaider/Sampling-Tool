"""Excel-/CSV-Importer mit Streaming-Read und Header-Detection.

Die Klasse `ExcelImporter` ist der einzige Eintrittspunkt für den
Import-Pfad. Sie produziert ein `Dataset` (frozen Dataclass aus
`core.models`) – der Aufrufer setzt anschließend `engagement_id` und
übergibt das Dataset an `DatasetRepo.create()`.

Architektur-Anker:
- **Excel-Engine**: seit Sprint 10.2 `python-calamine` (Rust-basiert,
  Streaming-Iterator, 10–30× schneller als openpyxl bei reinen Reads,
  signifikant niedrigerer RAM-Footprint). openpyxl wird im Import-Pfad
  NICHT mehr verwendet – bleibt aber für alle Exporter (Writes).
- **Header-Detection**: erste „dichte" Zeile (überwiegend Strings) gilt als
  Header, Inhalts-Zeilen folgen. Fallback: erste nicht-leere Zeile.
- **Encoding-Detection** für CSV: utf-8 → utf-8-sig → cp1252 → latin-1.
- **Native Python-Typen** im Output – kein numpy/pandas-Typ verlässt diese
  Datei.
- **Progress-Callback**: `progress(current, total)` wird in regelmäßigen
  Abständen während des Reads aufgerufen.

**Sprint 11.3 – Streaming-Import**: `ImportResult.rows` ist seit
diesem Sprint ein **einmalig konsumierbarer Iterator[DatasetRow]**.
Rows werden direkt von der Excel-Engine durch die Coercion in den
DB-Insert gepumpt, ohne komplette Materialisierung.
`ImportResult.stats` füllt sich während der Iteration (skipped,
warnings, processed_count) – Werte sind erst nach voller
Konsumierung aussagekräftig. Der typische Aufrufer ist
`DatasetRepo.create(dataset, result.rows)`, der den Generator
einmalig durchgeht und am Ende den `row_count` aufgrund der echten
Zahl korrigiert.
"""

from __future__ import annotations

import codecs
import csv
import itertools
import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time
from io import TextIOWrapper
from pathlib import Path
from typing import Any, Final, Literal

from python_calamine import CalamineSheet, CalamineWorkbook

from sampling_tool.config import (
    MAX_IMPORT_CELL_LENGTH,
    MAX_IMPORT_ROWS,
    SUPPORTED_CSV_SUFFIXES,
    SUPPORTED_EXCEL_SUFFIXES,
)
from sampling_tool.core.cancellation import CancellationToken
from sampling_tool.core.models import Dataset, DatasetRow

HeaderConfidence = Literal["high", "low", "ambiguous"]

ProgressCallback = Callable[[int, int], None]

# Alle Encodings, die wir bei CSV der Reihe nach probieren. Sprint 49 / A-005:
# cp1252 VOR latin-1 – latin-1 dekodiert jedes Byte (auch die, die cp1252
# als Sonderzeichen wie „€" definiert), wäre also sonst immer gewählt und
# cp1252 nie erreichbar.
_CSV_ENCODINGS: Final[tuple[str, ...]] = ("utf-8", "utf-8-sig", "cp1252", "latin-1")

# Sprint 96: Blockgröße des Encoding-Vorlaufs. Klein, damit der Vorlauf den
# Speicher-Peak nicht mit der Dateigröße wachsen lässt.
_CSV_SCAN_BLOCK_SIZE: Final[int] = 64 * 1024

# Zeichen, die `csv.Sniffer` sieht – unverändert seit vor dem Streaming-Umbau.
_CSV_SNIFF_CHARS: Final[int] = 8192

_UTF8_BOM: Final[bytes] = b"\xef\xbb\xbf"

# Sprint 85 / E3: Meldung nur bei einem Rückfall – UTF-8 mit BOM ist UTF-8 und
# kein Grund für ein Modal. Klartext statt Codec-Namen (Zielgruppe ohne
# Technik-Hintergrund).
_FALLBACK_ENCODING_NAMES: Final[dict[str, str]] = {
    "cp1252": "Windows-Zeichensatz",
    "latin-1": "westeuropäischen Zeichensatz (ISO 8859-1)",
}

# Schwellwert für Header-Detection: ≥ Anteil String-Zellen einer Zeile.
_HEADER_STRING_RATIO: Final[float] = 0.5

# Sprint 49 / N-006: signed-64-Bit-Grenzen für die Ganzzahl-Coercion – orjson
# wirft `TypeError` bei Ints außerhalb dieses Bereichs, und zwar VOR dem
# `default`-Callback (der Wert ist ja ein "unterstützter" Typ, nur zu groß).
_INT64_MIN: Final[int] = -(2**63)
_INT64_MAX: Final[int] = 2**63 - 1

# Progress-Frequenz beim Streaming-Read.
_PROGRESS_INTERVAL: Final[int] = 1000


# ---------------------------------------------------------------------------
# Result-Container
# ---------------------------------------------------------------------------


@dataclass
class ImportStats:
    """Mutable Statistik-Container für den Streaming-Import.

    Wird vom Generator während der Iteration befüllt – Werte sind erst
    nach vollständigem Verbrauch (z. B. via `DatasetRepo.create`)
    endgültig.

    ``skipped_rows`` zählt alle nicht importierten Zeilen: die Zeilen
    oberhalb der Kopfzeile plus die Leerzeilen im Datenteil.
    ``rows_above_header`` ist eine TEILMENGE davon – bewusst in
    ``skipped_rows`` mitgezählt, damit die Row-Limit-Bilanz
    (`_enforce_row_limit`) unverändert bleibt. ``blank_data_rows`` ist der
    Rest (echte Leerzeilen im Datenteil).
    """

    skipped_rows: int = 0
    warnings: list[str] = field(default_factory=list)
    processed_count: int = 0
    rows_above_header: int = 0

    @property
    def blank_data_rows(self) -> int:
        """Leerzeilen im Datenteil (ohne die Zeilen oberhalb der Kopfzeile)."""
        return self.skipped_rows - self.rows_above_header


@dataclass(frozen=True, slots=True)
class SheetInfo:
    """Metadaten eines Excel-Sheets für die UI-Multi-Sheet-Auswahl.

    `row_count` / `column_count` kommen direkt aus Calamine
    (`total_height` / `total_width`) und enthalten potentielle Leerzeilen
    / Leerspalten. Reine Anzeige-Daten – kein Daten-Lesepfad.
    """

    name: str
    row_count: int
    column_count: int


@dataclass(frozen=True, slots=True)
class SheetPreview:
    """Vorschau-Daten für den `ImportOptionsDialog`.

    `rows` enthält die rohen 2D-Zellen der ersten N Zeilen – inklusive
    Leerzeilen und ohne Header-Interpretation, damit der User im Dialog
    selbst entscheidet wo die Header-Zeile liegt. Werte sind durch
    `_coerce_value` gegangen (Calamine-Eigenheiten normalisiert).

    `confidence`-Semantik:
    - ``high``: Header in Zeile 0 erkannt + sieht wie ein Header aus
      (≥50 % String-Zellen). Dialog wird NICHT angezeigt, wenn zusätzlich
      nur ein Sheet vorhanden ist.
    - ``low``: Header in Zeile > 0 erkannt (z. B. mit Metadaten-Zeilen
      darüber). Dialog wird angezeigt, Header-Zeile preselected.
    - ``ambiguous``: keine Zeile sah wie ein Header aus, oder das Sheet
      ist leer. Dialog wird angezeigt, User muss manuell wählen.
    """

    sheet_name: str
    rows: tuple[tuple[Any, ...], ...]
    detected_header_row: int | None
    confidence: HeaderConfidence


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Rückgabe-Wert von `ExcelImporter.import_file`.

    Sprint-11.3: `rows` ist ein einmalig konsumierbarer Iterator.
    Sprint-11.5: keine Compat-Properties mehr – Caller lesen
    `result.stats.skipped_rows` und `result.stats.warnings` direkt.
    `stats` füllt sich während der Iteration – Werte sind erst nach
    vollem Generator-Verbrauch (typisch via `DatasetRepo.create`)
    endgültig.
    """

    dataset: Dataset
    rows: Iterator[DatasetRow]
    stats: ImportStats


# ---------------------------------------------------------------------------
# Fehler
# ---------------------------------------------------------------------------


# `ImportError` ist Builtin und darf nicht verschattet werden – daher das
# Domain-Präfix.
class DataImportError(ValueError):
    """Fachlicher Importfehler (deutsche Endnutzer-Message)."""


# ---------------------------------------------------------------------------
# Ressourcengrenzen (Sprint 48 / S2.3b, S-003)
# ---------------------------------------------------------------------------


def _enforce_row_limit(row_count: int) -> None:
    """Bricht den Import ab, sobald die Hard-Zeilengrenze überschritten ist.

    Läuft im Streaming-Generator selbst – ein Backstop zusätzlich zum
    (billigeren, aber überspringbaren) Main-Thread-Preflight in
    `io/import_preflight.py`. Kürzt nichts, bricht nur ab.

    ``row_count`` muss ALLE physisch durchlaufenen Zeilen zählen, auch
    übersprungene Leerzeilen (``stats.processed_count + stats.skipped_rows``
    in `_configured_row_generator`/`_excel_row_generator`) – sonst bindet der
    Cap nicht die Gesamtzahl der gescannten Zeilen, sondern nur die
    Nicht-Leerzeilen, und eine präparierte Datei mit unbegrenzt vielen
    Leerzeilen würde den `continue`-Zweig endlos durchlaufen, ohne je diese
    Prüfung zu erreichen.

    Für Excel (`_excel_row_generator`/`_configured_row_generator`) und seit
    Sprint 96 auch für CSV (`_csv_row_generator`, `_csv_width_pass`) ist das ein
    echter Streaming-Backstop: Zeilen werden einzeln gelesen, der Abbruch
    verhindert also tatsächlich weiteres Lesen. Bei CSV zählen auch Leerzeilen,
    die erst am Dateiende als „abschließend" (nicht übersprungen) feststehen.
    """
    if row_count > MAX_IMPORT_ROWS:
        raise DataImportError(
            f"Import-Sicherheitslimit erreicht: mehr als {MAX_IMPORT_ROWS:,} Zeilen."
        )


def _enforce_cell_length_limit(raw: list[Any] | tuple[Any, ...]) -> None:
    """Bricht ab, wenn ein roher Zellwert die Hard-Längengrenze überschreitet.

    Prüft den Rohwert VOR `_coerce_value` – reine Zeichenlänge, keine
    Interpretation. Nur `str`-Zellen können diese Grenze reißen.
    """
    for value in raw:
        if isinstance(value, str) and len(value) > MAX_IMPORT_CELL_LENGTH:
            raise DataImportError(
                f"Import-Sicherheitslimit erreicht: Zellwert länger als "
                f"{MAX_IMPORT_CELL_LENGTH:,} Zeichen."
            )


# ---------------------------------------------------------------------------
# Importer
# ---------------------------------------------------------------------------


class ExcelImporter:
    """Liest .xlsx/.xlsm/.csv und gibt ein `Dataset` zurück.

    Stateless im fachlichen Sinn – die Instanz hält nur den Progress-Callback.
    Die gleiche Instanz darf für mehrere Imports wiederverwendet werden.
    """

    def __init__(
        self,
        progress: ProgressCallback | None = None,
        cancellation: CancellationToken | None = None,
    ) -> None:
        self.progress = progress
        self.cancellation = cancellation

    def _check_cancel(self) -> None:
        """Wirft `OperationCancelled`, wenn das Token gesetzt ist.

        Im Streaming-Pfad alle `_PROGRESS_INTERVAL` Rows aufgerufen
        (Overhead ist vernachlässigbar, aber jede Row prüfen wäre zu
        viel).
        """
        if self.cancellation is not None:
            self.cancellation.raise_if_cancelled()

    # ---- Public API -----------------------------------------------------

    def import_file(self, path: Path, sheet_name: str | None = None) -> ImportResult:
        """Importiert die angegebene Datei und liefert ein `ImportResult`."""
        if not path.exists():
            raise DataImportError(f"Datei nicht gefunden: {path}")

        suffix = path.suffix.lower()
        if suffix in SUPPORTED_CSV_SUFFIXES:
            return self._import_csv(path)
        if suffix in SUPPORTED_EXCEL_SUFFIXES:
            return self._import_excel(path, sheet_name)
        raise DataImportError(
            f"Dateityp '{suffix}' wird nicht unterstützt. "
            f"Erlaubt: {', '.join(SUPPORTED_EXCEL_SUFFIXES + SUPPORTED_CSV_SUFFIXES)}"
        )

    # ---- Sprint 16: Sheet-/Header-Auswahl-Dialog-API --------------------

    def list_sheets(self, path: Path) -> list[SheetInfo]:
        """Liefert Metadaten aller Sheets als `SheetInfo`-Liste.

        Lädt die Sheets nicht – nur Namen + Dimensionen aus Calamine.
        Wird vom `ImportOptionsDialog` für das Sheet-Dropdown genutzt.
        """
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EXCEL_SUFFIXES:
            raise DataImportError(
                f"Sheet-Liste nur für Excel-Dateien verfügbar (Datei: {path.name})."
            )
        wb = CalamineWorkbook.from_path(str(path))
        infos: list[SheetInfo] = []
        for name in wb.sheet_names:
            sheet = wb.get_sheet_by_name(name)
            # Calamine: `total_height` ist `end_row - start_row` (Range-Größe),
            # `height` ist die echte Anzahl Zeilen. Für die UI-Anzeige wollen
            # wir die echte Zeilenanzahl inkl. Header.
            infos.append(
                SheetInfo(
                    name=name,
                    row_count=int(sheet.height),
                    column_count=int(sheet.width),
                )
            )
        return infos

    def preview_sheet(self, path: Path, sheet_name: str, max_rows: int = 20) -> SheetPreview:
        """Liefert die ersten ``max_rows`` Zeilen + Header-Heuristik.

        Im Gegensatz zu `preview()` werden die Rohzellen ZURÜCKGEGEBEN
        OHNE Header-Interpretation – der Dialog zeigt sie als 2D-Tabelle
        und der User markiert die Header-Zeile selbst.
        """
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EXCEL_SUFFIXES:
            raise DataImportError(
                f"Sheet-Vorschau nur für Excel-Dateien verfügbar (Datei: {path.name})."
            )
        if max_rows < 0:
            raise DataImportError("preview_sheet(): max_rows muss >= 0 sein.")

        wb = CalamineWorkbook.from_path(str(path))
        sheet = _select_sheet(wb, sheet_name)

        raw_rows: list[tuple[Any, ...]] = []
        if sheet.start is not None:
            for raw in sheet.iter_rows():
                raw_rows.append(tuple(_coerce_value(c) for c in raw))
                if len(raw_rows) >= max_rows:
                    break

        detected, confidence = _detect_header_with_confidence(raw_rows)
        return SheetPreview(
            sheet_name=sheet_name,
            rows=tuple(raw_rows),
            detected_header_row=detected,
            confidence=confidence,
        )

    def preview_csv(self, path: Path, max_rows: int = 20) -> SheetPreview:
        """Liefert die ersten ``max_rows`` Roh-Zeilen einer CSV + Header-Heuristik.

        Pendant zu `preview_sheet` für den CSV-Pfad (Sprint 29): rohe 2D-
        Zellen OHNE Header-Interpretation, damit der Dialog sie als Tabelle
        zeigen kann und der User die Kopfzeile selbst markiert. Werte gehen
        durch `_coerce_value` (gleiche Coercion wie der Import).
        """
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_CSV_SUFFIXES:
            raise DataImportError(
                f"CSV-Vorschau nur für CSV-Dateien verfügbar (Datei: {path.name})."
            )
        if max_rows < 0:
            raise DataImportError("preview_csv(): max_rows muss >= 0 sein.")

        source = _open_csv_source(path, suffix)
        with source.open() as fh:
            rows = list(itertools.islice(source.reader(fh), max_rows))
        raw_rows = [tuple(_coerce_value(c) for c in row) for row in rows]
        detected, confidence = _detect_header_with_confidence(raw_rows)
        return SheetPreview(
            sheet_name=path.name,
            rows=tuple(raw_rows),
            detected_header_row=detected,
            confidence=confidence,
        )

    def requires_options_dialog(self, path: Path) -> bool:
        """True, wenn der `ImportOptionsDialog` vor dem Import erscheinen soll.

        - **Excel**: mehr als ein Blatt ODER Header-Auto-Erkennung unsicher
          (``confidence != "high"``).
        - **CSV**: Header-Auto-Erkennung unsicher.

        Genau ein Blatt + sauber erkannte Kopfzeile (bzw. saubere CSV) ⇒
        ``False`` – der lautlose Direkt-Import bleibt unverändert. Andere
        Dateitypen ⇒ ``False`` (kein Dialog).
        """
        suffix = path.suffix.lower()
        if suffix in SUPPORTED_CSV_SUFFIXES:
            return self.preview_csv(path).confidence != "high"
        if suffix in SUPPORTED_EXCEL_SUFFIXES:
            sheets = self.list_sheets(path)
            if not sheets:
                return False
            if len(sheets) > 1:
                return True
            return self.preview_sheet(path, sheets[0].name).confidence != "high"
        return False

    def import_file_configured(
        self,
        path: Path,
        sheet_name: str | None,
        header_row: int | None,
    ) -> ImportResult:
        """Import mit explizit gewähltem Sheet + Kopfzeile (User-Override aus dem Dialog).

        ``header_row`` ist 0-basiert; ``None`` bedeutet **„keine Kopfzeile"** –
        dann werden generische Spaltennamen (``Spalte 1, Spalte 2, …``)
        vergeben und ALLE (nicht-leeren) Zeilen sind Daten. Ist eine
        Kopfzeile gesetzt, zählen die Zeilen davor als ``skipped_rows`` (und
        zusätzlich als ``rows_above_header``), die Kopfzeile definiert die
        Spalten, Daten beginnen in der Folgezeile.
        Skippt die Auto-Detection bewusst.

        Sprint 29 – gilt für Excel UND CSV. Bei CSV wird ``sheet_name``
        ignoriert (CSV hat keine Tabellenblätter). Die Coercion/Werte-Logik
        bleibt unverändert: Header-/Blatt-Wahl ändert nur die Auswahl der
        Rohzeilen.
        """
        if header_row is not None and header_row < 0:
            raise DataImportError(f"Header-Zeile muss >= 0 sein (war: {header_row}).")

        suffix = path.suffix.lower()
        if suffix in SUPPORTED_CSV_SUFFIXES:
            return self._import_csv_configured(path, header_row)
        if suffix in SUPPORTED_EXCEL_SUFFIXES:
            return self._import_excel_configured(path, sheet_name, header_row)
        raise DataImportError(
            f"Dateityp '{suffix}' wird nicht unterstützt. "
            f"Erlaubt: {', '.join(SUPPORTED_EXCEL_SUFFIXES + SUPPORTED_CSV_SUFFIXES)}"
        )

    def _import_excel_configured(
        self,
        path: Path,
        sheet_name: str | None,
        header_row: int | None,
    ) -> ImportResult:
        wb = CalamineWorkbook.from_path(str(path))
        sheet = _select_sheet(wb, sheet_name)
        if sheet.start is None:
            raise DataImportError(f"Sheet '{sheet_name or 'Standard'}' in '{path.name}' ist leer.")
        read_sheet = _read_sheet_name(wb, sheet_name)
        name = _dataset_name(path, read_sheet, wb)

        if header_row is None:
            # „keine Kopfzeile": generische Spaltennamen aus der Blattbreite,
            # alle Zeilen sind Daten (skip_rows=0).
            columns = _generic_columns(int(sheet.width))
            stats = ImportStats()
            total_estimate = max(0, int(sheet.total_height))
            dataset = Dataset(
                name=name,
                columns=tuple(columns),
                row_count=total_estimate,
                source_file=str(path),
                source_sheet=read_sheet,
                header_row=_header_row_number(None),
            )
            rows_iter = self._configured_row_generator(
                sheet, columns, stats, total_estimate, skip_rows=0
            )
            return ImportResult(dataset=dataset, rows=rows_iter, stats=stats)

        header_raw, leading_skipped = _read_header_row(sheet, header_row)
        if header_raw is None:
            # `height` ist die echte Zeilenzahl (was `iter_rows` liefert);
            # `total_height` wäre die Range-Größe und damit irreführend.
            raise DataImportError(
                f"Header-Zeile {header_row + 1} liegt jenseits der Daten in Sheet "
                f"'{sheet_name or 'Standard'}' (max. {int(sheet.height)} Zeilen)."
            )

        columns, header_warnings = _normalize_columns(header_raw)
        stats = ImportStats(
            skipped_rows=leading_skipped,
            rows_above_header=leading_skipped,
            warnings=list(header_warnings),
        )
        total_estimate = max(0, int(sheet.total_height) - header_row - 1)
        dataset = Dataset(
            name=name,
            columns=tuple(columns),
            row_count=max(0, total_estimate),
            source_file=str(path),
            source_sheet=read_sheet,
            header_row=_header_row_number(header_row),
        )
        rows_iter = self._configured_row_generator(
            sheet, columns, stats, total_estimate, skip_rows=header_row + 1
        )
        return ImportResult(dataset=dataset, rows=rows_iter, stats=stats)

    def _import_csv_configured(self, path: Path, header_row: int | None) -> ImportResult:
        """CSV-Import mit explizit gewählter Kopfzeile bzw. „keine Kopfzeile".

        Spiegelt `_import_csv`, ersetzt aber die Auto-Header-Erkennung durch
        die explizite Wahl. Nutzt denselben `_csv_row_generator` (gleiche
        Coercion) – nur die Auswahl der Rohzeilen unterscheidet sich.
        """
        source = _open_csv_source(path, path.suffix.lower())

        warnings: list[str] = []
        if header_row is None:
            columns = _generic_columns(self._csv_width_pass(source))
            skip_rows = 0
            leading_skipped = 0
        else:
            header_raw, rows_seen = _csv_row_at(source, header_row)
            if header_raw is None:
                raise DataImportError(
                    f"Header-Zeile {header_row + 1} liegt jenseits der Daten in "
                    f"'{path.name}' (max. {rows_seen} Zeilen)."
                )
            columns, warnings = _normalize_columns(header_raw)
            skip_rows = header_row + 1
            leading_skipped = header_row

        if not columns:
            raise DataImportError(f"CSV-Datei '{path.name}' enthält keine Daten.")

        stats = ImportStats(
            skipped_rows=leading_skipped,
            rows_above_header=leading_skipped,
            warnings=[*warnings, *_csv_source_warnings(source)],
        )
        total_estimate = max(0, source.line_estimate - skip_rows)
        dataset = Dataset(
            name=path.stem,
            columns=tuple(columns),
            row_count=total_estimate,
            source_file=str(path),
            header_row=_header_row_number(header_row),
        )
        rows_iter = self._csv_row_generator(source, columns, stats, total_estimate, skip_rows)
        return ImportResult(dataset=dataset, rows=rows_iter, stats=stats)

    def _csv_width_pass(self, source: _CsvSource) -> int:
        """Eigener Parse-Durchlauf für „keine Kopfzeile": breiteste nicht-leere Zeile.

        Die Breite muss vor dem ersten Datensatz feststehen; gespeichert wird
        nichts. Leerzeilen mit Trennern (',,' → drei leere Felder) blähen die
        Spaltenzahl nicht auf.
        """
        width = 0
        with source.open() as fh:
            for count, raw in enumerate(source.reader(fh), start=1):
                _enforce_row_limit(count)
                if count % _PROGRESS_INTERVAL == 0:
                    self._check_cancel()
                if not _is_blank(raw):
                    width = max(width, len(raw))
        return width

    def _configured_row_generator(
        self,
        sheet: CalamineSheet,
        columns: list[str],
        stats: ImportStats,
        total_estimate: int,
        skip_rows: int,
    ) -> Iterator[DatasetRow]:
        """Generator: überspringt ``skip_rows`` Zeilen, yieldet dann Daten-Rows.

        ``skip_rows`` ist ``header_row + 1`` (Kopfzeile + alles davor) bzw.
        ``0`` im „keine Kopfzeile"-Fall.
        """
        # Sprint 17: Cancel-Check vor dem ersten Read.
        self._check_cancel()
        rows_iter: Iterator[list[Any]] = iter(sheet.iter_rows())
        for _ in range(skip_rows):
            try:
                next(rows_iter)
            except StopIteration:
                return

        next_row_id = 1
        for raw in rows_iter:
            if _is_blank(raw):
                stats.skipped_rows += 1
                continue
            _enforce_cell_length_limit(raw)
            values = {
                col: _coerce_value(raw[i] if i < len(raw) else None)
                for i, col in enumerate(columns)
            }
            row = DatasetRow(row_id=next_row_id, values=values)
            next_row_id += 1
            stats.processed_count += 1
            # Zählt Skipped-Rows mit – sonst wäre eine XLSX mit unbegrenzt
            # vielen Leerzeilen nie durch die Hard-Grenze gestoppt (der
            # `continue` oben läuft am Limit-Check vorbei).
            _enforce_row_limit(stats.processed_count + stats.skipped_rows)
            if stats.processed_count % _PROGRESS_INTERVAL == 0:
                self._check_cancel()
                if self.progress is not None:
                    self.progress(stats.processed_count, max(total_estimate, stats.processed_count))
            yield row

        if self.progress is not None:
            self.progress(stats.processed_count, stats.processed_count)

    # ---- Excel ----------------------------------------------------------

    def _import_excel(self, path: Path, sheet_name: str | None) -> ImportResult:
        wb = CalamineWorkbook.from_path(str(path))
        sheet = _select_sheet(wb, sheet_name)
        columns, header_skipped, header_warnings, total_estimate = _excel_header_pass(sheet)

        if not columns:
            raise DataImportError(
                f"Keine Spaltenüberschriften gefunden in '{path.name}' "
                f"(Sheet: '{sheet_name or 'Standard'}')."
            )

        stats = ImportStats(
            skipped_rows=header_skipped,
            rows_above_header=header_skipped,
            warnings=list(header_warnings),
        )
        # `row_count` ist initial geschätzt (Calamine `total_height` abzüglich
        # Header + leading-blanks). `DatasetRepo.create` korrigiert den Wert
        # nach echter Persistierung.
        read_sheet = _read_sheet_name(wb, sheet_name)
        dataset = Dataset(
            name=_dataset_name(path, read_sheet, wb),
            columns=tuple(columns),
            row_count=max(0, total_estimate),
            source_file=str(path),
            source_sheet=read_sheet,
            # Die Auto-Erkennung nimmt die erste nicht-leere Zeile: ihr Index
            # ist genau die Zahl der Leerzeilen davor.
            header_row=_header_row_number(header_skipped),
        )
        rows_iter = self._excel_row_generator(sheet, columns, stats, total_estimate)
        return ImportResult(dataset=dataset, rows=rows_iter, stats=stats)

    def _excel_row_generator(
        self,
        sheet: CalamineSheet,
        columns: list[str],
        stats: ImportStats,
        total_estimate: int,
    ) -> Iterator[DatasetRow]:
        """Generator: liest Sheet-Rows, skipt Leerzeilen, yieldet DatasetRow.

        Header-Zeile wurde vorab im `_excel_header_pass` lokalisiert; hier
        re-iterieren wir und überspringen alle Rows bis zum ersten
        Daten-Index (header-Position kann nicht mehr direkt zwischen den
        Pässen weitergegeben werden – `iter_rows` liefert keinen
        Zufallszugriff). Stattdessen detektieren wir den Header beim
        zweiten Pass erneut und beginnen direkt danach.
        """
        # Sprint 17: Cancel-Check vor dem ersten Read.
        self._check_cancel()
        rows_iter: Iterator[list[Any]] = iter(sheet.iter_rows())
        header_row, _ = _detect_header(rows_iter)
        if header_row is None:
            # Defensiv – sollte durch `_excel_header_pass` schon abgefangen
            # sein, aber wenn das Sheet zwischen Pässen geleert würde.
            return

        next_row_id = 1
        for raw in rows_iter:
            if _is_blank(raw):
                stats.skipped_rows += 1
                continue
            _enforce_cell_length_limit(raw)
            values = {
                col: _coerce_value(raw[i] if i < len(raw) else None)
                for i, col in enumerate(columns)
            }
            row = DatasetRow(row_id=next_row_id, values=values)
            next_row_id += 1
            stats.processed_count += 1
            # Zählt Skipped-Rows mit – sonst wäre eine XLSX mit unbegrenzt
            # vielen Leerzeilen nie durch die Hard-Grenze gestoppt (der
            # `continue` oben läuft am Limit-Check vorbei).
            _enforce_row_limit(stats.processed_count + stats.skipped_rows)
            if stats.processed_count % _PROGRESS_INTERVAL == 0:
                self._check_cancel()
                if self.progress is not None:
                    self.progress(stats.processed_count, max(total_estimate, stats.processed_count))
            yield row

        # Abschluss-Tick (UIs erwarten oft ein finales current==total).
        if self.progress is not None:
            self.progress(stats.processed_count, stats.processed_count)

    # ---- CSV ------------------------------------------------------------

    def _import_csv(self, path: Path) -> ImportResult:
        source = _open_csv_source(path, path.suffix.lower())
        header_raw, leading = _csv_first_non_blank(source)
        if header_raw is None:
            raise DataImportError(f"CSV-Datei '{path.name}' enthält keine Daten.")

        columns, header_warnings = _normalize_columns(header_raw)
        stats = ImportStats(
            skipped_rows=leading,
            rows_above_header=leading,
            warnings=[*header_warnings, *_csv_source_warnings(source)],
        )
        # Wie bei Excel nur eine Schätzung (Zeilenumbrüche der Datei);
        # `DatasetRepo.create` korrigiert `row_count` nach dem Durchlauf.
        total_estimate = max(0, source.line_estimate - leading - 1)
        dataset = Dataset(
            name=path.stem,
            columns=tuple(columns),
            row_count=total_estimate,
            source_file=str(path),
            header_row=_header_row_number(leading),
        )
        rows_iter = self._csv_row_generator(
            source, columns, stats, total_estimate, skip_rows=leading + 1
        )
        return ImportResult(dataset=dataset, rows=rows_iter, stats=stats)

    def _csv_row_generator(
        self,
        source: _CsvSource,
        columns: list[str],
        stats: ImportStats,
        total_estimate: int,
        skip_rows: int,
    ) -> Iterator[DatasetRow]:
        """Generator: liest die CSV ab Zeile ``skip_rows`` und yieldet Daten-Rows.

        Die Datei ist nur offen, solange iteriert wird – auch bei Abbruch,
        Cancel oder `close()` wird sie geschlossen (unter Windows sonst gesperrt).
        """
        # Sprint 17: Cancel-Check vor dem ersten Read.
        self._check_cancel()
        # Leerzeilen zählen erst als übersprungen, wenn danach noch Daten kommen;
        # abschließende Leerzeilen fallen weg, ohne gezählt zu werden.
        pending_blanks = 0
        next_row_id = 1
        with source.open() as fh:
            reader = source.reader(fh)
            for _ in itertools.islice(reader, skip_rows):
                pass
            for raw in reader:
                if _is_blank(raw):
                    pending_blanks += 1
                    _enforce_row_limit(stats.processed_count + stats.skipped_rows + pending_blanks)
                    continue
                stats.skipped_rows += pending_blanks
                pending_blanks = 0
                _enforce_cell_length_limit(raw)
                values = {
                    col: _coerce_value(raw[i] if i < len(raw) else None)
                    for i, col in enumerate(columns)
                }
                row = DatasetRow(row_id=next_row_id, values=values)
                next_row_id += 1
                stats.processed_count += 1
                _enforce_row_limit(stats.processed_count + stats.skipped_rows)
                if stats.processed_count % _PROGRESS_INTERVAL == 0:
                    self._check_cancel()
                    if self.progress is not None:
                        self.progress(
                            stats.processed_count, max(total_estimate, stats.processed_count)
                        )
                yield row

        if self.progress is not None:
            self.progress(stats.processed_count, stats.processed_count)


# ---------------------------------------------------------------------------
# Hilfen – Excel
# ---------------------------------------------------------------------------


def _select_sheet(wb: CalamineWorkbook, sheet_name: str | None) -> CalamineSheet:
    """Liefert das gewünschte Sheet oder das erste Sheet als Default.

    `CalamineWorkbook` kennt kein „aktives" Sheet – wir folgen openpyxl-
    Konvention und nehmen das erste Sheet als Default.
    """
    names = list(wb.sheet_names)
    if not names:
        raise DataImportError("Workbook ist leer (kein aktives Arbeitsblatt).")
    if sheet_name is None:
        return wb.get_sheet_by_name(names[0])
    if sheet_name not in names:
        raise DataImportError(
            f"Sheet '{sheet_name}' existiert nicht. Verfügbar: {', '.join(names)}."
        )
    return wb.get_sheet_by_name(sheet_name)


def _read_sheet_name(wb: CalamineWorkbook, sheet_name: str | None) -> str:
    """Name des Blatts, das `_select_sheet` für ``sheet_name`` tatsächlich liest."""
    return sheet_name if sheet_name is not None else wb.sheet_names[0]


def _dataset_name(path: Path, sheet_name: str, wb: CalamineWorkbook) -> str:
    """Datensatzname: bei mehrblättrigen Mappen mit Blatt-Suffix (Sprint 83).

    Sonst hießen zwei Blätter derselben Datei gleich. Einblättrige Mappen
    behalten exakt ``path.stem`` – wie CSV-Dateien und alle Bestands-Datasets.
    """
    if len(wb.sheet_names) > 1:
        return f"{path.stem} ({sheet_name})"
    return path.stem


def _header_row_number(header_index: int | None) -> int:
    """Kopfzeile 1-basiert, wie der Import-Dialog sie anzeigt; ``0`` = keine Kopfzeile.

    Die EINE Umrechnung aus der 0-basierten Zählung des Importers (Sprint 83).
    Der Index zählt ab der ersten Zeile des Blatts bzw. der CSV-Datei – calamine
    liefert führende Leerzeilen mit, der Dialog nummeriert dieselben Zeilen.
    """
    return 0 if header_index is None else header_index + 1


def _excel_header_pass(sheet: CalamineSheet) -> tuple[list[str], int, list[str], int]:
    """Erster Mini-Pass über das Sheet: Header detektieren + Größe schätzen.

    Liefert ``(columns, leading_blanks_skipped, warnings, estimated_data_rows)``.
    Streaming-Generator macht den eigentlichen Daten-Pass.
    """
    if sheet.start is None:
        # Komplett leeres Sheet – calamine paniced sonst auf `iter_rows()`.
        return [], 0, [], 0

    rows_iter: Iterator[list[Any]] = iter(sheet.iter_rows())
    header_row, leading_blanks = _detect_header(rows_iter)
    if header_row is None:
        return [], leading_blanks, [], 0

    columns, header_warnings = _normalize_columns(header_row)

    # `total_height` ist die Anzahl Datenzeilen (ohne Header) laut calamine.
    # Wir ziehen die Leerzeilen vor dem Header noch ab – Trailing-Empty-
    # Rows werden vom Streaming-Generator als skipped gezählt; `row_count`
    # wird vom Repo nach echter Persistierung korrigiert.
    total_estimate = max(0, int(sheet.total_height) - leading_blanks)
    return columns, leading_blanks, header_warnings, total_estimate


def _parse_excel_sheet(
    sheet: CalamineSheet, limit: int | None
) -> tuple[list[str], list[list[Any]], int, list[str]]:
    """Parst ein Calamine-Sheet und liefert (Spalten, Datenzeilen, skipped, warnings).

    Wird nur noch vom `preview()`-Pfad benutzt (kleine n_rows-Materialisierung
    für den UI-Dialog). Der Hauptimport läuft über
    `_excel_row_generator`.
    """
    if sheet.start is None:
        return [], [], 0, []

    rows_iter: Iterator[list[Any]] = iter(sheet.iter_rows())
    header_row, leading_blanks = _detect_header(rows_iter)
    if header_row is None:
        return [], [], leading_blanks, []

    columns, header_warnings = _normalize_columns(header_row)

    data_rows: list[list[Any]] = []
    skipped = leading_blanks
    for raw in rows_iter:
        if _is_blank(raw):
            skipped += 1
            continue
        data_rows.append(list(raw))
        if limit is not None and len(data_rows) >= limit:
            break

    return columns, data_rows, skipped, header_warnings


def _detect_header(
    rows_iter: Iterator[list[Any]],
) -> tuple[list[Any] | None, int]:
    """Erste Zeile mit überwiegend Strings = Header. Leere davor zählen als skipped."""
    leading_blanks = 0
    for raw in rows_iter:
        if _is_blank(raw):
            leading_blanks += 1
            continue
        if _looks_like_header(raw):
            return list(raw), leading_blanks
        # Erste nicht-leere Zeile, aber nicht headerlike → trotzdem als Header
        # nehmen (Fallback). Ohne Header geht hier nichts weiter.
        return list(raw), leading_blanks
    return None, leading_blanks


def _detect_header_with_confidence(
    rows: list[tuple[Any, ...]],
) -> tuple[int | None, HeaderConfidence]:
    """Header-Index + Confidence für die Dialog-Vorschau (`preview_sheet`/`preview_csv`).

    Heuristik (Sprint 29 – robuster gegen Titelzeilen): die Kopfzeile ist die
    erste nicht-leere, überwiegend textige Zeile, die entweder (a) mehr als
    eine Zelle füllt ODER (b) die volle Tabellenbreite ausfüllt. Damit werden
    *spärliche* Einzelzellen-Titel darüber (z. B. „Quartalsbericht" in nur
    einer Zelle) übersprungen, während eine echte Kopfzeile erkannt wird –
    **auch wenn sie schmaler ist als eine breitere Daten-/Fußzeile darunter**
    (eine breite Zeile UNTER der Kopfzeile darf die Kopfzeile nicht vetoen).

    - ``high``: Kopfzeile in Zeile 1 (Index 0).
    - ``low``: Kopfzeile headerlike, aber Leer-/Titelzeilen davor.
    - ``ambiguous``: keine Zeile sieht wie eine Kopfzeile aus, oder die Daten
      sind leer. ``detected_header_row`` ist dann die erste nicht-leere Zeile
      (Fallback) bzw. ``None``.

    Wird NUR von der Vorschau genutzt – der byte-identische Auto-Import
    (`import_file`) hängt weiterhin an `_detect_header` und bleibt unberührt.
    """
    non_blank = [(idx, row) for idx, row in enumerate(rows) if not _is_blank(row)]
    if not non_blank:
        return None, "ambiguous"
    full_width = max(_non_empty_count(row) for _idx, row in non_blank)
    for idx, row in non_blank:
        count = _non_empty_count(row)
        if _looks_like_header(row) and (count >= 2 or count == full_width):
            return idx, ("high" if idx == 0 else "low")
    return non_blank[0][0], "ambiguous"


def _read_header_row(sheet: CalamineSheet, header_row: int) -> tuple[list[Any] | None, int]:
    """Liest die ``header_row``-te Zeile (0-basiert) inkl. Zähler übersprungener Zeilen.

    Liefert ``(header_zeile_oder_None, anzahl_übersprungener_zeilen)``. Wenn
    der Index jenseits der Datei liegt, ist die Zeile ``None``.
    """
    rows_iter: Iterator[list[Any]] = iter(sheet.iter_rows())
    skipped = 0
    for idx, raw in enumerate(rows_iter):
        if idx < header_row:
            skipped += 1
            continue
        return list(raw), skipped
    return None, skipped


def _looks_like_header(row: list[Any] | tuple[Any, ...]) -> bool:
    non_empty = [c for c in row if c is not None and str(c).strip() != ""]
    if not non_empty:
        return False
    string_like = sum(1 for c in non_empty if isinstance(c, str))
    return (string_like / len(non_empty)) >= _HEADER_STRING_RATIO


def _non_empty_count(row: list[Any] | tuple[Any, ...]) -> int:
    return sum(1 for c in row if c is not None and str(c).strip() != "")


def _is_blank(row: list[Any] | tuple[Any, ...]) -> bool:
    return all(c is None or (isinstance(c, str) and c.strip() == "") for c in row)


def _generic_columns(width: int) -> list[str]:
    """Generische Spaltennamen für „keine Kopfzeile": ``Spalte 1, Spalte 2, …``."""
    return [f"Spalte {i}" for i in range(1, width + 1)]


def _normalize_columns(header_row: list[Any]) -> tuple[list[str], list[str]]:
    """Stringifiziert + trimmt Spaltennamen, vergibt Suffixe bei Duplikaten."""
    raw_names: list[str] = []
    for idx, cell in enumerate(header_row, start=1):
        text = "" if cell is None else str(cell).strip()
        raw_names.append(text or f"Spalte_{idx}")

    seen: dict[str, int] = {}
    final: list[str] = []
    warnings: list[str] = []
    for name in raw_names:
        if name not in seen:
            seen[name] = 1
            final.append(name)
        else:
            seen[name] += 1
            new_name = f"{name}_{seen[name]}"
            warnings.append(f"Doppelter Spaltenname '{name}' → umbenannt zu '{new_name}'.")
            final.append(new_name)
    return final, warnings


# ---------------------------------------------------------------------------
# Hilfen – CSV
# ---------------------------------------------------------------------------


def _encoding_warning(encoding: str) -> str | None:
    """Klartext-Hinweis, wenn die CSV nicht als UTF-8 gelesen werden konnte."""
    name = _FALLBACK_ENCODING_NAMES.get(encoding)
    if name is None:
        return None
    return (
        f"Die Datei war nicht als UTF-8 gespeichert und wurde als {name} gelesen. "
        "Bitte Umlaute prüfen."
    )


@dataclass(frozen=True, slots=True)
class _CsvSource:
    """Lesbare CSV: Encoding und Dialekt stehen fest, die Datei ist (noch) zu.

    Jeder Durchlauf öffnet die Datei selbst (`open`) und schließt sie wieder –
    zwischen den Durchläufen hält niemand ein Dateihandle.
    """

    path: Path
    encoding: str
    dialect: type[csv.Dialect]
    delimiter_warning: str | None
    line_estimate: int

    def open(self) -> TextIOWrapper:
        # `newline=""`: Zeilenenden gehen unverändert an `csv.reader`, damit
        # Umbrüche in Anführungszeichen erhalten bleiben (Sprint 96).
        return open(self.path, encoding=self.encoding, newline="")

    def reader(self, fh: TextIOWrapper) -> Iterator[list[str]]:
        return csv.reader(fh, dialect=self.dialect)


def _open_csv_source(path: Path, suffix: str) -> _CsvSource:
    """Encoding-Vorlauf + Dialekt-Erkennung, ohne die Datei im Speicher zu halten."""
    encoding, line_estimate = _scan_csv_encoding(path)
    dialect, delimiter_warning = _sniff_csv_dialect(path, encoding, suffix)
    return _CsvSource(
        path=path,
        encoding=encoding,
        dialect=dialect,
        delimiter_warning=delimiter_warning,
        line_estimate=line_estimate,
    )


def _csv_source_warnings(source: _CsvSource) -> list[str]:
    """Delimiter- und Encoding-Hinweis in der Reihenfolge, die der Import meldet."""
    warnings: list[str] = []
    if source.delimiter_warning is not None:
        warnings.append(source.delimiter_warning)
    encoding_warning = _encoding_warning(source.encoding)
    if encoding_warning is not None:
        warnings.append(encoding_warning)
    return warnings


def _scan_csv_encoding(path: Path) -> tuple[str, int]:
    """Wählt das Encoding und zählt die Zeilenumbrüche (``\\n``-Bytes).

    Entscheidung wie vor Sprint 96: UTF-8-BOM ⇒ ``utf-8-sig`` (sonst hinge das
    BOM-Zeichen als unsichtbares Präfix in der ersten Spalte); andernfalls das
    erste Encoding aus `_CSV_ENCODINGS`, das die GANZE Datei fehlerfrei
    dekodiert. Geprüft wird blockweise mit einem inkrementellen Decoder – die
    Datei wird dabei weder als Bytes noch als Text gehalten. Das Byte ``0x0A``
    ist in allen Kandidaten-Encodings genau ``\\n`` und taugt deshalb als
    Zeilenschätzung für Fortschritt und `Dataset.row_count`.
    """
    with open(path, "rb") as fh:
        candidates = ("utf-8-sig",) if fh.read(len(_UTF8_BOM)) == _UTF8_BOM else _CSV_ENCODINGS
        last_error: UnicodeDecodeError | None = None
        for encoding in candidates:
            fh.seek(0)
            decoder = codecs.getincrementaldecoder(encoding)()
            newlines = 0
            try:
                while block := fh.read(_CSV_SCAN_BLOCK_SIZE):
                    decoder.decode(block)
                    newlines += block.count(b"\n")
                decoder.decode(b"", final=True)
            except UnicodeDecodeError as e:
                if len(candidates) == 1:
                    raise
                last_error = e
                continue
            return encoding, newlines
    # Sehr unwahrscheinlich – latin-1 nimmt jedes Byte. Aber defensiv:
    raise DataImportError(
        f"CSV '{path.name}' konnte mit keinem unterstützten Encoding gelesen werden "
        f"({', '.join(_CSV_ENCODINGS)}). Letzter Fehler: {last_error}"
    )


def _sniff_csv_dialect(
    path: Path, encoding: str, suffix: str
) -> tuple[type[csv.Dialect], str | None]:
    """Dialekt aus den ersten `_CSV_SNIFF_CHARS` Zeichen, Fallback per Dateiendung.

    Sprint 49 / A-005: `suffix` (z. B. ``.tsv``) ist nur für den Fallback
    relevant, wenn `csv.Sniffer` scheitert – eine erfolgreich geschnüffelte
    Datei wird nicht überstimmt. Rückgabe zusätzlich eine Warnung (oder
    ``None``), wenn der Fallback gegriffen hat – analog zur Encoding-Warnung
    nur bei Abweichung vom stillen Default.
    """
    with open(path, encoding=encoding, newline="") as fh:
        sample = fh.read(_CSV_SNIFF_CHARS)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|"), None
    except csv.Error:
        if suffix == ".tsv":
            return csv.excel_tab, "Trennzeichen: Tab (aus Dateiendung '.tsv')."
        return csv.excel, "Trennzeichen: Komma (Standard, Erkennung nicht eindeutig)."


def _csv_first_non_blank(source: _CsvSource) -> tuple[list[str] | None, int]:
    """Kopfzeile des Auto-Pfads: erste nicht-leere Zeile + Zahl der Leerzeilen davor."""
    leading = 0
    with source.open() as fh:
        for raw in source.reader(fh):
            if not _is_blank(raw):
                return raw, leading
            leading += 1
            _enforce_row_limit(leading)
    return None, leading


def _csv_row_at(source: _CsvSource, index: int) -> tuple[list[str] | None, int]:
    """Zeile ``index`` (0-basiert) bzw. ``None`` + Zeilenzahl, wenn die Datei vorher endet."""
    seen = 0
    with source.open() as fh:
        for raw in source.reader(fh):
            if seen == index:
                return raw, seen
            seen += 1
    return None, seen


# ---------------------------------------------------------------------------
# Typ-Konvertierung
# ---------------------------------------------------------------------------


def _coerce_value(value: Any) -> Any:
    """Mappt Calamine-/CSV-Zellwerte auf native Python-Typen.

    Wichtige Calamine-Eigenheiten (Sprint 10.2):
    - Leere Zellen kommen als ``""`` (empty string), nicht ``None``
      → wir normalisieren auf ``None``.
    - Excel-Zahlen kommen IMMER als ``float`` – auch ganzzahlige.
      Wir geben ganzzahlige ``float``-Werte als ``int`` zurück, damit
      Bestandstests und Audit-Trail-Persistenz stabil bleiben.
    - Datums-Zellen ohne Uhrzeit liefert Calamine als ``date`` (statt
      ``datetime`` wie openpyxl). Wir heben das auf ``datetime`` an,
      damit downstream-Code einheitlich mit ``datetime`` arbeitet.

    Numpy/Pandas-Typen werden bewusst NICHT erzeugt – das Dataset
    soll JSON-roundtrippable bleiben.
    """
    if value is None:
        return None
    # `bool` vor `int` prüfen – bool ist subclass von int.
    if isinstance(value, bool):
        return value
    # `datetime` vor `date` prüfen – datetime ist subclass von date.
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time(0, 0, 0))
    if isinstance(value, time):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return value
    if isinstance(value, str):
        return _coerce_string(value)
    # Letztes Mittel: stringifizieren, damit JSON-Persistierung funktioniert.
    return str(value)


# Sprint 49 / N-006: `_try_int`s drei möglichen Ausgänge – ob eine Ganzzahl
# in-range/out-of-range ist, entscheidet `_coerce_string`s Folge-Verzweigung
# (out-of-range darf NICHT an `_try_float` weitergereicht werden).
_IntCoercionKind = Literal["in_range", "out_of_range", "not_int"]


def _coerce_string(value: str) -> Any:
    """Stringwert auf Native-Typ (int/float/str/None) abbilden."""
    text = value.strip()
    if text == "":
        return None
    int_kind, as_int = _try_int(text)
    if int_kind == "in_range":
        return as_int
    if int_kind == "out_of_range":
        # Sprint 49 / N-006: ganzzahlig, aber außerhalb des signed-64-Bit-
        # Bereichs → Originalstring bewahren. NICHT an `_try_float`
        # weiterreichen, das würde die Zahl per Float-Rundung verfälschen.
        return text
    as_float = _try_float(text)
    if as_float is not None:
        return as_float
    return text


def _try_int(text: str) -> tuple[_IntCoercionKind, int | None]:
    try:
        # int("1.0") wirft – das ist Absicht, das wäre ein Float.
        value = int(text)
    except ValueError:
        return "not_int", None
    if _INT64_MIN <= value <= _INT64_MAX:
        return "in_range", value
    return "out_of_range", None


def _try_float(text: str) -> float | None:
    # Deutsche Komma-Dezimalzahl tolerieren ("1,5" → 1.5), aber nur wenn
    # eindeutig (kein zusätzlicher Punkt im String).
    candidate = text.replace(",", ".") if "." not in text and text.count(",") == 1 else text
    try:
        result = float(candidate)
    except ValueError:
        return None
    # Sprint 49 / N-007: non-finite (inf/nan/Float-Overflow wie "1e999")
    # verwerfen – orjson kodiert das sonst still als `null` (Datenverlust).
    # `_coerce_string` fällt dadurch auf den String-Zweig zurück.
    if not math.isfinite(result):
        return None
    return result
