"""Hauptfenster der Anwendung – Welcome ↔ Workspace State-Maschine.

Das Fenster ist „dumm" – es zeigt eines von zwei Top-Level-Widgets über
einen `QStackedWidget` an (Welcome / Workspace), bietet Menü+Toolbar und
gibt Signals an den `MainController` weiter. Persistenz und Repo-Calls
laufen ausschließlich im Controller.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QWidget,
)

from sampling_tool.config import APP_NAME
from sampling_tool.core.models import Dataset, Engagement, SampleResult
from sampling_tool.ui.recent import RecentEntry
from sampling_tool.ui.widgets.data_table import DataTableView
from sampling_tool.ui.widgets.sidebar import NavigationSidebar
from sampling_tool.ui.widgets.welcome import WelcomeScreen

_MAX_RECENT_IN_MENU: int = 5


class MainWindow(QMainWindow):
    """Top-Level-Fenster mit Welcome- und Workspace-Ansicht."""

    new_engagement_requested = pyqtSignal()
    open_engagement_requested = pyqtSignal(Path)
    close_engagement_requested = pyqtSignal()
    import_excel_requested = pyqtSignal()
    export_sample_requested = pyqtSignal()
    export_audit_pdf_requested = pyqtSignal()
    dataset_selected = pyqtSignal(int)
    sample_selected = pyqtSignal(int)
    sample_filter_toggled = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)

        # ---- zentrale Widgets ----
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._welcome = WelcomeScreen()
        self._welcome.new_engagement_requested.connect(self.new_engagement_requested.emit)
        self._welcome.open_engagement_requested.connect(self.open_engagement_requested.emit)
        self._stack.addWidget(self._welcome)

        self._workspace = self._build_workspace()
        self._stack.addWidget(self._workspace)

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
        self._build_menu()
        self._build_toolbar()

        self.show_welcome()

    # ---- Public API – State -------------------------------------------

    def show_welcome(self) -> None:
        """Zeigt den Welcome-Screen (keine .db geladen)."""
        self._stack.setCurrentWidget(self._welcome)
        self._set_workspace_actions_enabled(False)
        self._status_engagement.setText("Kein Engagement")
        self._status_dataset.setText("Kein Dataset")
        self._status_rows.setText("0 Zeilen")
        self._status_sample.setText("—")

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

    def show_dataset(self, dataset: Dataset) -> None:
        """Lädt das Dataset in die Tabelle und setzt Statusbar."""
        self._data_table.set_dataset(dataset)
        self._status_dataset.setText(dataset.name)
        self._status_rows.setText(f"{len(dataset.rows)} Zeilen")
        self._status_sample.setText("—")
        self._action_new_sample.setEnabled(True)

    def highlight_sample(self, sample: SampleResult) -> None:
        """Markiert Sample-Zeilen in der Tabelle gelb."""
        self._data_table.highlight_rows(sample.selected_row_ids)
        self._status_sample.setText(f"Sample n={sample.actual_size} ({sample.config.method.value})")
        self._action_export_sample.setEnabled(True)

    def filter_to_sample(self, sample: SampleResult) -> None:
        """Filtert die Tabelle auf Sample-Zeilen."""
        self._data_table.filter_to_rows(sample.selected_row_ids)

    def clear_sample_filter(self) -> None:
        """Hebt einen Sample-Filter wieder auf."""
        self._data_table.clear_filter()

    def clear_table(self) -> None:
        """Entfernt das aktuelle Dataset aus der Tabelle."""
        self._data_table.clear_dataset()

    def set_recent_entries(self, entries: list[RecentEntry]) -> None:
        """Aktualisiert Welcome-Screen und das File→Recent-Submenü."""
        self._welcome.set_recent_entries(entries[:_MAX_RECENT_IN_MENU])
        self._rebuild_recent_menu(entries[:_MAX_RECENT_IN_MENU])

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

    def is_workspace_visible(self) -> bool:
        """`True`, wenn aktuell der Workspace angezeigt wird."""
        return self._stack.currentWidget() is self._workspace

    # ---- Setup ---------------------------------------------------------

    def _build_workspace(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        self._sidebar = NavigationSidebar()
        self._sidebar.dataset_selected.connect(self.dataset_selected.emit)
        self._sidebar.sample_selected.connect(self.sample_selected.emit)
        self._sidebar.sample_double_clicked.connect(self.sample_filter_toggled.emit)
        splitter.addWidget(self._sidebar)

        self._data_table = DataTableView()
        splitter.addWidget(self._data_table)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 1030])
        return splitter

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        if menu_bar is None:
            return

        # ---- File ----
        file_menu = menu_bar.addMenu("&Datei")
        assert file_menu is not None

        self._action_new = QAction("Neues Engagement…", self)
        self._action_new.triggered.connect(self.new_engagement_requested.emit)
        file_menu.addAction(self._action_new)

        self._action_open = QAction("Engagement öffnen…", self)
        self._action_open.triggered.connect(self._on_open_clicked)
        file_menu.addAction(self._action_open)

        recent_menu = file_menu.addMenu("Zuletzt geöffnet")
        assert recent_menu is not None
        self._recent_menu: QMenu = recent_menu
        self._recent_menu.setEnabled(False)

        file_menu.addSeparator()
        self._action_close = QAction("Engagement schließen", self)
        self._action_close.triggered.connect(self.close_engagement_requested.emit)
        file_menu.addAction(self._action_close)

        file_menu.addSeparator()
        action_quit = QAction("Beenden", self)
        action_quit.setShortcut(QKeySequence.StandardKey.Quit)
        action_quit.triggered.connect(self.close)
        file_menu.addAction(action_quit)

        # ---- Edit ----
        edit_menu = menu_bar.addMenu("&Bearbeiten")
        assert edit_menu is not None

        self._action_import = QAction("Datei importieren…", self)
        self._action_import.triggered.connect(self.import_excel_requested.emit)
        edit_menu.addAction(self._action_import)

        self._action_export_sample = QAction("Sample exportieren…", self)
        self._action_export_sample.triggered.connect(self.export_sample_requested.emit)
        edit_menu.addAction(self._action_export_sample)

        self._action_export_pdf = QAction("AuditTrail-PDF…", self)
        self._action_export_pdf.triggered.connect(self.export_audit_pdf_requested.emit)
        edit_menu.addAction(self._action_export_pdf)

        # ---- Sample ----
        sample_menu = menu_bar.addMenu("&Stichprobe")
        assert sample_menu is not None

        self._action_new_sample = QAction("Neue Stichprobe…", self)
        sample_menu.addAction(self._action_new_sample)

        self._action_reset_sample = QAction("Auswahl zurücksetzen", self)
        sample_menu.addAction(self._action_reset_sample)

        sample_menu.addSeparator()
        self._action_undo = QAction("Rückgängig", self)
        self._action_undo.setShortcut(QKeySequence.StandardKey.Undo)
        sample_menu.addAction(self._action_undo)

        self._action_redo = QAction("Wiederholen", self)
        self._action_redo.setShortcut(QKeySequence.StandardKey.Redo)
        sample_menu.addAction(self._action_redo)

        # ---- Help ----
        help_menu = menu_bar.addMenu("&Hilfe")
        assert help_menu is not None

        self._action_bug_report = QAction("Bug melden…", self)
        self._action_bug_report.triggered.connect(self._open_bug_mail)
        help_menu.addAction(self._action_bug_report)

        self._action_about = QAction("Über…", self)
        self._action_about.triggered.connect(self._show_about)
        help_menu.addAction(self._action_about)

        # Sprint-4-Initial: alle workspace-only Aktionen disabled.
        self._set_workspace_actions_enabled(False)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Hauptaktionen", self)
        toolbar.setMovable(False)
        toolbar.addAction(self._action_new)
        toolbar.addAction(self._action_open)
        toolbar.addSeparator()
        toolbar.addAction(self._action_import)
        toolbar.addAction(self._action_new_sample)
        toolbar.addAction(self._action_export_sample)
        self.addToolBar(toolbar)

    # ---- State-Helfer --------------------------------------------------

    def _set_workspace_actions_enabled(self, enabled: bool) -> None:
        """Steuert die menu/toolbar-Aktionen, die nur mit offenem Engagement Sinn ergeben."""
        for action in (
            self._action_close,
            self._action_import,
            self._action_export_pdf,
        ):
            action.setEnabled(enabled)
        # Diese benötigen zusätzlich ein Dataset / Sample – Controller schaltet
        # sie später frei.
        for action in (
            self._action_new_sample,
            self._action_reset_sample,
            self._action_export_sample,
            self._action_undo,
            self._action_redo,
        ):
            action.setEnabled(False)

    def _rebuild_recent_menu(self, entries: list[RecentEntry]) -> None:
        menu = self._recent_menu
        menu.clear()
        if not entries:
            menu.setEnabled(False)
            return
        menu.setEnabled(True)
        for entry in entries:
            label = f"{entry.client_name} — {entry.path.name}"
            action = QAction(label, self)
            action.triggered.connect(
                lambda _checked=False, p=entry.path: self.open_engagement_requested.emit(p)
            )
            menu.addAction(action)

    # ---- Slots ---------------------------------------------------------

    def _on_open_clicked(self) -> None:
        path_str, _filter = QFileDialog.getOpenFileName(
            self,
            "Engagement öffnen",
            "",
            "SQLite-Engagement (*.db);;Alle Dateien (*)",
        )
        if path_str:
            self.open_engagement_requested.emit(Path(path_str))

    def _open_bug_mail(self) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl("mailto:nico.haider@bdo.at?subject=[Sampling-Tool Bug]"))

    def _show_about(self) -> None:
        from PyQt6.QtWidgets import QMessageBox

        QMessageBox.about(
            self,
            f"Über {APP_NAME}",
            f"<b>{APP_NAME}</b><br><br>"
            "Reproduzierbare Audit-Stichproben für ISAE-3402-Engagements.<br>"
            "Sprint 4 – UI-Skeleton.",
        )


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _separator() -> QLabel:
    label = QLabel("│")
    label.setStyleSheet("color: #D9D9D9; padding: 0 6px;")
    return label
