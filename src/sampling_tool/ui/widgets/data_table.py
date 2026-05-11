"""Datentabelle mit virtuellem Modell und Sample-Highlighting.

`DatasetTableModel` implementiert `QAbstractTableModel` direkt – damit auch
Datasets mit 100k+ Zeilen flüssig durchgescrollt werden können (Qt fragt
nur sichtbare Zellen ab). `QStandardItemModel` würde alles in den Speicher
ziehen und Drag-Scroll spürbar bremsen.

Sample-Highlighting läuft über eine `frozenset` von `row_id`s, die im
`data()`-Callback als `BackgroundRole` zurückgegeben wird. Filtering nutzt
ein Mapping `view_index → dataset_index`, das beim Setzen befüllt wird –
so brauchen wir keinen Proxy-Filter.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time
from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import QHeaderView, QTableView, QWidget

from sampling_tool.core.models import Dataset

HIGHLIGHT_COLOR: str = "#FFF4D6"

_MIN_COLUMN_WIDTH: int = 60
_MAX_COLUMN_WIDTH: int = 320


class DatasetTableModel(QAbstractTableModel):
    """Read-only Qt-Model um ein `Dataset` – stateless gegenüber Persistence."""

    def __init__(
        self,
        dataset: Dataset | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._dataset: Dataset | None = None
        self._columns: tuple[str, ...] = ()
        self._visible_indices: list[int] = []
        self._highlight: frozenset[int] = frozenset()
        self._highlight_brush = QBrush(QColor(HIGHLIGHT_COLOR))
        if dataset is not None:
            self.set_dataset(dataset)

    # ---- Public API -----------------------------------------------------

    def set_dataset(self, dataset: Dataset) -> None:
        """Ersetzt den dargestellten Datenbestand (komplettes Reset)."""
        self.beginResetModel()
        self._dataset = dataset
        self._columns = dataset.columns
        self._visible_indices = list(range(len(dataset.rows)))
        self._highlight = frozenset()
        self.endResetModel()

    def clear(self) -> None:
        """Leert das Modell vollständig."""
        self.beginResetModel()
        self._dataset = None
        self._columns = ()
        self._visible_indices = []
        self._highlight = frozenset()
        self.endResetModel()

    def set_highlight(self, row_ids: Sequence[int]) -> None:
        """Markiert Zeilen mit den angegebenen `row_id`s gelb."""
        self._highlight = frozenset(row_ids)
        if self.rowCount() > 0 and self._columns:
            top_left = self.index(0, 0)
            bottom_right = self.index(self.rowCount() - 1, len(self._columns) - 1)
            self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.BackgroundRole])

    def clear_highlight(self) -> None:
        """Entfernt eine bestehende Hervorhebung."""
        self.set_highlight(())

    def filter_to_row_ids(self, row_ids: Sequence[int]) -> None:
        """Reduziert die Sicht auf Zeilen mit passender `row_id`."""
        if self._dataset is None:
            return
        wanted = set(row_ids)
        self.beginResetModel()
        self._visible_indices = [i for i, r in enumerate(self._dataset.rows) if r.row_id in wanted]
        self.endResetModel()

    def clear_filter(self) -> None:
        """Hebt einen Filter auf – alle Zeilen werden wieder sichtbar."""
        if self._dataset is None:
            return
        self.beginResetModel()
        self._visible_indices = list(range(len(self._dataset.rows)))
        self.endResetModel()

    def view_row_for_row_id(self, row_id: int) -> int | None:
        """Liefert den View-Index für eine gegebene `row_id` (oder None)."""
        if self._dataset is None:
            return None
        for view_idx, ds_idx in enumerate(self._visible_indices):
            if self._dataset.rows[ds_idx].row_id == row_id:
                return view_idx
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
        return len(self._visible_indices)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self._columns)

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid() or self._dataset is None:
            return None
        ds_idx = self._visible_indices[index.row()]
        row = self._dataset.rows[ds_idx]
        column = self._columns[index.column()]

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return _format_value(row.values.get(column))
        if role == Qt.ItemDataRole.BackgroundRole and row.row_id in self._highlight:
            return self._highlight_brush
        if role == Qt.ItemDataRole.TextAlignmentRole:
            value = row.values.get(column)
            if isinstance(value, int | float) and not isinstance(value, bool):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return None

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
        if (
            orientation == Qt.Orientation.Vertical
            and self._dataset is not None
            and 0 <= section < len(self._visible_indices)
        ):
            ds_idx = self._visible_indices[section]
            return str(self._dataset.rows[ds_idx].row_id)
        return None


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
        v_header = self.verticalHeader()
        assert v_header is not None
        v_header.setDefaultSectionSize(22)
        v_header.setVisible(True)

    # ---- Public API -----------------------------------------------------

    def set_dataset(self, dataset: Dataset) -> None:
        """Lädt das Dataset und passt die Spaltenbreiten automatisch an."""
        self._model.set_dataset(dataset)
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

    # ---- intern ---------------------------------------------------------

    def _autosize_columns(self) -> None:
        """Heuristik: schmale Spalten an Inhalt, breite an Max-Wert."""
        self.resizeColumnsToContents()
        header = self.horizontalHeader()
        if header is None:
            return
        for col in range(self._model.columnCount()):
            width = header.sectionSize(col)
            clamped = max(_MIN_COLUMN_WIDTH, min(_MAX_COLUMN_WIDTH, width + 12))
            header.resizeSection(col, clamped)


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _format_value(value: Any) -> str:
    """Native Python-Typen menschenlesbar darstellen (deutsche Konventionen halten)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Ja" if value else "Nein"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)
