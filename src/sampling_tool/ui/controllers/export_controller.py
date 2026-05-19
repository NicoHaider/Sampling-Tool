"""ExportController – 4 Export-Handler (Sample-xlsx, AuditTrail-PDF,
Excel-Multi-Sheet, HTML).

Sprint 13 / F-001: aus dem MainController-God-Object zerlegt. Nimmt
ausschließlich Lese-Operationen + Datei-Writes, keine Mutation am
Session-State.
"""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import QMessageBox

from sampling_tool.audit.logger import AuditLogger
from sampling_tool.io.exporter import ExportError
from sampling_tool.persistence.repositories import AuditRepo, SampleRepo
from sampling_tool.ui.controllers._factories import ControllerFactories
from sampling_tool.ui.controllers.workspace_session import (
    AUDIT_EVENT_DISPLAY_LIMIT,
    WorkspaceSession,
)
from sampling_tool.ui.dialogs.progress_dialog import TaskProgressDialog
from sampling_tool.ui.workers.tasks import (
    AuditPdfExportTask,
    ExcelReportTask,
    HtmlReportTask,
    SampleExportTask,
)

logger = logging.getLogger(__name__)


class ExportController:
    """Sample-/Report-Export-Pfade."""

    def __init__(self, session: WorkspaceSession, factories: ControllerFactories) -> None:
        self.session = session
        self._factories = factories

    # ---- Sample-Export -------------------------------------------------

    def handle_export_sample(self) -> None:
        """Sample als Excel exportieren (Spaltenauswahl + Dateiname-Konfiguration)."""
        if not self.session.has_active_sample():
            self.session.error("Bitte zuerst ein Sample auswählen, bevor exportiert wird.")
            return
        s = self.session
        assert s.db is not None
        assert s.dataset is not None
        assert s.dataset.id is not None
        assert s.sample is not None
        assert s.sample.id is not None
        assert s.engagement is not None
        assert s.engagement.id is not None

        next_id = self._next_sample_id_for_export(s.dataset.id)
        default_dir = s.default_export_dir()
        dialog = self._factories.export_sample(
            s.window,
            s.dataset,
            s.dataset.name,
            str(next_id),
            default_dir,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        result = dialog.get_result()
        if result is None:
            return

        # Sprint 11.4: Exporter zieht sich die Sample-Rows on-demand via
        # `get_rows_by_ids` – kein voll materialisiertes Dataset mehr.
        # Bei 1M-Dataset und 1k-Sample werden nur 1k Rows aus der DB
        # geholt statt 1M.
        # Sprint 17: Worker-basiert – UI bleibt während des Exports responsiv.
        task = SampleExportTask(
            sample=s.sample,
            dataset=s.dataset,
            db_path=s.db.db_path,
            columns=result.columns,
            output_dir=result.output_dir,
            custom_name=result.custom_name,
            custom_id=result.custom_id,
            engagement=s.engagement,
        )
        progress_dialog = TaskProgressDialog("Exportiere Sample…", s.window)
        try:
            output_path = progress_dialog.run_task(task)
        except ExportError as exc:
            s.error(f"Export fehlgeschlagen: {exc}")
            return
        if output_path is None:
            return  # User-Cancel

        AuditLogger(AuditRepo(s.db.connect()), s.user_name(), s.engagement.id).log_export(
            s.sample.id, output_path, s.sample.actual_size
        )
        s.refresh_views()

        QMessageBox.information(
            s.window,
            "Export erfolgreich",
            f"Sample wurde exportiert nach:\n{output_path}",
        )

    # ---- AuditTrail-PDF ------------------------------------------------

    def handle_export_audit_pdf(self) -> None:
        """AuditTrail-PDF für das aktuelle Engagement exportieren.

        Öffnet den `ExportAuditPdfDialog`, filtert die Events nach gewähltem
        Zeitraum und Aktionstypen und rendert das PDF mit den gewünschten
        Optionen (Briefpapier-Layer, Statistik-Block).
        """
        if not self.session.has_engagement():
            return
        s = self.session
        assert s.db is not None
        assert s.engagement is not None
        assert s.engagement.id is not None

        events = AuditRepo(s.db.connect()).list_for_engagement(
            s.engagement.id, limit=AUDIT_EVENT_DISPLAY_LIMIT
        )
        available_types = sorted({e.event_type for e in events})
        briefpapier = s.resolve_briefpapier()

        dialog = self._factories.audit_pdf(
            s.window,
            s.engagement,
            available_types,
            briefpapier is not None,
            s.default_export_dir(),
            s.settings.default_include_briefpapier,
            s.settings.default_include_statistics,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        result = dialog.get_result()
        if result is None:
            return

        filtered = [
            e
            for e in events
            if (not result.event_types or e.event_type in result.event_types)
            and (result.date_from is None or e.timestamp.date() >= result.date_from)
            and (result.date_to is None or e.timestamp.date() <= result.date_to)
        ]

        # Sprint 17: Worker-basiert.
        task = AuditPdfExportTask(
            engagement=s.engagement,
            events=filtered,
            output_path=result.output_path,
            briefpapier=briefpapier if result.use_briefpapier else None,
            include_statistics=result.include_statistics,
        )
        progress_dialog = TaskProgressDialog("Erstelle AuditTrail-PDF…", s.window)
        try:
            output_path = progress_dialog.run_task(task)
        except Exception as exc:  # pragma: no cover – defensiv
            logger.exception("PDF-Export fehlgeschlagen")
            s.error(f"PDF-Export fehlgeschlagen: {exc}")
            return
        if output_path is None:
            return  # User-Cancel

        QMessageBox.information(
            s.window,
            "AuditTrail-PDF exportiert",
            f"Datei: {output_path.name}\n{len(filtered)} Events",
        )

    # ---- Multi-Sheet Excel-Report --------------------------------------

    def handle_export_excel_report(self) -> None:
        """Multi-Sheet Excel-Report für das aktuelle Engagement."""
        if not self.session.has_engagement():
            return
        s = self.session
        assert s.engagement is not None

        dialog = self._factories.excel_report(s.window, s.engagement, s.default_export_dir())
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        result = dialog.get_result()
        if result is None:
            return

        # Sprint 17: Worker-basiert.
        try:
            datasets, samples, events = s.collect_report_data()
        except Exception as exc:  # pragma: no cover – defensiv
            logger.exception("Excel-Report: Daten-Sammlung fehlgeschlagen")
            s.error(f"Excel-Report fehlgeschlagen: {exc}")
            return
        task = ExcelReportTask(
            engagement=s.engagement,
            datasets=datasets,
            samples=samples,
            audit_events=events,
            output_path=result.output_path,
            sheets=result.sheets,
        )
        progress_dialog = TaskProgressDialog("Erstelle Excel-Report…", s.window)
        try:
            output_path = progress_dialog.run_task(task)
        except Exception as exc:  # pragma: no cover – defensiv
            logger.exception("Excel-Report fehlgeschlagen")
            s.error(f"Excel-Report fehlgeschlagen: {exc}")
            return
        if output_path is None:
            return  # User-Cancel
        QMessageBox.information(
            s.window,
            "Excel-Report erstellt",
            f"Bericht gespeichert unter:\n{output_path}",
        )

    # ---- HTML-Report ---------------------------------------------------

    def handle_export_html_report(self) -> None:
        """HTML-Report für E-Mail-Versand."""
        if not self.session.has_engagement():
            return
        s = self.session
        assert s.engagement is not None

        dialog = self._factories.html_report(s.window, s.engagement, s.default_export_dir())
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        result = dialog.get_result()
        if result is None:
            return

        # Sprint 17: Worker-basiert.
        try:
            datasets, samples, events = s.collect_report_data()
        except Exception as exc:  # pragma: no cover – defensiv
            logger.exception("HTML-Report: Daten-Sammlung fehlgeschlagen")
            s.error(f"HTML-Report fehlgeschlagen: {exc}")
            return
        task = HtmlReportTask(
            engagement=s.engagement,
            datasets=datasets,
            samples=samples,
            audit_events=events,
            output_path=result.output_path,
            include_charts=result.include_charts,
            include_audit_trail=result.include_audit_trail,
            include_samples_table=result.include_samples_table,
        )
        progress_dialog = TaskProgressDialog("Erstelle HTML-Report…", s.window)
        try:
            output_path = progress_dialog.run_task(task)
        except Exception as exc:  # pragma: no cover – defensiv
            logger.exception("HTML-Report fehlgeschlagen")
            s.error(f"HTML-Report fehlgeschlagen: {exc}")
            return
        if output_path is None:
            return  # User-Cancel
        QMessageBox.information(
            s.window,
            "HTML-Report erstellt",
            f"Bericht gespeichert unter:\n{output_path}",
        )

    # ---- intern --------------------------------------------------------

    def _next_sample_id_for_export(self, dataset_id: int) -> int:
        """Fortlaufende Sample-Nummer für den Filename-Token (ID-Spalte)."""
        if self.session.db is None:
            return 1
        samples = SampleRepo(self.session.db.connect()).list_for_dataset(dataset_id)
        return len(samples) + 1
