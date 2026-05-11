"""Glue-Logik zwischen `MainWindow` und Persistence/IO.

Der Controller ist die einzige Stelle, die `Database`/Repositories/IO öffnet.
UI-Signals werden hier in Repo-Operationen übersetzt und die Resultate an
das Fenster zurückgegeben. Damit bleibt das UI testbar ohne SQLite.
"""

from __future__ import annotations

import getpass
import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from sampling_tool.audit.logger import AuditLogger
from sampling_tool.config import APP_NAME, SUPPORTED_CSV_SUFFIXES, SUPPORTED_EXCEL_SUFFIXES
from sampling_tool.core.models import Dataset, Engagement, SampleResult
from sampling_tool.io.importer import DataImportError, ExcelImporter
from sampling_tool.io.pdf_report import AuditTrailPDF
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import (
    AuditRepo,
    DatasetRepo,
    EngagementRepo,
    SampleRepo,
)
from sampling_tool.ui.dialogs.new_engagement_dialog import NewEngagementDialog
from sampling_tool.ui.main_window import MainWindow
from sampling_tool.ui.recent import RecentEngagementsStore

logger = logging.getLogger(__name__)

DialogFactory = Callable[[MainWindow], NewEngagementDialog]


class MainController:
    """Orchestriert UI ↔ DB ↔ Repositories. Lebenszyklus = App-Sitzung."""

    def __init__(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore | None = None,
        dialog_factory: DialogFactory | None = None,
    ) -> None:
        self.window = window
        self.recent_store = recent_store if recent_store is not None else RecentEngagementsStore()
        self._dialog_factory = dialog_factory if dialog_factory is not None else NewEngagementDialog

        self._db: Database | None = None
        self._engagement: Engagement | None = None
        self._dataset: Dataset | None = None
        self._sample: SampleResult | None = None
        self._datasets: list[Dataset] = []
        self._filter_active_sample_id: int | None = None

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
        w.export_audit_pdf_requested.connect(self.handle_export_audit_pdf)
        w.dataset_selected.connect(self.handle_dataset_selected)
        w.sample_selected.connect(self.handle_sample_selected)
        w.sample_filter_toggled.connect(self.handle_sample_filter_toggled)

    # ---- Handlers ------------------------------------------------------

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
        self.window.clear_table()
        self.window.set_engagement(None)
        self.window.set_datasets([])
        self.window.set_samples([])
        self.window.show_welcome()
        self.refresh_recent()

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

    def handle_export_audit_pdf(self) -> None:
        """AuditTrail-PDF für das aktuelle Engagement exportieren."""
        if self._db is None or self._engagement is None or self._engagement.id is None:
            return

        path_str, _filter = QFileDialog.getSaveFileName(
            self.window,
            "AuditTrail-PDF speichern",
            "audit_trail.pdf",
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

    # ---- intern --------------------------------------------------------

    def _adopt_database(self, db: Database, db_path: Path, engagement: Engagement) -> None:
        """Setzt internen State auf ein frisches/geöffnetes Engagement und aktualisiert das UI."""
        # Vorherige DB schließen (Welcome-Wechsel bekommt das nicht mit).
        if self._db is not None and self._db is not db:
            self._db.close()

        self._db = db
        self._engagement = engagement
        self._dataset = None
        self._sample = None
        self._filter_active_sample_id = None

        self.window.set_engagement(engagement)
        self.window.show_workspace()
        self._reload_datasets()
        self.window.set_samples([])
        self.window.clear_table()

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

    def _error(self, message: str) -> None:
        logger.error(message)
        QMessageBox.warning(self.window, APP_NAME, message)

    @staticmethod
    def _user_name() -> str:
        try:
            return getpass.getuser()
        except OSError:  # pragma: no cover
            return "system"
