"""Zentraler State + Glue-Methoden für die Sub-Controller.

Sprint 13 / F-001: aus dem MainController-God-Object zerlegt. Hält alle
App-Sitzungs-Daten (DB-Connection, Engagement, aktuelles Dataset/Sample,
Settings, UI-Refs) und stellt die `persist_state`/`restore_state`/
`refresh_*`-Helper bereit, die mehrere Sub-Controller brauchen.

Mutable bewusst – Reproducibility wird im Core gewährleistet (frozen
Domain-Modelle), Controller-State ist per Definition Session-mutabel.
"""

from __future__ import annotations

import getpass
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QMessageBox

from sampling_tool.config import APP_NAME, EXPORT_DIR_NAME
from sampling_tool.core.models import (
    AuditEvent,
    Dataset,
    Engagement,
    SampleResult,
)
from sampling_tool.core.undo import UndoManager
from sampling_tool.io.briefpapier import (
    BriefpapierConfig,
    briefpapier_from_path,
    get_default_briefpapier,
)
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import (
    AuditRepo,
    DatasetRepo,
    EngagementStateRepo,
    SampleRepo,
)
from sampling_tool.ui.recent import RecentEngagementsStore
from sampling_tool.ui.settings_store import AppSettings

if TYPE_CHECKING:
    from sampling_tool.ui.main_window import MainWindow

logger = logging.getLogger(__name__)

# Sprint 12.1 / Q-008: Audit-Read-Limit für UI-Pfade. Zentrale Konstante
# statt 4× hardcoded `limit=10_000` im Sub-Controller-Set.
AUDIT_EVENT_DISPLAY_LIMIT: int = 10_000


class WorkspaceSession:
    """Zentraler State + Glue-Methoden für die Sub-Controller.

    Sub-Controller halten eine Ref auf diese Session und mutieren den
    State über benannte Methoden. Convenience-Guards (`has_engagement`,
    `has_active_dataset`, `has_active_sample`) ersetzen die heute überall
    wiederholten Null-Checks im Controller-Pfad.
    """

    def __init__(
        self,
        window: MainWindow,
        settings: AppSettings,
        recent_store: RecentEngagementsStore,
    ) -> None:
        # Externe Refs
        self.window = window
        self.settings = settings
        self.recent_store = recent_store

        # Session-State (alle Default leer)
        self.db: Database | None = None
        self.engagement: Engagement | None = None
        self.dataset: Dataset | None = None
        self.sample: SampleResult | None = None
        self.datasets: list[Dataset] = []
        self.active_sample_id: int | None = None
        self.filter_active_sample_id: int | None = None
        self.undo_manager: UndoManager | None = None
        self.state_repo: EngagementStateRepo | None = None
        # `restoring_state` blockiert `persist_state` während des Restore-
        # Vorgangs, damit der frisch eingelesene State nicht durch jeden
        # einzelnen `handle_*`-Aufruf (Dataset, Sample, Filter) sofort
        # zwischenüberschrieben wird.
        self.restoring_state: bool = False

    # ---- Convenience-Guards --------------------------------------------

    def has_engagement(self) -> bool:
        """True, wenn DB + Engagement + Engagement.id alle gesetzt sind."""
        return (
            self.db is not None and self.engagement is not None and self.engagement.id is not None
        )

    def has_active_dataset(self) -> bool:
        """True, wenn zusätzlich zum Engagement ein Dataset aktiv ist."""
        return self.has_engagement() and self.dataset is not None and self.dataset.id is not None

    def has_active_sample(self) -> bool:
        """True, wenn zusätzlich zum Dataset ein Sample aktiv ist."""
        return self.has_active_dataset() and self.sample is not None and self.sample.id is not None

    # ---- State-Persistenz (Sprint 8.2) ---------------------------------

    def persist_state(self) -> None:
        """Schreibt den aktuellen UI-State in die DB (No-Op während Restore)."""
        if self.restoring_state:
            return
        if self.state_repo is None or self.engagement is None or self.engagement.id is None:
            return
        active_dataset_id = self.dataset.id if self.dataset is not None else None
        self.state_repo.upsert(
            engagement_id=self.engagement.id,
            active_dataset_id=active_dataset_id,
            active_sample_id=self.active_sample_id,
            filter_active=self.filter_active_sample_id is not None,
        )

    # ---- Refresh-Pfade --------------------------------------------------

    def reload_datasets(self) -> None:
        """Lädt die Dataset-Liste neu und gibt sie an die Sidebar."""
        if not self.has_engagement():
            return
        assert self.db is not None
        assert self.engagement is not None
        assert self.engagement.id is not None
        self.datasets = DatasetRepo(self.db.connect()).list_for_engagement(self.engagement.id)
        self.window.set_datasets(self.datasets)

    def refresh_audit_trail(self) -> None:
        """Lädt AuditEvents neu und gibt sie an AuditTrailView."""
        if not self.has_engagement():
            self.window.set_audit_events([])
            return
        assert self.db is not None
        assert self.engagement is not None
        assert self.engagement.id is not None
        events = AuditRepo(self.db.connect()).list_for_engagement(
            self.engagement.id, limit=AUDIT_EVENT_DISPLAY_LIMIT
        )
        self.window.set_audit_events(events)

    def refresh_dashboard(self) -> None:
        """Lädt Engagement-Stats neu und gibt sie an DashboardView."""
        if not self.has_engagement():
            self.window.set_dashboard_data(None, [], [], [])
            return
        datasets, samples, events = self.collect_report_data()
        self.window.set_dashboard_data(self.engagement, datasets, samples, events)

    def refresh_views(self) -> None:
        """Aktualisiert AuditTrail + Dashboard + Report-Buttons in einem Rutsch."""
        self.refresh_audit_trail()
        self.refresh_dashboard()
        self.window.set_reports_enabled(self.engagement is not None and self.db is not None)

    def update_undo_redo_state(self) -> None:
        """Schaltet die Undo-/Redo-Menüpunkte basierend auf dem Stack-Status."""
        can_undo = self.undo_manager is not None and self.undo_manager.can_undo()
        can_redo = self.undo_manager is not None and self.undo_manager.can_redo()
        self.window.set_undo_redo_enabled(can_undo, can_redo)
        has_sample = self.sample is not None
        self.window.set_reset_enabled(has_sample or self.filter_active_sample_id is not None)
        # Filter-Checkbox nur sinnvoll mit aktivem Sample – sonst wäre die
        # Tabelle nach dem Setzen leer.
        self.window.set_filter_enabled(has_sample)

    # ---- Audit/Report-Daten --------------------------------------------

    def collect_report_data(
        self,
    ) -> tuple[list[Dataset], list[SampleResult], list[AuditEvent]]:
        """Bündelt Datasets / Samples / Events fürs Report-Rendering."""
        assert self.db is not None
        assert self.engagement is not None
        assert self.engagement.id is not None
        engagement_id = self.engagement.id
        ds_repo = DatasetRepo(self.db.connect())
        sample_repo = SampleRepo(self.db.connect())
        audit_repo = AuditRepo(self.db.connect())
        datasets = ds_repo.list_for_engagement(engagement_id)
        samples: list[SampleResult] = []
        for ds in datasets:
            if ds.id is None:
                continue
            samples.extend(sample_repo.list_for_dataset(ds.id))
        events = audit_repo.list_for_engagement(engagement_id, limit=AUDIT_EVENT_DISPLAY_LIMIT)
        return datasets, samples, events

    # ---- Briefpapier + Export-Pfade -------------------------------------

    def resolve_briefpapier(self) -> BriefpapierConfig | None:
        """Liefert das aktive Briefpapier: User-Setting > Default-Resolution.

        Setting-Override (`custom_briefpapier_path`) hat Vorrang. Existiert
        der Pfad nicht, fällt der Controller still auf das Default-System
        (`get_default_briefpapier`) zurück.
        """
        custom = self.settings.custom_briefpapier_path
        if custom is not None and custom.exists():
            try:
                return briefpapier_from_path(custom)
            except (FileNotFoundError, ValueError):
                logger.exception("Custom-Briefpapier ungültig, falle auf Default zurück")
        return get_default_briefpapier()

    def default_export_dir(self) -> Path:
        """Default-Ordner für Exporte: <engagement-folder>/exports."""
        if self.db is not None:
            return self.db.db_path.parent / EXPORT_DIR_NAME
        return Path.cwd() / EXPORT_DIR_NAME

    # ---- Settings-Update ------------------------------------------------

    def apply_new_settings(self, settings: AppSettings) -> None:
        """Settings updaten + Engagement-Dir anlegen + Panel-Visibility anwenden."""
        self.settings = settings
        try:
            settings.engagements_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.exception("Engagement-Ordner konnte nicht angelegt werden")
        self.window.apply_panel_visibility(
            show_dashboard=settings.show_dashboard,
            show_audit_trail=settings.show_audit_trail,
        )

    # ---- Dataset-Auswahl (geteilt zwischen Selection- und WorkspaceController) ---

    def select_dataset(self, dataset_id: int) -> bool:
        """Dataset aus DB laden, in der Tabelle anzeigen, Sample-State syncen.

        Wird vom `SelectionController` (Sidebar-Klick) UND vom
        `WorkspaceController` (Auto-Select nach Import) aufgerufen –
        deshalb lebt die Logik auf der Session, nicht in einem
        Sub-Controller.

        Liefert `True` bei Erfolg, `False` wenn das Dataset nicht
        gefunden wurde (Caller hat dann bereits eine Fehlermeldung
        erhalten oder ignoriert den No-Op).

        No-Op + True, wenn das aktuell schon offene Dataset re-selected
        wird – Highlight bleibt dann erhalten.
        """
        if self.db is None:
            return False

        if self.dataset is not None and self.dataset.id == dataset_id:
            return True  # Nichts zu tun – Highlight bleibt.

        dataset = DatasetRepo(self.db.connect()).get_by_id(dataset_id)
        if dataset is None:
            self.error(f"Dataset {dataset_id} nicht gefunden.")
            return False

        self.dataset = dataset
        self.filter_active_sample_id = None
        # Dataset-Wechsel setzt Filter-Status zurück – sonst wäre die Checkbox
        # an, aber die Tabelle zeigt das ganze neue Dataset.
        self.window.set_filter_only_sample(False)
        # Sprint 11.2: das TableModel liest on-demand via Repo. Der Controller
        # öffnet eine eigene Connection und übergibt das Repo durch –
        # `DatasetTableModel.set_dataset` hält den Cache klein (~3 MB,
        # konstant).
        self.window.show_dataset(dataset, DatasetRepo(self.db.connect()))

        samples = SampleRepo(self.db.connect()).list_for_dataset(dataset_id)
        self.window.set_samples(samples)

        sample_ids = {s_obj.id for s_obj in samples if s_obj.id is not None}
        if self.active_sample_id is not None and self.active_sample_id in sample_ids:
            # Sample gehört zum neuen Dataset – Highlight wiederherstellen.
            stored = next((s_obj for s_obj in samples if s_obj.id == self.active_sample_id), None)
            if stored is not None:
                self.sample = stored
                self.window.highlight_sample(stored)
        else:
            # Sample gehört nicht zu diesem Dataset – Highlight wird ausgeblendet,
            # `active_sample_id` bleibt aber gesetzt, damit ein Re-Klick auf das
            # ursprüngliche Dataset die Auswahl wiederherstellt.
            self.sample = None
            self.window.clear_active_sample()

        self.update_undo_redo_state()
        self.persist_state()
        return True

    # ---- Sampling-Reset (Sprint 20) ------------------------------------

    def reset_sampling(self) -> bool:
        """Setzt ausschließlich den gezogenen-Stichprobe-/Ergebnis-State zurück.

        Leert die aktive Stichprobe, das Tabellen-Highlight und den
        Sample-Filter – der UI-Zustand ist danach „noch nie gezogen".
        Population (Dataset) und Parameter (Settings, die den Sampling-
        Dialog speisen) bleiben unangetastet.

        Audit-safe: persistierte `samples`-/`audit_events`-Zeilen werden
        NICHT gelöscht – ein hartes Löschen ist wegen des Append-only-
        Audit-FK (`audit_events.sample_id ON DELETE SET NULL` feuert den
        `audit_events_no_update`-Trigger) ohne Schema-Änderung unmöglich,
        und der Append-only-Trail ist ISAE-3402-Pflicht. Eine identische
        Re-Ziehung mit gleichem Seed rekonstruiert die Stichprobe
        bit-genau.

        Liefert True, wenn etwas zurückgesetzt wurde, sonst False (No-Op,
        wenn nichts gezogen/ausgewählt war).
        """
        if (
            self.sample is None
            and self.active_sample_id is None
            and self.filter_active_sample_id is None
        ):
            return False
        self.sample = None
        self.active_sample_id = None
        self.filter_active_sample_id = None
        self.window.clear_sample_filter()
        self.window.set_filter_only_sample(False)
        self.window.data_table().clear_highlight()
        self.window.clear_active_sample()
        return True

    # ---- Engagement-Reset ----------------------------------------------

    def reset_to_welcome(self) -> None:
        """Schließt DB und leert allen Session-State – Welcome-Screen-Zustand."""
        if self.db is not None:
            self.db.close()
        self.db = None
        self.engagement = None
        self.dataset = None
        self.sample = None
        self.active_sample_id = None
        self.datasets = []
        self.filter_active_sample_id = None
        self.undo_manager = None
        self.state_repo = None
        self.restoring_state = False

    # ---- Hilfen --------------------------------------------------------

    @staticmethod
    def user_name() -> str:
        """Login-User-Name (für AuditLog), fällt auf 'system' zurück."""
        try:
            return getpass.getuser()
        except OSError:  # pragma: no cover
            return "system"

    def error(self, message: str) -> None:
        """Loggt + zeigt eine User-Warnung."""
        logger.error(message)
        QMessageBox.warning(self.window, APP_NAME, message)
