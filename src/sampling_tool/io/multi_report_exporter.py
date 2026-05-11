"""Multi-Sheet Excel-Report: Komplett-Bericht eines Engagements.

`MultiSheetReportExporter` schreibt eine .xlsx mit vier Sheets:

1. **Übersicht** – Engagement-Metadaten + Anzahlen (Datasets / Samples /
   Audit-Events / letzte Aktivität).
2. **AuditTrail** – alle Events chronologisch (älteste oben).
3. **Samples** – jede Stichprobe mit Methode, Größe, Seed, Filter, Datum.
4. **Statistiken** – Methoden-Verteilung als Tabelle + eingebettetes
   Bar-Chart-Bild via `chart_renderer`.

Schreibt atomar (.tmp → `os.replace`), damit ein Absturz beim Speichern
keine halbe Datei hinterlässt – das gleiche Muster wie in `exporter.py`.
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Final

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XlImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from sampling_tool.core.models import (
    AuditEvent,
    Dataset,
    Engagement,
    SampleResult,
)
from sampling_tool.ui.widgets.chart_renderer import render_bar_chart_bytes

_HEADER_FILL: Final = PatternFill(start_color="FFE81A3B", end_color="FFE81A3B", fill_type="solid")
_HEADER_FONT: Final = Font(bold=True, color="FFFFFFFF")
_HEADER_ALIGN: Final = Alignment(vertical="center", horizontal="left")
_MAX_COL_WIDTH: Final[int] = 50

SHEET_UEBERSICHT: Final[str] = "Übersicht"
SHEET_AUDIT_TRAIL: Final[str] = "AuditTrail"
SHEET_SAMPLES: Final[str] = "Samples"
SHEET_STATISTIKEN: Final[str] = "Statistiken"

ALL_SHEETS: Final[frozenset[str]] = frozenset(
    {SHEET_UEBERSICHT, SHEET_AUDIT_TRAIL, SHEET_SAMPLES, SHEET_STATISTIKEN}
)


class MultiSheetReportExporter:
    """Erzeugt einen Engagement-Komplett-Bericht als Multi-Sheet-Excel."""

    def export(
        self,
        engagement: Engagement,
        datasets: list[Dataset],
        samples: list[SampleResult],
        audit_events: list[AuditEvent],
        output_path: Path,
        sheets: set[str] | None = None,
    ) -> Path:
        """Schreibt die .xlsx atomar nach `output_path` und gibt den Pfad zurück.

        `sheets` filtert die geschriebenen Sheets nach Namen aus
        `ALL_SHEETS`. `None` oder leeres Set ⇒ alle Sheets.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        target = (
            output_path
            if output_path.suffix.lower() == ".xlsx"
            else output_path.with_suffix(".xlsx")
        )
        tmp = target.with_suffix(target.suffix + ".tmp")

        active = ALL_SHEETS if not sheets else (sheets & ALL_SHEETS)
        if not active:
            active = ALL_SHEETS

        wb = Workbook()
        try:
            if SHEET_UEBERSICHT in active:
                self._write_uebersicht(wb, engagement, datasets, samples, audit_events)
            if SHEET_AUDIT_TRAIL in active:
                self._write_audit_trail(wb, audit_events)
            if SHEET_SAMPLES in active:
                self._write_samples(wb, samples)
            if SHEET_STATISTIKEN in active:
                self._write_statistiken(wb, samples, audit_events)

            # Das Default-Sheet "Sheet" von openpyxl bleibt übrig, wenn das
            # erste tatsächlich geschriebene Sheet via `create_sheet` angelegt
            # wurde – wir entfernen es. Wurde nur „Übersicht" geschrieben,
            # hat es bereits den Titel überschrieben.
            for ws in list(wb.worksheets):
                if ws.title == "Sheet":
                    wb.remove(ws)
            wb.save(tmp)
        except Exception:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise
        finally:
            wb.close()

        os.replace(tmp, target)
        return target

    # ---- Sheets ---------------------------------------------------------

    def _write_uebersicht(
        self,
        wb: Workbook,
        engagement: Engagement,
        datasets: list[Dataset],
        samples: list[SampleResult],
        audit_events: list[AuditEvent],
    ) -> None:
        ws = wb.active
        assert ws is not None
        ws.title = "1. Übersicht"
        ws.append(["BDO Audit Sampling Tool – Engagement-Bericht"])
        title_cell = ws.cell(row=1, column=1)
        title_cell.font = Font(bold=True, size=14, color="FFE81A3B")
        ws.append([])

        meta_rows: list[tuple[str, Any]] = [
            ("Mandant", engagement.client_name),
            ("Prüfungstyp", engagement.audit_type or "—"),
            ("Auditor", engagement.auditor_name),
            ("Position", engagement.auditor_position or "—"),
            ("Engagement-ID", engagement.id if engagement.id is not None else "—"),
            ("Bericht erstellt", _format_now()),
        ]
        for label, value in meta_rows:
            ws.append([label, _ensure_cell_value(value)])

        ws.append([])
        ws.append(["Statistiken"])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True, color="FFE81A3B")
        ws.append(["Datasets", len(datasets)])
        ws.append(["Samples", len(samples)])
        ws.append(["Audit-Events", len(audit_events)])
        if audit_events:
            latest = max(audit_events, key=lambda e: e.timestamp)
            ws.append(["Letzte Aktivität", _format_dt(latest.timestamp)])
        else:
            ws.append(["Letzte Aktivität", "—"])

        _autosize(ws, 2)
        # Erstes Spalten-Label fett.
        for row_idx in range(3, ws.max_row + 1):
            cell = ws.cell(row=row_idx, column=1)
            if cell.value not in ("", None):
                cell.font = Font(bold=True)

    def _write_audit_trail(self, wb: Workbook, events: list[AuditEvent]) -> None:
        ws = wb.create_sheet("2. AuditTrail")
        header = [
            "Zeitstempel",
            "Aktion",
            "User",
            "Sample",
            "Größe",
            "%",
            "Seed",
            "Datei",
            "Korrektur",
        ]
        ws.append(header)
        _style_header_row(ws, len(header))

        chronological = sorted(events, key=lambda e: (e.timestamp, e.id or 0))
        for evt in chronological:
            ws.append(
                [
                    _format_dt(evt.timestamp),
                    evt.event_type,
                    evt.user_name,
                    evt.sample_id if evt.sample_id is not None else "—",
                    evt.sample_size if evt.sample_size is not None else "—",
                    (f"{evt.sample_percent:.2f}" if evt.sample_percent is not None else "—"),
                    evt.seed if evt.seed is not None else "—",
                    Path(evt.export_file or evt.import_file or "").name or "—",
                    f"#{evt.corrects_event_id}" if evt.corrects_event_id is not None else "—",
                ]
            )
        _autosize(ws, len(header))
        ws.freeze_panes = "A2"

    def _write_samples(self, wb: Workbook, samples: list[SampleResult]) -> None:
        ws = wb.create_sheet("3. Samples")
        header = [
            "ID",
            "Methode",
            "Größe",
            "Population",
            "Anteil %",
            "Seed",
            "Filter-Feld",
            "Filter-Wert",
            "Cluster-Feld",
            "Stratum-Feld",
            "Erstellt am",
            "Erstellt von",
        ]
        ws.append(header)
        _style_header_row(ws, len(header))

        ordered = sorted(samples, key=lambda s: s.drawn_at)
        for sample in ordered:
            cfg = sample.config
            percent = (
                sample.actual_size / sample.population_size * 100.0
                if sample.population_size
                else 0.0
            )
            ws.append(
                [
                    sample.id if sample.id is not None else "—",
                    cfg.method.value,
                    sample.actual_size,
                    sample.population_size,
                    round(percent, 2),
                    cfg.seed,
                    cfg.filter_field or "—",
                    str(cfg.filter_value) if cfg.filter_value is not None else "—",
                    cfg.cluster_field or "—",
                    cfg.stratum_field or "—",
                    _format_dt(sample.drawn_at),
                    sample.created_by,
                ]
            )
        _autosize(ws, len(header))
        ws.freeze_panes = "A2"

    def _write_statistiken(
        self,
        wb: Workbook,
        samples: list[SampleResult],
        events: list[AuditEvent],
    ) -> None:
        ws = wb.create_sheet("4. Statistiken")

        # Methoden-Verteilung als Tabelle.
        ws.append(["Methode", "Anzahl"])
        _style_header_row(ws, 2)
        method_counts: Counter[str] = Counter(s.config.method.value for s in samples)
        for method, count in method_counts.most_common():
            ws.append([method, count])

        # Event-Typen-Verteilung als zweite Tabelle.
        start = ws.max_row + 2
        ws.cell(row=start, column=1, value="Eventtyp")
        ws.cell(row=start, column=2, value="Anzahl")
        for col in (1, 2):
            cell = ws.cell(row=start, column=col)
            cell.fill = _HEADER_FILL
            cell.font = _HEADER_FONT
            cell.alignment = _HEADER_ALIGN
        type_counts: Counter[str] = Counter(e.event_type for e in events)
        for event_type, count in type_counts.most_common():
            ws.append([event_type, count])

        _autosize(ws, 2)

        # Chart als eingebettetes PNG.
        if method_counts:
            labels = list(method_counts.keys())
            values = [float(method_counts[k]) for k in labels]
            png_bytes = render_bar_chart_bytes(
                labels, values, title="Sampling-Methoden", width=480, height=240
            )
            image = XlImage(BytesIO(png_bytes))
            image.anchor = "E2"
            ws.add_image(image)


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _style_header_row(ws: Worksheet, columns: int) -> None:
    for col in range(1, columns + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = _HEADER_ALIGN


def _autosize(ws: Worksheet, columns: int) -> None:
    widths = [0] * columns
    for row in ws.iter_rows(values_only=True):
        for i, val in enumerate(row[:columns]):
            length = len(_display(val))
            if length > widths[i]:
                widths[i] = min(length, _MAX_COL_WIDTH)
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(12, width + 2)


def _ensure_cell_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime | int | float | bool | str):
        return value
    return str(value)


def _format_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    ts = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return ts.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)
