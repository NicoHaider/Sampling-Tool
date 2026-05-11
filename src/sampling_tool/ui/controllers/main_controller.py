"""Glue-Logik zwischen `MainWindow` und Persistence/IO.

Der Controller ist die einzige Stelle, die `Database`/Repositories/IO öffnet.
UI-Signals werden hier in Repo-Operationen übersetzt und die Resultate an
das Fenster zurückgegeben. Damit bleibt das UI testbar ohne SQLite.

Undo/Redo-Konvention (verbindlich):
- Nach jeder mutierenden Aktion (Sampling, Reset) wird der NEUE State auf
  den Undo-Stack gelegt.
- `handle_undo()` entfernt den Top vom Undo-Stack (Push to Redo) und
  rekonstruiert den **dahinterliegenden** State via `peek_undo()`. Ist der
  Stack leer, gilt der „leere" Zustand (kein Sample, keine Highlights).
- `handle_redo()` holt den Top vom Redo-Stack zurück und wendet ihn an.
"""

from __future__ import annotations

import getpass
import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from sampling_tool.audit.logger import AuditLogger
from sampling_tool.config import (
    APP_NAME,
    EXPORT_DIR_NAME,
    SUPPORTED_CSV_SUFFIXES,
    SUPPORTED_EXCEL_SUFFIXES,
)
from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    Engagement,
    SampleResult,
    Snapshot,
)
from sampling_tool.core.sampling import SamplingError, create_sampler
from sampling_tool.core.undo import UndoManager
from sampling_tool.io.exporter import ExcelExporter, ExportError
from sampling_tool.io.importer import DataImportError, ExcelImporter
from sampling_tool.io.pdf_report import AuditTrailPDF
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import (
    AuditRepo,
    DatasetRepo,
    EngagementRepo,
    SampleRepo,
)
from sampling_tool.ui.dialogs.about_dialog import AboutDialog
from sampling_tool.ui.dialogs.bug_report_dialog import BugReportDialog
from sampling_tool.ui.dialogs.export_sample_dialog import ExportSampleDialog
from sampling_tool.ui.dialogs.new_engagement_dialog import NewEngagementDialog
from sampling_tool.ui.dialogs.sampling_dialog import SamplingDialog
from sampling_tool.ui.recent import RecentEngagementsStore

if TYPE_CHECKING:
    from sampling_tool.ui.main_window import MainWindow

logger = logging.getLogger(__name__)

DialogFactory = Callable[["MainWindow"], NewEngagementDialog]
SamplingDialogFactory = Callable[["MainWindow", Dataset, SampleResult | None], SamplingDialog]
ExportDialogFactory = Callable[["MainWindow", Dataset, str, str, Path | None], ExportSampleDialog]


class MainController:
    """Orchestriert UI ↔ DB ↔ Repositories. Lebenszyklus = App-Sitzung."""

    def __init__(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore | None = None,
        dialog_factory: DialogFactory | None = None,
        sampling_dialog_factory: SamplingDialogFactory | None = None,
        export_dialog_factory: ExportDialogFactory | None = None,
    ) -> None:
        self.window = window
        self.recent_store = recent_store if recent_store is not None else RecentEngagementsStore()
        self._dialog_factory = dialog_factory if dialog_factory is not None else NewEngagementDialog
        self._sampling_factory = (
            sampling_dialog_factory
            if sampling_dialog_factory is not None
            else _default_sampling_factory
        )
        self._export_factory = (
            export_dialog_factory if export_dialog_factory is not None else _default_export_factory
        )

        self._db: Database | None = None
        self._engagement: Engagement | None = None
        self._dataset: Dataset | None = None
        self._sample: SampleResult | None = None
        self._datasets: list[Dataset] = []
        self._filter_active_sample_id: int | None = None
        self._undo_manager: UndoManager | None = None

        self._connect_signals()
        self.refresh_recent()

    # ---- Public API ----------------------------------------------------

    def refresh_recent(self) -> None:
        """Liest die Recent-Liste und gibt sie ans Fenster."""
        self.recent_store.prune_missing()
        self.window.set_recent_entries(self.recent_store.list())

    # ---- Connect -------------------------------------------------------

    def _connect_signals(self) -> None:
        w = self.window
        w.new_engagement_requested.connect(self.handle_new_engagement)
        w.open_engagement_requested.connect(self.handle_open_engagement)
        w.close_engagement_requested.connect(self.handle_close_engagement)
        w.import_excel_requested.connect(self.handle_import_excel)
        w.new_sample_requested.connect(self.handle_new_sampling)
        w.reset_sample_requested.connect(self.handle_reset)
        w.undo_requested.connect(self.handle_undo)
        w.redo_requested.connect(self.handle_redo)
        w.export_sample_requested.connect(self.handle_export_sample)
        w.export_audit_pdf_requested.connect(self.handle_export_audit_pdf)
        w.bug_report_requested.connect(self.handle_bug_report)
        w.about_requested.connect(self.handle_about)
        w.dataset_selected.connect(self.handle_dataset_selected)
        w.sample_selected.connect(self.handle_sample_selected)
        w.sample_filter_toggled.connect(self.handle_sample_filter_toggled)

    # ---- Engagement-Lifecycle ------------------------------------------

    def handle_new_engagement(self) -> None:
        """Dialog anzeigen, neues Engagement anlegen + DB initialisieren."""
        dialog = self._dialog_factory(self.window)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        engagement = dialog.get_engagement()
        db_path = dialog.get_db_path()
        if db_path.exists():
            db_path.unlink()

        try:
            db = Database(db_path)
            db.migrate()
            created = EngagementRepo(db.connect()).get_or_create(engagement)
        except Exception as exc:  # pragma: no cover – defensiv
            logger.exception("Engagement-Anlage fehlgeschlagen")
            self._error(f"Engagement konnte nicht angelegt werden: {exc}")
            return

        self._adopt_database(db, db_path, created)

    def handle_open_engagement(self, db_path: Path) -> None:
        """Bestehende SQLite-Datei öffnen und Engagement laden."""
        if not db_path.exists():
            self._error(f"Datei '{db_path}' existiert nicht.")
            self.recent_store.remove(db_path)
            self.refresh_recent()
            return

        try:
            db = Database(db_path)
            db.migrate()
            engagement = EngagementRepo(db.connect()).get()
        except Exception as exc:
            logger.exception("Engagement öffnen fehlgeschlagen")
            self._error(f"Datenbank '{db_path.name}' kann nicht geöffnet werden: {exc}")
            return

        if engagement is None:
            self._error("Die ausgewählte Datei enthält kein Engagement.")
            return

        self._adopt_database(db, db_path, engagement)

    def handle_close_engagement(self) -> None:
        """Aktuelles Engagement schließen und zum Welcome-Screen wechseln."""
        if self._db is not None:
            self._db.close()
        self._db = None
        self._engagement = None
        self._dataset = None
        self._sample = None
        self._datasets = []
        self._filter_active_sample_id = None
        self._undo_manager = None
        self.window.clear_table()
        self.window.set_engagement(None)
        self.window.set_datasets([])
        self.window.set_samples([])
        self.window.show_welcome()
        self._update_undo_redo_state()
        self.refresh_recent()

    # ---- Import / Dataset ----------------------------------------------

    def handle_import_excel(self) -> None:
        """Excel-/CSV-Datei importieren und als Dataset persistieren."""
        if self._db is None or self._engagement is None or self._engagement.id is None:
            return

        accepted = "*" + " *".join(SUPPORTED_EXCEL_SUFFIXES + SUPPORTED_CSV_SUFFIXES)
        path_str, _filter = QFileDialog.getOpenFileName(
            self.window,
            "Datei importieren",
            "",
            f"Tabellen ({accepted});;Alle Dateien (*)",
        )
        if not path_str:
            return
        path = Path(path_str)

        try:
            result = ExcelImporter().import_file(path)
        except DataImportError as exc:
            self._error(f"Import fehlgeschlagen: {exc}")
            return

        dataset = replace(result.dataset, engagement_id=self._engagement.id)
        try:
            with self._db.session() as conn:
                stored = DatasetRepo(conn).create(dataset)
                AuditLogger(AuditRepo(conn), self._user_name(), self._engagement.id).log_import(
                    stored
                )
        except Exception as exc:  # pragma: no cover – defensiv
            logger.exception("Dataset persistieren fehlgeschlagen")
            self._error(f"Dataset konnte nicht gespeichert werden: {exc}")
            return

        self._reload_datasets()
        if stored.id is not None:
            self.handle_dataset_selected(stored.id)

        warning_text = ""
        if result.skipped_rows:
            warning_text += f"{result.skipped_rows} Leerzeile(n) übersprungen.\n"
        if result.warnings:
            warning_text += "\n".join(result.warnings)
        if warning_text:
            QMessageBox.information(self.window, "Import abgeschlossen", warning_text.strip())

    def handle_dataset_selected(self, dataset_id: int) -> None:
        """Dataset aus DB laden und in der Tabelle anzeigen."""
        if self._db is None:
            return
        dataset = DatasetRepo(self._db.connect()).get_by_id(dataset_id)
        if dataset is None:
            self._error(f"Dataset {dataset_id} nicht gefunden.")
            return

        self._dataset = dataset
        self._sample = None
        self._filter_active_sample_id = None
        self.window.show_dataset(dataset)

        samples = SampleRepo(self._db.connect()).list_for_dataset(dataset_id)
        self.window.set_samples(samples)
        self._update_undo_redo_state()

    def handle_sample_selected(self, sample_id: int) -> None:
        """Sample-Zeilen in der Tabelle gelb markieren + zur ersten scrollen."""
        if self._db is None:
            return
        sample = SampleRepo(self._db.connect()).get_by_id(sample_id)
        if sample is None:
            return
        self._sample = sample
        if self._filter_active_sample_id is not None:
            self.window.clear_sample_filter()
            self._filter_active_sample_id = None
        self.window.highlight_sample(sample)

    def handle_sample_filter_toggled(self, sample_id: int) -> None:
        """Doppelklick: Filter auf Sample-Zeilen ein/aus."""
        if self._db is None:
            return

        if self._filter_active_sample_id == sample_id:
            self.window.clear_sample_filter()
            self._filter_active_sample_id = None
            return

        sample = SampleRepo(self._db.connect()).get_by_id(sample_id)
        if sample is None:
            return
        self._sample = sample
        self.window.highlight_sample(sample)
        self.window.filter_to_sample(sample)
        self._filter_active_sample_id = sample_id

    # ---- Sampling ------------------------------------------------------

    def handle_new_sampling(self) -> None:
        """Sampling-Dialog öffnen, Stichprobe ziehen, persistieren, loggen."""
        if (
            self._db is None
            or self._dataset is None
            or self._dataset.id is None
            or self._engagement is None
            or self._engagement.id is None
        ):
            return

        dialog = self._sampling_factory(self.window, self._dataset, self._sample)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        result = dialog.get_result()
        if result is None:
            return

        try:
            sampler = create_sampler(result.config)
            effective_dataset = self._build_sampling_dataset(result.from_sample_only)
            sample_result = sampler.sample(effective_dataset)
        except SamplingError as exc:
            self._error(f"Stichprobe konnte nicht gezogen werden: {exc}")
            return

        parent_sample_id = (
            self._sample.id if result.from_sample_only and self._sample is not None else None
        )
        sample_result = replace(sample_result, parent_sample_id=parent_sample_id)

        try:
            with self._db.session() as conn:
                sample_id = SampleRepo(conn).create_from_result(
                    sample_result, self._dataset.id, self._user_name()
                )
                stored = replace(sample_result, id=sample_id)
                AuditLogger(AuditRepo(conn), self._user_name(), self._engagement.id).log_sampling(
                    stored, sample_id
                )
        except Exception as exc:  # pragma: no cover – defensiv
            logger.exception("Sample persistieren fehlgeschlagen")
            self._error(f"Sample konnte nicht gespeichert werden: {exc}")
            return

        # Sidebar + Tabelle aktualisieren.
        samples = SampleRepo(self._db.connect()).list_for_dataset(self._dataset.id)
        self.window.set_samples(samples)
        self._sample = stored
        self.window.highlight_sample(stored)
        self._push_undo_snapshot()
        self._update_undo_redo_state()

    def handle_reset(self) -> None:
        """Auswahl zurücksetzen (Highlights entfernen, Filter raus)."""
        if self._db is None or self._engagement is None or self._engagement.id is None:
            return
        if self._sample is None and not self._filter_active_sample_id:
            return

        answer = QMessageBox.question(
            self.window,
            "Auswahl zurücksetzen",
            "Sollen die aktuelle Sample-Hervorhebung und der Filter entfernt werden?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        if self._dataset is not None and self._dataset.id is not None:
            AuditLogger(
                AuditRepo(self._db.connect()), self._user_name(), self._engagement.id
            ).log_reset(self._dataset.id)

        self._sample = None
        self._filter_active_sample_id = None
        self.window.clear_sample_filter()
        self.window.data_table().clear_highlight()
        self._push_undo_snapshot()
        self._update_undo_redo_state()

    # ---- Undo / Redo ---------------------------------------------------

    def handle_undo(self) -> None:
        """Vorherigen Sample-Zustand wiederherstellen."""
        if self._undo_manager is None or not self._undo_manager.can_undo():
            return
        if self._db is None or self._engagement is None or self._engagement.id is None:
            return

        self._undo_manager.undo()
        previous = self._undo_manager.peek_undo()
        self._apply_snapshot(previous)
        if self._sample is not None and self._sample.id is not None:
            AuditLogger(
                AuditRepo(self._db.connect()), self._user_name(), self._engagement.id
            ).log_undo(self._sample.id)
        self._update_undo_redo_state()

    def handle_redo(self) -> None:
        """Letzten rückgängig gemachten Zustand wiederherstellen."""
        if self._undo_manager is None or not self._undo_manager.can_redo():
            return
        if self._db is None or self._engagement is None or self._engagement.id is None:
            return

        snapshot = self._undo_manager.redo()
        if snapshot is None:
            return
        self._apply_snapshot(snapshot)
        if self._sample is not None and self._sample.id is not None:
            AuditLogger(
                AuditRepo(self._db.connect()), self._user_name(), self._engagement.id
            ).log_redo(self._sample.id)
        self._update_undo_redo_state()

    # ---- Export --------------------------------------------------------

    def handle_export_sample(self) -> None:
        """Sample als Excel exportieren (Spaltenauswahl + Dateiname-Konfiguration)."""
        if (
            self._db is None
            or self._dataset is None
            or self._dataset.id is None
            or self._sample is None
            or self._sample.id is None
            or self._engagement is None
            or self._engagement.id is None
        ):
            self._error("Bitte zuerst ein Sample auswählen, bevor exportiert wird.")
            return

        next_id = self._next_sample_id_for_export(self._dataset.id)
        default_dir = self._default_export_dir()
        dialog = self._export_factory(
            self.window,
            self._dataset,
            self._dataset.name,
            str(next_id),
            default_dir,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        result = dialog.get_result()
        if result is None:
            return

        try:
            output_path = ExcelExporter().export_sample(
                self._sample,
                self._dataset,
                columns=result.columns,
                output_dir=result.output_dir,
                custom_name=result.custom_name,
                custom_id=result.custom_id,
                engagement=self._engagement,
            )
        except ExportError as exc:
            self._error(f"Export fehlgeschlagen: {exc}")
            return

        AuditLogger(
            AuditRepo(self._db.connect()), self._user_name(), self._engagement.id
        ).log_export(self._sample.id, output_path, self._sample.actual_size)

        QMessageBox.information(
            self.window,
            "Export erfolgreich",
            f"Sample wurde exportiert nach:\n{output_path}",
        )

    def handle_export_audit_pdf(self) -> None:
        """AuditTrail-PDF für das aktuelle Engagement exportieren."""
        if self._db is None or self._engagement is None or self._engagement.id is None:
            return

        default_name = f"AuditTrail_{_safe_filename(self._engagement.client_name)}.pdf"
        path_str, _filter = QFileDialog.getSaveFileName(
            self.window,
            "AuditTrail-PDF speichern",
            default_name,
            "PDF (*.pdf)",
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix.lower() != ".pdf":
            path = path.with_suffix(".pdf")

        events = AuditRepo(self._db.connect()).list_for_engagement(
            self._engagement.id, limit=10_000
        )
        try:
            AuditTrailPDF().render(self._engagement, events, path)
        except Exception as exc:  # pragma: no cover – defensiv
            logger.exception("PDF-Export fehlgeschlagen")
            self._error(f"PDF-Export fehlgeschlagen: {exc}")
            return
        QMessageBox.information(
            self.window, "AuditTrail exportiert", f"PDF gespeichert unter:\n{path}"
        )

    # ---- Help ----------------------------------------------------------

    def handle_bug_report(self) -> None:
        """Bug-Report-Dialog öffnen (mailto-Fallback)."""
        BugReportDialog(self.window).exec()

    def handle_about(self) -> None:
        """About-Dialog öffnen."""
        AboutDialog(self.window).exec()

    # ---- intern --------------------------------------------------------

    def _adopt_database(self, db: Database, db_path: Path, engagement: Engagement) -> None:
        """Setzt internen State auf ein frisches/geöffnetes Engagement und aktualisiert das UI."""
        if self._db is not None and self._db is not db:
            self._db.close()

        self._db = db
        self._engagement = engagement
        self._dataset = None
        self._sample = None
        self._filter_active_sample_id = None
        if engagement.id is not None:
            self._undo_manager = UndoManager(db, engagement.id)
        else:
            self._undo_manager = None

        self.window.set_engagement(engagement)
        self.window.show_workspace()
        self._reload_datasets()
        self.window.set_samples([])
        self.window.clear_table()
        self._update_undo_redo_state()

        self.recent_store.add(
            db_path,
            client_name=engagement.client_name,
            audit_type=engagement.audit_type or "",
        )
        self.refresh_recent()

    def _reload_datasets(self) -> None:
        if self._db is None or self._engagement is None or self._engagement.id is None:
            return
        self._datasets = DatasetRepo(self._db.connect()).list_for_engagement(self._engagement.id)
        self.window.set_datasets(self._datasets)

    def _build_sampling_dataset(self, from_sample_only: bool) -> Dataset:
        """Liefert das Dataset, auf dem der Sampler arbeitet.

        Bei Resampling werden die Rows auf die Auswahl des aktuellen Samples
        eingeschränkt – ohne dass das Persistenz-Dataset selbst modifiziert wird.
        """
        assert self._dataset is not None
        if not from_sample_only or self._sample is None:
            return self._dataset
        wanted = set(self._sample.selected_row_ids)
        filtered: tuple[DatasetRow, ...] = tuple(
            r for r in self._dataset.rows if r.row_id in wanted
        )
        return replace(self._dataset, rows=filtered)

    def _push_undo_snapshot(self) -> None:
        if self._undo_manager is None:
            return
        sample_id = self._sample.id if self._sample is not None else None
        highlighted = list(self._sample.selected_row_ids) if self._sample is not None else []
        visible = (
            list(self._sample.selected_row_ids)
            if self._filter_active_sample_id is not None and self._sample is not None
            else []
        )
        self._undo_manager.push(
            sample_id=sample_id,
            visible_rows=visible,
            highlighted_rows=highlighted,
        )

    def _apply_snapshot(self, snapshot: Snapshot | None) -> None:
        """Wendet einen `Snapshot` (oder den leeren Initialzustand) auf das UI an."""
        if self._db is None:
            return

        if snapshot is None or snapshot.sample_id is None:
            self._sample = None
            self._filter_active_sample_id = None
            self.window.clear_sample_filter()
            self.window.data_table().clear_highlight()
            return

        sample = SampleRepo(self._db.connect()).get_by_id(snapshot.sample_id)
        if sample is None:
            # Sample wurde zwischenzeitlich gelöscht – defensiv: leeren State anwenden.
            self._sample = None
            self.window.data_table().clear_highlight()
            return

        self._sample = sample
        if snapshot.visible_rows:
            self.window.filter_to_sample(sample)
            self._filter_active_sample_id = sample.id
        else:
            self.window.clear_sample_filter()
            self._filter_active_sample_id = None
        self.window.highlight_sample(sample)

    def _update_undo_redo_state(self) -> None:
        """Schaltet die Undo-/Redo-Menüpunkte basierend auf dem Stack-Status."""
        can_undo = self._undo_manager is not None and self._undo_manager.can_undo()
        can_redo = self._undo_manager is not None and self._undo_manager.can_redo()
        self.window.set_undo_redo_enabled(can_undo, can_redo)
        has_sample = self._sample is not None
        self.window.set_reset_enabled(has_sample or self._filter_active_sample_id is not None)

    def _next_sample_id_for_export(self, dataset_id: int) -> int:
        if self._db is None:
            return 1
        samples = SampleRepo(self._db.connect()).list_for_dataset(dataset_id)
        return len(samples) + 1

    def _default_export_dir(self) -> Path:
        if self._db is not None:
            return self._db.db_path.parent / EXPORT_DIR_NAME
        return Path.cwd() / EXPORT_DIR_NAME

    def _error(self, message: str) -> None:
        logger.error(message)
        QMessageBox.warning(self.window, APP_NAME, message)

    @staticmethod
    def _user_name() -> str:
        try:
            return getpass.getuser()
        except OSError:  # pragma: no cover
            return "system"


# ---------------------------------------------------------------------------
# Default-Factories
# ---------------------------------------------------------------------------


def _default_sampling_factory(
    parent: MainWindow, dataset: Dataset, current_sample: SampleResult | None
) -> SamplingDialog:
    return SamplingDialog(dataset, current_sample=current_sample, parent=parent)


def _default_export_factory(
    parent: MainWindow,
    dataset: Dataset,
    default_name: str,
    default_id: str,
    default_dir: Path | None,
) -> ExportSampleDialog:
    return ExportSampleDialog(
        dataset,
        default_name=default_name,
        default_id=default_id,
        default_output_dir=default_dir,
        parent=parent,
    )


def _safe_filename(token: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in token).strip()
    return cleaned.replace(" ", "_") or "AuditTrail"
