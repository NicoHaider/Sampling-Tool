"""Datentabelle mit lazy-loadendem Modell + LRU-Cache.

`DatasetTableModel` implementiert `QAbstractTableModel` direkt – damit auch
Datasets mit 1M+ Zeilen flüssig durchgescrollt werden können (Qt fragt
nur sichtbare Zellen ab).

**Sprint 11.2 – Streaming-UI**: Das Model hält keine In-Memory-Liste mehr,
sondern liest Rows on-demand via `DatasetRepo.get_rows_in_range`. Ein
FIFO-Cache (`DEFAULT_CACHE_SIZE = 1000` Rows) hält den Viewport + ein
Look-Ahead-Window. Bei Cache-Miss wird ein ganzer Block geladen
(`BULK_LOAD_HALF_WINDOW = 125` davor + 125 dahinter). RAM-Footprint
konstant ~3 MB, unabhängig von Dataset-Größe.

FIFO statt echtes LRU: Qt-Views scrollen sequentiell, die Hit-Rate ist
mit Look-Ahead-Bulk-Load auch ohne Hit-Tracking >99 %. Wenn Filter-
oder Sprung-Zugriffe das mal ändern, kann auf `OrderedDict` mit
`move_to_end` aufgerüstet werden.

Sample-Highlighting läuft über eine `frozenset` von `row_id`s, die im
`data()`-Callback als `BackgroundRole` zurückgegeben wird. Filtering nutzt
ein Mapping `view_index → dataset_index` (`_visible_indices`).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from datetime import date, datetime, time
from typing import Any, ClassVar

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPaintEvent
from PyQt6.QtWidgets import QHeaderView, QTableView, QWidget

from sampling_tool.config import SAMPLE_HIGHLIGHT_ALPHA, SAMPLE_HIGHLIGHT_COLOR
from sampling_tool.core.models import Dataset, DatasetRow
from sampling_tool.persistence.repositories import DatasetRepo

HIGHLIGHT_COLOR: str = SAMPLE_HIGHLIGHT_COLOR
HIGHLIGHT_ALPHA: int = SAMPLE_HIGHLIGHT_ALPHA

_MIN_COLUMN_WIDTH: int = 60
_MAX_COLUMN_WIDTH: int = 320
_EMPTY_MESSAGE: str = "Keine Datensätze – Datei importieren"


class DatasetTableModel(QAbstractTableModel):
    """Read-only Qt-Model mit lazy-Loading via DatasetRepo + FIFO-Cache."""

    DEFAULT_CACHE_SIZE: ClassVar[int] = 1000
    BULK_LOAD_HALF_WINDOW: ClassVar[int] = 125

    def __init__(
        self,
        dataset: Dataset | None = None,
        repo: DatasetRepo | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._dataset: Dataset | None = None
        self._dataset_id: int | None = None
        self._row_count: int = 0
        self._columns: tuple[str, ...] = ()
        self._repo: DatasetRepo | None = None
        # Cache: row_index → DatasetRow; cache_order = FIFO-Eviction-Reihenfolge.
        self._row_cache: dict[int, DatasetRow] = {}
        self._cache_order: deque[int] = deque()
        self._cache_size: int = self.DEFAULT_CACHE_SIZE
        # Filter: None = alle Rows sichtbar, sonst Liste der row_ids
        self._visible_indices: list[int] | None = None
        self._highlight: frozenset[int] = frozenset()
        color = QColor(HIGHLIGHT_COLOR)
        color.setAlpha(HIGHLIGHT_ALPHA)
        self._highlight_brush = QBrush(color)
        if dataset is not None and repo is not None:
            self.set_dataset(dataset, repo)

    # ---- Public API -----------------------------------------------------

    def set_dataset(self, dataset: Dataset, repo: DatasetRepo) -> None:
        """Bindet das Model an ein Dataset + Repo. Cache wird invalidiert."""
        if dataset.id is None:
            raise ValueError(
                "DatasetTableModel.set_dataset benötigt persistiertes Dataset (id!=None)."
            )
        self.beginResetModel()
        self._dataset = dataset
        self._dataset_id = dataset.id
        self._row_count = dataset.row_count
        self._columns = dataset.columns
        self._repo = repo
        self._row_cache.clear()
        self._cache_order.clear()
        self._visible_indices = None
        self._highlight = frozenset()
        self.endResetModel()

    def clear(self) -> None:
        """Leert das Modell vollständig (Welcome-Screen-Zustand)."""
        self.beginResetModel()
        self._dataset = None
        self._dataset_id = None
        self._row_count = 0
        self._columns = ()
        self._repo = None
        self._row_cache.clear()
        self._cache_order.clear()
        self._visible_indices = None
        self._highlight = frozenset()
        self.endResetModel()

    def set_highlight(self, row_ids: Sequence[int]) -> None:
        """Markiert Zeilen mit den angegebenen `row_id`s in der Highlight-Farbe."""
        self._highlight = frozenset(row_ids)
        if self.rowCount() > 0 and self._columns:
            top_left = self.index(0, 0)
            bottom_right = self.index(self.rowCount() - 1, len(self._columns) - 1)
            self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.BackgroundRole])

    def clear_highlight(self) -> None:
        """Entfernt eine bestehende Hervorhebung."""
        self.set_highlight(())

    def filter_to_row_ids(self, row_ids: Sequence[int]) -> None:
        """Reduziert die Sicht auf Zeilen mit passender `row_id`.

        Da Rows on-demand geladen werden, brauchen wir keinen vollen
        Cache-Walk – wir merken uns einfach die row_id-Liste in
        Reihenfolge und mappen `view_row → row_id` beim Data-Lookup.
        """
        if self._dataset_id is None:
            return
        self.beginResetModel()
        # In stabiler Reihenfolge – Sampling liefert sortiert, andere Callers
        # bekommen die row_id-Reihenfolge die sie übergeben haben.
        self._visible_indices = list(row_ids)
        self.endResetModel()

    def clear_filter(self) -> None:
        """Hebt einen Filter auf – alle Zeilen werden wieder sichtbar."""
        if self._dataset_id is None:
            return
        self.beginResetModel()
        self._visible_indices = None
        self.endResetModel()

    def view_row_for_row_id(self, row_id: int) -> int | None:
        """Liefert den View-Index für eine gegebene `row_id` (oder None)."""
        if self._dataset_id is None:
            return None
        if self._visible_indices is not None:
            try:
                return self._visible_indices.index(row_id)
            except ValueError:
                return None
        # Ungefilterte Sicht: row_id == view_row (siehe `_actual_row_id`).
        if 0 <= row_id - 1 < self._row_count:
            return row_id - 1
        return None

    def highlighted_row_ids(self) -> frozenset[int]:
        """Aktuell hervorgehobene `row_id`s (read-only Snapshot)."""
        return self._highlight

    def dataset(self) -> Dataset | None:
        """Aktuell gehaltenes Dataset (oder None)."""
        return self._dataset

    # ---- QAbstractTableModel-Override -----------------------------------

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        if self._visible_indices is not None:
            return len(self._visible_indices)
        return self._row_count

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self._columns)

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid() or self._dataset_id is None:
            return None
        row_id = self._actual_row_id(index.row())
        if row_id is None:
            return None

        if role == Qt.ItemDataRole.BackgroundRole:
            if row_id in self._highlight:
                return self._highlight_brush
            return None

        if role not in (
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.EditRole,
            Qt.ItemDataRole.TextAlignmentRole,
        ):
            return None

        self._ensure_cached(row_id)
        row = self._row_cache.get(row_id)
        if row is None:
            return None
        column = self._columns[index.column()]

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return _format_value(row.values.get(column))
        # TextAlignmentRole
        value = row.values.get(column)
        if isinstance(value, int | float) and not isinstance(value, bool):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self._columns):
                return self._columns[section]
            return None
        if orientation == Qt.Orientation.Vertical and self._dataset_id is not None:
            row_id = self._actual_row_id(section)
            if row_id is not None:
                return str(row_id)
        return None

    # ---- Cache-interna --------------------------------------------------

    def _actual_row_id(self, view_row: int) -> int | None:
        """Übersetzt einen sichtbaren Zeilen-Index in die echte `row_id`.

        Ohne Filter: `view_row` (0-basiert) → `row_id = view_row + 1`
        (DatasetRow.row_id ist 1-basiert, siehe Importer/Models).
        Mit Filter: `_visible_indices[view_row]`.
        """
        if self._visible_indices is not None:
            if 0 <= view_row < len(self._visible_indices):
                return self._visible_indices[view_row]
            return None
        if 0 <= view_row < self._row_count:
            return view_row + 1
        return None

    def _ensure_cached(self, row_id: int) -> None:
        """Stellt sicher, dass `row_id` im Cache liegt – lädt sonst einen Block."""
        if row_id in self._row_cache:
            return
        if self._repo is None or self._dataset_id is None:
            return

        # Window um den Miss herum, half-open Range [start, end) – passt zu
        # `DatasetRepo.get_rows_in_range`. row_ids sind 1-basiert; das Repo
        # liest row_index, der mit row_id identisch ist.
        start = max(1, row_id - self.BULK_LOAD_HALF_WINDOW)
        end = min(self._row_count + 1, row_id + self.BULK_LOAD_HALF_WINDOW + 1)

        rows = self._repo.get_rows_in_range(self._dataset_id, start, end)
        for row in rows:
            if row.row_id not in self._row_cache:
                self._row_cache[row.row_id] = row
                self._cache_order.append(row.row_id)

        self._evict_if_full()

    def _evict_if_full(self) -> None:
        """FIFO-Eviction wenn die Cache-Größe überschritten wird."""
        while len(self._row_cache) > self._cache_size:
            oldest = self._cache_order.popleft()
            self._row_cache.pop(oldest, None)


class DataTableView(QTableView):
    """`QTableView` mit Komfort-Methoden für das Sampling-Tool."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model: DatasetTableModel = DatasetTableModel(parent=self)
        self.setModel(self._model)

        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableView.SelectionMode.NoSelection)
        self.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.setShowGrid(True)
        self.setSortingEnabled(False)

        h_header = self.horizontalHeader()
        assert h_header is not None
        h_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h_header.setStretchLastSection(False)
        h_header.setHighlightSections(False)
        # Qt6 sampelt für resizeColumnsToContents default ALLE Rows (rowCount=-1).
        # Bei 1M Zeilen × 15 Spalten = 15M data()-Calls, was bei unserem
        # FIFO-Cache (1000 Rows) zu ~56k SQLite-Queries führt → 34 s Freeze
        # (Pass 3 v2 P-001). 100 Rows reichen für eine sinnvolle Breiten-
        # Heuristik, die teure Voll-Iteration entfällt.
        h_header.setResizeContentsPrecision(100)
        v_header = self.verticalHeader()
        assert v_header is not None
        v_header.setDefaultSectionSize(22)
        v_header.setVisible(True)

    # ---- Public API -----------------------------------------------------

    def set_dataset(self, dataset: Dataset, repo: DatasetRepo) -> None:
        """Lädt das Dataset und passt die Spaltenbreiten automatisch an.

        Sprint-11.2: rows werden on-demand vom `repo` geholt (statt einer
        In-Memory-Liste übergeben).
        """
        self._model.set_dataset(dataset, repo)
        self._autosize_columns()

    def clear_dataset(self) -> None:
        """Entfernt das aktuelle Dataset aus der Ansicht."""
        self._model.clear()

    def highlight_rows(self, row_ids: Sequence[int]) -> None:
        """Markiert Zeilen mit den angegebenen `row_id`s und scrollt zur ersten."""
        self._model.set_highlight(row_ids)
        if not row_ids:
            return
        first = min(row_ids)
        view_row = self._model.view_row_for_row_id(first)
        if view_row is not None:
            self.scrollTo(self._model.index(view_row, 0), QTableView.ScrollHint.PositionAtTop)

    def clear_highlight(self) -> None:
        """Entfernt eine bestehende Hervorhebung."""
        self._model.clear_highlight()

    def filter_to_rows(self, row_ids: Sequence[int]) -> None:
        """Reduziert die Sicht auf die angegebenen `row_id`s."""
        self._model.filter_to_row_ids(row_ids)

    def clear_filter(self) -> None:
        """Hebt einen aktiven Filter wieder auf."""
        self._model.clear_filter()

    def table_model(self) -> DatasetTableModel:
        """Direkter Zugriff auf das interne Model (für Tests)."""
        return self._model

    def paintEvent(self, e: QPaintEvent | None) -> None:  # noqa: N802
        """Zeichnet zusätzlich einen Empty-State-Hinweis, wenn keine Daten geladen sind."""
        super().paintEvent(e)
        if self._model.rowCount() > 0:
            return
        viewport = self.viewport()
        if viewport is None:
            return
        painter = QPainter(viewport)
        try:
            painter.setPen(QColor("#B0B0B0"))
            font = painter.font()
            font.setPointSize(font.pointSize() + 2)
            font.setItalic(True)
            painter.setFont(font)
            painter.drawText(
                viewport.rect(),
                int(Qt.AlignmentFlag.AlignCenter),
                _EMPTY_MESSAGE,
            )
        finally:
            painter.end()

    # ---- intern ---------------------------------------------------------

    def _autosize_columns(self) -> None:
        """Heuristik: schmale Spalten an Inhalt, breite an Max-Wert.

        Sprint 12.1: `setResizeContentsPrecision(100)` im Konstruktor begrenzt
        die Qt-Sample-Anzahl pro Spalte – sonst würde `resizeColumnsToContents`
        bei 1M-Datasets alle Rows durchgehen und 56k SQLite-Queries
        produzieren (Pass 3 v2 P-001). Spalten ohne Inhalt im Viewport
        bekommen die `_MIN_COLUMN_WIDTH`.
        """
        self.resizeColumnsToContents()
        header = self.horizontalHeader()
        if header is None:
            return
        for col in range(self._model.columnCount()):
            width = header.sectionSize(col)
            if width < _MIN_COLUMN_WIDTH:
                header.resizeSection(col, _MIN_COLUMN_WIDTH)
            elif width > _MAX_COLUMN_WIDTH:
                header.resizeSection(col, _MAX_COLUMN_WIDTH)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_value(value: Any) -> str:
    """Native Python-Typen menschenlesbar darstellen (deutsche Konventionen halten)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Ja" if value else "Nein"
    if isinstance(value, datetime):
        # Excel-Importe ohne Uhrzeit kommen als datetime mit 00:00:00 rein –
        # dann sähe " ... 00:00:00" wie ein Bug aus. Nur Datum anzeigen.
        if value.hour == 0 and value.minute == 0 and value.second == 0 and value.microsecond == 0:
            return value.strftime("%Y-%m-%d")
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)
