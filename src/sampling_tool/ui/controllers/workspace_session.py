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

from PyQt6.QtWidgets import QApplication, QMessageBox

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
    get_default_briefpapier,
    validate_briefpapier,
)
from sampling_tool.logging_setup import resolve_log_level
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import (
    AuditRepo,
    DatasetRepo,
    EngagementStateRepo,
    SampleRepo,
)
from sampling_tool.ui._scaling import load_scaled_stylesheet, scale_factor
from sampling_tool.ui.dataset_id_store import DatasetIdColumnStore
from sampling_tool.ui.recent import RecentEngagementsStore
from sampling_tool.ui.settings_store import AppSettings
from sampling_tool.ui.widgets.sidebar import MAX_IDS_IN_LABEL, format_sample_id_values

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
        # Sprint 21: zuletzt gezogener Seed. Wird beim erneuten Öffnen des
        # Sampling-Dialogs als Default übernommen, damit eine Re-Ziehung
        # (auch nach „Sampling zurücksetzen") bit-genau reproduzierbar ist.
        # Überlebt `reset_sampling()` bewusst (Seed = Parameter, bleibt),
        # wird nur beim Engagement-Wechsel (`reset_to_welcome`) geleert.
        self.last_seed: int | None = None
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

    # ---- Sample-Sidebar inkl. optionaler ID-Spalte (Sprint 31) ---------

    def push_samples(self, samples: list[SampleResult]) -> None:
        """Reicht Samples an die Sidebar – inkl. optionaler ID-Spalten-Anzeige.

        Zentraler Eintrittspunkt für ALLE Sample-Sidebar-Updates mit echten
        Samples: löst die für das aktive Dataset gewählte ID-Spalte (QSettings,
        siehe `DatasetIdColumnStore`) auf, materialisiert pro Sample nur die
        ersten Werte fürs (gekürzte) Label und reicht alles via
        `window.set_samples` durch. Ist der Toggle aus oder keine Spalte
        gewählt, bleibt das Label bit-genau das bisherige Format.
        """
        id_column, id_values = self._resolve_sample_ids(samples)
        self.window.set_samples(
            samples,
            id_column=id_column,
            id_values_by_sample=id_values,
            show_sample_id_column=self.settings.show_sample_id_column,
        )

    def _resolve_sample_ids(self, samples: list[SampleResult]) -> tuple[str | None, dict[int, str]]:
        """Ermittelt (ID-Spalte, {sample_id: gekürzter ID-String}) für die Sidebar.

        No-Op-Rückgabe `(None, {})`, wenn der Toggle aus ist, kein Dataset aktiv
        ist, keine ID-Spalte gewählt wurde oder die gewählte Spalte nicht (mehr)
        im aktiven Dataset existiert. Materialisiert pro Sample höchstens
        `MAX_IDS_IN_LABEL` Row-Werte via `get_rows_by_ids` (Streaming-konform,
        **kein** `get_all_rows`).
        """
        if not self.settings.show_sample_id_column:
            return None, {}
        if self.db is None or self.dataset is None or self.dataset.id is None:
            return None, {}
        id_column = DatasetIdColumnStore().get(self.db.db_path.stem, self.dataset.id)
        if id_column is None or id_column not in self.dataset.columns:
            return None, {}
        repo = DatasetRepo(self.db.connect())
        id_values: dict[int, str] = {}
        for sample in samples:
            if sample.id is None:
                continue
            head_ids = list(sample.selected_row_ids[:MAX_IDS_IN_LABEL])
            rows = repo.get_rows_by_ids(self.dataset.id, head_ids)
            values = [row.get(id_column) for row in rows]
            id_values[sample.id] = format_sample_id_values(values, len(sample.selected_row_ids))
        return id_column, id_values

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
        datasets, samples, events, _dataset_ids_by_sample = self.collect_report_data()
        self.window.set_dashboard_data(self.engagement, datasets, samples, events)

    def refresh_views(self) -> None:
        """Aktualisiert AuditTrail + Dashboard + Report-Buttons in einem Rutsch.

        Sprint 34 / WP5: lädt die Report-Daten (inkl. der bis zu
        ``AUDIT_EVENT_DISPLAY_LIMIT`` Audit-Events) genau EINMAL und verteilt
        sie an beide Views. Vorher liefen ``refresh_audit_trail`` +
        ``refresh_dashboard`` je einen identischen Event-Fetch – 2× 10k-Row-
        Decode pro mutierender User-Aktion (9 Controller-Call-Sites: Import,
        Sampling, Reset, Sampling-Reset, Undo, Redo, Export, Open, Close).
        """
        if not self.has_engagement():
            self.window.set_audit_events([])
            self.window.set_dashboard_data(None, [], [], [])
        else:
            datasets, samples, events, _dataset_ids_by_sample = self.collect_report_data()
            self.window.set_audit_events(events)
            self.window.set_dashboard_data(self.engagement, datasets, samples, events)
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
    ) -> tuple[list[Dataset], list[SampleResult], list[AuditEvent], dict[int, int]]:
        """Bündelt Datasets / Samples / Events fürs Report-Rendering.

        Das vierte Element bildet `sample.id -> dataset.id` ab (Sprint 43 /
        A-001): die flache `samples`-Liste verliert sonst, aus welchem
        Dataset jedes Sample stammt – die Projekt-Report-Exporter brauchen
        das für `SamplingProvenance.dataset_id`."""
        assert self.db is not None
        assert self.engagement is not None
        assert self.engagement.id is not None
        engagement_id = self.engagement.id
        ds_repo = DatasetRepo(self.db.connect())
        sample_repo = SampleRepo(self.db.connect())
        audit_repo = AuditRepo(self.db.connect())
        datasets = ds_repo.list_for_engagement(engagement_id)
        samples: list[SampleResult] = []
        dataset_ids_by_sample: dict[int, int] = {}
        for ds in datasets:
            if ds.id is None:
                continue
            for sample in sample_repo.list_for_dataset(ds.id):
                samples.append(sample)
                if sample.id is not None:
                    dataset_ids_by_sample[sample.id] = ds.id
        events = audit_repo.list_for_engagement(engagement_id, limit=AUDIT_EVENT_DISPLAY_LIMIT)
        return datasets, samples, events, dataset_ids_by_sample

    # ---- Briefpapier + Export-Pfade -------------------------------------

    def resolve_briefpapier(self) -> BriefpapierConfig | None:
        """Liefert das aktive Briefpapier: User-Setting > Default-Resolution.

        Setting-Override (`custom_briefpapier_path`) hat Vorrang. Ist der
        Pfad ungültig – fehlt, falsches Format, zu groß oder nicht parsebar
        (Sprint 47 / N-010) – fällt der Controller sichtbar (WARN-Log) auf
        das Default-System (`get_default_briefpapier`) zurück.
        """
        custom = self.settings.custom_briefpapier_path
        if custom is not None:
            try:
                validate_briefpapier(custom)
            except Exception:
                logger.warning(
                    "Custom-Briefpapier '%s' ungültig, falle auf Default zurück",
                    custom.name,
                    exc_info=True,
                )
            else:
                # `validate_briefpapier` hat Existenz/Format/Größe/Parsebarkeit
                # bereits geprüft – kein zweiter fehleranfälliger Aufruf hier
                # nötig (der würde außerhalb des try/except liegen).
                return BriefpapierConfig(background_image=custom)
        return get_default_briefpapier()

    def default_export_dir(self) -> Path:
        """Default-Ordner für Exporte: <engagement-folder>/exports."""
        if self.db is not None:
            return self.db.db_path.parent / EXPORT_DIR_NAME
        return Path.cwd() / EXPORT_DIR_NAME

    # ---- Settings-Update ------------------------------------------------

    def apply_new_settings(self, settings: AppSettings) -> None:
        """Settings updaten + Log-Level, Undo-Tiefe und UI-Größe live setzen +
        Engagement-Dir anlegen + Panel-Visibility anwenden."""
        self.settings = settings
        logging.getLogger().setLevel(resolve_log_level(settings.log_level))
        if self.undo_manager is not None:
            self.undo_manager.set_max_depth(settings.undo_depth)

        # Sprint 68 / Teil B1: UI-Größe wirkt sofort – reapplied stylesheet +
        # persistente Widgets (kein neuer Sonderweg: derselbe Lade-Pfad wie
        # beim App-Start in `__main__.main`).
        factor = scale_factor(settings.ui_scale)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(load_scaled_stylesheet(factor))
        self.window.apply_ui_scale(factor)

        try:
            settings.engagements_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.exception("Engagement-Ordner konnte nicht angelegt werden")
        self.window.apply_panel_visibility(
            show_dashboard=settings.show_dashboard,
            show_audit_trail=settings.show_audit_trail,
        )
        # Sprint 31: ID-Spalten-Anzeige-Toggle live anwenden – die Sidebar-
        # Stichprobenliste des aktiven Datasets wird mit dem neuen Toggle-Wert
        # neu aufgebaut (kein Neustart nötig).
        if self.has_active_dataset():
            assert self.db is not None
            assert self.dataset is not None
            assert self.dataset.id is not None
            samples = SampleRepo(self.db.connect()).list_for_dataset(self.dataset.id)
            self.push_samples(samples)
            # `push_samples` baut die Sidebar-Liste neu auf (Bullet/Bold weg) und
            # `set_samples` deaktiviert den Export-Button – ist eine Stichprobe
            # aktiv, die Markierung daher wieder setzen (analog `select_dataset`),
            # sonst verliert man beim Settings-OK/Panel-Toggle die aktive-Sample-
            # Markierung + den Export-Button, obwohl das Tabellen-Highlight bleibt.
            if self.sample is not None:
                self.window.highlight_sample(
                    self.sample, filtered=self.filter_active_sample_id is not None
                )

    def sync_view_menu(self) -> None:
        """Spiegelt die app-weiten View-Toggles ins „Ansicht"-Menü (Sprint 22).

        Beim Start und nach jeder Settings-Änderung aufgerufen, damit Menü,
        Settings-Dialog und persistierter State konsistent bleiben. Die
        Feature-Häkchen zeigen die rohen Einzel-Toggles."""
        self.window.apply_view_menu_state(
            show_filter=self.settings.show_filter_feature,
            show_cluster=self.settings.show_cluster_feature,
            show_stratified=self.settings.show_stratified_feature,
            show_dashboard=self.settings.show_dashboard,
            show_audit_trail=self.settings.show_audit_trail,
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
        self.push_samples(samples)

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

    # ---- Ansichts-Reset (Sprint 31) ------------------------------------

    def clear_view(self) -> bool:
        """Leert NUR die Ansicht (Datentabelle + Sidebar-Listen) – ohne DB-Eingriff.

        Bewusst ein *Ansichts*-Reset, KEIN Lösch-Feature: weder `datasets`/
        `dataset_rows` noch Audit-Events werden angefasst. Ein hartes Delete
        wäre ohne Schema-Änderung gar nicht möglich (Append-only-Audit-FK, vgl.
        `reset_sampling`) und würde den ISAE-3402-Trail verletzen. Das Projekt
        bleibt offen; ein erneutes `reload_datasets`/Öffnen zeigt die
        Datensätze wieder, weil sie nie gelöscht wurden.

        Lehnt sich an `EngagementController.handle_close_engagement` an (Tabelle
        + Sidebar leeren ohne DB-Eingriff), schaltet aber bewusst NICHT auf den
        Welcome-Screen um. Liefert False als No-Op, wenn nichts geladen war.
        """
        if not self.has_engagement():
            return False
        if self.dataset is None and not self.datasets:
            return False
        # In-Memory-Auswahl/Highlight/Filter leeren (wie `reset_sampling`),
        # zusätzlich das aktive Dataset und die Dataset-Liste.
        self.dataset = None
        self.sample = None
        self.active_sample_id = None
        self.filter_active_sample_id = None
        self.datasets = []
        # Tabelle VOR allem anderen leeren (Muster `handle_close_engagement`),
        # damit kein paintEvent auf einer veralteten Verbindung landet.
        self.window.data_table().clear_dataset()
        self.window.clear_table()
        self.window.set_filter_only_sample(False)
        self.window.clear_active_sample()
        self.window.set_datasets([])
        self.window.set_samples([])
        self.update_undo_redo_state()
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
        self.last_seed = None
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
