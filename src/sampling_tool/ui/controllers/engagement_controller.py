"""EngagementController – Engagement-Lifecycle (New, Open, Close, Adopt).

Sprint 13 / F-001: aus dem MainController-God-Object zerlegt. Verantwortet
das Anlegen + Öffnen + Schließen von Engagement-DBs und das damit
einhergehende Setup (Snapshot, Migration, EngagementState-Restore,
Sub-Controller-Initialisierung von UndoManager + EngagementStateRepo).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtWidgets import QMessageBox

from sampling_tool.core.models import Engagement
from sampling_tool.core.undo import UndoManager
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import (
    DatasetRepo,
    EngagementRepo,
    EngagementStateRepo,
    SampleRepo,
    UndoRepo,
)
from sampling_tool.persistence.version_manager import EngagementVersionManager
from sampling_tool.ui.controllers._factories import ControllerFactories
from sampling_tool.ui.controllers.workspace_session import WorkspaceSession
from sampling_tool.ui.dialogs.duplicate_engagement_dialog import DuplicateEngagementChoice

logger = logging.getLogger(__name__)


class EngagementController:
    """Engagement-Lifecycle: anlegen, öffnen, schließen, Recent verwalten."""

    def __init__(self, session: WorkspaceSession, factories: ControllerFactories) -> None:
        self.session = session
        self._factories = factories

    # ---- Recent --------------------------------------------------------

    def refresh_recent(self) -> None:
        """Liest die Recent-Liste und gibt sie ans Fenster."""
        s = self.session
        s.recent_store.prune_missing()
        s.window.set_recent_entries(s.recent_store.list())

    # ---- New -----------------------------------------------------------

    def handle_new_engagement(self) -> None:
        """Dialog anzeigen, neues Engagement anlegen + DB initialisieren.

        Wenn der gewählte Ziel-DB-Pfad bereits existiert, wird der
        `DuplicateEngagementDialog` gezeigt – der User kann dann das
        bestehende Engagement öffnen, einen anderen Namen wählen
        (Dialog wird mit den bisherigen Werten erneut geöffnet) oder
        komplett abbrechen. Verhindert versehentliches Überschreiben.
        """
        s = self.session
        prefill: Engagement | None = None
        while True:
            dialog = self._factories.new_engagement(s.window, s.settings, prefill)
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
                s.error(f"Engagement konnte nicht angelegt werden: {exc}")
                return

            self._adopt_database(db, db_path, created)
            return

    def _prompt_duplicate(self, db_path: Path) -> DuplicateEngagementChoice:
        """Zeigt den DuplicateEngagementDialog und liefert das User-Choice."""
        dialog = self._factories.duplicate(self.session.window, db_path)
        dialog.exec()
        return dialog.choice()

    # ---- Open ----------------------------------------------------------

    def handle_open_engagement(self, db_path: Path) -> None:
        """Bestehende SQLite-Datei öffnen und Engagement laden."""
        s = self.session
        if not db_path.exists():
            s.error(f"Datei '{db_path}' existiert nicht.")
            s.recent_store.remove(db_path)
            self.refresh_recent()
            return

        # Compliance-Snapshot BEVOR die Session anfängt – ein Fehler dabei
        # soll das Öffnen nicht blockieren (Defense-in-Depth, nicht kritisch).
        try:
            EngagementVersionManager(db_path).create_snapshot(s.user_name())
        except Exception:
            logger.exception("Snapshot beim Öffnen fehlgeschlagen (nicht-kritisch)")

        try:
            db = Database(db_path)
            db.migrate()
            engagement = EngagementRepo(db.connect()).get()
        except Exception as exc:
            logger.exception("Engagement öffnen fehlgeschlagen")
            s.error(f"Datenbank '{db_path.name}' kann nicht geöffnet werden: {exc}")
            return

        if engagement is None:
            s.error("Die ausgewählte Datei enthält kein Engagement.")
            return

        self._adopt_database(db, db_path, engagement)

    # ---- Close ---------------------------------------------------------

    def handle_close_engagement_requested(self) -> None:
        """Vom UI angefragtes Schließen – fragt nach Bestätigung, schließt dann."""
        s = self.session
        if s.db is None:
            return
        answer = QMessageBox.question(
            s.window,
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
        s = self.session
        # Tabelle vor dem Repo-Schließen leeren, sonst greift das Model auf
        # eine geschlossene Connection zu, wenn das nächste paintEvent läuft.
        s.window.data_table().clear_dataset()
        s.reset_to_welcome()
        s.window.set_filter_only_sample(False)
        s.window.clear_table()
        s.window.set_engagement(None)
        s.window.set_datasets([])
        s.window.set_samples([])
        s.window.show_welcome()
        s.update_undo_redo_state()
        s.refresh_views()
        self.refresh_recent()

    # ---- intern --------------------------------------------------------

    def _adopt_database(self, db: Database, db_path: Path, engagement: Engagement) -> None:
        """Setzt internen State auf ein frisches/geöffnetes Engagement und aktualisiert das UI."""
        s = self.session
        if s.db is not None and s.db is not db:
            s.db.close()

        s.db = db
        s.engagement = engagement
        s.dataset = None
        s.sample = None
        s.active_sample_id = None
        s.filter_active_sample_id = None
        s.window.data_table().clear_dataset()
        if engagement.id is not None:
            s.undo_manager = UndoManager(UndoRepo(db.connect(), engagement.id))
            s.state_repo = EngagementStateRepo(db.connect())
        else:
            s.undo_manager = None
            s.state_repo = None

        s.window.set_engagement(engagement)
        s.window.show_workspace()
        s.reload_datasets()
        s.window.set_samples([])
        s.window.clear_table()
        s.update_undo_redo_state()
        s.refresh_views()

        s.recent_store.add(
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
        Dataset/Sample inzwischen gelöscht wurde. `persist_state` wird
        während des Restores via `restoring_state`-Flag blockiert.

        Wichtig: stale Referenzen werden hier *still* übersprungen, damit
        beim Öffnen kein blockierender QMessageBox-Dialog aufpoppt – der
        Anwender erwartet einen sauberen Restore, keine Fehlermeldung.
        """
        s = self.session
        if s.state_repo is None or s.db is None or s.engagement is None or s.engagement.id is None:
            return
        state = s.state_repo.get(s.engagement.id)
        if state is None:
            return

        s.restoring_state = True
        try:
            if state.active_dataset_id is not None:
                # Vor dem Dispatch prüfen, damit `select_dataset` bei stale IDs
                # keine Fehlermeldung anzeigt.
                dataset = DatasetRepo(s.db.connect()).get_by_id(state.active_dataset_id)
                if dataset is not None:
                    s.select_dataset(state.active_dataset_id)
            if state.active_sample_id is not None and s.dataset is not None:
                sample = SampleRepo(s.db.connect()).get_by_id(state.active_sample_id)
                if sample is not None:
                    # Filter-Checkbox vor der Sample-Auswahl setzen, damit der
                    # Code-Pfad weiß, dass nach dem Highlight gefiltert werden soll.
                    s.window.set_filter_only_sample(state.filter_active)
                    self._apply_restored_sample(state.active_sample_id)
        finally:
            s.restoring_state = False

    def _apply_restored_sample(self, sample_id: int) -> None:
        """Sample-Auswahl wie der `SelectionController` – aber ohne Zirkular-Ref.

        Spiegelt die `handle_sample_selected`-Logik mit der Filter-Checkbox-
        Konvention. Wird ausschließlich aus `_restore_state` gerufen.
        """
        s = self.session
        if s.db is None:
            return
        sample = SampleRepo(s.db.connect()).get_by_id(sample_id)
        if sample is None:
            return
        s.sample = sample
        s.active_sample_id = sample.id
        if s.window.sidebar().is_filter_only_sample():
            s.window.filter_to_sample(sample)
            s.filter_active_sample_id = sample.id
            s.window.highlight_sample(sample, filtered=True)
        else:
            if s.filter_active_sample_id is not None:
                s.window.clear_sample_filter()
                s.filter_active_sample_id = None
            s.window.highlight_sample(sample)
        s.update_undo_redo_state()
        # persist_state ist während restoring_state ein No-Op – passt.
        s.persist_state()
