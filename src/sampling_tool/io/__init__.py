"""I/O-Layer: Excel-/CSV-Import, Excel-Export, PDF-Report (AuditTrail).

Public API:
    ExcelImporter      – Excel/CSV → Dataset
    ImportResult       – Dataset + skipped_rows + warnings
    DataImportError    – fachlicher Import-Fehler
    ExcelExporter      – SampleResult → .xlsx (atomar, mit Metadaten-Sheet)
    ExportError        – fachlicher Export-Fehler
    AuditTrailPDF      – Engagement + AuditEvents → PDF (reportlab)
"""

from __future__ import annotations

from sampling_tool.io.exporter import ExcelExporter, ExportError
from sampling_tool.io.importer import (
    DataImportError,
    ExcelImporter,
    ImportResult,
)
from sampling_tool.io.pdf_report import AuditTrailPDF

__all__ = [
    "AuditTrailPDF",
    "DataImportError",
    "ExcelExporter",
    "ExcelImporter",
    "ExportError",
    "ImportResult",
]
