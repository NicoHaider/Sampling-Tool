"""ExportController – 4 Export-Handler (Sample-xlsx, AuditTrail-PDF,
Excel-Multi-Sheet, HTML).

Sprint 13 / F-001: aus dem MainController-God-Object zerlegt. Nimmt
ausschließlich Lese-Operationen + Datei-Writes, keine Mutation am
Session-State.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

from PyQt6.QtWidgets import QMessageBox

from sampling_tool.audit.logger import AuditLogger
from sampling_tool.config import ARCHIVE_DIR_NAME
from sampling_tool.core.models import AuditEvent
from sampling_tool.io.bdo_locations import company_by_key, location_by_key
from sampling_tool.io.exporter import ExcelExporter, ExportError
from sampling_tool.persistence.repositories import AuditRepo
from sampling_tool.ui._scaling import scale_factor
from sampling_tool.ui.controllers._factories import ControllerFactories
from sampling_tool.ui.controllers.workspace_session import (
    AUDIT_EVENT_DISPLAY_LIMIT,
    WorkspaceSession,
)
from sampling_tool.ui.dialogs.existing_export_dialog import ExistingExportChoice
from sampling_tool.ui.dialogs.progress_dialog import TaskProgressDialog
from sampling_tool.ui.settings_store import save_settings
from sampling_tool.ui.workers.tasks import (
    AuditPdfExportTask,
    ExcelReportTask,
    HtmlReportTask,
    SampleExportTask,
)

logger = logging.getLogger(__name__)

#: Zeitstempel im Namen einer archivierten Export-Fassung – dasselbe Schema wie
#: die Projekt-Snapshots unter `archiv/` (Datum und Uhrzeit, dateisystemtauglich).
_ARCHIVE_TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"

#: Anzeige-Bezeichnungen der Berichte im Audit-Trail (`details["report"]`).
REPORT_AUDIT_PDF = "AuditTrail-PDF"
REPORT_EXCEL = "Excel-Bericht"
REPORT_HTML = "HTML-Bericht"


@dataclass(frozen=True, slots=True)
class ExportTarget:
    """Aufgelöstes Export-Ziel: wohin geschrieben wird, wohin die alte Fassung ging."""

    path: Path
    archived_previous: Path | None = None


def next_free_path(path: Path) -> Path:
    """Erste freie Variante `<stem>_2<suffix>`, `_3`, … neben `path`."""
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def archive_existing_export(path: Path, now: datetime) -> Path:
    """Verschiebt eine vorhandene Export-Datei nach `<Ordner>/archiv/`.

    Name: `<stem>_<Zeitstempel><suffix>`, bei Kollision (zweimal in derselben
    Sekunde) mit `_2`, `_3`, … – eine archivierte Fassung wird nie ersetzt.
    Wirft `OSError`, wenn Ordner oder Verschieben scheitern; dann liegt die
    Datei unverändert am alten Ort.
    """
    archive_dir = path.parent / ARCHIVE_DIR_NAME
    archive_dir.mkdir(exist_ok=True)
    target = archive_dir / f"{path.stem}_{now.strftime(_ARCHIVE_TIMESTAMP_FORMAT)}{path.suffix}"
    if target.exists():
        target = next_free_path(target)
    path.rename(target)
    return target


def filter_audit_events(
    events: Iterable[AuditEvent],
    event_types: Sequence[str] | set[str],
    date_from: date | None,
    date_to: date | None,
) -> list[AuditEvent]:
    """Filtert Audit-Events nach Aktionstyp und (optionalem) Zeitraum.

    `date_from`/`date_to` = None bedeutet „keine untere/obere Grenze" – ist
    der Audit-Export-Datumsfilter aus (Sprint 27, Default), kommen beide als
    None herein und der komplette Trail wird exportiert. Eine leere
    `event_types`-Menge filtert nicht nach Typ (alle Typen).
    """
    selected = set(event_types)
    return [
        e
        for e in events
        if (not selected or e.event_type in selected)
        and (date_from is None or e.timestamp.date() >= date_from)
        and (date_to is None or e.timestamp.date() <= date_to)
    ]


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

        default_dir = s.ensure_export_dir()
        # Sprint 82 / Befund B: vorgeschlagen wird die Nummer der exportierten
        # Stichprobe (= Statusleiste/Sidebar/AuditTrail), nicht „Anzahl + 1".
        dialog = self._factories.export_sample(
            s.window,
            s.dataset,
            s.dataset.name,
            str(s.sample.id),
            default_dir,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        result = dialog.get_result()
        if result is None:
            return
        target = self._resolve_export_target(
            result.output_dir
            / ExcelExporter.build_filename(result.custom_name, result.custom_id, result.now)
        )
        if target is None:
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
            output_dir=target.path.parent,
            custom_name=result.custom_name,
            custom_id=result.custom_id,
            engagement=s.engagement,
            # Sprint 74 / Befund B: derselbe Zeitpunkt, aus dem der Dialog
            # seine Vorschau gebaut hat – sonst könnte der Writer bei einem
            # Tageswechsel einen anderen {date}-Token schreiben, als der
            # Auditor im Dialog gelesen hat.
            now=result.now,
            filename=target.path.name,
        )
        progress_dialog = TaskProgressDialog("Exportiere Sample…", s.window)
        try:
            output_path = progress_dialog.run_task(task)
        except ExportError as exc:
            s.error(f"Sample-Export fehlgeschlagen: {exc}")
            return
        except Exception as exc:
            logger.exception("Sample-Export fehlgeschlagen")
            s.error(f"Sample-Export fehlgeschlagen: {exc}")
            return
        if output_path is None:
            return  # User-Cancel

        sample_id, row_count = s.sample.id, s.sample.actual_size
        self._log_export_with_retry(
            s,
            output_path,
            lambda audit: audit.log_export(
                sample_id, output_path, row_count, target.archived_previous
            ),
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
            s.ensure_export_dir(),
            s.settings.default_include_briefpapier,
            s.settings.default_include_statistics,
            s.settings.audit_export_offer_date_filter,
            s.settings.bdo_company_key,
            s.settings.bdo_location_key,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        result = dialog.get_result()
        if result is None:
            return
        target = self._resolve_export_target(result.output_path)
        if target is None:
            return

        # Sprint 33: gewählte BDO-Gesellschaft + Standort app-weit merken
        # (analog default_auditor_name) und auf die Daten-Objekte auflösen.
        new_settings = replace(
            s.settings,
            bdo_company_key=result.company_key,
            bdo_location_key=result.location_key,
        )
        save_settings(new_settings)
        s.settings = new_settings

        filtered = filter_audit_events(events, result.event_types, result.date_from, result.date_to)

        # Sprint 17: Worker-basiert.
        task = AuditPdfExportTask(
            engagement=s.engagement,
            events=filtered,
            output_path=target.path,
            briefpapier=briefpapier if result.use_briefpapier else None,
            include_statistics=result.include_statistics,
            company=company_by_key(result.company_key),
            location=location_by_key(result.location_key),
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
        self._log_report_export(s, output_path, REPORT_AUDIT_PDF, target)

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

        dialog = self._factories.excel_report(s.window, s.engagement, s.ensure_export_dir())
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        result = dialog.get_result()
        if result is None:
            return

        # Sprint 17: Worker-basiert.
        try:
            datasets, samples, events, dataset_ids_by_sample = s.collect_report_data()
        except Exception as exc:  # pragma: no cover – defensiv
            logger.exception("Excel-Report: Daten-Sammlung fehlgeschlagen")
            s.error(f"Excel-Report fehlgeschlagen: {exc}")
            return
        target = self._resolve_export_target(result.output_path)
        if target is None:
            return
        task = ExcelReportTask(
            engagement=s.engagement,
            datasets=datasets,
            samples=samples,
            audit_events=events,
            output_path=target.path,
            sheets=result.sheets,
            dataset_ids_by_sample=dataset_ids_by_sample,
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
        self._log_report_export(s, output_path, REPORT_EXCEL, target)
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

        dialog = self._factories.html_report(s.window, s.engagement, s.ensure_export_dir())
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        result = dialog.get_result()
        if result is None:
            return

        # Sprint 17: Worker-basiert.
        try:
            datasets, samples, events, dataset_ids_by_sample = s.collect_report_data()
        except Exception as exc:  # pragma: no cover – defensiv
            logger.exception("HTML-Report: Daten-Sammlung fehlgeschlagen")
            s.error(f"HTML-Report fehlgeschlagen: {exc}")
            return
        target = self._resolve_export_target(result.output_path)
        if target is None:
            return
        task = HtmlReportTask(
            engagement=s.engagement,
            datasets=datasets,
            samples=samples,
            audit_events=events,
            output_path=target.path,
            include_charts=result.include_charts,
            include_audit_trail=result.include_audit_trail,
            include_samples_table=result.include_samples_table,
            dataset_ids_by_sample=dataset_ids_by_sample,
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
        self._log_report_export(s, output_path, REPORT_HTML, target)
        QMessageBox.information(
            s.window,
            "HTML-Report erstellt",
            f"Bericht gespeichert unter:\n{output_path}",
        )

    # ---- intern --------------------------------------------------------

    def _resolve_export_target(self, planned: Path) -> ExportTarget | None:
        """Die eine Stelle, an der alle vier Exporte ihr Ziel festlegen (Sprint 84 / C).

        Existiert `planned` nicht, wird dorthin geschrieben. Sonst fragt der
        `ExistingExportDialog` VOR dem Worker: neuer Name (erste freie Nummer),
        überschreiben nach Sicherung der alten Fassung in `archiv/`, oder
        abbrechen. `None` heißt: nicht exportieren. Scheitert die Sicherung,
        wird nichts überschrieben – die vorhandene Datei bleibt, wo sie ist.
        """
        if not planned.exists():
            return ExportTarget(planned)
        s = self.session
        new_name = next_free_path(planned)
        dialog = self._factories.existing_export(
            s.window, planned, new_name, scale_factor(s.settings.ui_scale)
        )
        dialog.exec()
        choice = dialog.choice()
        if choice == ExistingExportChoice.NEW_NAME:
            return ExportTarget(new_name)
        if choice != ExistingExportChoice.OVERWRITE:
            return None
        try:
            archived = archive_existing_export(planned, s.now())
        except OSError as exc:
            logger.exception("Vorhandene Export-Datei konnte nicht archiviert werden")
            s.error(
                f"Die vorhandene Datei „{planned.name}“ konnte nicht gesichert werden. "
                f"Es wurde nichts überschrieben.\n\nUrsache: {exc}"
            )
            return None
        return ExportTarget(planned, archived)

    def _log_report_export(
        self, s: WorkspaceSession, export_file: Path, report: str, target: ExportTarget
    ) -> None:
        """`export`-Event für einen Bericht + Views auffrischen (Sprint 84 / C)."""
        self._log_export_with_retry(
            s,
            export_file,
            lambda audit: audit.log_report_export(export_file, report, target.archived_previous),
        )
        s.refresh_views()

    def _log_export_with_retry(
        self,
        s: WorkspaceSession,
        export_file: Path,
        write: Callable[[AuditLogger], object],
    ) -> None:
        """Schreibt das Export-Audit-Event. Schlägt das INSERT fehl, bleibt die
        bereits erstellte Exportdatei erhalten (Compliance-Entscheidung Nico,
        Sprint 42) – der Nutzer bekommt eine blockierende Warnung mit
        Retry-Option statt eines App-Absturzes ohne Trail-Eintrag.

        Der Loop endet nur bei Erfolg oder explizitem Abort-Klick – bewusst
        unbegrenzt, kein Bug (ein Retry-Limit würde das Compliance-Ziel
        unterlaufen).

        Reset/Undo/Redo nutzen stattdessen den einfacheren `WorkspaceController.
        _log_audit_event_safely` (warnen + weiterlaufen, kein Retry) – dort
        gibt es kein Datei-Artefakt zu erhalten, nur In-Memory-State.
        """
        assert s.db is not None
        assert s.engagement is not None
        assert s.engagement.id is not None
        while True:
            try:
                # s.db.connect() liefert die bereits offene Connection (kein Reconnect) –
                # der Retry wiederholt nur das INSERT, sinnvoll bei transienten Locks (WAL).
                write(AuditLogger(AuditRepo(s.db.connect()), s.user_name(), s.engagement.id))
                return
            except Exception:
                logger.exception("Audit-Log für Export fehlgeschlagen")
                answer = QMessageBox.warning(
                    s.window,
                    "Audit-Protokollierung fehlgeschlagen",
                    "Der Export wurde erstellt, konnte aber NICHT im Audit-Trail "
                    f"protokolliert werden – Datei „{export_file.name}“ ist nicht "
                    "prüfungssicher.",
                    QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Abort,
                    QMessageBox.StandardButton.Retry,
                )
                if answer != QMessageBox.StandardButton.Retry:
                    return
