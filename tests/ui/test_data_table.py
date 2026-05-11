"""DatasetTableModel + DataTableView – Highlight, Filter, Performance-Pfad."""

from __future__ import annotations

from datetime import date, datetime, time

import pytest
from PyQt6.QtCore import Qt
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import Dataset, DatasetRow
from sampling_tool.ui.widgets.data_table import (
    HIGHLIGHT_ALPHA,
    HIGHLIGHT_COLOR,
    DatasetTableModel,
    DataTableView,
)

pytestmark = pytest.mark.ui


def _make_dataset(n: int = 5) -> Dataset:
    rows = tuple(
        DatasetRow(
            row_id=i,
            values={
                "Name": f"Posten {i}",
                "Betrag": 100 + i,
                "Datum": date(2026, 1, i),
            },
        )
        for i in range(1, n + 1)
    )
    return Dataset(name="t", columns=("Name", "Betrag", "Datum"), rows=rows)


class TestDatasetTableModel:
    """Model-Verhalten in Isolation."""

    def test_set_dataset_fills_dimensions(self) -> None:
        model = DatasetTableModel()
        model.set_dataset(_make_dataset(3))
        assert model.rowCount() == 3
        assert model.columnCount() == 3

    def test_display_role_formats_native_types(self) -> None:
        model = DatasetTableModel(_make_dataset(2))
        idx = model.index(0, 2)
        assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "2026-01-01"

    def test_highlight_paints_only_selected_rows(self) -> None:
        model = DatasetTableModel(_make_dataset(4))
        model.set_highlight([2, 4])
        bg_row_2 = model.data(model.index(1, 0), Qt.ItemDataRole.BackgroundRole)
        bg_row_3 = model.data(model.index(2, 0), Qt.ItemDataRole.BackgroundRole)
        assert bg_row_2 is not None
        color = bg_row_2.color()
        assert color.name().lower() == HIGHLIGHT_COLOR.lower()
        assert (color.red(), color.green(), color.blue()) == (40, 167, 69)
        assert color.alpha() == HIGHLIGHT_ALPHA
        assert HIGHLIGHT_ALPHA == 90
        assert bg_row_3 is None

    def test_clear_highlight_removes_marker(self) -> None:
        model = DatasetTableModel(_make_dataset(3))
        model.set_highlight([1])
        model.clear_highlight()
        assert model.data(model.index(0, 0), Qt.ItemDataRole.BackgroundRole) is None

    def test_filter_to_row_ids_reduces_row_count(self) -> None:
        model = DatasetTableModel(_make_dataset(5))
        model.filter_to_row_ids([2, 4])
        assert model.rowCount() == 2
        assert model.headerData(0, Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole) == "2"
        assert model.headerData(1, Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole) == "4"

    def test_clear_filter_restores_all_rows(self) -> None:
        model = DatasetTableModel(_make_dataset(5))
        model.filter_to_row_ids([3])
        model.clear_filter()
        assert model.rowCount() == 5

    def test_clear_empties_model(self) -> None:
        model = DatasetTableModel(_make_dataset(3))
        model.clear()
        assert model.rowCount() == 0
        assert model.columnCount() == 0
        assert model.dataset() is None

    def test_format_value_handles_datetime_none_bool(self) -> None:
        ds = Dataset(
            name="x",
            columns=("a", "b", "c", "d"),
            rows=(
                DatasetRow(
                    row_id=1,
                    values={
                        "a": None,
                        "b": True,
                        "c": datetime(2026, 1, 2, 3, 4, 5),
                        "d": 1.5,
                    },
                ),
            ),
        )
        model = DatasetTableModel(ds)
        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == ""
        assert model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole) == "Ja"
        assert model.data(model.index(0, 2), Qt.ItemDataRole.DisplayRole) == "2026-01-02 03:04:05"
        assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "1.5"

    def test_datetime_with_midnight_shows_only_date(self) -> None:
        ds = Dataset(
            name="x",
            columns=("dt",),
            rows=(DatasetRow(row_id=1, values={"dt": datetime(2026, 5, 11, 0, 0, 0)}),),
        )
        model = DatasetTableModel(ds)
        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "2026-05-11"

    def test_datetime_with_time_shows_full_timestamp(self) -> None:
        ds = Dataset(
            name="x",
            columns=("dt",),
            rows=(DatasetRow(row_id=1, values={"dt": datetime(2026, 5, 11, 14, 30, 5)}),),
        )
        model = DatasetTableModel(ds)
        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "2026-05-11 14:30:05"

    def test_pure_date_value(self) -> None:
        ds = Dataset(
            name="x",
            columns=("d",),
            rows=(DatasetRow(row_id=1, values={"d": date(2026, 5, 11)}),),
        )
        model = DatasetTableModel(ds)
        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "2026-05-11"

    def test_pure_time_value(self) -> None:
        ds = Dataset(
            name="x",
            columns=("t",),
            rows=(DatasetRow(row_id=1, values={"t": time(9, 15, 30)}),),
        )
        model = DatasetTableModel(ds)
        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "09:15:30"


class TestDataTableView:
    """View-Wrapper – Convenience-Methoden."""

    def test_set_dataset_routes_through_to_model(self, qtbot: QtBot) -> None:
        view = DataTableView()
        qtbot.addWidget(view)
        view.set_dataset(_make_dataset(4))
        assert view.table_model().rowCount() == 4

    def test_highlight_rows_marks_first(self, qtbot: QtBot) -> None:
        view = DataTableView()
        qtbot.addWidget(view)
        view.set_dataset(_make_dataset(4))
        view.highlight_rows([2, 3])
        assert 2 in view.table_model().highlighted_row_ids()

    def test_filter_to_rows_then_clear(self, qtbot: QtBot) -> None:
        view = DataTableView()
        qtbot.addWidget(view)
        view.set_dataset(_make_dataset(5))
        view.filter_to_rows([2, 4])
        assert view.table_model().rowCount() == 2
        view.clear_filter()
        assert view.table_model().rowCount() == 5

    def test_clear_dataset_empties_view(self, qtbot: QtBot) -> None:
        view = DataTableView()
        qtbot.addWidget(view)
        view.set_dataset(_make_dataset(2))
        view.clear_dataset()
        assert view.table_model().rowCount() == 0
