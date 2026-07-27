"""WindowStateController – QSettings-Restore/Save + Panel-Visibility (Sprint 19 / F-006).

Sprint 67 / Teil A: übernimmt zusätzlich die Fenster-Startgröße –
bildschirmgerecht über `_geometry.fit_to_available` statt einer harten
`resize()`. Die Entscheidungslogik steckt in den reinen Funktionen aus
`_geometry.py`; hier bleibt nur die dünne Qt-Anbindung (Property-Lesen/
-Schreiben, QSettings-I/O).
"""

from __future__ import annotations

from PyQt6.QtCore import QByteArray, QRect, QSettings, QSize, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QMainWindow, QSplitter, QTabWidget

from sampling_tool.ui._geometry import fit_to_available, is_geometry_visible
from sampling_tool.ui._window_layout import _TAB_TITLE_AUDIT, _TAB_TITLE_DASHBOARD
from sampling_tool.ui.settings_store import _bool
from sampling_tool.ui.widgets.audit_trail_view import AuditTrailView
from sampling_tool.ui.widgets.dashboard_view import DashboardView

# Wunschgröße beim Start – wird über `fit_to_available` auf den tatsächlich
# verfügbaren Bildschirmbereich begrenzt (vorher hart `resize(1280, 800)`
# ohne jeden Bezug zur Bildschirmgröße – auf 1280×720 ragte das Fenster
# unter die Taskleiste).
_DESIRED_WIDTH: int = 1280
_DESIRED_HEIGHT: int = 800


class WindowStateController:
    """QSettings-Restore/Save + Panel-Visibility + Splitter-Sizes-Cache."""

    def __init__(
        self,
        *,
        settings: QSettings,
        window: QMainWindow,
        workspace_splitter: QSplitter,
        lower_tabs: QTabWidget,
        audit_trail_view: AuditTrailView,
        dashboard_view: DashboardView,
    ) -> None:
        self._settings = settings
        self._window = window
        self._workspace_splitter = workspace_splitter
        self._lower_tabs = lower_tabs
        self._audit_trail_view = audit_trail_view
        self._dashboard_view = dashboard_view
        self._cached_splitter_sizes: list[int] | None = None

    def restore(self) -> None:
        """Stellt Fenstergeometrie, Splitter-Größen + aktiven Tab wieder her."""
        self._restore_window_geometry()
        state = self._settings.value("workspace/inner_splitter")
        if isinstance(state, QByteArray):
            self._workspace_splitter.restoreState(state)
        tab_index = self._settings.value("workspace/lower_tab", 0)
        try:
            self._lower_tabs.setCurrentIndex(int(tab_index))
        except (TypeError, ValueError):
            self._lower_tabs.setCurrentIndex(0)

    def save(self) -> None:
        """Persistiert Fenstergeometrie, Splitter-Größen + aktiven Tab.

        Wenn beide Insights-Panels aus sind, ist der Splitter aktuell auf
        `[total, 0]` kollabiert – wir wollen aber die ECHTE Aufteilung
        speichern, damit Re-Show beim nächsten Start funktioniert. Dafür
        werden die gecachten Sizes vor dem `saveState()` temporär gesetzt.
        Qt respektiert `setSizes` nur, wenn das jeweilige Kind sichtbar
        ist – darum muss `_lower_tabs` kurz wieder eingeblendet werden.
        Das ist unkritisch, weil Save in der Praxis nur im `closeEvent`
        beim App-Beenden läuft.
        """
        self._save_window_geometry()
        if self._cached_splitter_sizes is not None:
            self._lower_tabs.setVisible(True)
            self._workspace_splitter.setSizes(self._cached_splitter_sizes)
        self._settings.setValue("workspace/inner_splitter", self._workspace_splitter.saveState())
        self._settings.setValue("workspace/lower_tab", self._lower_tabs.currentIndex())

    # ---- Fenstergeometrie (Sprint 67 / Teil A) --------------------------

    def _restore_window_geometry(self) -> None:
        """Stellt gespeicherte Geometrie wieder her – wenn (noch) sichtbar.

        Reihenfolge (verbindlich, siehe SPRINT_67_PROMPT.md §3.3): gespeicherte
        Geometrie laden → Sichtbarkeit prüfen → gültig? anwenden : berechnete
        Startgröße anwenden. Maximiert-Zustand NACH der Geometrie setzen. Ein
        Fenster, das unsichtbar außerhalb aller Screens landet (Monitor
        abgesteckt / Auflösung geändert), ist schlimmer als kein Restore.
        """
        desired = QSize(_DESIRED_WIDTH, _DESIRED_HEIGHT)
        fallback = fit_to_available(desired, self._current_available_geometry())

        saved_rect = self._read_saved_rect()
        screens = [s.availableGeometry() for s in QGuiApplication.screens()]
        if saved_rect is not None and is_geometry_visible(saved_rect, screens):
            self._window.setGeometry(saved_rect)
        else:
            self._window.setGeometry(fallback)

        if _bool(self._settings.value("window/maximized", False)):
            self._window.setWindowState(self._window.windowState() | Qt.WindowState.WindowMaximized)

    def _current_available_geometry(self) -> QRect:
        screen = self._window.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return QRect(0, 0, _DESIRED_WIDTH, _DESIRED_HEIGHT)
        return screen.availableGeometry()

    def _read_saved_rect(self) -> QRect | None:
        """Gespeicherte Fenster-Rechteck-Werte – `None`, wenn unvollständig/kaputt."""
        x = _int_or_none(self._settings.value("window/x"))
        y = _int_or_none(self._settings.value("window/y"))
        width = _int_or_none(self._settings.value("window/width"))
        height = _int_or_none(self._settings.value("window/height"))
        if x is None or y is None or width is None or height is None:
            return None
        if width <= 0 or height <= 0:
            return None
        return QRect(x, y, width, height)

    def _save_window_geometry(self) -> None:
        is_maximized = bool(self._window.windowState() & Qt.WindowState.WindowMaximized)
        self._settings.setValue("window/maximized", is_maximized)
        # `normalGeometry()` ist die Größe/Position VOR dem Maximieren – so
        # bleibt beim nächsten Start ein sinnvolles Rechteck gespeichert,
        # selbst wenn maximiert geschlossen wird.
        rect = self._window.geometry()
        if is_maximized:
            normal = self._window.normalGeometry()
            if normal.isValid():
                rect = normal
        self._settings.setValue("window/x", rect.x())
        self._settings.setValue("window/y", rect.y())
        self._settings.setValue("window/width", rect.width())
        self._settings.setValue("window/height", rect.height())

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


def _int_or_none(value: object) -> int | None:
    """QSettings liefert je nach Backend `str` (Windows/INI) oder nativen
    Typ (macOS/Linux) – siehe `settings_store._bool` für dieselbe Problematik."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
