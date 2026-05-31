"""Hauptfenster der Anwendung – Welcome ↔ Workspace State-Maschine.

Das Fenster ist „dumm" – es zeigt eines von zwei Top-Level-Widgets über
einen `QStackedWidget` an (Welcome / Workspace), bietet Menü+Toolbar und
gibt Signals an den `MainController` weiter. Persistenz und Repo-Calls
laufen ausschließlich im Controller.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QWidget,
)

from sampling_tool.config import APP_NAME, APP_ORG, ENGAGEMENTS_DIR
from sampling_tool.core.models import AuditEvent, Dataset, Engagement, SampleResult
from sampling_tool.persistence.repositories import DatasetRepo
from sampling_tool.ui._window_layout import (
    build_workspace,
)
from sampling_tool.ui._window_menu import (
    _MAX_RECENT_IN_MENU,
    build_menu,
    rebuild_recent_menu,
)
from sampling_tool.ui._window_state import WindowStateController
from sampling_tool.ui._window_toolbar import build_toolbar
from sampling_tool.ui.recent import RecentEntry
from sampling_tool.ui.widgets.audit_trail_view import AuditTrailView
from sampling_tool.ui.widgets.dashboard_view import DashboardView
from sampling_tool.ui.widgets.data_table import DataTableView
from sampling_tool.ui.widgets.sidebar import NavigationSidebar
from sampling_tool.ui.widgets.welcome import WelcomeScreen

# Deutsche Anzeige-Namen der Sampling-Methoden für die Statusbar.
_METHOD_LABELS: dict[str, str] = {
    "simple": "Einfach",
    "cluster": "Cluster",
    "stratified": "Geschichtet",
}


class MainWindow(QMainWindow):
    """Top-Level-Fenster mit Welcome- und Workspace-Ansicht."""

    new_engagement_requested = pyqtSignal()
    open_engagement_requested = pyqtSignal(Path)
    close_engagement_requested = pyqtSignal()
    import_excel_requested = pyqtSignal()
    new_sample_requested = pyqtSignal()
    reset_sample_requested = pyqtSignal()
    reset_sampling_requested = pyqtSignal()
    undo_requested = pyqtSignal()
    redo_requested = pyqtSignal()
    export_sample_requested = pyqtSignal()
    export_audit_pdf_requested = pyqtSignal()
    export_excel_report_requested = pyqtSignal()
    export_html_report_requested = pyqtSignal()
    bug_report_requested = pyqtSignal()
    about_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    hotkeys_requested = pyqtSignal()
    dataset_selected = pyqtSignal(int)
    sample_selected = pyqtSignal(int)
    sample_filter_toggled = pyqtSignal(int)
    filter_only_sample_toggled = pyqtSignal(bool)
    audit_event_double_clicked = pyqtSignal(int)
    audit_refresh_requested = pyqtSignal()
    dashboard_refresh_requested = pyqtSignal()

    # Von den _window_*-Buildern (Sprint 19 / F-006) befüllte Attribute –
    # hier deklariert, damit mypy-strict die externe Zuweisung akzeptiert.
    _file_menu: QMenu
    _recent_menu: QMenu
    _help_menu: QMenu
    _action_new: QAction
    _action_open: QAction
    _action_close: QAction
    _action_settings: QAction
    _action_import: QAction
    _action_export_sample: QAction
    _action_export_pdf: QAction
    _action_excel_report: QAction
    _action_html_report: QAction
    _action_new_sample: QAction
    _action_reset_sample: QAction
    _action_reset_sampling: QAction
    _action_undo: QAction
    _action_redo: QAction
    _action_hotkeys: QAction
    _action_bug_report: QAction
    _action_about: QAction
    _action_switch_engagement: QAction
    _toolbar: QToolBar
    _sidebar: NavigationSidebar
    _workspace_splitter: QSplitter
    _data_table: DataTableView
    _lower_tabs: QTabWidget
    _audit_trail_view: AuditTrailView
    _dashboard_view: DashboardView

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)

        self._settings = QSettings(APP_ORG, APP_NAME)

        # ---- zentrale Widgets ----
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._welcome = WelcomeScreen()
        self._welcome.new_engagement_requested.connect(self.new_engagement_requested.emit)
        self._welcome.open_engagement_requested.connect(self.open_engagement_requested.emit)
        self._stack.addWidget(self._welcome)

        self._workspace = build_workspace(self)
        self._stack.addWidget(self._workspace)
        self._window_state = WindowStateController(
            settings=self._settings,
            workspace_splitter=self._workspace_splitter,
            lower_tabs=self._lower_tabs,
            audit_trail_view=self._audit_trail_view,
            dashboard_view=self._dashboard_view,
        )
        self._window_state.restore()

        # ---- Statusbar ----
        self._status_engagement = QLabel("Kein Engagement")
        self._status_dataset = QLabel("Kein Dataset")
        self._status_rows = QLabel("0 Zeilen")
        self._status_sample = QLabel("—")
        status = QStatusBar()
        status.addPermanentWidget(self._status_engagement)
        status.addPermanentWidget(_separator())
        status.addPermanentWidget(self._status_dataset)
        status.addPermanentWidget(_separator())
        status.addPermanentWidget(self._status_rows)
        status.addPermanentWidget(_separator())
        status.addPermanentWidget(self._status_sample)
        self.setStatusBar(status)

        # ---- Menü + Toolbar ----
        build_menu(self)
        build_toolbar(self)

        self.show_welcome()

    # ---- Public API – State -------------------------------------------

    def show_welcome(self) -> None:
        """Zeigt den Welcome-Screen (keine .db geladen)."""
        self._stack.setCurrentWidget(self._welcome)
        self._set_workspace_actions_enabled(False)
        self._status_engagement.setText("Kein Engagement")
        self._status_dataset.setText("Kein Dataset")
        self._status_rows.setText("0 Zeilen")
        self.set_active_sample_label(None)

    def show_workspace(self) -> None:
        """Wechselt zur Arbeitsansicht (Sidebar + Tabelle)."""
        self._stack.setCurrentWidget(self._workspace)
        self._set_workspace_actions_enabled(True)

    # ---- Public API – Daten -------------------------------------------

    def set_engagement(self, engagement: Engagement | None) -> None:
        """Engagement-Block in Sidebar + Statusbar aktualisieren."""
        self._sidebar.set_engagement(engagement)
        self._status_engagement.setText(
            engagement.client_name if engagement is not None else "Kein Engagement"
        )

    def set_datasets(self, datasets: list[Dataset]) -> None:
        """Datasets in der Sidebar aktualisieren."""
        self._sidebar.set_datasets(datasets)

    def set_samples(self, samples: list[SampleResult]) -> None:
        """Samples in der Sidebar aktualisieren."""
        self._sidebar.set_samples(samples)
        self._action_export_sample.setEnabled(False)

    def show_dataset(self, dataset: Dataset, repo: DatasetRepo) -> None:
        """Lädt das Dataset in die Tabelle und setzt Statusbar.

        Sprint-11.2: rows werden on-demand vom `repo` geladen
        (FIFO-Cache im TableModel, siehe `DatasetTableModel`). Der
        Controller übergibt das Repo statt einer materialisierten
        Row-Liste; das hält den UI-RAM konstant.
        """
        self._data_table.set_dataset(dataset, repo)
        self._status_dataset.setText(dataset.name)
        self._status_rows.setText(f"{dataset.row_count} Zeilen")
        self.set_active_sample_label(None)
        self._sidebar.set_active_sample(None)
        self._action_new_sample.setEnabled(True)

    def set_audit_events(self, events: list[AuditEvent]) -> None:
        """Liefert die Events an die AuditTrail-View."""
        self._audit_trail_view.set_events(events)

    def set_dashboard_data(
        self,
        engagement: Engagement | None,
        datasets: list[Dataset],
        samples: list[SampleResult],
        audit_events: list[AuditEvent],
    ) -> None:
        """Liefert die Dashboard-Daten an die DashboardView."""
        self._dashboard_view.set_data(engagement, datasets, samples, audit_events)

    def set_reports_enabled(self, enabled: bool) -> None:
        """Schaltet die Report-Buttons (Excel/HTML) ein/aus."""
        for action in (self._action_excel_report, self._action_html_report):
            action.setEnabled(enabled)

    def highlight_sample(self, sample: SampleResult, *, filtered: bool = False) -> None:
        """Markiert Sample-Zeilen und aktualisiert Statusbar + Sidebar."""
        self._data_table.highlight_rows(sample.selected_row_ids)
        self.set_active_sample_label(sample, filtered=filtered)
        self._sidebar.set_active_sample(sample.id)
        self._action_export_sample.setEnabled(True)

    def set_active_sample_label(
        self,
        sample: SampleResult | None,
        *,
        filtered: bool = False,
    ) -> None:
        """Aktualisiert das „Aktive Stichprobe"-Label in der Statusbar.

        Wenn `filtered=True`, wird der Suffix " – gefiltert" angehängt.
        """
        if sample is None or sample.id is None:
            self._status_sample.setText("Aktive Stichprobe: keine")
            return
        method_label = _METHOD_LABELS.get(sample.config.method.value, sample.config.method.value)
        text = (
            f"Aktive Stichprobe: #{sample.id} ({method_label}, "
            f"{sample.actual_size}/{sample.population_size})"
        )
        if filtered:
            text += " – gefiltert"
        self._status_sample.setText(text)

    def clear_active_sample(self) -> None:
        """Entfernt die aktive-Stichprobe-Markierung aus Sidebar + Statusbar."""
        self._sidebar.set_active_sample(None)
        self.set_active_sample_label(None)

    def filter_to_sample(self, sample: SampleResult) -> None:
        """Filtert die Tabelle auf Sample-Zeilen."""
        self._data_table.filter_to_rows(sample.selected_row_ids)

    def clear_sample_filter(self) -> None:
        """Hebt einen Sample-Filter wieder auf."""
        self._data_table.clear_filter()

    def set_filter_only_sample(self, active: bool) -> None:
        """Setzt die Sidebar-Checkbox programmatisch (ohne Signal-Loop)."""
        self._sidebar.set_filter_only_sample(active)

    def set_filter_enabled(self, enabled: bool) -> None:
        """Schaltet die Sidebar-Filter-Checkbox (Controller entscheidet)."""
        self._sidebar.set_filter_enabled(enabled)

    def clear_table(self) -> None:
        """Entfernt das aktuelle Dataset aus der Tabelle."""
        self._data_table.clear_dataset()

    def set_recent_entries(self, entries: list[RecentEntry]) -> None:
        """Aktualisiert Welcome-Screen und das File→Recent-Submenü."""
        self._welcome.set_recent_entries(entries[:_MAX_RECENT_IN_MENU])
        rebuild_recent_menu(self, entries[:_MAX_RECENT_IN_MENU])

    # ---- Accessors (für Tests) ----------------------------------------

    def workspace_widget(self) -> QWidget:
        """Workspace-Container (interner Splitter)."""
        return self._workspace

    def data_table(self) -> DataTableView:
        """Datentabelle (Tests)."""
        return self._data_table

    def sidebar(self) -> NavigationSidebar:
        """Sidebar-Widget (Tests)."""
        return self._sidebar

    def welcome_screen(self) -> WelcomeScreen:
        """Welcome-Screen-Widget (Tests)."""
        return self._welcome

    def audit_trail_view(self) -> AuditTrailView:
        """AuditTrail-View (Tests / Controller)."""
        return self._audit_trail_view

    def dashboard_view(self) -> DashboardView:
        """Dashboard-View (Tests / Controller)."""
        return self._dashboard_view

    def workspace_splitter(self) -> QSplitter:
        """Vertikaler Workspace-Splitter (Tests)."""
        return self._workspace_splitter

    def lower_tabs(self) -> QTabWidget:
        """Tab-Widget unten (Tests)."""
        return self._lower_tabs

    def is_workspace_visible(self) -> bool:
        """`True`, wenn aktuell der Workspace angezeigt wird."""
        return self._stack.currentWidget() is self._workspace

    # ---- Settings-Persistenz (Backward-Compat-Shims → WindowStateController) ----

    def apply_panel_visibility(self, *, show_dashboard: bool, show_audit_trail: bool) -> None:
        """Schaltet Dashboard-/AuditTrail-Tab (Delegate an WindowStateController)."""
        self._window_state.apply_panel_visibility(
            show_dashboard=show_dashboard, show_audit_trail=show_audit_trail
        )

    @property
    def _cached_splitter_sizes(self) -> list[int] | None:
        """Backward-Compat-Shim → WindowStateController (Sprint 19 / F-006)."""
        return self._window_state._cached_splitter_sizes

    @_cached_splitter_sizes.setter
    def _cached_splitter_sizes(self, value: list[int] | None) -> None:
        """Backward-Compat-Shim → WindowStateController (Sprint 19 / F-006)."""
        self._window_state._cached_splitter_sizes = value

    def _save_workspace_state(self) -> None:
        """Backward-Compat-Shim → WindowStateController.save()."""
        self._window_state.save()

    def closeEvent(self, a0: QCloseEvent | None) -> None:  # noqa: N802
        """Sichert UI-State beim Schließen."""
        try:
            self._window_state.save()
        finally:
            super().closeEvent(a0)

    # ---- State-Helfer --------------------------------------------------

    def _set_workspace_actions_enabled(self, enabled: bool) -> None:
        """Steuert die menu/toolbar-Aktionen, die nur mit offenem Engagement Sinn ergeben."""
        for action in (
            self._action_close,
            self._action_import,
            self._action_export_pdf,
            self._action_excel_report,
            self._action_html_report,
        ):
            action.setEnabled(enabled)
        # Diese benötigen zusätzlich ein Dataset / Sample – Controller schaltet
        # sie später frei.
        for action in (
            self._action_new_sample,
            self._action_reset_sample,
            self._action_reset_sampling,
            self._action_export_sample,
            self._action_undo,
            self._action_redo,
        ):
            action.setEnabled(False)

    # ---- Slots ---------------------------------------------------------

    def _on_open_clicked(self) -> None:
        start_dir = str(ENGAGEMENTS_DIR) if ENGAGEMENTS_DIR.exists() else ""
        path_str, _filter = QFileDialog.getOpenFileName(
            self,
            "Engagement öffnen",
            start_dir,
            "SQLite-Engagement (*.db);;Alle Dateien (*)",
        )
        if path_str:
            self.open_engagement_requested.emit(Path(path_str))

    # ---- Public API – Undo/Redo + Reset --------------------------------

    def set_undo_redo_enabled(self, can_undo: bool, can_redo: bool) -> None:
        """Schaltet die Undo-/Redo-Menüpunkte. Wird vom Controller aufgerufen."""
        self._action_undo.setEnabled(can_undo)
        self._action_redo.setEnabled(can_redo)

    def set_reset_enabled(self, enabled: bool) -> None:
        """Schaltet die Reset-Aktionen (Menü + Toolbar). Nur wenn ein Sample aktiv ist."""
        self._action_reset_sample.setEnabled(enabled)
        self._action_reset_sampling.setEnabled(enabled)


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _separator() -> QLabel:
    label = QLabel("│")
    label.setStyleSheet("color: #D9D9D9; padding: 0 6px;")
    return label
