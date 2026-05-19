"""AuditTrail-View – filterbare, sortierbare Tabelle aller Audit-Events.

Wird im Workspace unter der Datentabelle in einem `QTabWidget` neben dem
Dashboard angezeigt. Doppelklick auf einen Sample-Event sendet das
`event_double_clicked(int)`-Signal, damit der Controller das zugehörige
Sample in der Tabelle markieren kann.

Filter-Zeile oben:
- Volltext-Suche (durchsucht User, Aktion, Datei).
- ComboBox "Aktion": Sampling / Reset / Import / Export / Undo / Redo /
  Korrektur / Alle.
- ComboBox "User": dynamisch aus den geladenen Events befüllt.
- ComboBox "Zeitraum": Heute / Diese Woche / Dieser Monat / Alle.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.core.formatting import ensure_utc, format_optional_timestamp
from sampling_tool.core.models import AuditEvent

_COLUMNS: Final[tuple[str, ...]] = (
    "Zeitstempel",
    "Aktion",
    "User",
    "Sample",
    "Größe",
    "%",
    "Seed",
    "Datei",
)

_ACTION_LABELS: Final[dict[str, str]] = {
    "sampling": "Sampling",
    "reset": "Reset",
    "import": "Import",
    "export": "Export",
    "undo": "Undo",
    "redo": "Redo",
    "correction": "Korrektur",
}

# Spezial-Wert für ComboBoxen, der „kein Filter" bedeutet.
_FILTER_ALL: Final[str] = "Alle"
_RANGE_TODAY: Final[str] = "Heute"
_RANGE_WEEK: Final[str] = "Diese Woche"
_RANGE_MONTH: Final[str] = "Dieser Monat"

_EVENT_ID_ROLE: Final[int] = int(Qt.ItemDataRole.UserRole) + 1
_SAMPLE_ID_ROLE: Final[int] = int(Qt.ItemDataRole.UserRole) + 2
_EVENT_TYPE_ROLE: Final[int] = int(Qt.ItemDataRole.UserRole) + 3
_USER_ROLE: Final[int] = int(Qt.ItemDataRole.UserRole) + 4
_TIMESTAMP_ROLE: Final[int] = int(Qt.ItemDataRole.UserRole) + 5


class AuditTrailModel(QAbstractTableModel):
    """Read-only Model um eine Liste von `AuditEvent`s."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._events: list[AuditEvent] = []

    # ---- Public API -----------------------------------------------------

    def set_events(self, events: list[AuditEvent]) -> None:
        """Tauscht den kompletten Datenbestand aus."""
        self.beginResetModel()
        self._events = list(events)
        self.endResetModel()

    def event_at(self, row: int) -> AuditEvent | None:
        """Liefert das Event in der gegebenen Zeile (oder None)."""
        if 0 <= row < len(self._events):
            return self._events[row]
        return None

    def users(self) -> list[str]:
        """Eindeutige User-Namen aller Events – sortiert."""
        return sorted({e.user_name for e in self._events if e.user_name})

    # ---- QAbstractTableModel-Override -----------------------------------

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self._events)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(_COLUMNS)

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(_COLUMNS):
            return _COLUMNS[section]
        return None

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid():
            return None
        evt = self._events[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return _format_cell(evt, col)
        if role == _EVENT_ID_ROLE:
            return evt.id
        if role == _SAMPLE_ID_ROLE:
            return evt.sample_id
        if role == _EVENT_TYPE_ROLE:
            return evt.event_type
        if role == _USER_ROLE:
            return evt.user_name
        if role == _TIMESTAMP_ROLE:
            return ensure_utc(evt.timestamp).timestamp() if evt.timestamp else 0.0
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (3, 4, 5, 6):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None


class AuditTrailFilterProxy(QSortFilterProxyModel):
    """Filter nach Aktion, User, Zeitraum + Volltext."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._action_filter: str | None = None
        self._user_filter: str | None = None
        self._range: str = _FILTER_ALL
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    # ---- Public API -----------------------------------------------------

    def set_action_filter(self, action: str | None) -> None:
        self._action_filter = action
        self.invalidateFilter()

    def set_user_filter(self, user: str | None) -> None:
        self._user_filter = user
        self.invalidateFilter()

    def set_range_filter(self, range_label: str) -> None:
        self._range = range_label
        self.invalidateFilter()

    # ---- Qt-Override ----------------------------------------------------

    def filterAcceptsRow(  # noqa: N802
        self,
        source_row: int,
        source_parent: QModelIndex,
    ) -> bool:
        model = self.sourceModel()
        if not isinstance(model, AuditTrailModel):
            return True
        evt = model.event_at(source_row)
        if evt is None:
            return False

        if self._action_filter and evt.event_type != self._action_filter:
            return False
        if self._user_filter and evt.user_name != self._user_filter:
            return False
        if not _in_range(evt.timestamp, self._range):
            return False

        text = self.filterRegularExpression().pattern()
        if text:
            haystack = " ".join(
                [
                    format_optional_timestamp(evt.timestamp),
                    evt.event_type,
                    evt.user_name or "",
                    _format_file(evt),
                ]
            ).lower()
            if text.lower() not in haystack:
                return False

        return True

    def lessThan(  # noqa: N802
        self,
        left: QModelIndex,
        right: QModelIndex,
    ) -> bool:
        """Sortierung nutzt typisierte Roles für korrekte Reihenfolge."""
        model = self.sourceModel()
        if model is None:
            return False
        column = left.column()
        if column == 0:
            lt = model.data(left, _TIMESTAMP_ROLE) or 0.0
            rt = model.data(right, _TIMESTAMP_ROLE) or 0.0
            return bool(lt < rt)
        if column == 4:
            return _to_int(model.data(left, Qt.ItemDataRole.DisplayRole)) < _to_int(
                model.data(right, Qt.ItemDataRole.DisplayRole)
            )
        return super().lessThan(left, right)


class AuditTrailView(QWidget):
    """Filterbare, sortierbare Audit-Trail-Ansicht."""

    event_double_clicked = pyqtSignal(int)
    refresh_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AuditTrailView")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # ---- Filter-Zeile ----
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Suchen…")
        self._search.textChanged.connect(self._on_search_changed)
        filter_row.addWidget(self._search, stretch=2)

        self._action_combo = QComboBox()
        self._action_combo.addItem(_FILTER_ALL, None)
        for key, label in _ACTION_LABELS.items():
            self._action_combo.addItem(label, key)
        self._action_combo.currentIndexChanged.connect(self._on_action_changed)
        filter_row.addWidget(QLabel("Aktion:"))
        filter_row.addWidget(self._action_combo, stretch=1)

        self._user_combo = QComboBox()
        self._user_combo.addItem(_FILTER_ALL, None)
        self._user_combo.currentIndexChanged.connect(self._on_user_changed)
        filter_row.addWidget(QLabel("User:"))
        filter_row.addWidget(self._user_combo, stretch=1)

        self._range_combo = QComboBox()
        for label in (_FILTER_ALL, _RANGE_TODAY, _RANGE_WEEK, _RANGE_MONTH):
            self._range_combo.addItem(label, label)
        self._range_combo.currentIndexChanged.connect(self._on_range_changed)
        filter_row.addWidget(QLabel("Zeitraum:"))
        filter_row.addWidget(self._range_combo, stretch=1)

        self._refresh_button = QPushButton("Aktualisieren")
        self._refresh_button.clicked.connect(self.refresh_requested.emit)
        filter_row.addWidget(self._refresh_button)

        outer.addLayout(filter_row)

        # ---- Tabelle + Empty-State (gestapelt) ----
        self._stack = QStackedWidget()

        self._model = AuditTrailModel(self)
        self._proxy = AuditTrailFilterProxy(self)
        self._proxy.setSourceModel(self._model)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        h_header = self._table.horizontalHeader()
        if h_header is not None:
            h_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            h_header.setStretchLastSection(True)
        self._table.doubleClicked.connect(self._on_double_click)
        self._stack.addWidget(self._table)

        self._empty_label = QLabel("Noch keine Audit-Events – starte mit einem Import oder Sample.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #7F7F7F; font-style: italic; padding: 24px;")
        self._stack.addWidget(self._empty_label)

        outer.addWidget(self._stack, stretch=1)

        self._stack.setCurrentWidget(self._empty_label)

    # ---- Public API -----------------------------------------------------

    def set_events(self, events: list[AuditEvent]) -> None:
        """Setzt den Datenbestand neu (User-ComboBox wird mitgepflegt)."""
        self._model.set_events(events)
        self._update_user_combo()
        # Default-Sortierung: neueste zuerst.
        self._table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        self._stack.setCurrentWidget(self._table if events else self._empty_label)

    def model(self) -> AuditTrailModel:
        """Zugriff aufs Model (Tests)."""
        return self._model

    def proxy(self) -> AuditTrailFilterProxy:
        """Zugriff auf den Proxy (Tests)."""
        return self._proxy

    def table(self) -> QTableView:
        """Zugriff auf die Tabelle (Tests)."""
        return self._table

    def visible_row_count(self) -> int:
        """Anzahl sichtbarer Zeilen nach Filter (Tests)."""
        return self._proxy.rowCount()

    # ---- Slots ----------------------------------------------------------

    def _on_search_changed(self, text: str) -> None:
        self._proxy.setFilterFixedString(text)

    def _on_action_changed(self, _index: int) -> None:
        key = self._action_combo.currentData()
        self._proxy.set_action_filter(key if isinstance(key, str) else None)

    def _on_user_changed(self, _index: int) -> None:
        user = self._user_combo.currentData()
        self._proxy.set_user_filter(user if isinstance(user, str) else None)

    def _on_range_changed(self, _index: int) -> None:
        label = self._range_combo.currentData()
        self._proxy.set_range_filter(label if isinstance(label, str) else _FILTER_ALL)

    def _on_double_click(self, proxy_index: QModelIndex) -> None:
        if not proxy_index.isValid():
            return
        source_index = self._proxy.mapToSource(proxy_index)
        evt = self._model.event_at(source_index.row())
        if evt is None or evt.id is None:
            return
        self.event_double_clicked.emit(evt.id)

    def _update_user_combo(self) -> None:
        """Hält die User-ComboBox synchron zu den geladenen Events."""
        current = self._user_combo.currentData()
        self._user_combo.blockSignals(True)
        try:
            self._user_combo.clear()
            self._user_combo.addItem(_FILTER_ALL, None)
            for user in self._model.users():
                self._user_combo.addItem(user, user)
            # Vorherige Auswahl wieder herstellen, falls noch vorhanden.
            if isinstance(current, str):
                idx = self._user_combo.findData(current)
                if idx >= 0:
                    self._user_combo.setCurrentIndex(idx)
        finally:
            self._user_combo.blockSignals(False)


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _format_cell(evt: AuditEvent, col: int) -> str:
    if col == 0:
        return format_optional_timestamp(evt.timestamp)
    if col == 1:
        action = _ACTION_LABELS.get(evt.event_type, evt.event_type)
        if evt.corrects_event_id is not None:
            action = f"{action} → #{evt.corrects_event_id}"
        return action
    if col == 2:
        return evt.user_name or ""
    if col == 3:
        return f"#{evt.sample_id}" if evt.sample_id is not None else "—"
    if col == 4:
        return str(evt.sample_size) if evt.sample_size is not None else "—"
    if col == 5:
        return f"{evt.sample_percent:.2f} %" if evt.sample_percent is not None else "—"
    if col == 6:
        return str(evt.seed) if evt.seed is not None else "—"
    if col == 7:
        return _format_file(evt)
    return ""


def _format_file(evt: AuditEvent) -> str:
    path = evt.export_file or evt.import_file
    if not path:
        return "—"
    return Path(path).name


def _in_range(ts: datetime | None, range_label: str) -> bool:
    if range_label == _FILTER_ALL or ts is None:
        return True
    now = datetime.now(UTC)
    when = ensure_utc(ts)
    if range_label == _RANGE_TODAY:
        return when.date() == now.date()
    if range_label == _RANGE_WEEK:
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        return when >= start
    if range_label == _RANGE_MONTH:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return when >= start
    return True


def _to_int(value: Any) -> int:
    """Tolerante Konversion für Sortierung von "Größe"-Strings."""
    if value in (None, "—", ""):
        return -1
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


__all__ = [
    "AuditTrailFilterProxy",
    "AuditTrailModel",
    "AuditTrailView",
]
