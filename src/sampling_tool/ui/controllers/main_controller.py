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
from collections.abc import Callable, Iterable, Sequence
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
    AuditEvent,
    Dataset,
    DatasetRow,
    Engagement,
    SampleResult,
    Snapshot,
)
from sampling_tool.core.sampling import SamplingError, create_sampler
from sampling_tool.core.undo import UndoManager
from sampling_tool.io.briefpapier import (
    BriefpapierConfig,
    briefpapier_from_path,
    get_default_briefpapier,
)
from sampling_tool.io.exporter import ExcelExporter, ExportError
from sampling_tool.io.html_report import HtmlReportGenerator
from sampling_tool.io.importer import DataImportError, ExcelImporter
from sampling_tool.io.multi_report_exporter import MultiSheetReportExporter
from sampling_tool.io.pdf_report import AuditTrailPDF
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import (
    AuditRepo,
    DatasetRepo,
    EngagementRepo,
    EngagementStateRepo,
    SampleRepo,
)
from sampling_tool.persistence.version_manager import EngagementVersionManager
from sampling_tool.ui.dialogs.about_dialog import AboutDialog
from sampling_tool.ui.dialogs.bug_report_dialog import BugReportDialog
from sampling_tool.ui.dialogs.duplicate_engagement_dialog import (
    DuplicateEngagementChoice,
    DuplicateEngagementDialog,
)
from sampling_tool.ui.dialogs.export_audit_pdf_dialog import ExportAuditPdfDialog
from sampling_tool.ui.dialogs.export_excel_report_dialog import ExportExcelReportDialog
from sampling_tool.ui.dialogs.export_html_report_dialog import ExportHtmlReportDialog
from sampling_tool.ui.dialogs.export_sample_dialog import ExportSampleDialog
from sampling_tool.ui.dialogs.new_engagement_dialog import NewEngagementDialog
from sampling_tool.ui.dialogs.sampling_dialog import SamplingDialog
from sampling_tool.ui.dialogs.settings_dialog import SettingsDialog
from sampling_tool.ui.recent import RecentEngagementsStore
from sampling_tool.ui.settings_store import AppSettings, load_settings, save_settings

if TYPE_CHECKING:
    from sampling_tool.ui.main_window import MainWindow

logger = logging.getLogger(__name__)

DialogFactory = Callable[["MainWindow", AppSettings, Engagement | None], NewEngagementDialog]
DuplicateDialogFactory = Callable[["MainWindow", Path], DuplicateEngagementDialog]
SamplingDialogFactory = Callable[
    ["MainWindow", Dataset, Sequence[DatasetRow] | None, SampleResult | None, bool],
    SamplingDialog,
]
ExportDialogFactory = Callable[["MainWindow", Dataset, str, str, Path | None], ExportSampleDialog]
AuditPdfDialogFactory = Callable[
    ["MainWindow", Engagement, list[str], bool, Path | None, bool, bool],
    ExportAuditPdfDialog,
]
ExcelReportDialogFactory = Callable[
    ["MainWindow", Engagement, Path | None], ExportExcelReportDialog
]
HtmlReportDialogFactory = Callable[["MainWindow", Engagement, Path | None], ExportHtmlReportDialog]
SettingsDialogFactory = Callable[["MainWindow", AppSettings], SettingsDialog]


class MainController:
    """Orchestriert UI ↔ DB ↔ Repositories. Lebenszyklus = App-Sitzung."""

    def __init__(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore | None = None,
        dialog_factory: DialogFactory | None = None,
        duplicate_dialog_factory: DuplicateDialogFactory | None = None,
        sampling_dialog_factory: SamplingDialogFactory | None = None,
        export_dialog_factory: ExportDialogFactory | None = None,
        audit_pdf_dialog_factory: AuditPdfDialogFactory | None = None,
        excel_report_dialog_factory: ExcelReportDialogFactory | None = None,
        html_report_dialog_factory: HtmlReportDialogFactory | None = None,
        settings_dialog_factory: SettingsDialogFactory | None = None,
        settings: AppSettings | None = None,
    ) -> None:
        self.window = window
        self.recent_store = recent_store if recent_store is not None else RecentEngagementsStore()
        self._settings = settings if settings is not None else load_settings()
        self._dialog_factory = (
            dialog_factory if dialog_factory is not None else _default_new_engagement_factory
        )
        self._duplicate_factory = (
            duplicate_dialog_factory
            if duplicate_dialog_factory is not None
            else _default_duplicate_dialog_factory
        )
        self._sampling_factory = (
            sampling_dialog_factory
            if sampling_dialog_factory is not None
            else _default_sampling_factory
        )
        self._export_factory = (
            export_dialog_factory if export_dialog_factory is not None else _default_export_factory
        )
        self._audit_pdf_factory = (
            audit_pdf_dialog_factory
            if audit_pdf_dialog_factory is not None
            else _default_audit_pdf_factory
        )
        self._excel_report_factory = (
            excel_report_dialog_factory
            if excel_report_dialog_factory is not None
            else _default_excel_report_factory
        )
        self._html_report_factory = (
            html_report_dialog_factory
            if html_report_dialog_factory is not None
            else _default_html_report_factory
        )
        self._settings_factory = (
            settings_dialog_factory
            if settings_dialog_factory is not None
            else _default_settings_factory
        )

        self._db: Database | None = None
        self._engagement: Engagement | None = None
        self._dataset: Dataset | None = None
        self._sample: SampleResult | None = None
        self._datasets: list[Dataset] = []
        self._filter_active_sample_id: int | None = None
        # Aktuell hervorgehobenes Sample (überlebt einen Dataset-Klick, sofern
        # das Sample weiterhin zum geklickten Dataset gehört).
        self._active_sample_id: int | None = None
        self._undo_manager: UndoManager | None = None
        self._state_repo: EngagementStateRepo | None = None
        # `_restoring_state` blockiert `_persist_state` während des Restore-
        # Vorgangs, damit der frisch eingelesene State nicht durch jeden
        # einzelnen `handle_*`-Aufruf (Dataset, Sample, Filter) sofort
        # zwischenüberschrieben wird.
        self._restoring_state: bool = False

        # Engagement-Ordner aus Settings sicherstellen, damit File-Dialoge
        # direkt dort starten können. Idempotent.
        self._settings.engagements_dir.mkdir(parents=True, exist_ok=True)

        self._connect_signals()
        self.refresh_recent()
        # Initiales Panel-Sichtbarkeits-Setup aus AppSettings anwenden.
        self.window.apply_panel_visibility(
            show_dashboard=self._settings.show_dashboard,
            show_audit_trail=self._settings.show_audit_trail,
        )

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
        w.close_engagement_requested.connect(self.handle_close_engagement_requested)
        w.import_excel_requested.connect(self.handle_import_excel)
        w.new_sample_requested.connect(self.handle_new_sampling)
        w.reset_sample_requested.connect(self.handle_reset)
        w.undo_requested.connect(self.handle_undo)
        w.redo_requested.connect(self.handle_redo)
        w.export_sample_requested.connect(self.handle_export_sample)
        w.export_audit_pdf_requested.connect(self.handle_export_audit_pdf)
        w.export_excel_report_requested.connect(self.handle_export_excel_report)
        w.export_html_report_requested.connect(self.handle_export_html_report)
        w.bug_report_requested.connect(self.handle_bug_report)
        w.about_requested.connect(self.handle_about)
        w.settings_requested.connect(self.handle_settings)
        w.hotkeys_requested.connect(self.handle_hotkeys)
        w.dataset_selected.connect(self.handle_dataset_selected)
        w.sample_selected.connect(self.handle_sample_selected)
        w.sample_filter_toggled.connect(self.handle_sample_filter_toggled)
        w.filter_only_sample_toggled.connect(self.handle_filter_only_sample_toggled)
        w.audit_event_double_clicked.connect(self.handle_audit_event_double_clicked)
        w.audit_refresh_requested.connect(self._refresh_audit_trail)
        w.dashboard_refresh_requested.connect(self._refresh_dashboard)

    # ---- Engagement-Lifecycle ------------------------------------------

    def handle_new_engagement(self) -> None:
        """Dialog anzeigen, neues Engagement anlegen + DB initialisieren.

        Wenn der gewählte Ziel-DB-Pfad bereits existiert, wird der
        `DuplicateEngagementDialog` gezeigt – der User kann dann das
        bestehende Engagement öffnen, einen anderen Namen wählen
        (Dialog wird mit den bisherigen Werten erneut geöffnet) oder
        komplett abbrechen. Verhindert versehentliches Überschreiben.
        """
        prefill: Engagement | None = None
        while True:
            dialog = self._dialog_factory(self.window, self._settings, prefill)
            if dialog.exec() != dialog.DialogCode.Accepted:
                return

            engagement = dialog.get_engagement()
            db_path = dialog.get_db_path()

            if db_path.exists():
                choice = self._prompt_duplicate(db_path)
                if choice is DuplicateEngagementChoice.OPEN_EXISTING:
                    self.handle_open_engagement(db_path)
                    return
                if choice is DuplicateEngagementChoice.RENAME:
                    prefill = engagement
                    continue
                # CANCEL → komplettes Abbrechen
                return

            try:
                db = Database(db_path)
                db.migrate()
                created = EngagementRepo(db.connect()).get_or_create(engagement)
            except Exception as exc:  # pragma: no cover – defensiv
                logger.exception("Engagement-Anlage fehlgeschlagen")
                self._error(f"Engagement konnte nicht angelegt werden: {exc}")
                return

            self._adopt_database(db, db_path, created)
            return

    def _prompt_duplicate(self, db_path: Path) -> DuplicateEngagementChoice:
        """Zeigt den DuplicateEngagementDialog und liefert das User-Choice."""
        dialog = self._duplicate_factory(self.window, db_path)
        dialog.exec()
        return dialog.choice()

    def handle_open_engagement(self, db_path: Path) -> None:
        """Bestehende SQLite-Datei öffnen und Engagement laden."""
        if not db_path.exists():
            self._error(f"Datei '{db_path}' existiert nicht.")
            self.recent_store.remove(db_path)
            self.refresh_recent()
            return

        # Compliance-Snapshot BEVOR die Session anfängt – ein Fehler dabei
        # soll das Öffnen nicht blockieren (Defense-in-Depth, nicht kritisch).
        try:
            EngagementVersionManager(db_path).create_snapshot(self._user_name())
        except Exception:
            logger.exception("Snapshot beim Öffnen fehlgeschlagen (nicht-kritisch)")

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

    def handle_close_engagement_requested(self) -> None:
        """Vom UI angefragtes Schließen – fragt nach Bestätigung, schließt dann."""
        if self._db is None:
            return
        answer = QMessageBox.question(
            self.window,
            "Engagement schließen",
            "Engagement schließen und zum Startbildschirm zurückkehren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.handle_close_engagement()

    def handle_close_engagement(self) -> None:
        """Aktuelles Engagement schließen und zum Welcome-Screen wechseln."""
        if self._db is not None:
            self._db.close()
        self._db = None
        self._engagement = None
        self._dataset = None
        self._sample = None
        self._active_sample_id = None
        self._datasets = []
        self._filter_active_sample_id = None
        self._undo_manager = None
        self.window.data_table().clear_dataset()
        self._state_repo = None
        self._restoring_state = False
        self.window.set_filter_only_sample(False)
        self.window.clear_table()
        self.window.set_engagement(None)
        self.window.set_datasets([])
        self.window.set_samples([])
        self.window.show_welcome()
        self._update_undo_redo_state()
        self._refresh_views()
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
                stored = DatasetRepo(conn).create(dataset, result.rows)
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
        self._refresh_views()

        stats = result.stats
        warning_text = ""
        if stats.skipped_rows:
            warning_text += f"{stats.skipped_rows} Leerzeile(n) übersprungen.\n"
        if stats.warnings:
            warning_text += "\n".join(stats.warnings)
        if warning_text:
            QMessageBox.information(self.window, "Import abgeschlossen", warning_text.strip())

    def handle_dataset_selected(self, dataset_id: int) -> None:
        """Dataset aus DB laden und in der Tabelle anzeigen.

        Klick auf das aktuell schon offene Dataset ist ein No-Op (insbesondere
        bleibt ein laufendes Sample-Highlight stehen). Wechsel auf ein anderes
        Dataset versucht, das aktive Sample dort wiederzufinden – falls das
        Sample nicht zum neuen Dataset gehört, wird das Highlight geleert.
        """
        if self._db is None:
            return

        if self._dataset is not None and self._dataset.id == dataset_id:
            return  # Nichts zu tun – Highlight bleibt.

        dataset = DatasetRepo(self._db.connect()).get_by_id(dataset_id)
        if dataset is None:
            self._error(f"Dataset {dataset_id} nicht gefunden.")
            return

        self._dataset = dataset
        self._filter_active_sample_id = None
        # Dataset-Wechsel setzt Filter-Status zurück – sonst wäre die Checkbox
        # an, aber die Tabelle zeigt das ganze neue Dataset.
        self.window.set_filter_only_sample(False)
        # Sprint 11.2: das TableModel liest on-demand via Repo. Der Controller
        # öffnet eine eigene Connection und übergibt das Repo durch –
        # `DatasetTableModel.set_dataset` hält den Cache klein (~3 MB,
        # konstant).
        self.window.show_dataset(dataset, DatasetRepo(self._db.connect()))

        samples = SampleRepo(self._db.connect()).list_for_dataset(dataset_id)
        self.window.set_samples(samples)

        sample_ids = {s.id for s in samples if s.id is not None}
        if self._active_sample_id is not None and self._active_sample_id in sample_ids:
            # Sample gehört zum neuen Dataset – Highlight wiederherstellen.
            stored = next((s for s in samples if s.id == self._active_sample_id), None)
            if stored is not None:
                self._sample = stored
                self.window.highlight_sample(stored)
        else:
            # Sample gehört nicht zu diesem Dataset – Highlight wird ausgeblendet,
            # `_active_sample_id` bleibt aber gesetzt, damit ein Re-Klick auf das
            # ursprüngliche Dataset die Auswahl wiederherstellt.
            self._sample = None
            self.window.clear_active_sample()

        self._update_undo_redo_state()
        self._persist_state()

    def handle_sample_selected(self, sample_id: int) -> None:
        """Sample-Zeilen in der Tabelle markieren + zur ersten scrollen.

        Wenn die Filter-Checkbox aktiv ist, wird der Filter auf das neue
        Sample umgehängt (statt zurückgesetzt).
        """
        if self._db is None:
            return
        sample = SampleRepo(self._db.connect()).get_by_id(sample_id)
        if sample is None:
            return
        self._sample = sample
        self._active_sample_id = sample.id
        if self.window.sidebar().is_filter_only_sample():
            self.window.filter_to_sample(sample)
            self._filter_active_sample_id = sample.id
            self.window.highlight_sample(sample, filtered=True)
        else:
            if self._filter_active_sample_id is not None:
                self.window.clear_sample_filter()
                self._filter_active_sample_id = None
            self.window.highlight_sample(sample)
        self._update_undo_redo_state()
        self._persist_state()

    def handle_sample_filter_toggled(self, sample_id: int) -> None:
        """Doppelklick: Filter auf Sample-Zeilen ein/aus."""
        if self._db is None:
            return

        if self._filter_active_sample_id == sample_id:
            self.window.clear_sample_filter()
            self._filter_active_sample_id = None
            self.window.set_filter_only_sample(False)
            if self._sample is not None:
                self.window.set_active_sample_label(self._sample, filtered=False)
            self._persist_state()
            return

        sample = SampleRepo(self._db.connect()).get_by_id(sample_id)
        if sample is None:
            return
        self._sample = sample
        self._active_sample_id = sample.id
        self.window.highlight_sample(sample, filtered=True)
        self.window.filter_to_sample(sample)
        self._filter_active_sample_id = sample_id
        self.window.set_filter_only_sample(True)
        self._persist_state()

    def handle_filter_only_sample_toggled(self, active: bool) -> None:
        """Sidebar-Checkbox – Filter auf aktuelles Sample ein/aus.

        Funktioniert auch, wenn programmatisch (statt durch Klick) aufgerufen –
        die Checkbox wird zur Spiegelung des States synchron mitgezogen.
        """
        if self._db is None:
            return
        if active:
            if self._sample is None:
                # Ohne aktives Sample wäre die Tabelle leer – Checkbox zurücksetzen.
                self.window.set_filter_only_sample(False)
                return
            self.window.filter_to_sample(self._sample)
            self._filter_active_sample_id = self._sample.id
            self.window.set_filter_only_sample(True)
            self.window.set_active_sample_label(self._sample, filtered=True)
        else:
            self.window.clear_sample_filter()
            self._filter_active_sample_id = None
            self.window.set_filter_only_sample(False)
            if self._sample is not None:
                self.window.set_active_sample_label(self._sample, filtered=False)
        self._persist_state()

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

        # Sprint 11.4: Dialog-Rows nur noch im Advanced-Mode laden – dort
        # braucht das UI distinct-Werte fürs Filter-Dropdown. Im Simple-
        # Mode reicht `dataset.row_count` für die Größenvalidierung, also
        # kein voller Materialisierung des Datasets nur für den Dialog.
        repo = DatasetRepo(self._db.connect())
        dialog_rows: tuple[DatasetRow, ...] | None = (
            repo.get_all_rows(self._dataset.id) if self._settings.advanced_mode else None
        )
        dialog = self._sampling_factory(
            self.window, self._dataset, dialog_rows, self._sample, self._settings.advanced_mode
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        result = dialog.get_result()
        if result is None:
            return

        try:
            sampler = create_sampler(result.config)
            effective_rows, population_size = self._build_sampling_iterator(
                repo, self._dataset, result.from_sample_only
            )
            sample_result = sampler.sample(effective_rows, population_size=population_size)
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
        self._active_sample_id = stored.id
        # Auto-Filter: nach dem Sampling sieht der Auditor sofort nur die
        # gezogenen Zeilen, ohne erst die Checkbox suchen zu müssen.
        self.window.filter_to_sample(stored)
        self._filter_active_sample_id = stored.id
        self.window.highlight_sample(stored, filtered=True)
        self.window.set_filter_only_sample(True)
        self._push_undo_snapshot()
        self._update_undo_redo_state()
        self._refresh_views()
        self._persist_state()

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
        self._active_sample_id = None
        if self._settings.reset_keeps_filter and self._filter_active_sample_id is not None:
            # User-Setting: Filter bleibt aktiv, nur das Sample-Highlight geht.
            self.window.data_table().clear_highlight()
            self.window.clear_active_sample()
        else:
            self._filter_active_sample_id = None
            self.window.clear_sample_filter()
            self.window.set_filter_only_sample(False)
            self.window.data_table().clear_highlight()
            self.window.clear_active_sample()
        self._push_undo_snapshot()
        self._update_undo_redo_state()
        self._refresh_views()
        self._persist_state()

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
        self._refresh_views()
        self._persist_state()

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
        self._refresh_views()
        self._persist_state()

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

        # Sprint 11.4: Exporter zieht sich die Sample-Rows on-demand via
        # `get_rows_by_ids` – kein voll materialisiertes Dataset mehr.
        # Bei 1M-Dataset und 1k-Sample werden nur 1k Rows aus der DB
        # geholt statt 1M.
        try:
            output_path = ExcelExporter().export_sample(
                self._sample,
                self._dataset,
                DatasetRepo(self._db.connect()),
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
        self._refresh_views()

        QMessageBox.information(
            self.window,
            "Export erfolgreich",
            f"Sample wurde exportiert nach:\n{output_path}",
        )

    def handle_export_audit_pdf(self) -> None:
        """AuditTrail-PDF für das aktuelle Engagement exportieren.

        Öffnet den `ExportAuditPdfDialog`, filtert die Events nach gewähltem
        Zeitraum und Aktionstypen und rendert das PDF mit den gewünschten
        Optionen (Briefpapier-Layer, Statistik-Block).
        """
        if self._db is None or self._engagement is None or self._engagement.id is None:
            return

        events = AuditRepo(self._db.connect()).list_for_engagement(
            self._engagement.id, limit=10_000
        )
        available_types = sorted({e.event_type for e in events})
        briefpapier = self._resolve_briefpapier()

        dialog = self._audit_pdf_factory(
            self.window,
            self._engagement,
            available_types,
            briefpapier is not None,
            self._default_export_dir(),
            self._settings.default_include_briefpapier,
            self._settings.default_include_statistics,
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

        try:
            renderer = AuditTrailPDF(briefpapier=briefpapier if result.use_briefpapier else None)
            renderer.render(
                self._engagement,
                filtered,
                result.output_path,
                include_statistics=result.include_statistics,
            )
        except Exception as exc:  # pragma: no cover – defensiv
            logger.exception("PDF-Export fehlgeschlagen")
            self._error(f"PDF-Export fehlgeschlagen: {exc}")
            return

        QMessageBox.information(
            self.window,
            "AuditTrail-PDF exportiert",
            f"Datei: {result.output_path.name}\n{len(filtered)} Events",
        )

    def handle_export_excel_report(self) -> None:
        """Multi-Sheet Excel-Report für das aktuelle Engagement."""
        if self._db is None or self._engagement is None or self._engagement.id is None:
            return

        dialog = self._excel_report_factory(
            self.window, self._engagement, self._default_export_dir()
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        result = dialog.get_result()
        if result is None:
            return

        try:
            datasets, samples, events = self._collect_report_data()
            MultiSheetReportExporter().export(
                self._engagement,
                datasets,
                samples,
                events,
                result.output_path,
                sheets=result.sheets,
            )
        except Exception as exc:  # pragma: no cover – defensiv
            logger.exception("Excel-Report fehlgeschlagen")
            self._error(f"Excel-Report fehlgeschlagen: {exc}")
            return
        QMessageBox.information(
            self.window,
            "Excel-Report erstellt",
            f"Bericht gespeichert unter:\n{result.output_path}",
        )

    def handle_export_html_report(self) -> None:
        """HTML-Report für E-Mail-Versand."""
        if self._db is None or self._engagement is None or self._engagement.id is None:
            return

        dialog = self._html_report_factory(
            self.window, self._engagement, self._default_export_dir()
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        result = dialog.get_result()
        if result is None:
            return

        try:
            datasets, samples, events = self._collect_report_data()
            HtmlReportGenerator().render(
                self._engagement,
                datasets,
                samples,
                events,
                result.output_path,
                include_charts=result.include_charts,
                include_audit_trail=result.include_audit_trail,
                include_samples_table=result.include_samples_table,
            )
        except Exception as exc:  # pragma: no cover – defensiv
            logger.exception("HTML-Report fehlgeschlagen")
            self._error(f"HTML-Report fehlgeschlagen: {exc}")
            return
        QMessageBox.information(
            self.window,
            "HTML-Report erstellt",
            f"Bericht gespeichert unter:\n{result.output_path}",
        )

    # ---- AuditTrail / Dashboard ----------------------------------------

    def handle_audit_event_double_clicked(self, event_id: int) -> None:
        """Doppelklick auf einen AuditTrail-Event: falls Sample-Bezug → markieren."""
        if self._db is None or self._engagement is None or self._engagement.id is None:
            return
        events = AuditRepo(self._db.connect()).list_for_engagement(
            self._engagement.id, limit=10_000
        )
        event = next((e for e in events if e.id == event_id), None)
        if event is None or event.sample_id is None:
            return
        self.handle_sample_selected(event.sample_id)

    # ---- Help ----------------------------------------------------------

    def handle_bug_report(self) -> None:
        """Bug-Report-Dialog öffnen (mailto-Fallback)."""
        BugReportDialog(self.window).exec()

    def handle_about(self) -> None:
        """About-Dialog öffnen."""
        AboutDialog(self.window).exec()

    def handle_settings(self) -> None:
        """Settings-Dialog öffnen und auf OK persistieren."""
        dialog = self._settings_factory(self.window, self._settings)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        new_settings = dialog.get_settings()
        if new_settings is None:
            return
        self._settings = new_settings
        save_settings(new_settings)
        # Engagement-Ordner ggf. neu anlegen.
        try:
            new_settings.engagements_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.exception("Engagement-Ordner konnte nicht angelegt werden")
        # Panel-Sichtbarkeit live anwenden – kein Neustart nötig.
        self.window.apply_panel_visibility(
            show_dashboard=new_settings.show_dashboard,
            show_audit_trail=new_settings.show_audit_trail,
        )

    def handle_hotkeys(self) -> None:
        """Statisches Info-Fenster mit Tastatur-Shortcuts."""
        QMessageBox.information(
            self.window,
            "Tastatur-Shortcuts",
            (
                "<table cellpadding='6'>"
                "<tr><td><b>Cmd/Ctrl+Z</b></td><td>Rückgängig</td></tr>"
                "<tr><td><b>Cmd/Ctrl+Shift+Z</b></td><td>Wiederherstellen</td></tr>"
                "<tr><td><b>Cmd/Ctrl+N</b></td><td>Neues Engagement</td></tr>"
                "<tr><td><b>Cmd/Ctrl+O</b></td><td>Engagement öffnen</td></tr>"
                "<tr><td><b>Cmd/Ctrl+I</b></td><td>Datei importieren</td></tr>"
                "<tr><td><b>Cmd/Ctrl+W</b></td><td>Engagement schließen</td></tr>"
                "<tr><td><b>Cmd/Ctrl+,</b></td><td>Einstellungen</td></tr>"
                "<tr><td><b>Cmd/Ctrl+Q</b></td><td>Beenden</td></tr>"
                "</table>"
            ),
        )

    # ---- intern --------------------------------------------------------

    def _adopt_database(self, db: Database, db_path: Path, engagement: Engagement) -> None:
        """Setzt internen State auf ein frisches/geöffnetes Engagement und aktualisiert das UI."""
        if self._db is not None and self._db is not db:
            self._db.close()

        self._db = db
        self._engagement = engagement
        self._dataset = None
        self._sample = None
        self._active_sample_id = None
        self._filter_active_sample_id = None
        self.window.data_table().clear_dataset()
        if engagement.id is not None:
            self._undo_manager = UndoManager(db, engagement.id)
            self._state_repo = EngagementStateRepo(db.connect())
        else:
            self._undo_manager = None
            self._state_repo = None

        self.window.set_engagement(engagement)
        self.window.show_workspace()
        self._reload_datasets()
        self.window.set_samples([])
        self.window.clear_table()
        self._update_undo_redo_state()
        self._refresh_views()

        self.recent_store.add(
            db_path,
            client_name=engagement.client_name,
            audit_type=engagement.audit_type or "",
        )
        self.refresh_recent()

        # Letzten UI-State (Dataset/Sample/Filter) wiederherstellen, sofern
        # einer für dieses Engagement persistiert wurde.
        self._restore_state()

    def _restore_state(self) -> None:
        """Wendet den zuletzt persistierten `EngagementState` aufs UI an.

        Stille No-Op, wenn nichts gespeichert ist oder das referenzierte
        Dataset/Sample inzwischen gelöscht wurde. `_persist_state` wird
        während des Restores via `_restoring_state` blockiert.

        Wichtig: stale Referenzen werden hier *still* übersprungen, damit
        beim Öffnen kein blockierender QMessageBox-Dialog aufpoppt – der
        Anwender erwartet einen sauberen Restore, keine Fehlermeldung.
        """
        if (
            self._state_repo is None
            or self._db is None
            or self._engagement is None
            or self._engagement.id is None
        ):
            return
        state = self._state_repo.get(self._engagement.id)
        if state is None:
            return

        self._restoring_state = True
        try:
            if state.active_dataset_id is not None:
                # Vor dem Dispatch prüfen, damit `handle_dataset_selected`
                # bei stale IDs keine Fehlermeldung anzeigt.
                dataset = DatasetRepo(self._db.connect()).get_by_id(state.active_dataset_id)
                if dataset is not None:
                    self.handle_dataset_selected(state.active_dataset_id)
            if state.active_sample_id is not None and self._dataset is not None:
                sample = SampleRepo(self._db.connect()).get_by_id(state.active_sample_id)
                if sample is not None:
                    # Filter-Checkbox vor `handle_sample_selected` setzen,
                    # damit der Handler weiß, dass nach dem Highlight
                    # gefiltert werden soll.
                    self.window.set_filter_only_sample(state.filter_active)
                    self.handle_sample_selected(state.active_sample_id)
        finally:
            self._restoring_state = False

    def _persist_state(self) -> None:
        """Schreibt den aktuellen UI-State in die DB (No-Op während Restore)."""
        if self._restoring_state:
            return
        if self._state_repo is None or self._engagement is None or self._engagement.id is None:
            return
        active_dataset_id = self._dataset.id if self._dataset is not None else None
        self._state_repo.upsert(
            engagement_id=self._engagement.id,
            active_dataset_id=active_dataset_id,
            active_sample_id=self._active_sample_id,
            filter_active=self._filter_active_sample_id is not None,
        )

    def _reload_datasets(self) -> None:
        if self._db is None or self._engagement is None or self._engagement.id is None:
            return
        self._datasets = DatasetRepo(self._db.connect()).list_for_engagement(self._engagement.id)
        self.window.set_datasets(self._datasets)

    def _collect_report_data(
        self,
    ) -> tuple[list[Dataset], list[SampleResult], list[AuditEvent]]:
        """Bündelt Datasets / Samples / Events fürs Report-Rendering."""
        assert self._db is not None
        assert self._engagement is not None
        assert self._engagement.id is not None
        engagement_id = self._engagement.id
        ds_repo = DatasetRepo(self._db.connect())
        sample_repo = SampleRepo(self._db.connect())
        audit_repo = AuditRepo(self._db.connect())
        datasets = ds_repo.list_for_engagement(engagement_id)
        samples: list[SampleResult] = []
        for ds in datasets:
            if ds.id is None:
                continue
            samples.extend(sample_repo.list_for_dataset(ds.id))
        events = audit_repo.list_for_engagement(engagement_id, limit=10_000)
        return datasets, samples, events

    def _refresh_audit_trail(self) -> None:
        """Lädt AuditEvents neu und gibt sie an AuditTrailView."""
        if self._db is None or self._engagement is None or self._engagement.id is None:
            self.window.set_audit_events([])
            return
        events = AuditRepo(self._db.connect()).list_for_engagement(
            self._engagement.id, limit=10_000
        )
        self.window.set_audit_events(events)

    def _refresh_dashboard(self) -> None:
        """Lädt Engagement-Stats neu und gibt sie an DashboardView."""
        if self._db is None or self._engagement is None or self._engagement.id is None:
            self.window.set_dashboard_data(None, [], [], [])
            return
        datasets, samples, events = self._collect_report_data()
        self.window.set_dashboard_data(self._engagement, datasets, samples, events)

    def _refresh_views(self) -> None:
        """Aktualisiert AuditTrail + Dashboard + Report-Buttons in einem Rutsch."""
        self._refresh_audit_trail()
        self._refresh_dashboard()
        self.window.set_reports_enabled(self._engagement is not None and self._db is not None)

    def _build_sampling_iterator(
        self,
        repo: DatasetRepo,
        dataset: Dataset,
        from_sample_only: bool,
    ) -> tuple[Iterable[DatasetRow], int]:
        """Liefert (Iterator, Population-Size) für den Sampler.

        Sprint-11.4-Streaming: kein voll materialisiertes Row-Tuple mehr,
        sondern entweder
        - bei Sub-Sampling: `get_rows_by_ids` mit den Sample-IDs (klein,
          typischerweise 50–5000 Rows), oder
        - bei normalem Sampling: `iter_rows` als Generator über die ganze
          Tabelle (kein voller RAM-Footprint).

        Population-Size kommt für den Full-Dataset-Fall aus den Metadaten
        (`dataset.row_count`), damit Sub-Sample-Population korrekt
        dokumentiert wird.
        """
        assert dataset.id is not None
        if from_sample_only and self._sample is not None:
            sample_ids = list(self._sample.selected_row_ids)
            return repo.get_rows_by_ids(dataset.id, sample_ids), len(sample_ids)
        return repo.iter_rows(dataset.id), dataset.row_count

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
            self._active_sample_id = None
            self._filter_active_sample_id = None
            self.window.clear_sample_filter()
            self.window.set_filter_only_sample(False)
            self.window.data_table().clear_highlight()
            self.window.clear_active_sample()
            return

        sample = SampleRepo(self._db.connect()).get_by_id(snapshot.sample_id)
        if sample is None:
            # Sample wurde zwischenzeitlich gelöscht – defensiv: leeren State anwenden.
            self._sample = None
            self._active_sample_id = None
            self.window.set_filter_only_sample(False)
            self.window.data_table().clear_highlight()
            self.window.clear_active_sample()
            return

        self._sample = sample
        self._active_sample_id = sample.id
        if snapshot.visible_rows:
            self.window.filter_to_sample(sample)
            self._filter_active_sample_id = sample.id
            self.window.set_filter_only_sample(True)
            self.window.highlight_sample(sample, filtered=True)
        else:
            self.window.clear_sample_filter()
            self._filter_active_sample_id = None
            self.window.set_filter_only_sample(False)
            self.window.highlight_sample(sample)

    def _update_undo_redo_state(self) -> None:
        """Schaltet die Undo-/Redo-Menüpunkte basierend auf dem Stack-Status."""
        can_undo = self._undo_manager is not None and self._undo_manager.can_undo()
        can_redo = self._undo_manager is not None and self._undo_manager.can_redo()
        self.window.set_undo_redo_enabled(can_undo, can_redo)
        has_sample = self._sample is not None
        self.window.set_reset_enabled(has_sample or self._filter_active_sample_id is not None)
        # Filter-Checkbox nur sinnvoll mit aktivem Sample – sonst wäre die
        # Tabelle nach dem Setzen leer.
        self.window.set_filter_enabled(has_sample)

    def _next_sample_id_for_export(self, dataset_id: int) -> int:
        if self._db is None:
            return 1
        samples = SampleRepo(self._db.connect()).list_for_dataset(dataset_id)
        return len(samples) + 1

    def _default_export_dir(self) -> Path:
        if self._db is not None:
            return self._db.db_path.parent / EXPORT_DIR_NAME
        return Path.cwd() / EXPORT_DIR_NAME

    def _resolve_briefpapier(self) -> BriefpapierConfig | None:
        """Liefert das aktive Briefpapier: User-Setting > Default-Resolution.

        Setting-Override (`custom_briefpapier_path`) hat Vorrang. Existiert
        der Pfad nicht, fällt der Controller still auf das Default-System
        (`get_default_briefpapier`) zurück.
        """
        custom = self._settings.custom_briefpapier_path
        if custom is not None and custom.exists():
            try:
                return briefpapier_from_path(custom)
            except (FileNotFoundError, ValueError):
                logger.exception("Custom-Briefpapier ungültig, falle auf Default zurück")
        return get_default_briefpapier()

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


def _default_new_engagement_factory(
    parent: MainWindow,
    settings: AppSettings,
    initial_engagement: Engagement | None,
) -> NewEngagementDialog:
    return NewEngagementDialog(
        parent=parent,
        default_auditor_name=settings.default_auditor_name or None,
        engagements_dir=settings.engagements_dir,
        initial_engagement=initial_engagement,
    )


def _default_duplicate_dialog_factory(
    parent: MainWindow, db_path: Path
) -> DuplicateEngagementDialog:
    return DuplicateEngagementDialog(db_path=db_path, parent=parent)


def _default_sampling_factory(
    parent: MainWindow,
    dataset: Dataset,
    rows: Sequence[DatasetRow] | None,
    current_sample: SampleResult | None,
    advanced_mode: bool,
) -> SamplingDialog:
    return SamplingDialog(
        dataset,
        rows,
        current_sample=current_sample,
        parent=parent,
        advanced_mode=advanced_mode,
    )


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


def _default_audit_pdf_factory(
    parent: MainWindow,
    engagement: Engagement,
    event_types_available: list[str],
    briefpapier_available: bool,
    default_dir: Path | None,
    default_use_briefpapier: bool = True,
    default_include_statistics: bool = True,
) -> ExportAuditPdfDialog:
    return ExportAuditPdfDialog(
        engagement=engagement,
        event_types_available=event_types_available,
        briefpapier_available=briefpapier_available,
        parent=parent,
        default_output_dir=default_dir,
        default_use_briefpapier=default_use_briefpapier,
        default_include_statistics=default_include_statistics,
    )


def _default_excel_report_factory(
    parent: MainWindow,
    engagement: Engagement,
    default_dir: Path | None,
) -> ExportExcelReportDialog:
    return ExportExcelReportDialog(engagement, parent=parent, default_output_dir=default_dir)


def _default_html_report_factory(
    parent: MainWindow,
    engagement: Engagement,
    default_dir: Path | None,
) -> ExportHtmlReportDialog:
    return ExportHtmlReportDialog(engagement, parent=parent, default_output_dir=default_dir)


def _default_settings_factory(parent: MainWindow, current: AppSettings) -> SettingsDialog:
    return SettingsDialog(current, parent=parent)
