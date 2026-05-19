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
- **Encoding-Detection** für CSV: utf-8 → utf-8-sig → latin-1 → cp1252.
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

import csv
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Final, Literal

from python_calamine import CalamineSheet, CalamineWorkbook

from sampling_tool.config import SUPPORTED_CSV_SUFFIXES, SUPPORTED_EXCEL_SUFFIXES
from sampling_tool.core.cancellation import CancellationToken
from sampling_tool.core.models import Dataset, DatasetRow

HeaderConfidence = Literal["high", "low", "ambiguous"]

ProgressCallback = Callable[[int, int], None]

# Alle Encodings, die wir bei CSV der Reihe nach probieren.
_CSV_ENCODINGS: Final[tuple[str, ...]] = ("utf-8", "utf-8-sig", "latin-1", "cp1252")

# Schwellwert für Header-Detection: ≥ Anteil String-Zellen einer Zeile.
_HEADER_STRING_RATIO: Final[float] = 0.5

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
    """

    skipped_rows: int = 0
    warnings: list[str] = field(default_factory=list)
    processed_count: int = 0


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

    def detect_sheets(self, path: Path) -> list[str]:
        """Listet die Sheet-Namen einer Excel-Datei (für UI-Multi-Sheet-Auswahl)."""
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EXCEL_SUFFIXES:
            raise DataImportError(
                f"Sheet-Liste nur für Excel-Dateien verfügbar (Datei: {path.name})."
            )
        wb = CalamineWorkbook.from_path(str(path))
        return list(wb.sheet_names)

    def preview(
        self,
        path: Path,
        sheet_name: str | None = None,
        n_rows: int = 10,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """Liefert (Spalten, erste n Zeilen) für eine UI-Vorschau – kein vollständiger Import.

        Materialisiert intern eine kleine Liste – nicht für große
        Dataseträume, sondern explizit für den Dialog.
        """
        if n_rows < 0:
            raise DataImportError("preview(): n_rows muss >= 0 sein.")

        suffix = path.suffix.lower()
        if suffix in SUPPORTED_CSV_SUFFIXES:
            text, _enc = _read_csv_text(path)
            columns, rows_iter, _skipped, _warns = _parse_csv(text)
            preview_rows = [dict(zip(columns, r, strict=False)) for r in rows_iter[:n_rows]]
            return list(columns), preview_rows

        if suffix in SUPPORTED_EXCEL_SUFFIXES:
            wb = CalamineWorkbook.from_path(str(path))
            sheet = _select_sheet(wb, sheet_name)
            columns, data_rows, _skipped, _warns = _parse_excel_sheet(sheet, limit=n_rows)
            preview_rows = [dict(zip(columns, r, strict=False)) for r in data_rows]
            return list(columns), preview_rows

        raise DataImportError(f"Vorschau für Dateityp '{suffix}' nicht unterstützt.")

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

    def import_file_configured(
        self,
        path: Path,
        sheet_name: str,
        header_row: int,
    ) -> ImportResult:
        """Excel-Import mit explizit gewählten Sheet + Header-Zeile.

        ``header_row`` ist 0-basiert. Alle Zeilen davor zählen als
        ``skipped_rows``, der Header definiert die Spalten, alle Zeilen
        danach werden als Daten interpretiert (Leerzeilen weiterhin
        geskipped). Skippt die Auto-Detection bewusst – ist der User-
        Override aus dem `ImportOptionsDialog`.
        """
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EXCEL_SUFFIXES:
            raise DataImportError(
                f"import_file_configured() ist nur für Excel-Dateien verfügbar "
                f"(Datei: {path.name})."
            )
        if header_row < 0:
            raise DataImportError(f"Header-Zeile muss >= 0 sein (war: {header_row}).")

        wb = CalamineWorkbook.from_path(str(path))
        sheet = _select_sheet(wb, sheet_name)
        if sheet.start is None:
            raise DataImportError(f"Sheet '{sheet_name}' in '{path.name}' ist leer.")

        header_raw, leading_skipped = _read_header_row(sheet, header_row)
        if header_raw is None:
            raise DataImportError(
                f"Header-Zeile {header_row + 1} liegt jenseits der Daten in Sheet "
                f"'{sheet_name}' (max. {int(sheet.total_height)} Zeilen)."
            )

        columns, header_warnings = _normalize_columns(header_raw)
        stats = ImportStats(skipped_rows=leading_skipped, warnings=list(header_warnings))
        total_estimate = max(0, int(sheet.total_height) - header_row - 1)
        dataset = Dataset(
            name=path.stem,
            columns=tuple(columns),
            row_count=max(0, total_estimate),
            source_file=str(path),
        )
        rows_iter = self._configured_row_generator(
            sheet, columns, stats, total_estimate, header_row
        )
        return ImportResult(dataset=dataset, rows=rows_iter, stats=stats)

    def _configured_row_generator(
        self,
        sheet: CalamineSheet,
        columns: list[str],
        stats: ImportStats,
        total_estimate: int,
        header_row: int,
    ) -> Iterator[DatasetRow]:
        """Generator: skipt bis zur Header-Zeile, dann yieldet Daten-Rows."""
        # Sprint 17: Cancel-Check vor dem ersten Read.
        self._check_cancel()
        rows_iter: Iterator[list[Any]] = iter(sheet.iter_rows())
        # Header-Row + alle vorhergehenden überspringen.
        for _ in range(header_row + 1):
            try:
                next(rows_iter)
            except StopIteration:
                return

        next_row_id = 1
        for raw in rows_iter:
            if _is_blank(raw):
                stats.skipped_rows += 1
                continue
            values = {
                col: _coerce_value(raw[i] if i < len(raw) else None)
                for i, col in enumerate(columns)
            }
            row = DatasetRow(row_id=next_row_id, values=values)
            next_row_id += 1
            stats.processed_count += 1
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
            warnings=list(header_warnings),
        )
        # `row_count` ist initial geschätzt (Calamine `total_height` abzüglich
        # Header + leading-blanks). `DatasetRepo.create` korrigiert den Wert
        # nach echter Persistierung.
        dataset = Dataset(
            name=path.stem,
            columns=tuple(columns),
            row_count=max(0, total_estimate),
            source_file=str(path),
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
            values = {
                col: _coerce_value(raw[i] if i < len(raw) else None)
                for i, col in enumerate(columns)
            }
            row = DatasetRow(row_id=next_row_id, values=values)
            next_row_id += 1
            stats.processed_count += 1
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
        text, encoding = _read_csv_text(path)
        columns, data_rows, skipped, warnings = _parse_csv(text)

        if not columns:
            raise DataImportError(f"CSV-Datei '{path.name}' enthält keine Daten.")

        if encoding != "utf-8":
            warnings = [*warnings, f"CSV-Encoding erkannt als '{encoding}'."]

        stats = ImportStats(skipped_rows=skipped, warnings=list(warnings))
        total = len(data_rows)
        dataset = Dataset(
            name=path.stem,
            columns=tuple(columns),
            row_count=total,
            source_file=str(path),
        )
        rows_iter = self._csv_row_generator(columns, data_rows, stats, total)
        return ImportResult(dataset=dataset, rows=rows_iter, stats=stats)

    def _csv_row_generator(
        self,
        columns: list[str],
        data_rows: list[list[Any]],
        stats: ImportStats,
        total: int,
    ) -> Iterator[DatasetRow]:
        """CSV-Pfad als Generator. `data_rows` ist bereits geparst (csv.reader
        liest Zeile für Zeile, aber wir haben den Text einmal voll im RAM)."""
        # Sprint 17: Cancel-Check vor dem ersten Read.
        self._check_cancel()
        for idx, raw in enumerate(data_rows, start=1):
            values = {
                col: _coerce_value(raw[i] if i < len(raw) else None)
                for i, col in enumerate(columns)
            }
            stats.processed_count += 1
            if stats.processed_count % _PROGRESS_INTERVAL == 0:
                self._check_cancel()
                if self.progress is not None:
                    self.progress(stats.processed_count, total)
            yield DatasetRow(row_id=idx, values=values)

        if self.progress is not None:
            self.progress(stats.processed_count, max(total, stats.processed_count))


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
    """Header-Index + Confidence für `preview_sheet`.

    - ``high``: erste Zeile (Index 0) ist headerlike.
    - ``low``: Header headerlike, aber Leerzeilen oder Metadaten davor.
    - ``ambiguous``: erste non-blank Zeile sieht NICHT wie ein Header aus,
      oder das Sheet ist komplett leer. ``detected_header_row`` ist dann
      die erste non-blank Zeile (Fallback) bzw. ``None``.
    """
    for idx, row in enumerate(rows):
        if _is_blank(row):
            continue
        if _looks_like_header(row):
            return idx, ("high" if idx == 0 else "low")
        return idx, "ambiguous"
    return None, "ambiguous"


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


def _is_blank(row: list[Any] | tuple[Any, ...]) -> bool:
    return all(c is None or (isinstance(c, str) and c.strip() == "") for c in row)


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


def _read_csv_text(path: Path) -> tuple[str, str]:
    """Probiert die Encoding-Liste durch und gibt (Text, gewähltes Encoding) zurück.

    UTF-8-BOM wird vorab erkannt, weil sonst der utf-8-Decode zwar erfolgreich
    durchläuft, aber das BOM-Zeichen `﻿` als unsichtbares Präfix in der
    ersten Spalte hängenbleibt.
    """
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"

    last_error: Exception | None = None
    for encoding in _CSV_ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError as e:
            last_error = e
    # Sehr unwahrscheinlich – latin-1 nimmt jedes Byte. Aber defensiv:
    raise DataImportError(
        f"CSV '{path.name}' konnte mit keinem unterstützten Encoding gelesen werden "
        f"({', '.join(_CSV_ENCODINGS)}). Letzter Fehler: {last_error}"
    )


def _parse_csv(text: str) -> tuple[list[str], list[list[Any]], int, list[str]]:
    """Splittet CSV-Text in Header + Datenzeilen. Delimiter wird geschnüffelt."""
    sample = text[:8192] or text
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel  # Default: Komma

    reader = csv.reader(text.splitlines(), dialect=dialect)
    all_rows = [row for row in reader]

    # Leere Zeilen am Anfang strippen, davon zählen wir die ersten als
    # "leading blanks" für die skipped-Bilanz.
    leading = 0
    while all_rows and _is_blank(all_rows[0]):
        all_rows.pop(0)
        leading += 1

    # Trailing-Blanks ebenfalls strippen (zählen aber nicht als skipped).
    while all_rows and _is_blank(all_rows[-1]):
        all_rows.pop()

    if not all_rows:
        return [], [], leading, []

    header_row = list(all_rows[0])
    columns, warnings = _normalize_columns(header_row)

    data_rows: list[list[Any]] = []
    skipped = leading
    for raw in all_rows[1:]:
        if _is_blank(raw):
            skipped += 1
            continue
        data_rows.append(list(raw))

    return columns, data_rows, skipped, warnings


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


def _coerce_string(value: str) -> Any:
    """Stringwert auf Native-Typ (int/float/str/None) abbilden."""
    text = value.strip()
    if text == "":
        return None
    as_int = _try_int(text)
    if as_int is not None:
        return as_int
    as_float = _try_float(text)
    if as_float is not None:
        return as_float
    return text


def _try_int(text: str) -> int | None:
    try:
        # int("1.0") wirft – das ist Absicht, das wäre ein Float.
        return int(text)
    except ValueError:
        return None


def _try_float(text: str) -> float | None:
    # Deutsche Komma-Dezimalzahl tolerieren ("1,5" → 1.5), aber nur wenn
    # eindeutig (kein zusätzlicher Punkt im String).
    candidate = text.replace(",", ".") if "." not in text and text.count(",") == 1 else text
    try:
        return float(candidate)
    except ValueError:
        return None
