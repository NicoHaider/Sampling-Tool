"""Coordinator zwischen `MainWindow`-Signals und den Sub-Controllern.

Sprint 13 / F-001: aus dem 1300-LoC-God-Object zerlegt. Diese Datei
hat jetzt nur noch zwei Aufgaben:
1. Sub-Controller + `WorkspaceSession` aufbauen, Factories durchreichen.
2. UI-Signale an den jeweils zuständigen Sub-Controller weiterleiten.

Externe API (`MainController(window, **factories)`) unverändert. Public
`handle_*`-Methoden bleiben als Backward-Compat-Fassade erhalten, damit
bestehende Tests ohne Anpassung weiterlaufen.

Sub-Controller:
- `EngagementController` – Engagement-Lifecycle (New, Open, Close, Recent)
- `WorkspaceController` – Import, Sampling, Reset, Undo/Redo
- `SelectionController` – Dataset-/Sample-/Filter-Auswahl, AuditEvent-Doppelklick
- `ExportController` – 4 Export-Handler (Sample-xlsx, AuditTrail-PDF, Excel-Multi, HTML)
- `HelpController` – Bug-Report, About, Settings, Hotkeys

Geteilter State + Glue-Helper leben in `WorkspaceSession`.

Undo/Redo-Konvention (verbindlich, unverändert):
- Nach jeder mutierenden Aktion (Sampling, Reset) wird der NEUE State auf
  den Undo-Stack gelegt.
- `handle_undo()` entfernt den Top vom Undo-Stack (Push to Redo) und
  rekonstruiert den **dahinterliegenden** State via `peek_undo()`. Ist der
  Stack leer, gilt der „leere" Zustand (kein Sample, keine Highlights).
- `handle_redo()` holt den Top vom Redo-Stack zurück und wendet ihn an.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from sampling_tool.ui.controllers._factories import (
    AuditPdfDialogFactory,
    ControllerFactories,
    DialogFactory,
    DuplicateDialogFactory,
    ExcelReportDialogFactory,
    ExportDialogFactory,
    HtmlReportDialogFactory,
    ImportOptionsDialogFactory,
    SamplingDialogFactory,
    SettingsDialogFactory,
    default_audit_pdf_factory,
    default_duplicate_dialog_factory,
    default_excel_report_factory,
    default_export_factory,
    default_html_report_factory,
    default_import_options_factory,
    default_new_engagement_factory,
    default_sampling_factory,
    default_settings_factory,
)
from sampling_tool.ui.controllers.engagement_controller import EngagementController
from sampling_tool.ui.controllers.export_controller import ExportController
from sampling_tool.ui.controllers.help_controller import HelpController
from sampling_tool.ui.controllers.selection_controller import SelectionController
from sampling_tool.ui.controllers.workspace_controller import WorkspaceController
from sampling_tool.ui.controllers.workspace_session import WorkspaceSession
from sampling_tool.ui.recent import RecentEngagementsStore
from sampling_tool.ui.settings_store import AppSettings, load_settings

if TYPE_CHECKING:
    from sampling_tool.core.models import Dataset, Engagement, SampleResult
    from sampling_tool.core.undo import UndoManager
    from sampling_tool.io.briefpapier import BriefpapierConfig
    from sampling_tool.persistence.database import Database
    from sampling_tool.persistence.repositories import EngagementStateRepo
    from sampling_tool.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


class MainController:
    """Coordinator – delegiert UI-Signale an Sub-Controller.

    Externe API (Konstruktor-Parameter + public `handle_*`-Methoden)
    unverändert ggü. dem Pre-Sprint-13-Stand. Tests, die `controller.
    handle_new_sampling()` direkt aufrufen, laufen unverändert weiter.
    """

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
        import_options_dialog_factory: ImportOptionsDialogFactory | None = None,
        settings: AppSettings | None = None,
    ) -> None:
        # ---- Session aufbauen --------------------------------------
        self.session = WorkspaceSession(
            window=window,
            settings=settings if settings is not None else load_settings(),
            recent_store=recent_store if recent_store is not None else RecentEngagementsStore(),
        )

        # ---- Factories bündeln -------------------------------------
        factories = ControllerFactories(
            new_engagement=dialog_factory
            if dialog_factory is not None
            else default_new_engagement_factory,
            duplicate=duplicate_dialog_factory
            if duplicate_dialog_factory is not None
            else default_duplicate_dialog_factory,
            sampling=sampling_dialog_factory
            if sampling_dialog_factory is not None
            else default_sampling_factory,
            export_sample=export_dialog_factory
            if export_dialog_factory is not None
            else default_export_factory,
            audit_pdf=audit_pdf_dialog_factory
            if audit_pdf_dialog_factory is not None
            else default_audit_pdf_factory,
            excel_report=excel_report_dialog_factory
            if excel_report_dialog_factory is not None
            else default_excel_report_factory,
            html_report=html_report_dialog_factory
            if html_report_dialog_factory is not None
            else default_html_report_factory,
            settings=settings_dialog_factory
            if settings_dialog_factory is not None
            else default_settings_factory,
            import_options=import_options_dialog_factory
            if import_options_dialog_factory is not None
            else default_import_options_factory,
        )

        # ---- Sub-Controller aufbauen -------------------------------
        self.engagement = EngagementController(self.session, factories)
        self.workspace = WorkspaceController(self.session, factories)
        self.selection = SelectionController(self.session, factories)
        self.export = ExportController(self.session, factories)
        self.help = HelpController(self.session, factories)

        # ---- Engagement-Ordner sicherstellen, damit File-Dialoge ---
        # direkt dort starten können. Idempotent.
        self.session.settings.engagements_dir.mkdir(parents=True, exist_ok=True)

        # ---- Signals verdrahten + Initial-Refresh ------------------
        self._connect_signals()
        self.engagement.refresh_recent()
        self.session.window.apply_panel_visibility(
            show_dashboard=self.session.settings.show_dashboard,
            show_audit_trail=self.session.settings.show_audit_trail,
        )

    # ---- Externe Convenience-Properties (für Tests) --------------------
    #
    # Bestehende Tests greifen direkt auf private MainController-Attribute
    # zu (`controller._sample`, `controller._engagement`, etc.). Diese
    # Properties delegieren transparent an die Session-State, damit die
    # Tests unverändert weiterlaufen.

    @property
    def recent_store(self) -> RecentEngagementsStore:
        return self.session.recent_store

    @property
    def window(self) -> MainWindow:
        return self.session.window

    @property
    def _settings(self) -> AppSettings:
        return self.session.settings

    @_settings.setter
    def _settings(self, value: AppSettings) -> None:
        self.session.settings = value

    @property
    def _db(self) -> Database | None:
        return self.session.db

    @property
    def _engagement(self) -> Engagement | None:
        return self.session.engagement

    @property
    def _dataset(self) -> Dataset | None:
        return self.session.dataset

    @property
    def _sample(self) -> SampleResult | None:
        return self.session.sample

    @property
    def _active_sample_id(self) -> int | None:
        return self.session.active_sample_id

    @property
    def _filter_active_sample_id(self) -> int | None:
        return self.session.filter_active_sample_id

    @property
    def _undo_manager(self) -> UndoManager | None:
        return self.session.undo_manager

    @property
    def _state_repo(self) -> EngagementStateRepo | None:
        return self.session.state_repo

    @property
    def _restoring_state(self) -> bool:
        return self.session.restoring_state

    @property
    def _datasets(self) -> list[Dataset]:
        return self.session.datasets

    # ---- Public Convenience-Methode -------------------------------------

    def refresh_recent(self) -> None:
        """Liest die Recent-Liste und gibt sie ans Fenster."""
        self.engagement.refresh_recent()

    # ---- Backward-Compat-Fassade für public handle_*-Methoden ----------
    #
    # Bestehende Tests rufen diese Methoden direkt auf dem MainController auf.
    # Forwards an den jeweiligen Sub-Controller. Reine Delegation, keine
    # eigene Logik.

    def handle_new_engagement(self) -> None:
        self.engagement.handle_new_engagement()

    def handle_open_engagement(self, db_path: Path) -> None:
        self.engagement.handle_open_engagement(db_path)

    def handle_close_engagement_requested(self) -> None:
        self.engagement.handle_close_engagement_requested()

    def handle_close_engagement(self) -> None:
        self.engagement.handle_close_engagement()

    def handle_import_excel(self) -> None:
        self.workspace.handle_import_excel()

    def handle_new_sampling(self) -> None:
        self.workspace.handle_new_sampling()

    def handle_reset(self) -> None:
        self.workspace.handle_reset()

    def handle_reset_sampling(self) -> None:
        self.workspace.handle_reset_sampling()

    def handle_undo(self) -> None:
        self.workspace.handle_undo()

    def handle_redo(self) -> None:
        self.workspace.handle_redo()

    def handle_dataset_selected(self, dataset_id: int) -> None:
        self.selection.handle_dataset_selected(dataset_id)

    def handle_sample_selected(self, sample_id: int) -> None:
        self.selection.handle_sample_selected(sample_id)

    def handle_sample_filter_toggled(self, sample_id: int) -> None:
        self.selection.handle_sample_filter_toggled(sample_id)

    def handle_filter_only_sample_toggled(self, active: bool) -> None:
        self.selection.handle_filter_only_sample_toggled(active)

    def handle_audit_event_double_clicked(self, event_id: int) -> None:
        self.selection.handle_audit_event_double_clicked(event_id)

    def handle_export_sample(self) -> None:
        self.export.handle_export_sample()

    def handle_export_audit_pdf(self) -> None:
        self.export.handle_export_audit_pdf()

    def handle_export_excel_report(self) -> None:
        self.export.handle_export_excel_report()

    def handle_export_html_report(self) -> None:
        self.export.handle_export_html_report()

    def handle_bug_report(self) -> None:
        self.help.handle_bug_report()

    def handle_about(self) -> None:
        self.help.handle_about()

    def handle_settings(self) -> None:
        self.help.handle_settings()

    def handle_hotkeys(self) -> None:
        self.help.handle_hotkeys()

    # ---- Backward-Compat: interne Helfer als Forwards ------------------
    #
    # Einzelne Tests greifen auf private Helper zu (z. B. `_refresh_audit_trail`
    # in einem Test, der manuell einen Refresh triggert; `_resolve_briefpapier`
    # für Briefpapier-Logik). Delegate-Forwards auf die Session.

    def _refresh_audit_trail(self) -> None:
        self.session.refresh_audit_trail()

    def _refresh_dashboard(self) -> None:
        self.session.refresh_dashboard()

    def _refresh_views(self) -> None:
        self.session.refresh_views()

    def _resolve_briefpapier(self) -> BriefpapierConfig | None:
        return self.session.resolve_briefpapier()

    # ---- Signal-Routing ------------------------------------------------

    def _connect_signals(self) -> None:
        """Verdrahtet MainWindow-Signals an die zuständigen Sub-Controller."""
        w = self.session.window
        # Engagement-Lifecycle
        w.new_engagement_requested.connect(self.engagement.handle_new_engagement)
        w.open_engagement_requested.connect(self.engagement.handle_open_engagement)
        w.close_engagement_requested.connect(self.engagement.handle_close_engagement_requested)
        # Workspace-Mutationen
        w.import_excel_requested.connect(self.workspace.handle_import_excel)
        w.new_sample_requested.connect(self.workspace.handle_new_sampling)
        w.reset_sample_requested.connect(self.workspace.handle_reset)
        w.reset_sampling_requested.connect(self.workspace.handle_reset_sampling)
        w.undo_requested.connect(self.workspace.handle_undo)
        w.redo_requested.connect(self.workspace.handle_redo)
        # Selektion
        w.dataset_selected.connect(self.selection.handle_dataset_selected)
        w.sample_selected.connect(self.selection.handle_sample_selected)
        w.sample_filter_toggled.connect(self.selection.handle_sample_filter_toggled)
        w.filter_only_sample_toggled.connect(self.selection.handle_filter_only_sample_toggled)
        w.audit_event_double_clicked.connect(self.selection.handle_audit_event_double_clicked)
        # Export
        w.export_sample_requested.connect(self.export.handle_export_sample)
        w.export_audit_pdf_requested.connect(self.export.handle_export_audit_pdf)
        w.export_excel_report_requested.connect(self.export.handle_export_excel_report)
        w.export_html_report_requested.connect(self.export.handle_export_html_report)
        # Help / Settings
        w.bug_report_requested.connect(self.help.handle_bug_report)
        w.about_requested.connect(self.help.handle_about)
        w.settings_requested.connect(self.help.handle_settings)
        w.hotkeys_requested.connect(self.help.handle_hotkeys)
        # Refresh-Triggers
        w.audit_refresh_requested.connect(self.session.refresh_audit_trail)
        w.dashboard_refresh_requested.connect(self.session.refresh_dashboard)
