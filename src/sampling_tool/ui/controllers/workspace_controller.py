"""WorkspaceController – Import, Sampling, Reset, Undo/Redo.

Sprint 13 / F-001: aus dem MainController-God-Object zerlegt. Bündelt
die mutierenden Workspace-Operationen, die den Sample-/Filter-State
verändern und Audit-Events erzeugen.

Reproducibility-relevante Pfade:
- `handle_new_sampling`: SimpleSampler-Spezialpfad (Sprint 12.1 P-002)
  bleibt erhalten – ungefilterte SimpleSampling-Zugriffe gehen über
  `sample_ids(iter_row_ids)` statt voller Row-Materialisierung.
- `_push_undo_snapshot` / `_apply_snapshot` machen exakt dieselbe
  Stack-Manipulation wie vorher.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from PyQt6.QtWidgets import QDialog, QFileDialog, QMessageBox

from sampling_tool.audit.logger import AuditLogger
from sampling_tool.config import SUPPORTED_CSV_SUFFIXES, SUPPORTED_EXCEL_SUFFIXES
from sampling_tool.core.models import Dataset, DatasetRow, Snapshot
from sampling_tool.core.sampling import SamplingError, SimpleSampler, create_sampler
from sampling_tool.io.importer import (
    DataImportError,
    ExcelImporter,
    ImportStats,
)
from sampling_tool.persistence.repositories import (
    AuditRepo,
    DatasetRepo,
    SampleRepo,
)
from sampling_tool.ui.controllers._factories import ControllerFactories
from sampling_tool.ui.controllers.workspace_session import WorkspaceSession
from sampling_tool.ui.dialogs.progress_dialog import TaskProgressDialog
from sampling_tool.ui.workers.tasks import ExcelImportTask, ExcelImportTaskResult

logger = logging.getLogger(__name__)


class WorkspaceController:
    """Import, Sampling, Reset, Undo/Redo – alles was den Sample-State ändert."""

    def __init__(self, session: WorkspaceSession, factories: ControllerFactories) -> None:
        self.session = session
        self._factories = factories

    # ---- Import / Dataset ----------------------------------------------

    def handle_import_excel(self) -> None:
        """Excel-/CSV-Datei importieren und als Dataset persistieren."""
        s = self.session
        if not s.has_engagement():
            return

        path = self._ask_import_path()
        if path is None:
            return

        # Sprint 16: Bei Excel-Dateien prüfen, ob ein Sheet-/Header-Auswahl-
        # Dialog erscheinen muss. Multi-Sheet ODER Header-Auto-Detection
        # unsicher → Dialog. Sonst lautloser One-shot-Import.
        configured: tuple[str, int] | None = None
        if path.suffix.lower() in SUPPORTED_EXCEL_SUFFIXES:
            try:
                needs_dialog = self._import_needs_dialog(path)
            except DataImportError as exc:
                s.error(f"Import fehlgeschlagen: {exc}")
                return
            if needs_dialog:
                configured = self._run_import_options_dialog(path)
                if configured is None:
                    return  # User-Cancel → kein Import.

        task_result = self._do_import_with_progress(path, configured)
        if task_result is None:
            return

        s.reload_datasets()
        if task_result.dataset.id is not None:
            # Auto-Select des neuen Datasets via Session-Helper – identische
            # Logik wie `SelectionController.handle_dataset_selected`.
            s.select_dataset(task_result.dataset.id)
        s.refresh_views()
        self._show_import_summary(task_result.stats)

    def _ask_import_path(self) -> Path | None:
        """File-Dialog für die Datei-Auswahl. None bei Cancel."""
        accepted = "*" + " *".join(SUPPORTED_EXCEL_SUFFIXES + SUPPORTED_CSV_SUFFIXES)
        path_str, _filter = QFileDialog.getOpenFileName(
            self.session.window,
            "Datei importieren",
            "",
            f"Tabellen ({accepted});;Alle Dateien (*)",
        )
        if not path_str:
            return None
        return Path(path_str)

    def _do_import_with_progress(
        self, path: Path, configured: tuple[str, int] | None
    ) -> ExcelImportTaskResult | None:
        """Worker-basierter Import + DB-Persist. UI bleibt während der
        Operation responsiv (Sprint 17 / P-008).

        Bei `DataImportError` zeigt der Controller einen Error-Dialog,
        liefert ``None``. Bei User-Cancel liefert der Worker `None` und
        wir geben es weiter. Bei anderen Exceptions (DB-Fehler) ebenso
        Error-Dialog + ``None``.
        """
        s = self.session
        assert s.db is not None
        assert s.engagement is not None
        assert s.engagement.id is not None

        # Sprint 17: Der Worker öffnet seine eigene Database-Instanz im
        # Worker-Thread. Wir reichen nur den DB-Path durch.
        sheet_name, header_row = configured if configured is not None else (None, None)
        task = ExcelImportTask(
            path=path,
            db_path=s.db.db_path,
            engagement_id=s.engagement.id,
            user_name=s.user_name(),
            sheet_name=sheet_name,
            header_row=header_row,
        )
        progress_dialog = TaskProgressDialog(f"Importiere {path.name}…", s.window)
        try:
            return progress_dialog.run_task(task)
        except DataImportError as exc:
            s.error(f"Import fehlgeschlagen: {exc}")
            return None
        except Exception as exc:  # pragma: no cover – defensiv
            logger.exception("Import-Worker fehlgeschlagen")
            s.error(f"Import fehlgeschlagen: {exc}")
            return None

    def _show_import_summary(self, stats: ImportStats) -> None:
        """Skipped-/Warning-Übersicht als Info-Dialog (oder nichts, wenn leer)."""
        warning_text = ""
        if stats.skipped_rows:
            warning_text += f"{stats.skipped_rows} Leerzeile(n) übersprungen.\n"
        if stats.warnings:
            warning_text += "\n".join(stats.warnings)
        if warning_text:
            QMessageBox.information(
                self.session.window, "Import abgeschlossen", warning_text.strip()
            )

    def _import_needs_dialog(self, path: Path) -> bool:
        """Excel-Datei kurz probieren: Sheet-Liste + Header-Confidence.

        Liefert ``True``, wenn der `ImportOptionsDialog` erscheinen soll
        (Multi-Sheet ODER ``confidence != "high"``). Wirft `DataImportError`,
        wenn die Datei nicht lesbar ist – Caller behandelt das einheitlich.
        """
        importer_probe = ExcelImporter()
        sheets = importer_probe.list_sheets(path)
        if not sheets:
            return False
        if len(sheets) > 1:
            return True
        preview = importer_probe.preview_sheet(path, sheets[0].name)
        return preview.confidence != "high"

    def _run_import_options_dialog(self, path: Path) -> tuple[str, int] | None:
        """Öffnet den `ImportOptionsDialog` und liefert (sheet, header_row) oder None."""
        s = self.session
        importer_probe = ExcelImporter()
        dialog = self._factories.import_options(path, importer_probe, s.window)
        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return None
        result = dialog.get_result()
        if result is None:
            return None
        return result.sheet_name, result.header_row

    # ---- Sampling ------------------------------------------------------

    def handle_new_sampling(self) -> None:
        """Sampling-Dialog öffnen, Stichprobe ziehen, persistieren, loggen."""
        s = self.session
        if not s.has_active_dataset():
            return
        assert s.db is not None
        assert s.dataset is not None
        assert s.dataset.id is not None
        assert s.engagement is not None
        assert s.engagement.id is not None

        # Sprint 11.4: Dialog-Rows nur noch im Advanced-Mode laden – dort
        # braucht das UI distinct-Werte fürs Filter-Dropdown. Im Simple-
        # Mode reicht `dataset.row_count` für die Größenvalidierung, also
        # kein voller Materialisierung des Datasets nur für den Dialog.
        repo = DatasetRepo(s.db.connect())
        dialog_rows: tuple[DatasetRow, ...] | None = (
            repo.get_all_rows(s.dataset.id) if s.settings.advanced_mode else None
        )
        dialog = self._factories.sampling(
            s.window, s.dataset, dialog_rows, s.sample, s.settings.advanced_mode
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        result = dialog.get_result()
        if result is None:
            return

        try:
            sampler = create_sampler(result.config)
            # Sprint 12.1 / P-002: SimpleSampler ohne Filter + ohne Sub-Sampling
            # bekommt nur die row_ids (kein DatasetRow-Materialize).
            # Cluster/Stratified und gefilterte Samples brauchen die Row-Values
            # und gehen weiterhin durch den klassischen Streaming-Pfad.
            if (
                isinstance(sampler, SimpleSampler)
                and result.config.filter_field is None
                and not result.from_sample_only
            ):
                sample_result = sampler.sample_ids(
                    repo.iter_row_ids(s.dataset.id),
                    population_size=s.dataset.row_count,
                )
            else:
                effective_rows, population_size = self._build_sampling_iterator(
                    repo, s.dataset, result.from_sample_only
                )
                sample_result = sampler.sample(effective_rows, population_size=population_size)
        except SamplingError as exc:
            s.error(f"Stichprobe konnte nicht gezogen werden: {exc}")
            return

        parent_sample_id = s.sample.id if result.from_sample_only and s.sample is not None else None
        sample_result = replace(sample_result, parent_sample_id=parent_sample_id)

        try:
            with s.db.session() as conn:
                sample_id = SampleRepo(conn).create_from_result(
                    sample_result, s.dataset.id, s.user_name()
                )
                stored = replace(sample_result, id=sample_id)
                AuditLogger(AuditRepo(conn), s.user_name(), s.engagement.id).log_sampling(
                    stored, sample_id
                )
        except Exception as exc:  # pragma: no cover – defensiv
            logger.exception("Sample persistieren fehlgeschlagen")
            s.error(f"Sample konnte nicht gespeichert werden: {exc}")
            return

        # Sidebar + Tabelle aktualisieren.
        samples = SampleRepo(s.db.connect()).list_for_dataset(s.dataset.id)
        s.window.set_samples(samples)
        s.sample = stored
        s.active_sample_id = stored.id
        # Auto-Filter: nach dem Sampling sieht der Auditor sofort nur die
        # gezogenen Zeilen, ohne erst die Checkbox suchen zu müssen.
        s.window.filter_to_sample(stored)
        s.filter_active_sample_id = stored.id
        s.window.highlight_sample(stored, filtered=True)
        s.window.set_filter_only_sample(True)
        self._push_undo_snapshot()
        s.update_undo_redo_state()
        s.refresh_views()
        s.persist_state()

    # ---- Reset ---------------------------------------------------------

    def handle_reset(self) -> None:
        """Auswahl zurücksetzen (Highlights entfernen, Filter raus)."""
        s = self.session
        if not s.has_engagement():
            return
        if s.sample is None and not s.filter_active_sample_id:
            return

        answer = QMessageBox.question(
            s.window,
            "Auswahl zurücksetzen",
            "Sollen die aktuelle Sample-Hervorhebung und der Filter entfernt werden?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        assert s.db is not None
        assert s.engagement is not None
        assert s.engagement.id is not None
        if s.dataset is not None and s.dataset.id is not None:
            AuditLogger(AuditRepo(s.db.connect()), s.user_name(), s.engagement.id).log_reset(
                s.dataset.id
            )

        s.sample = None
        s.active_sample_id = None
        if s.settings.reset_keeps_filter and s.filter_active_sample_id is not None:
            # User-Setting: Filter bleibt aktiv, nur das Sample-Highlight geht.
            s.window.data_table().clear_highlight()
            s.window.clear_active_sample()
        else:
            s.filter_active_sample_id = None
            s.window.clear_sample_filter()
            s.window.set_filter_only_sample(False)
            s.window.data_table().clear_highlight()
            s.window.clear_active_sample()
        self._push_undo_snapshot()
        s.update_undo_redo_state()
        s.refresh_views()
        s.persist_state()

    # ---- Undo / Redo ---------------------------------------------------

    def handle_undo(self) -> None:
        """Vorherigen Sample-Zustand wiederherstellen."""
        s = self.session
        if s.undo_manager is None or not s.undo_manager.can_undo():
            return
        if not s.has_engagement():
            return
        assert s.db is not None
        assert s.engagement is not None
        assert s.engagement.id is not None

        s.undo_manager.undo()
        previous = s.undo_manager.peek_undo()
        self._apply_snapshot(previous)
        if s.sample is not None and s.sample.id is not None:
            AuditLogger(AuditRepo(s.db.connect()), s.user_name(), s.engagement.id).log_undo(
                s.sample.id
            )
        s.update_undo_redo_state()
        s.refresh_views()
        s.persist_state()

    def handle_redo(self) -> None:
        """Letzten rückgängig gemachten Zustand wiederherstellen."""
        s = self.session
        if s.undo_manager is None or not s.undo_manager.can_redo():
            return
        if not s.has_engagement():
            return
        assert s.db is not None
        assert s.engagement is not None
        assert s.engagement.id is not None

        snapshot = s.undo_manager.redo()
        if snapshot is None:
            return
        self._apply_snapshot(snapshot)
        if s.sample is not None and s.sample.id is not None:
            AuditLogger(AuditRepo(s.db.connect()), s.user_name(), s.engagement.id).log_redo(
                s.sample.id
            )
        s.update_undo_redo_state()
        s.refresh_views()
        s.persist_state()

    # ---- intern --------------------------------------------------------

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
        s = self.session
        assert dataset.id is not None
        if from_sample_only and s.sample is not None:
            sample_ids = list(s.sample.selected_row_ids)
            return repo.get_rows_by_ids(dataset.id, sample_ids), len(sample_ids)
        return repo.iter_rows(dataset.id), dataset.row_count

    def _push_undo_snapshot(self) -> None:
        """Aktuellen Sample/Filter-State auf den Undo-Stack legen."""
        s = self.session
        if s.undo_manager is None:
            return
        sample_id = s.sample.id if s.sample is not None else None
        highlighted = list(s.sample.selected_row_ids) if s.sample is not None else []
        visible = (
            list(s.sample.selected_row_ids)
            if s.filter_active_sample_id is not None and s.sample is not None
            else []
        )
        s.undo_manager.push(
            sample_id=sample_id,
            visible_rows=visible,
            highlighted_rows=highlighted,
        )

    def _apply_snapshot(self, snapshot: Snapshot | None) -> None:
        """Wendet einen `Snapshot` (oder den leeren Initialzustand) auf das UI an."""
        s = self.session
        if s.db is None:
            return

        if snapshot is None or snapshot.sample_id is None:
            s.sample = None
            s.active_sample_id = None
            s.filter_active_sample_id = None
            s.window.clear_sample_filter()
            s.window.set_filter_only_sample(False)
            s.window.data_table().clear_highlight()
            s.window.clear_active_sample()
            return

        sample = SampleRepo(s.db.connect()).get_by_id(snapshot.sample_id)
        if sample is None:
            # Sample wurde zwischenzeitlich gelöscht – defensiv: leeren State anwenden.
            s.sample = None
            s.active_sample_id = None
            s.window.set_filter_only_sample(False)
            s.window.data_table().clear_highlight()
            s.window.clear_active_sample()
            return

        s.sample = sample
        s.active_sample_id = sample.id
        if snapshot.visible_rows:
            s.window.filter_to_sample(sample)
            s.filter_active_sample_id = sample.id
            s.window.set_filter_only_sample(True)
            s.window.highlight_sample(sample, filtered=True)
        else:
            s.window.clear_sample_filter()
            s.filter_active_sample_id = None
            s.window.set_filter_only_sample(False)
            s.window.highlight_sample(sample)
