"""DatasetTableModel + DataTableView – Cache, Filter, Highlight."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import Dataset, DatasetRow, Engagement
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import DatasetRepo, EngagementRepo
from sampling_tool.ui.widgets.data_table import (
    HIGHLIGHT_ALPHA,
    HIGHLIGHT_COLOR,
    DatasetTableModel,
    DataTableView,
)

pytestmark = pytest.mark.ui


@pytest.fixture
def db_with_engagement(tmp_path: Path) -> Iterator[tuple[Database, int]]:
    """Frische File-basierte DB mit Default-Engagement."""
    db = Database(tmp_path / "table.db")
    db.migrate()
    eng = EngagementRepo(db.connect()).get_or_create(
        Engagement(auditor_name="A", client_name="C", auditor_position="S", audit_type="ISAE 3402")
    )
    assert eng.id is not None
    try:
        yield db, eng.id
    finally:
        db.close()


def _persist_dataset(
    db: Database,
    engagement_id: int,
    rows: tuple[DatasetRow, ...],
    *,
    columns: tuple[str, ...] | None = None,
    name: str = "t",
) -> tuple[Dataset, DatasetRepo]:
    if columns is None:
        columns = tuple(rows[0].values.keys()) if rows else ()
    repo = DatasetRepo(db.connect())
    dataset = repo.create(
        Dataset(name=name, columns=columns, engagement_id=engagement_id),
        rows,
    )
    return dataset, repo


def _make_dataset(
    db: Database,
    engagement_id: int,
    n: int = 5,
) -> tuple[Dataset, DatasetRepo]:
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
    return _persist_dataset(db, engagement_id, rows, columns=("Name", "Betrag", "Datum"))


class TestDatasetTableModel:
    """Model-Verhalten in Isolation."""

    def test_set_dataset_fills_dimensions(self, db_with_engagement: tuple[Database, int]) -> None:
        db, eng_id = db_with_engagement
        ds, repo = _make_dataset(db, eng_id, 3)
        model = DatasetTableModel()
        model.set_dataset(ds, repo)
        assert model.rowCount() == 3
        assert model.columnCount() == 3

    def test_display_role_formats_native_types(
        self, db_with_engagement: tuple[Database, int]
    ) -> None:
        db, eng_id = db_with_engagement
        ds, repo = _make_dataset(db, eng_id, 2)
        model = DatasetTableModel(ds, repo)
        idx = model.index(0, 2)
        assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "2026-01-01"

    def test_highlight_paints_only_selected_rows(
        self, db_with_engagement: tuple[Database, int]
    ) -> None:
        db, eng_id = db_with_engagement
        ds, repo = _make_dataset(db, eng_id, 4)
        model = DatasetTableModel(ds, repo)
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

    def test_clear_highlight_removes_marker(self, db_with_engagement: tuple[Database, int]) -> None:
        db, eng_id = db_with_engagement
        ds, repo = _make_dataset(db, eng_id, 3)
        model = DatasetTableModel(ds, repo)
        model.set_highlight([1])
        model.clear_highlight()
        assert model.data(model.index(0, 0), Qt.ItemDataRole.BackgroundRole) is None

    def test_filter_to_row_ids_reduces_row_count(
        self, db_with_engagement: tuple[Database, int]
    ) -> None:
        db, eng_id = db_with_engagement
        ds, repo = _make_dataset(db, eng_id, 5)
        model = DatasetTableModel(ds, repo)
        model.filter_to_row_ids([2, 4])
        assert model.rowCount() == 2
        assert model.headerData(0, Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole) == "2"
        assert model.headerData(1, Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole) == "4"

    def test_clear_filter_restores_all_rows(self, db_with_engagement: tuple[Database, int]) -> None:
        db, eng_id = db_with_engagement
        ds, repo = _make_dataset(db, eng_id, 5)
        model = DatasetTableModel(ds, repo)
        model.filter_to_row_ids([3])
        model.clear_filter()
        assert model.rowCount() == 5

    def test_clear_empties_model(self, db_with_engagement: tuple[Database, int]) -> None:
        db, eng_id = db_with_engagement
        ds, repo = _make_dataset(db, eng_id, 3)
        model = DatasetTableModel(ds, repo)
        model.clear()
        assert model.rowCount() == 0
        assert model.columnCount() == 0
        assert model.dataset() is None

    def test_format_value_handles_datetime_none_bool(
        self, db_with_engagement: tuple[Database, int]
    ) -> None:
        db, eng_id = db_with_engagement
        rows = (
            DatasetRow(
                row_id=1,
                values={
                    "a": None,
                    "b": True,
                    "c": datetime(2026, 1, 2, 3, 4, 5),
                    "d": 1.5,
                },
            ),
        )
        ds, repo = _persist_dataset(db, eng_id, rows, columns=("a", "b", "c", "d"))
        model = DatasetTableModel(ds, repo)
        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == ""
        assert model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole) == "Ja"
        assert model.data(model.index(0, 2), Qt.ItemDataRole.DisplayRole) == "2026-01-02 03:04:05"
        assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "1.5"

    def test_datetime_with_midnight_shows_only_date(
        self, db_with_engagement: tuple[Database, int]
    ) -> None:
        db, eng_id = db_with_engagement
        rows = (DatasetRow(row_id=1, values={"dt": datetime(2026, 5, 11, 0, 0, 0)}),)
        ds, repo = _persist_dataset(db, eng_id, rows, columns=("dt",))
        model = DatasetTableModel(ds, repo)
        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "2026-05-11"

    def test_datetime_with_time_shows_full_timestamp(
        self, db_with_engagement: tuple[Database, int]
    ) -> None:
        db, eng_id = db_with_engagement
        rows = (DatasetRow(row_id=1, values={"dt": datetime(2026, 5, 11, 14, 30, 5)}),)
        ds, repo = _persist_dataset(db, eng_id, rows, columns=("dt",))
        model = DatasetTableModel(ds, repo)
        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "2026-05-11 14:30:05"

    def test_pure_date_value(self, db_with_engagement: tuple[Database, int]) -> None:
        db, eng_id = db_with_engagement
        rows = (DatasetRow(row_id=1, values={"d": date(2026, 5, 11)}),)
        ds, repo = _persist_dataset(db, eng_id, rows, columns=("d",))
        model = DatasetTableModel(ds, repo)
        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "2026-05-11"

    def test_pure_time_value(self, db_with_engagement: tuple[Database, int]) -> None:
        db, eng_id = db_with_engagement
        rows = (DatasetRow(row_id=1, values={"t": time(9, 15, 30)}),)
        ds, repo = _persist_dataset(db, eng_id, rows, columns=("t",))
        model = DatasetTableModel(ds, repo)
        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "09:15:30"


class TestDataTableView:
    """View-Wrapper – Convenience-Methoden."""

    def test_set_dataset_routes_through_to_model(
        self, qtbot: QtBot, db_with_engagement: tuple[Database, int]
    ) -> None:
        db, eng_id = db_with_engagement
        ds, repo = _make_dataset(db, eng_id, 4)
        view = DataTableView()
        qtbot.addWidget(view)
        view.set_dataset(ds, repo)
        assert view.table_model().rowCount() == 4

    def test_horizontal_header_uses_resize_precision_100(self, qtbot: QtBot) -> None:
        """Regression-Schutz für Sprint 12.1 / P-001 + Pass-4 T-003.

        Ohne setResizeContentsPrecision(100) iteriert Qt6 in
        resizeColumnsToContents über ALLE Rows pro Spalte → bei 1M-
        Datasets ~56k SQLite-Queries → 34 s UI-Freeze. Mit Precision 100
        sampelt Qt nur die ersten 100 Rows → <1 s.
        """
        view = DataTableView()
        qtbot.addWidget(view)
        header = view.horizontalHeader()
        assert header is not None
        assert header.resizeContentsPrecision() == 100

    def test_highlight_rows_marks_first(
        self, qtbot: QtBot, db_with_engagement: tuple[Database, int]
    ) -> None:
        db, eng_id = db_with_engagement
        ds, repo = _make_dataset(db, eng_id, 4)
        view = DataTableView()
        qtbot.addWidget(view)
        view.set_dataset(ds, repo)
        view.highlight_rows([2, 3])
        assert 2 in view.table_model().highlighted_row_ids()

    def test_filter_to_rows_then_clear(
        self, qtbot: QtBot, db_with_engagement: tuple[Database, int]
    ) -> None:
        db, eng_id = db_with_engagement
        ds, repo = _make_dataset(db, eng_id, 5)
        view = DataTableView()
        qtbot.addWidget(view)
        view.set_dataset(ds, repo)
        view.filter_to_rows([2, 4])
        assert view.table_model().rowCount() == 2
        view.clear_filter()
        assert view.table_model().rowCount() == 5

    def test_clear_dataset_empties_view(
        self, qtbot: QtBot, db_with_engagement: tuple[Database, int]
    ) -> None:
        db, eng_id = db_with_engagement
        ds, repo = _make_dataset(db, eng_id, 2)
        view = DataTableView()
        qtbot.addWidget(view)
        view.set_dataset(ds, repo)
        view.clear_dataset()
        assert view.table_model().rowCount() == 0


class TestLazyCache:
    """Sprint 11.2: Cache lädt nur Range um Cache-Miss herum."""

    def test_initial_read_loads_bulk_around_first_row(
        self, db_with_engagement: tuple[Database, int]
    ) -> None:
        db, eng_id = db_with_engagement
        rows = tuple(DatasetRow(row_id=i, values={"a": i}) for i in range(1, 1001))
        ds, repo = _persist_dataset(db, eng_id, rows, columns=("a",))

        model = DatasetTableModel(ds, repo)
        # Request Zeile mit view_row=0 → row_id=1 → Bulk-Load Range
        model.data(model.index(0, 0))
        assert 1 in model._row_cache
        # Look-Ahead-Window läuft bis row_id = 1 + 125 = 126
        assert 100 in model._row_cache
        # Außerhalb des Windows: noch nicht geladen
        assert 800 not in model._row_cache

    def test_jump_far_triggers_new_bulk_load(
        self, db_with_engagement: tuple[Database, int]
    ) -> None:
        db, eng_id = db_with_engagement
        rows = tuple(DatasetRow(row_id=i, values={"a": i}) for i in range(1, 2001))
        ds, repo = _persist_dataset(db, eng_id, rows, columns=("a",))

        model = DatasetTableModel(ds, repo)
        model.data(model.index(0, 0))  # Range 1..126
        assert 1500 not in model._row_cache
        model.data(model.index(1499, 0))  # row_id=1500 → Range 1375..1625
        assert 1500 in model._row_cache

    def test_cache_evicted_when_size_exceeded(
        self, db_with_engagement: tuple[Database, int]
    ) -> None:
        db, eng_id = db_with_engagement
        rows = tuple(DatasetRow(row_id=i, values={"a": i}) for i in range(1, 3001))
        ds, repo = _persist_dataset(db, eng_id, rows, columns=("a",))

        model = DatasetTableModel(ds, repo)
        model._cache_size = 500  # für den Test verkleinern

        # Viele unterschiedliche Positionen anfragen, jede triggert ggf. einen
        # neuen Bulk-Load. Cache darf die Größe nicht überschreiten.
        for view_row in range(0, 3000, 300):
            model.data(model.index(view_row, 0))

        assert len(model._row_cache) <= 500

    def test_set_dataset_invalidates_cache(self, db_with_engagement: tuple[Database, int]) -> None:
        db, eng_id = db_with_engagement
        ds1, repo1 = _make_dataset(db, eng_id, 5)

        model = DatasetTableModel(ds1, repo1)
        model.data(model.index(0, 0))
        assert len(model._row_cache) > 0

        # Zweites Dataset – Cache muss komplett invalidiert sein.
        rows2 = tuple(DatasetRow(row_id=i, values={"x": i * 10}) for i in range(1, 4))
        ds2, repo2 = _persist_dataset(db, eng_id, rows2, columns=("x",), name="t2")
        model.set_dataset(ds2, repo2)

        assert model._row_cache == {}
        assert model.rowCount() == 3
        assert model.columnCount() == 1

    def test_clear_drops_cache(self, db_with_engagement: tuple[Database, int]) -> None:
        db, eng_id = db_with_engagement
        ds, repo = _make_dataset(db, eng_id, 3)
        model = DatasetTableModel(ds, repo)
        model.data(model.index(0, 0))
        assert len(model._row_cache) > 0
        model.clear()
        assert model._row_cache == {}
        assert model.rowCount() == 0
