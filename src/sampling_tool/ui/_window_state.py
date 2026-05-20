"""WindowStateController – QSettings-Restore/Save + Panel-Visibility (Sprint 19 / F-006)."""

from __future__ import annotations

from PyQt6.QtCore import QByteArray, QSettings
from PyQt6.QtWidgets import QSplitter, QTabWidget

from sampling_tool.ui._window_layout import _TAB_TITLE_AUDIT, _TAB_TITLE_DASHBOARD
from sampling_tool.ui.widgets.audit_trail_view import AuditTrailView
from sampling_tool.ui.widgets.dashboard_view import DashboardView


class WindowStateController:
    """QSettings-Restore/Save + Panel-Visibility + Splitter-Sizes-Cache."""

    def __init__(
        self,
        *,
        settings: QSettings,
        workspace_splitter: QSplitter,
        lower_tabs: QTabWidget,
        audit_trail_view: AuditTrailView,
        dashboard_view: DashboardView,
    ) -> None:
        self._settings = settings
        self._workspace_splitter = workspace_splitter
        self._lower_tabs = lower_tabs
        self._audit_trail_view = audit_trail_view
        self._dashboard_view = dashboard_view
        self._cached_splitter_sizes: list[int] | None = None

    def restore(self) -> None:
        """Stellt Splitter-Größen + aktiven Tab aus QSettings wieder her."""
        state = self._settings.value("workspace/inner_splitter")
        if isinstance(state, QByteArray):
            self._workspace_splitter.restoreState(state)
        tab_index = self._settings.value("workspace/lower_tab", 0)
        try:
            self._lower_tabs.setCurrentIndex(int(tab_index))
        except (TypeError, ValueError):
            self._lower_tabs.setCurrentIndex(0)

    def save(self) -> None:
        """Persistiert Splitter-Größen + aktiven Tab.

        Wenn beide Insights-Panels aus sind, ist der Splitter aktuell auf
        `[total, 0]` kollabiert – wir wollen aber die ECHTE Aufteilung
        speichern, damit Re-Show beim nächsten Start funktioniert. Dafür
        werden die gecachten Sizes vor dem `saveState()` temporär gesetzt.
        Qt respektiert `setSizes` nur, wenn das jeweilige Kind sichtbar
        ist – darum muss `_lower_tabs` kurz wieder eingeblendet werden.
        Das ist unkritisch, weil Save in der Praxis nur im `closeEvent`
        beim App-Beenden läuft.
        """
        if self._cached_splitter_sizes is not None:
            self._lower_tabs.setVisible(True)
            self._workspace_splitter.setSizes(self._cached_splitter_sizes)
        self._settings.setValue("workspace/inner_splitter", self._workspace_splitter.saveState())
        self._settings.setValue("workspace/lower_tab", self._lower_tabs.currentIndex())

    def apply_panel_visibility(self, *, show_dashboard: bool, show_audit_trail: bool) -> None:
        """Schaltet Dashboard- und AuditTrail-Tab im unteren Panel ein/aus.

        Wenn beide aus sind, verschwindet das gesamte `QTabWidget` und die
        Datentabelle nutzt die volle Höhe. Beim Re-Aktivieren werden die
        zuvor gemerkten Splitter-Größen wiederhergestellt.
        """
        self._rebuild_lower_tabs(show_dashboard=show_dashboard, show_audit_trail=show_audit_trail)
        both_off = not show_dashboard and not show_audit_trail
        self._lower_tabs.setVisible(not both_off)
        self._update_splitter_for_visibility(both_off=both_off)

    def _rebuild_lower_tabs(self, *, show_dashboard: bool, show_audit_trail: bool) -> None:
        """Tabs in fester Reihenfolge neu zusammensetzen, aktive Auswahl retten."""
        current_widget = self._lower_tabs.currentWidget()
        while self._lower_tabs.count() > 0:
            self._lower_tabs.removeTab(0)
        if show_audit_trail:
            self._lower_tabs.addTab(self._audit_trail_view, _TAB_TITLE_AUDIT)
        if show_dashboard:
            self._lower_tabs.addTab(self._dashboard_view, _TAB_TITLE_DASHBOARD)
        if current_widget is not None:
            idx = self._lower_tabs.indexOf(current_widget)
            if idx >= 0:
                self._lower_tabs.setCurrentIndex(idx)

    def _update_splitter_for_visibility(self, *, both_off: bool) -> None:
        """Splitter kollabieren oder wiederherstellen – inkl. Sizes-Cache."""
        if both_off:
            if self._cached_splitter_sizes is None:
                current_sizes = self._workspace_splitter.sizes()
                # Nur cachen, wenn der Splitter überhaupt schon Größen hat –
                # während des App-Starts kann sizes() noch [0, 0] liefern.
                if sum(current_sizes) > 0:
                    self._cached_splitter_sizes = current_sizes
            if self._cached_splitter_sizes is not None:
                total = sum(self._cached_splitter_sizes)
                self._workspace_splitter.setSizes([total, 0])
        elif self._cached_splitter_sizes is not None:
            self._workspace_splitter.setSizes(self._cached_splitter_sizes)
            self._cached_splitter_sizes = None
