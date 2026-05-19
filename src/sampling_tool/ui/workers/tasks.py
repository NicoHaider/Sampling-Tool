"""Konkrete Worker-Tasks für Long-Running-Operations (Sprint 17 / P-008).

Jeder Task implementiert das `WorkerTask`-Protocol und kapselt eine
einzelne Long-Running-Operation (Excel-Import, Multi-Sheet-Excel-Report,
PDF-Report, HTML-Report). Tasks bekommen `ProgressReporter` und
`CancellationToken` per Argument – kein Qt-Code, keine UI-Abhängigkeit.

Connection-Thread-Safety: Tasks, die in die SQLite-DB schreiben, öffnen
eine eigene `Database`-Instanz im Worker-Thread (siehe `ExcelImportTask`).
Damit gibt es keinen Shared-Connection-State zwischen Threads. WAL-Mode
erlaubt parallele Reader (Main-Thread) + 1 Writer (Worker).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from sampling_tool.audit.logger import AuditLogger
from sampling_tool.core.cancellation import CancellationToken
from sampling_tool.io.exporter import ExcelExporter
from sampling_tool.io.html_report import HtmlReportGenerator
from sampling_tool.io.importer import ExcelImporter, ImportStats
from sampling_tool.io.multi_report_exporter import MultiSheetReportExporter
from sampling_tool.io.pdf_report import AuditTrailPDF
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import AuditRepo, DatasetRepo

if TYPE_CHECKING:
    from sampling_tool.core.models import (
        AuditEvent,
        Dataset,
        Engagement,
        SampleResult,
    )
    from sampling_tool.io.briefpapier import BriefpapierConfig
    from sampling_tool.ui.workers.task_worker import ProgressReporter


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExcelImportTaskResult:
    """Rückgabe von `ExcelImportTask` – persistiertes Dataset + Stats."""

    dataset: Dataset
    stats: ImportStats


@dataclass(frozen=True, slots=True)
class ExcelImportTask:
    """Excel-Import + DB-Persist als einzelne Worker-Task.

    Eröffnet eine eigene `Database`-Instanz im Worker-Thread, persistiert
    das Dataset, schreibt den Audit-Log-Eintrag und schließt die
    Connection wieder. Damit gibt es keine Shared-Connection mit dem
    Main-Thread.

    ``sheet_name`` und ``header_row`` sind die optionalen Overrides aus
    dem `ImportOptionsDialog` (Sprint 16). Beide ``None`` ⇒ Auto-Detect
    (Standard-Pfad ``import_file``).
    """

    path: Path
    db_path: Path
    engagement_id: int
    user_name: str
    sheet_name: str | None = None
    header_row: int | None = None

    def run(
        self,
        progress: ProgressReporter,
        cancellation: CancellationToken,
    ) -> ExcelImportTaskResult:
        importer = ExcelImporter(
            progress=progress.report,
            cancellation=cancellation,
        )
        if self.sheet_name is not None and self.header_row is not None:
            result = importer.import_file_configured(self.path, self.sheet_name, self.header_row)
        else:
            result = importer.import_file(self.path)

        # Eigene Database-Connection im Worker-Thread – kein Shared-State
        # mit dem Main-Thread. WAL erlaubt parallele Reader, BEGIN IMMEDIATE
        # serialisiert den Writer.
        db = Database(self.db_path)
        try:
            dataset = replace(result.dataset, engagement_id=self.engagement_id)
            with db.session() as conn:
                stored = DatasetRepo(conn).create(
                    dataset,
                    result.rows,
                    progress=progress.report,
                    cancellation=cancellation,
                )
                AuditLogger(AuditRepo(conn), self.user_name, self.engagement_id).log_import(stored)
            # `stats` ist nach voller `rows`-Konsumierung gefüllt (Sprint 11.3).
            return ExcelImportTaskResult(dataset=stored, stats=result.stats)
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Export-Tasks
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SampleExportTask:
    """Sample-Excel-Export als Worker-Task.

    Öffnet eine eigene `Database`-Instanz im Worker-Thread (read-only-
    Zugriff via DatasetRepo). Liefert den geschriebenen Pfad zurück.
    """

    sample: SampleResult
    dataset: Dataset
    db_path: Path
    columns: list[str]
    output_dir: Path
    custom_name: str
    custom_id: str
    engagement: Engagement

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> Path:
        cancellation.raise_if_cancelled()
        progress.report(0, 1)
        db = Database(self.db_path)
        try:
            path = ExcelExporter().export_sample(
                self.sample,
                self.dataset,
                DatasetRepo(db.connect()),
                columns=self.columns,
                output_dir=self.output_dir,
                custom_name=self.custom_name,
                custom_id=self.custom_id,
                engagement=self.engagement,
            )
        finally:
            db.close()
        cancellation.raise_if_cancelled()
        progress.report(1, 1)
        return path


@dataclass(frozen=True, slots=True)
class AuditPdfExportTask:
    """AuditTrail-PDF-Export als Worker-Task."""

    engagement: Engagement
    events: list[AuditEvent]
    output_path: Path
    briefpapier: BriefpapierConfig | None
    include_statistics: bool

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> Path:
        cancellation.raise_if_cancelled()
        progress.report(0, 1)
        # reportlab hat keinen Mid-Render-Cancel-Point. Wir prüfen nur
        # vor + nach dem Render. PDFs bei realistischen AuditTrail-Größen
        # (< 20k Events) sind seit Sprint 10.4 in < 2 s gerendert.
        AuditTrailPDF(briefpapier=self.briefpapier).render(
            self.engagement,
            self.events,
            self.output_path,
            include_statistics=self.include_statistics,
        )
        cancellation.raise_if_cancelled()
        progress.report(1, 1)
        return self.output_path


@dataclass(frozen=True, slots=True)
class ExcelReportTask:
    """Multi-Sheet Excel-Report als Worker-Task."""

    engagement: Engagement
    datasets: list[Dataset]
    samples: list[SampleResult]
    audit_events: list[AuditEvent]
    output_path: Path
    sheets: set[str]

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> Path:
        cancellation.raise_if_cancelled()
        progress.report(0, 1)
        MultiSheetReportExporter().export(
            self.engagement,
            self.datasets,
            self.samples,
            self.audit_events,
            self.output_path,
            sheets=self.sheets,
        )
        cancellation.raise_if_cancelled()
        progress.report(1, 1)
        return self.output_path


@dataclass(frozen=True, slots=True)
class HtmlReportTask:
    """HTML-Report als Worker-Task."""

    engagement: Engagement
    datasets: list[Dataset]
    samples: list[SampleResult]
    audit_events: list[AuditEvent]
    output_path: Path
    include_charts: bool
    include_audit_trail: bool
    include_samples_table: bool

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> Path:
        cancellation.raise_if_cancelled()
        progress.report(0, 1)
        HtmlReportGenerator().render(
            self.engagement,
            self.datasets,
            self.samples,
            self.audit_events,
            self.output_path,
            include_charts=self.include_charts,
            include_audit_trail=self.include_audit_trail,
            include_samples_table=self.include_samples_table,
        )
        cancellation.raise_if_cancelled()
        progress.report(1, 1)
        return self.output_path
