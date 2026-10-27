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

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from sampling_tool.audit.logger import AuditLogger
from sampling_tool.core.cancellation import CancellationToken, OperationCancelled
from sampling_tool.io.exporter import ExcelExporter, ExportError
from sampling_tool.io.html_report import HtmlReportGenerator
from sampling_tool.io.importer import ExcelImporter, ImportProbe, ImportStats
from sampling_tool.io.multi_report_exporter import MultiSheetReportExporter
from sampling_tool.io.pdf_report import AuditTrailPDF
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import AuditRepo, DatasetRepo, SampleRepo
from sampling_tool.ui.controllers.sampling_paths import (
    DrawRequest,
    FieldValueStats,
    count_filter_matches,
    count_groups,
    draw_sample,
    field_value_stats,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sampling_tool.core.models import (
        AuditEvent,
        Dataset,
        Engagement,
        FilterCondition,
        SampleResult,
    )
    from sampling_tool.io.bdo_locations import BdoCompany, BdoLocation
    from sampling_tool.io.briefpapier import BriefpapierConfig
    from sampling_tool.ui.workers.task_worker import ProgressReporter


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImportProbeTask:
    """Vorprüfung + Vorschau einer Importdatei als Worker-Task (Sprint 97).

    Lädt die Blätter genau einmal (`ExcelImporter.probe`) – vorher passierte das
    bis zu dreimal auf dem UI-Thread. Kein DB-Zugriff. Das Ergebnis ist ein
    reines Daten-Objekt; calamine-Objekte verlassen den Worker-Thread nicht.
    """

    path: Path

    # Sprint 98 / C: liest nur – „Abbrechen" schließt sofort, der Worker läuft
    # im Hintergrund zu Ende und sein Ergebnis wird verworfen.
    detach_on_cancel: ClassVar[bool] = True

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> ImportProbe:
        return ExcelImporter(cancellation=cancellation).probe(self.path)


@dataclass(frozen=True, slots=True)
class ExcelImportTaskResult:
    """Rückgabe von `ExcelImportTask` – persistiertes Dataset + Stats."""

    dataset: Dataset
    stats: ImportStats


def unique_dataset_name(name: str, existing: Iterable[str]) -> str:
    """`name`, oder bei Kollision `name (2)`, `name (3)`, … – erste freie Nummer.

    Sprint 85 / E7: zweimal dieselbe Datei importiert hieß vorher zweimal gleich
    in der Sidebar. Nur der Anzeigename; die Werte bleiben unverändert, und
    bestehende Datensätze werden nicht umbenannt.
    """
    taken = set(existing)
    if name not in taken:
        return name
    n = 2
    while f"{name} ({n})" in taken:
        n += 1
    return f"{name} ({n})"


@dataclass(frozen=True, slots=True)
class ExcelImportTask:
    """Excel-Import + DB-Persist als einzelne Worker-Task.

    Eröffnet eine eigene `Database`-Instanz im Worker-Thread, persistiert
    das Dataset, schreibt den Audit-Log-Eintrag und schließt die
    Connection wieder. Damit gibt es keine Shared-Connection mit dem
    Main-Thread.

    ``sheet_name`` und ``header_row`` sind die Overrides aus dem
    `ImportOptionsDialog` (Sprint 16). ``configured`` schaltet bewusst
    explizit zwischen Auto-Import (``import_file``, Default) und dem
    Override-Pfad (``import_file_configured``) um – ein reiner ``None``-
    Check reicht seit Sprint 29 nicht mehr, weil ``header_row=None``
    („keine Kopfzeile") und ``sheet_name=None`` (CSV) gültige
    Override-Werte sind.
    """

    path: Path
    db_path: Path
    engagement_id: int
    user_name: str
    sheet_name: str | None = None
    header_row: int | None = None
    configured: bool = False

    def run(
        self,
        progress: ProgressReporter,
        cancellation: CancellationToken,
    ) -> ExcelImportTaskResult:
        importer = ExcelImporter(
            progress=progress.report,
            cancellation=cancellation,
        )
        if self.configured:
            result = importer.import_file_configured(self.path, self.sheet_name, self.header_row)
        else:
            result = importer.import_file(self.path)

        try:
            # Eigene Database-Connection im Worker-Thread – kein Shared-State
            # mit dem Main-Thread. WAL erlaubt parallele Reader, BEGIN IMMEDIATE
            # serialisiert den Writer.
            db = Database(self.db_path)
            try:
                with db.session() as conn:
                    # Sprint 85 / E7: in derselben Transaktion wie das Anlegen, damit
                    # kein paralleler Import denselben Namen bekommt.
                    existing = [
                        d.name for d in DatasetRepo(conn).list_for_engagement(self.engagement_id)
                    ]
                    dataset = replace(
                        result.dataset,
                        engagement_id=self.engagement_id,
                        name=unique_dataset_name(result.dataset.name, existing),
                    )
                    stored = DatasetRepo(conn).create(
                        dataset,
                        result.rows,
                        progress=progress.report,
                        cancellation=cancellation,
                    )
                    AuditLogger(AuditRepo(conn), self.user_name, self.engagement_id).log_import(
                        stored, rows_above_header=result.stats.rows_above_header
                    )
                # `stats` ist nach voller `rows`-Konsumierung gefüllt (Sprint 11.3).
                return ExcelImportTaskResult(dataset=stored, stats=result.stats)
            finally:
                db.close()
        finally:
            # Sprint 97 / B: scheitert das Persistieren, hielte der nicht erschöpfte
            # CSV-Generator die Datei offen, solange der Fortschrittsdialog lebt –
            # unter Windows ließe sie sich so lange nicht umbenennen oder löschen.
            close = getattr(result.rows, "close", None)
            if callable(close):
                close()


# ---------------------------------------------------------------------------
# Lese-Tasks des Stichproben-Dialogs (Sprint 98)
# ---------------------------------------------------------------------------

# SQLite ruft den Progress-Handler alle so viele VM-Anweisungen – damit bricht
# auch eine einzelne GROUP-BY-Abfrage ab, die vor der ersten Ergebniszeile scannt.
_SQLITE_CANCEL_CHECK_OPS = 10_000


@contextmanager
def _read_repo(db_path: Path, cancellation: CancellationToken) -> Iterator[DatasetRepo]:
    """Eigene, nur lesend genutzte Verbindung im Worker-Thread (Muster `ExcelImportTask`).

    Ein gesetztes Token unterbricht laufende SQL-Anweisungen; der dabei
    geworfene `sqlite3.OperationalError` wird zu `OperationCancelled`.
    """
    db = Database(db_path)
    try:
        conn = db.connect()
        conn.set_progress_handler(lambda: int(cancellation.is_set()), _SQLITE_CANCEL_CHECK_OPS)
        try:
            yield DatasetRepo(conn)
        except sqlite3.OperationalError:
            if cancellation.is_set():
                raise OperationCancelled() from None
            raise
    finally:
        db.close()


@dataclass(frozen=True, slots=True)
class FieldStatsTask:
    """Werteliste + Wertzählung einer Filterspalte (`field_value_stats`)."""

    db_path: Path
    dataset_id: int
    column: str

    detach_on_cancel: ClassVar[bool] = True

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> FieldValueStats:
        with _read_repo(self.db_path, cancellation) as repo:
            return field_value_stats(repo, self.dataset_id, self.column, cancellation)


@dataclass(frozen=True, slots=True)
class FilterCountTask:
    """Trefferzahl aller Filter (UND), optional innerhalb der aktiven Stichprobe."""

    db_path: Path
    dataset_id: int
    filters: tuple[FilterCondition, ...]
    restrict_to_ids: tuple[int, ...] | None = None

    detach_on_cancel: ClassVar[bool] = True

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> int:
        with _read_repo(self.db_path, cancellation) as repo:
            return count_filter_matches(
                repo, self.dataset_id, self.filters, self.restrict_to_ids, cancellation
            )


@dataclass(frozen=True, slots=True)
class GroupCountTask:
    """Anzahl Cluster bzw. Schichten einer Spalte (`count_groups`)."""

    db_path: Path
    dataset_id: int
    column: str

    detach_on_cancel: ClassVar[bool] = True

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> int:
        with _read_repo(self.db_path, cancellation) as repo:
            return count_groups(repo, self.dataset_id, self.column, cancellation)


@dataclass(frozen=True, slots=True)
class DrawSampleTask:
    """Probeziehung (`draw_sample`) – liest nur; gespeichert wird auf dem UI-Thread."""

    db_path: Path
    dataset: Dataset
    request: DrawRequest
    parent_ids: tuple[int, ...] | None

    detach_on_cancel: ClassVar[bool] = True

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> SampleResult:
        with _read_repo(self.db_path, cancellation) as repo:
            return draw_sample(repo, self.dataset, self.request, self.parent_ids, cancellation)


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
    # Sprint 74 / §2.2: der Zeitpunkt aus dem Export-Dialog. `None` = der
    # Writer liest selbst (Aufrufer ohne Dialog).
    now: datetime | None = None
    # Sprint 84 / C: vom Controller aufgelöster Dateiname (z. B. `…_2.xlsx`
    # nach der Rückfrage). `None` = Namensmuster des Exporters.
    filename: str | None = None
    # Sprint 89 / B4: Population stammt von vor Sprint 89 (Hinweis bei Filter).
    population_predates_basis: bool = False

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> Path:
        cancellation.raise_if_cancelled()
        progress.report(0, 1)
        db = Database(self.db_path)
        try:
            # Letzte Verteidigung (Sprint 86): die Zeilen-IDs einer Stichprobe
            # gelten nur in ihrem eigenen Datensatz. Bevor eine Zeile gelesen
            # wird – kein File, kein Audit-Event.
            owner = (
                SampleRepo(db.connect()).dataset_id_of(self.sample.id)
                if self.sample.id is not None
                else None
            )
            if owner is None or owner != self.dataset.id:
                raise ExportError(
                    f"Stichprobe #{self.sample.id} gehört nicht zum Datensatz "
                    f"„{self.dataset.name}“. Es wurde keine Datei geschrieben."
                )
            path = ExcelExporter().export_sample(
                self.sample,
                self.dataset,
                DatasetRepo(db.connect()),
                columns=self.columns,
                output_dir=self.output_dir,
                custom_name=self.custom_name,
                custom_id=self.custom_id,
                engagement=self.engagement,
                now=self.now,
                filename=self.filename,
                population_predates_basis=self.population_predates_basis,
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
    # Sprint 33 – gewählte BDO-Gesellschaft + Standort für den Adressblock.
    location: BdoLocation | None = None
    company: BdoCompany | None = None

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> Path:
        cancellation.raise_if_cancelled()
        progress.report(0, 1)
        # reportlab hat keinen Mid-Render-Cancel-Point. Wir prüfen nur
        # vor + nach dem Render. PDFs bei realistischen AuditTrail-Größen
        # (< 20k Events) sind seit Sprint 10.4 in < 2 s gerendert.
        AuditTrailPDF(
            briefpapier=self.briefpapier,
            location=self.location,
            company=self.company,
        ).render(
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
    dataset_ids_by_sample: dict[int, int] = field(default_factory=dict)
    sampling_details_by_sample: dict[int, dict[str, Any]] | None = None

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
            dataset_ids_by_sample=self.dataset_ids_by_sample,
            sampling_details_by_sample=self.sampling_details_by_sample,
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
    dataset_ids_by_sample: dict[int, int] = field(default_factory=dict)
    sampling_details_by_sample: dict[int, dict[str, Any]] | None = None

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
            dataset_ids_by_sample=self.dataset_ids_by_sample,
            sampling_details_by_sample=self.sampling_details_by_sample,
        )
        cancellation.raise_if_cancelled()
        progress.report(1, 1)
        return self.output_path
