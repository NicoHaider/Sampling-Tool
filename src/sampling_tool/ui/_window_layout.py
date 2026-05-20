"""Workspace-Layout-Builder für MainWindow (Sprint 19 / F-006)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSplitter, QTabWidget

from sampling_tool.ui.widgets.audit_trail_view import AuditTrailView
from sampling_tool.ui.widgets.dashboard_view import DashboardView
from sampling_tool.ui.widgets.data_table import DataTableView
from sampling_tool.ui.widgets.sidebar import NavigationSidebar

if TYPE_CHECKING:
    from sampling_tool.ui.main_window import MainWindow

# Tab-Titel im unteren QTabWidget (vorher in main_window.py).
_TAB_TITLE_AUDIT: str = "AuditTrail"
_TAB_TITLE_DASHBOARD: str = "Dashboard"


def build_workspace(window: MainWindow) -> QSplitter:
    """Baut den Workspace-Splitter und setzt window._sidebar /
    _workspace_splitter / _data_table / _lower_tabs / _audit_trail_view /
    _dashboard_view. Returnt den äußeren Splitter."""
    # Outer horizontal splitter: Sidebar | (Tabelle / AuditTrail+Dashboard)
    outer = QSplitter(Qt.Orientation.Horizontal)
    outer.setHandleWidth(1)
    outer.setObjectName("WorkspaceOuterSplitter")

    window._sidebar = NavigationSidebar()
    window._sidebar.dataset_selected.connect(window.dataset_selected.emit)
    window._sidebar.sample_selected.connect(window.sample_selected.emit)
    window._sidebar.sample_double_clicked.connect(window.sample_filter_toggled.emit)
    window._sidebar.filter_only_sample_toggled.connect(window.filter_only_sample_toggled.emit)
    outer.addWidget(window._sidebar)

    # Inner vertical splitter: Tabelle oben, Tab-Widget (AuditTrail/Dashboard) unten.
    window._workspace_splitter = QSplitter(Qt.Orientation.Vertical)
    window._workspace_splitter.setObjectName("WorkspaceInnerSplitter")
    window._workspace_splitter.setHandleWidth(2)

    window._data_table = DataTableView()
    window._workspace_splitter.addWidget(window._data_table)

    window._lower_tabs = QTabWidget()
    window._lower_tabs.setObjectName("LowerTabs")

    window._audit_trail_view = AuditTrailView()
    window._audit_trail_view.event_double_clicked.connect(window.audit_event_double_clicked.emit)
    window._audit_trail_view.refresh_requested.connect(window.audit_refresh_requested.emit)
    window._lower_tabs.addTab(window._audit_trail_view, _TAB_TITLE_AUDIT)

    window._dashboard_view = DashboardView()
    window._dashboard_view.refresh_requested.connect(window.dashboard_refresh_requested.emit)
    window._dashboard_view.sample_clicked.connect(window.sample_selected.emit)
    window._dashboard_view.dataset_clicked.connect(window.dataset_selected.emit)
    window._lower_tabs.addTab(window._dashboard_view, _TAB_TITLE_DASHBOARD)

    window._workspace_splitter.addWidget(window._lower_tabs)
    window._workspace_splitter.setSizes([600, 400])
    window._workspace_splitter.setStretchFactor(0, 3)
    window._workspace_splitter.setStretchFactor(1, 2)

    outer.addWidget(window._workspace_splitter)
    outer.setStretchFactor(0, 0)
    outer.setStretchFactor(1, 1)
    outer.setSizes([250, 1030])
    return outer
