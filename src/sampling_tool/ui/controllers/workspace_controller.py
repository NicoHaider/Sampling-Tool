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
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from PyQt6.QtWidgets import QDialog, QFileDialog, QMessageBox

from sampling_tool.audit.logger import AuditLogger
from sampling_tool.config import SUPPORTED_CSV_SUFFIXES, SUPPORTED_EXCEL_SUFFIXES
from sampling_tool.core.models import (
    AuditEvent,
    Dataset,
    DatasetRow,
    FilterOperator,
    SampleResult,
    Snapshot,
)
from sampling_tool.core.sampling import (
    ClusterSampler,
    SamplingError,
    SimpleSampler,
    StratifiedSampler,
    create_sampler,
    matches_filter,
)
from sampling_tool.io.import_preflight import preflight_import
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
from sampling_tool.ui._scaling import scale_factor
from sampling_tool.ui.controllers._factories import ControllerFactories
from sampling_tool.ui.controllers.workspace_session import WorkspaceSession
from sampling_tool.ui.dataset_id_store import DatasetIdColumnStore
from sampling_tool.ui.dialogs.import_options_dialog import ImportOptionsResult
from sampling_tool.ui.dialogs.progress_dialog import TaskProgressDialog
from sampling_tool.ui.dialogs.sampling_dialog import SamplingDialogResult
from sampling_tool.ui.workers.tasks import ExcelImportTask, ExcelImportTaskResult

logger = logging.getLogger(__name__)


def _count_filter_matches(
    repo: DatasetRepo,
    dataset_id: int,
    column: str,
    operator: FilterOperator,
    value: Any,
    restrict_to_ids: Sequence[int] | None,
) -> int:
    """Zählt Rows, die den Filter erfüllen – dieselbe `matches_filter`-Logik wie die
    Ziehung, damit Vorschau-Zahl und tatsächlicher Pool nie auseinanderlaufen.

    `restrict_to_ids` (gesetzt bei „nur aus aktueller Auswahl"): zählt innerhalb der
    bestehenden Stichprobe (kleine, beschränkte Menge → get_rows_by_ids ist ok).
    Sonst Streaming über die volle Tabelle: bevorzugt (row_id, wert)-Pairs
    (json_extract, RAM ~ ein 2-Tupel/Row); Spalten mit `"`/`\\` im Namen können das
    nicht → Fallback auf iter_rows.
    """
    if restrict_to_ids is not None:
        rows = repo.get_rows_by_ids(dataset_id, restrict_to_ids)
        return sum(1 for r in rows if matches_filter(r.get(column), operator, value))
    if DatasetRepo.supports_field_pairs(column):
        pairs = repo.iter_row_field_pairs(dataset_id, column)
        return sum(1 for _, v in pairs if matches_filter(v, operator, value))
    rows_iter = repo.iter_rows(dataset_id)
    return sum(1 for r in rows_iter if matches_filter(r.get(column), operator, value))


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

        if not self._run_import_preflight(path):
            return

        # Sprint 16/29: prüfen, ob ein Sheet-/Header-Auswahl-Dialog erscheinen
        # muss. Excel: Multi-Sheet ODER Header-Auto-Detection unsicher. CSV
        # (Sprint 29): Header-Auto-Detection unsicher. Sonst lautloser
        # One-shot-Import (unverändertes Verhalten für saubere Dateien).
        configured: ImportOptionsResult | None = None
        if path.suffix.lower() in SUPPORTED_EXCEL_SUFFIXES + SUPPORTED_CSV_SUFFIXES:
            try:
                needs_dialog = ExcelImporter().requires_options_dialog(path)
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
            # Sprint 31: optionaler Schritt – ID-Spalte für die Sidebar-
            # Übersicht wählen. Immer angeboten (unabhängig vom Header-Dialog),
            # solange der Import Spalten hat.
            self._ask_id_column(task_result.dataset)
        s.refresh_views()
        self._show_import_summary(task_result.stats)

    def _run_import_preflight(self, path: Path) -> bool:
        """Sprint 48 / S2.3b: billiger Preflight-Check auf dem Main-Thread,
        BEVOR der Import-Worker startet.

        Reject (Hard-Cap überschritten) → Error-Dialog, Import bricht ab
        (`False`). Warnings (Soft-Cap überschritten) → Confirm-Dialog, „Nein"
        bricht ab. Ohne Warnungen (Default für saubere Dateien) → `True`,
        lautloser Import wie vor Sprint 48.
        """
        s = self.session
        preflight = preflight_import(path)
        if preflight.rejected:
            s.error(f"Import abgelehnt: {preflight.reject_reason}")
            return False
        if not preflight.warnings:
            return True
        answer = QMessageBox.question(
            s.window,
            "Große Datei",
            "Die gewählte Datei ist ungewöhnlich groß oder umfangreich:\n\n"
            + "\n".join(preflight.warnings)
            + "\n\nImport trotzdem fortsetzen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

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
        self, path: Path, configured: ImportOptionsResult | None
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
        # Worker-Thread. Wir reichen nur den DB-Path durch. ``configured``
        # schaltet explizit auf `import_file_configured` (Sprint 29: auch
        # ``sheet_name``/``header_row`` == None sind gültige Overrides).
        task = ExcelImportTask(
            path=path,
            db_path=s.db.db_path,
            engagement_id=s.engagement.id,
            user_name=s.user_name(),
            sheet_name=configured.sheet_name if configured is not None else None,
            header_row=configured.header_row if configured is not None else None,
            configured=configured is not None,
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

    def _ask_id_column(self, dataset: Dataset) -> None:
        """Optionaler Post-Import-Schritt (Sprint 31): ID-Spalte für die Sidebar wählen.

        Wird nur gezeigt, wenn der Import Spalten hat. Unabhängig davon, ob der
        Header-/Sheet-Dialog erschien (dort gibt es bei sauberen Dateien keinen
        Dialog). Die Wahl landet in `QSettings` (`DatasetIdColumnStore`),
        **nicht** in der DB – reine Anzeige-Hilfe, kein Schema-Eingriff. Cancel
        oder „Keine" lässt die bisherige Wahl unverändert bzw. setzt sie zurück.
        """
        s = self.session
        if s.db is None or dataset.id is None or not dataset.columns:
            return
        db_stem = s.db.db_path.stem
        store = DatasetIdColumnStore()
        current = store.get(db_stem, dataset.id)
        dialog = self._factories.id_column(list(dataset.columns), current, s.window)
        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return  # Cancel → keine Änderung (Schritt ist optional).
        store.set(db_stem, dataset.id, dialog.selected_column())

    def _run_import_options_dialog(self, path: Path) -> ImportOptionsResult | None:
        """Öffnet den `ImportOptionsDialog` und liefert das `ImportOptionsResult` oder None.

        Die Dialog-/Header-Logik (welche Datei welchen Dialog braucht) lebt in
        `ExcelImporter.requires_options_dialog`; hier wird nur das Ergebnis der
        User-Interaktion durchgereicht.
        """
        s = self.session
        importer_probe = ExcelImporter()
        dialog = self._factories.import_options(path, importer_probe, s.window)
        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return None
        return dialog.get_result()

    def handle_clear_loaded_datasets(self) -> None:
        """Entfernt die geladenen Datensätze NUR aus der Ansicht (kein DB-Delete).

        Audit-safe (ISAE-3402): `datasets`/`dataset_rows`/Audit-Events bleiben
        unangetastet – ein hartes Delete bräuchte einen Schema-Eingriff (vgl.
        die Begründung bei `WorkspaceSession.reset_sampling`). Das ist bewusst
        ein *Ansichts*-Reset, kein Lösch-Feature: das Projekt bleibt offen und
        nach erneutem Öffnen/Reload sind die Datensätze wieder da. Mit
        Bestätigungsdialog + Statusmeldung.
        """
        s = self.session
        if not s.has_engagement():
            return
        if not s.datasets and s.dataset is None:
            return  # Nichts geladen.

        answer = QMessageBox.question(
            s.window,
            "Datensätze aus Ansicht entfernen",
            "Die geladenen Datensätze werden aus der Ansicht entfernt. "
            "Importierte Daten bleiben in der Projektdatei erhalten und sind "
            "nach erneutem Öffnen wieder verfügbar.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        if not s.clear_view():
            return

        status = s.window.statusBar()
        if status is not None:
            status.showMessage(
                "Datensätze aus der Ansicht entfernt – die Projektdatei bleibt unverändert.",
                5000,
            )

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

        # Sprint 19 / P-005: das Filter-Feld bekommt einen distinct-Werte-
        # Provider statt einem voll materialisierten Row-Tuple. Der Dialog
        # ruft den Callback lazy beim Filter-Spalten-Wechsel – RAM ~ Anzahl
        # distinkter Werte statt Zeilenzahl, kein get_all_rows mehr.
        # Sprint 22: die Sichtbarkeit jeder Funktion wird zentral via
        # `resolve_sampling_features()` aufgelöst (ODER aus Advanced-Mode +
        # Einzel-Toggle). Der Provider ist nur nötig, wenn der Filter sichtbar
        # ist.
        repo = DatasetRepo(s.db.connect())
        dataset_id = s.dataset.id
        features = s.settings.resolve_sampling_features()
        distinct_provider: Callable[[str], Sequence[Any]] | None = (
            (lambda col: repo.distinct_values(dataset_id, col)) if features.show_filter else None
        )
        match_count_provider = (
            self._make_match_count_provider(repo, dataset_id) if features.show_filter else None
        )
        dialog = self._factories.sampling(
            s.window,
            s.dataset,
            distinct_provider,
            s.sample,
            features,
            match_count_provider,
            scale_factor(s.settings.ui_scale),
        )
        # Seed-Quelle auflösen (Sprint 27): ein fester Seed aus den
        # Einstellungen hat Vorrang („geänderter Seed gilt für die nächste
        # Ziehung"); sonst greift der Sprint-21-Mechanismus, der den zuletzt
        # genutzten Seed vorbefüllt, damit eine erneute Ziehung (auch nach
        # „Sampling zurücksetzen") bit-genau reproduziert (ISAE-3402). Ist
        # beides None, würfelt der Dialog intern einen Zufalls-Seed. Das
        # Seed-Feld ist schreibgeschützt – der Eingabeort ist verschoben, der
        # RNG-/Zieh-Pfad bleibt unverändert.
        resolved_seed = s.settings.seed if s.settings.seed is not None else s.last_seed
        if resolved_seed is not None:
            dialog.set_initial_seed(resolved_seed)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        result = dialog.get_result()
        if result is None:
            return

        try:
            sample_result = self._draw_sample_result(repo, s.dataset, result)
        except SamplingError as exc:
            s.error(f"Stichprobe konnte nicht gezogen werden: {exc}")
            return

        # Sprint 36 / WP-B: eine Nachstichprobe zieht aus derselben Eltern-
        # Stichproben-Lineage wie das Sub-Sampling (from_sample_only).
        parent_sample_id = (
            s.sample.id
            if (result.from_sample_only or result.exclude_sample_ids) and s.sample is not None
            else None
        )
        sample_result = replace(sample_result, parent_sample_id=parent_sample_id)

        try:
            with s.db.session() as conn:
                sample_id = SampleRepo(conn).create_from_result(
                    sample_result, s.dataset.id, s.user_name()
                )
                stored = replace(sample_result, id=sample_id)
                AuditLogger(AuditRepo(conn), s.user_name(), s.engagement.id).log_sampling(
                    stored, sample_id, dataset_id
                )
        except Exception as exc:  # pragma: no cover – defensiv
            logger.exception("Sample persistieren fehlgeschlagen")
            s.error(f"Sample konnte nicht gespeichert werden: {exc}")
            return

        # Sidebar + Tabelle aktualisieren (Sprint 31: inkl. optionaler ID-Spalte).
        samples = SampleRepo(s.db.connect()).list_for_dataset(s.dataset.id)
        s.push_samples(samples)
        s.sample = stored
        s.active_sample_id = stored.id
        # Sprint 21: Seed merken, damit der nächste Dialog-Open ihn vorbefüllt
        # (überlebt „Sampling zurücksetzen", siehe `set_initial_seed` oben).
        s.last_seed = stored.config.seed
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
            dataset_id = s.dataset.id
            self._log_audit_event_safely("Der Reset", lambda al: al.log_reset(dataset_id))

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

    def handle_reset_sampling(self) -> None:
        """Sampling zurücksetzen (Toolbar, Sprint 20): gezogene Stichprobe leeren.

        Audit-safe In-Memory-Reset: aktive Stichprobe, Highlight und
        Sample-Filter werden geleert; importierte Population und Sampling-
        Parameter bleiben erhalten, persistierte Sample-/Audit-Zeilen
        ebenso (Append-only-Trail). Mit Bestätigungsdialog; Statusmeldung
        nach Erfolg.
        """
        s = self.session
        if not s.has_engagement():
            return
        if s.sample is None and s.filter_active_sample_id is None:
            return

        answer = QMessageBox.question(
            s.window,
            "Sampling zurücksetzen",
            "Die gezogene Stichprobe und die berechneten Ergebnisse werden entfernt.\n"
            "Importierte Daten und Sampling-Parameter bleiben erhalten. Fortfahren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        assert s.db is not None
        assert s.engagement is not None
        assert s.engagement.id is not None
        if s.dataset is not None and s.dataset.id is not None:
            dataset_id = s.dataset.id
            self._log_audit_event_safely("Der Reset", lambda al: al.log_reset(dataset_id))

        if not s.reset_sampling():
            return
        self._push_undo_snapshot()
        s.update_undo_redo_state()
        s.refresh_views()
        s.persist_state()

        status = s.window.statusBar()
        if status is not None:
            status.showMessage(
                "Sampling zurückgesetzt – importierte Daten und Parameter bleiben erhalten.",
                5000,
            )

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
        sample_id = s.sample.id if s.sample is not None else None
        self._log_audit_event_safely("Das Undo", lambda al: al.log_undo(sample_id))
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
        sample_id = s.sample.id if s.sample is not None else None
        self._log_audit_event_safely("Das Redo", lambda al: al.log_redo(sample_id))
        s.update_undo_redo_state()
        s.refresh_views()
        s.persist_state()

    # ---- intern --------------------------------------------------------

    def _make_match_count_provider(
        self, repo: DatasetRepo, dataset_id: int
    ) -> Callable[[str, FilterOperator, Any, bool], int]:
        """Baut den Trefferzahl-Provider für die Größen-/Filter-Vorschau des Dialogs.

        Liest `session.sample` bewusst *bei Aufruf* (nicht beim Dialog-Bau): der
        Dialog reicht den Live-Stand der Resample-Checkbox durch, und die Zählung
        muss die aktuell aktive Stichprobe widerspiegeln.
        """
        s = self.session

        def _provider(field: str, operator: FilterOperator, value: Any, restrict: bool) -> int:
            restrict_ids = (
                list(s.sample.selected_row_ids) if restrict and s.sample is not None else None
            )
            return _count_filter_matches(repo, dataset_id, field, operator, value, restrict_ids)

        return _provider

    def _draw_sample_result(
        self,
        repo: DatasetRepo,
        dataset: Dataset,
        result: SamplingDialogResult,
    ) -> SampleResult:
        """Wählt den Sampler-Pfad und zieht die Stichprobe. Kann `SamplingError` werfen.

        Sprint 12.1 / P-002: SimpleSampler ohne Filter + ohne Sub-Sampling bekommt
        nur die row_ids (kein DatasetRow-Materialize). Sprint 35 / P-003:
        Cluster/Stratified ohne Filter + ohne Sub-Sampling bekommen
        (row_id, feldwert)-Pairs – bit-identische Ziehung (Oracles in
        test_sampling.py), aber ohne den vollen 15-Spalten-Row-Pool im RAM.
        Sprint 36 / WP-B: eine Nachstichprobe (exclude_sample_ids) darf NIE einen
        der P-002/P-003-Fastpaths nehmen – sie geht immer über den klassischen
        `sample(rows)`-Pfad, damit der Ausschluss-Filter greift. Gefilterte und
        Resample-Ziehungen laufen ebenfalls klassisch.
        """
        s = self.session
        assert dataset.id is not None
        sampler = create_sampler(result.config)
        unfiltered_full_population = (
            result.config.filter_field is None
            and not result.from_sample_only
            and not result.exclude_sample_ids
        )
        if isinstance(sampler, SimpleSampler) and unfiltered_full_population:
            return sampler.sample_ids(
                repo.iter_row_ids(dataset.id),
                population_size=dataset.row_count,
            )
        if (
            isinstance(sampler, ClusterSampler)
            and unfiltered_full_population
            and result.config.cluster_field is not None
            and DatasetRepo.supports_field_pairs(result.config.cluster_field)
        ):
            return sampler.sample_pairs(
                repo.iter_row_field_pairs(dataset.id, result.config.cluster_field),
                population_size=dataset.row_count,
            )
        if (
            isinstance(sampler, StratifiedSampler)
            and unfiltered_full_population
            and result.config.stratum_field is not None
            and DatasetRepo.supports_field_pairs(result.config.stratum_field)
        ):
            return sampler.sample_pairs(
                repo.iter_row_field_pairs(dataset.id, result.config.stratum_field),
                population_size=dataset.row_count,
            )
        if result.exclude_sample_ids and s.sample is not None:
            # Sprint 36 / WP-B: Nachstichprobe – klassischer Pfad über einen
            # Iterator, der die bereits gezogene aktive Stichprobe ausschließt.
            effective_rows, population_size = self._build_supplement_iterator(
                repo, dataset, s.sample.selected_row_ids
            )
            return sampler.sample(effective_rows, population_size=population_size)
        effective_rows, population_size = self._build_sampling_iterator(
            repo, dataset, result.from_sample_only
        )
        return sampler.sample(effective_rows, population_size=population_size)

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

    def _build_supplement_iterator(
        self,
        repo: DatasetRepo,
        dataset: Dataset,
        exclude_ids: Sequence[int],
    ) -> tuple[Iterable[DatasetRow], int]:
        """Alle Rows AUSSER den übergebenen IDs – Basis minus bereits gezogener Stichprobe.

        `population_size` ist die tatsächlich verfügbare Restmenge
        (row_count - len(exclude)), nicht die volle Dataset-Größe – dokumentiert die
        für DIESE Ziehung reale Population (Audit-Nachstichprobe ohne Dubletten).
        """
        assert dataset.id is not None
        exclude_set = frozenset(exclude_ids)
        filtered = (row for row in repo.iter_rows(dataset.id) if row.row_id not in exclude_set)
        # Invariante: exclude_ids ⊆ Dataset (das aktive Sample gehört zu diesem
        # Dataset; Rows werden nie gelöscht) → len(exclude_set) zählt exakt die
        # ausgeschlossenen Rows, damit die population_size-Mathe (row_count -
        # len(exclude)) stimmt.
        return filtered, dataset.row_count - len(exclude_set)

    def _log_audit_event_safely(
        self, action_label: str, log_call: Callable[[AuditLogger], AuditEvent]
    ) -> None:
        """Schreibt ein Audit-Event ab, ohne bei einem DB-Fehler zu crashen.

        Die Aktion selbst (Reset/Undo/Redo) ist bereits ausgeführt – der
        In-Memory-State ist schon geändert – bei einem Log-Fehler wird nur
        gewarnt, nicht zurückgerollt. `action_label` ist bereits die volle
        deutsche Subjekt-Phrase inkl. Artikel (z. B. "Der Reset", "Das
        Undo"), damit die Warnung grammatikalisch korrekt bleibt.

        Der Sample-Export hat eine eigene Variante (`ExportController.
        _log_export_with_retry`) statt diesem Helper: dort existiert bereits
        eine Datei auf der Platte, die bei einem Log-Fehler NICHT gelöscht
        werden darf (Compliance-Entscheidung) – deshalb Retry/Abort statt
        einfachem Warnen.
        """
        s = self.session
        assert s.db is not None
        assert s.engagement is not None
        assert s.engagement.id is not None
        try:
            log_call(AuditLogger(AuditRepo(s.db.connect()), s.user_name(), s.engagement.id))
        except Exception:
            logger.exception("Audit-Log-Fehler bei: %s", action_label)
            s.error(
                f"{action_label} wurde ausgeführt, konnte aber NICHT im Audit-Trail "
                "protokolliert werden."
            )

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

        # Leerer Initialzustand ODER keine Population in der Ansicht (z. B. nach
        # „Datensätze aus Ansicht entfernen", Sprint 31): leeren State anwenden,
        # statt ein Sample-Highlight ohne sichtbares Dataset zu setzen (sonst
        # inkonsistente UI + inkonsistenter persistierter `engagement_state`).
        if snapshot is None or snapshot.sample_id is None or s.dataset is None:
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
