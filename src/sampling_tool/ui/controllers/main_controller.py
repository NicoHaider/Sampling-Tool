"""Coordinator zwischen `MainWindow`-Signals und den Sub-Controllern.

Sprint 13 / F-001: aus dem 1300-LoC-God-Object zerlegt. Diese Datei
hat jetzt nur noch zwei Aufgaben:
1. Sub-Controller + `WorkspaceSession` aufbauen, Factories durchreichen.
2. UI-Signale an den jeweils zuständigen Sub-Controller weiterleiten.

Externe API (`MainController(window, **factories)`) unverändert. Public
`handle_*`-Methoden bleiben (noch) als Backward-Compat-Fassade erhalten,
damit bestehende Tests ohne Anpassung weiterlaufen — wird schrittweise pro
Subcontroller abgebaut (Sprint 59 / Teil C: `export` migriert,
`self.export.handle_export_*` statt Forward).

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

import dataclasses
import logging
from typing import TYPE_CHECKING, Any

from sampling_tool.ui.controllers._factories import (
    AuditPdfDialogFactory,
    ControllerFactories,
    DialogFactory,
    DuplicateDialogFactory,
    ExcelReportDialogFactory,
    ExportDialogFactory,
    HtmlReportDialogFactory,
    IdColumnDialogFactory,
    ImportOptionsDialogFactory,
    SamplingDialogFactory,
    SettingsDialogFactory,
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
    from sampling_tool.core.models import Engagement, SampleResult
    from sampling_tool.io.briefpapier import BriefpapierConfig
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
        id_column_dialog_factory: IdColumnDialogFactory | None = None,
        settings: AppSettings | None = None,
    ) -> None:
        # ---- Session aufbauen --------------------------------------
        self.session = WorkspaceSession(
            window=window,
            settings=settings if settings is not None else load_settings(),
            recent_store=recent_store if recent_store is not None else RecentEngagementsStore(),
        )

        # ---- Factories bündeln -------------------------------------
        # Sprint 59 / Teil B (L-003): Basis sind die 10 Default-Factories aus
        # `ControllerFactories.defaults()`; nur tatsächlich übergebene
        # (nicht-`None`) Konstruktor-Kwargs überschreiben sie per
        # `dataclasses.replace`. Verhaltensidentisch zur vorherigen
        # 10-Ternary-Kette: pro Feld gilt "Override falls gesetzt, sonst
        # Default". (Als Comprehension statt 10 einzelner `if`s, damit die
        # McCabe-Komplexität von `__init__` nicht über den Ruff-Grenzwert
        # steigt.)
        #
        # `dict[str, Any]`: die Feldnamen sind hier zur Laufzeit erzeugte
        # Strings, keine Literal-Keywords – kein Typ (auch nicht `TypedDict`
        # + `cast`) lässt mypy die Feld<->Wert-Zuordnung aus dieser
        # String-Tuple-Liste ableiten. `dataclasses.replace()`s eigener
        # Stub ist ohnehin `**changes: Any`, die Korrektheit der Zuordnung
        # sichert stattdessen die Factory-Injection-Testsuite ab (u. a.
        # `test_controller_factories_defaults`), nicht der Type-Checker.
        factory_overrides: tuple[tuple[str, object], ...] = (
            ("new_engagement", dialog_factory),
            ("duplicate", duplicate_dialog_factory),
            ("sampling", sampling_dialog_factory),
            ("export_sample", export_dialog_factory),
            ("audit_pdf", audit_pdf_dialog_factory),
            ("excel_report", excel_report_dialog_factory),
            ("html_report", html_report_dialog_factory),
            ("settings", settings_dialog_factory),
            ("import_options", import_options_dialog_factory),
            ("id_column", id_column_dialog_factory),
        )
        overrides: dict[str, Any] = {
            field: value for field, value in factory_overrides if value is not None
        }
        factories = dataclasses.replace(ControllerFactories.defaults(), **overrides)

        # ---- Sub-Controller aufbauen -------------------------------
        self.engagement = EngagementController(self.session, factories)
        self.workspace = WorkspaceController(self.session, factories)
        self.selection = SelectionController(self.session)
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
        # Sprint 22: „Ansicht"-Menü-Checks aus den app-weiten Toggles spiegeln.
        self.session.sync_view_menu()

    # ---- Externe Convenience-Properties (für Tests) --------------------
    #
    # Bestehende Tests greifen direkt auf private MainController-Attribute
    # zu (`controller._sample`, `controller._engagement`, etc.). Diese
    # Properties delegieren transparent an die Session-State, damit die
    # Tests unverändert weiterlaufen.

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
    def _engagement(self) -> Engagement | None:
        return self.session.engagement

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
    def _state_repo(self) -> EngagementStateRepo | None:
        return self.session.state_repo

    # ---- Public Convenience-Methode -------------------------------------

    def refresh_recent(self) -> None:
        """Liest die Recent-Liste und gibt sie ans Fenster."""
        self.engagement.refresh_recent()

    # ---- Backward-Compat: interne Helfer als Forwards ------------------
    #
    # Einzelne Tests greifen auf private Helper zu (z. B. `_refresh_audit_trail`
    # in einem Test, der manuell einen Refresh triggert; `_resolve_briefpapier`
    # für Briefpapier-Logik). Delegate-Forwards auf die Session.

    def _refresh_audit_trail(self) -> None:
        self.session.refresh_audit_trail()

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
        w.clear_loaded_datasets_requested.connect(self.workspace.handle_clear_loaded_datasets)
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
        # Sprint 28: Vorlagen-Verwaltungsfenster (einziger Einstiegspunkt).
        w.manage_templates_requested.connect(self.help.handle_manage_templates)
        # Ansicht-Menü (Sprint 22): Einzel-Toggles + Panel-Toggles
        w.feature_toggled.connect(self.help.handle_feature_toggled)
        w.panel_toggled.connect(self.help.handle_panel_toggled)
        # Refresh-Triggers
        w.audit_refresh_requested.connect(self.session.refresh_audit_trail)
        w.dashboard_refresh_requested.connect(self.session.refresh_dashboard)
