"""DatasetRepo.distinct_values – SQL-DISTINCT statt get_all_rows (Sprint 19 / P-005)."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

import pytest

from sampling_tool.core.models import Dataset, DatasetRow, Engagement
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import DatasetRepo, EngagementRepo

pytestmark = pytest.mark.integration


def _engagement_id(db: Database) -> int:
    eng = EngagementRepo(db.connect()).get_or_create(
        Engagement(auditor_name="A", client_name="C", auditor_position="S", audit_type="ISAE 3402")
    )
    assert eng.id is not None
    return eng.id


def _persist(db: Database, eng_id: int, rows: list[DatasetRow], columns: tuple[str, ...]) -> int:
    repo = DatasetRepo(db.connect())
    ds = repo.create(Dataset(name="t", columns=columns, engagement_id=eng_id), tuple(rows))
    assert ds.id is not None
    return ds.id


def _reference_distinct(rows: list[DatasetRow], field: str) -> list[Any]:
    """Oracle – repliziert die ursprüngliche _distinct_values-Semantik exakt."""
    seen: set[str] = set()
    result: list[Any] = []
    for row in rows:
        value = row.values.get(field)
        if value is None:
            continue
        key = repr(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    result.sort(key=lambda v: str(v))
    return result


class TestDistinctValues:
    def test_returns_distinct_strings_sorted(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = [
            DatasetRow(row_id=1, values={"Land": "DEU"}),
            DatasetRow(row_id=2, values={"Land": "AUT"}),
            DatasetRow(row_id=3, values={"Land": "DEU"}),
            DatasetRow(row_id=4, values={"Land": "CHE"}),
        ]
        ds_id = _persist(db, eng, rows, ("Land",))
        assert DatasetRepo(db.connect()).distinct_values(ds_id, "Land") == ["AUT", "CHE", "DEU"]

    def test_skips_none_values(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = [
            DatasetRow(row_id=1, values={"Land": "AUT"}),
            DatasetRow(row_id=2, values={"Land": None}),
            DatasetRow(row_id=3, values={"Land": "CHE"}),
        ]
        ds_id = _persist(db, eng, rows, ("Land",))
        assert DatasetRepo(db.connect()).distinct_values(ds_id, "Land") == ["AUT", "CHE"]

    def test_handles_datetime_column(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = [
            DatasetRow(row_id=1, values={"Ts": datetime(2026, 1, 2, 9, 0, 0)}),
            DatasetRow(row_id=2, values={"Ts": datetime(2026, 1, 1, 9, 0, 0)}),
            DatasetRow(row_id=3, values={"Ts": datetime(2026, 1, 2, 9, 0, 0)}),
        ]
        ds_id = _persist(db, eng, rows, ("Ts",))
        result = DatasetRepo(db.connect()).distinct_values(ds_id, "Ts")
        assert result == [datetime(2026, 1, 1, 9, 0, 0), datetime(2026, 1, 2, 9, 0, 0)]

    def test_handles_date_and_time_columns(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = [
            DatasetRow(row_id=1, values={"D": date(2026, 1, 2), "T": time(8, 30)}),
            DatasetRow(row_id=2, values={"D": date(2026, 1, 1), "T": time(8, 30)}),
        ]
        ds_id = _persist(db, eng, rows, ("D", "T"))
        repo = DatasetRepo(db.connect())
        assert repo.distinct_values(ds_id, "D") == [date(2026, 1, 1), date(2026, 1, 2)]
        assert repo.distinct_values(ds_id, "T") == [time(8, 30)]

    def test_distinguishes_int_from_float(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = [
            DatasetRow(row_id=1, values={"N": 5}),
            DatasetRow(row_id=2, values={"N": 5.0}),
        ]
        ds_id = _persist(db, eng, rows, ("N",))
        result = DatasetRepo(db.connect()).distinct_values(ds_id, "N")
        assert result == _reference_distinct(rows, "N")
        assert any(isinstance(v, int) for v in result)
        assert any(isinstance(v, float) for v in result)

    def test_handles_bool_column(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = [
            DatasetRow(row_id=1, values={"B": True}),
            DatasetRow(row_id=2, values={"B": False}),
            DatasetRow(row_id=3, values={"B": True}),
        ]
        ds_id = _persist(db, eng, rows, ("B",))
        result = DatasetRepo(db.connect()).distinct_values(ds_id, "B")
        assert result == _reference_distinct(rows, "B")
        assert all(isinstance(v, bool) for v in result)

    def test_column_name_with_spaces(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = [
            DatasetRow(row_id=1, values={"Mit Leerzeichen": "x"}),
            DatasetRow(row_id=2, values={"Mit Leerzeichen": "y"}),
        ]
        ds_id = _persist(db, eng, rows, ("Mit Leerzeichen",))
        assert DatasetRepo(db.connect()).distinct_values(ds_id, "Mit Leerzeichen") == ["x", "y"]

    def test_empty_dataset_returns_empty_list(self, db: Database) -> None:
        eng = _engagement_id(db)
        ds_id = _persist(db, eng, [], ("Land",))
        assert DatasetRepo(db.connect()).distinct_values(ds_id, "Land") == []

    def test_missing_column_returns_empty_list(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = [DatasetRow(row_id=1, values={"Land": "AUT"})]
        ds_id = _persist(db, eng, rows, ("Land",))
        assert DatasetRepo(db.connect()).distinct_values(ds_id, "GibtsNicht") == []


class TestDistinctValuesReproducibility:
    """KERN-Test: SQL-Pfad muss bit-identisch zum alten RAM-Pfad sein –
    inklusive str()-Gleichstand-Tie-Break über die Zeilen-Reihenfolge."""

    def test_sql_path_matches_ram_reference_all_types(self, db: Database) -> None:
        eng = _engagement_id(db)
        # `mixed` enthält bewusst: int 5 UND str "5" (gleicher str(),
        # anderer Wert), ein nicht-benachbartes Duplikat von "5" (row 2 und
        # row 7), float, bool, datetime, None. `none_haltig` testet das
        # None-Überspringen. Reine Ein-Typ-Spalten beweisen die
        # Bit-Gleichheit beim Tie-Break NICHT.
        rows = [
            DatasetRow(
                row_id=1,
                values={
                    "mixed": 5,
                    "none_haltig": "a",
                    "txt": "delta",
                    "zahl": 30,
                    "fl": 1.5,
                    "ts": datetime(2026, 3, 1, 8, 0),
                },
            ),
            DatasetRow(
                row_id=2,
                values={
                    "mixed": "5",
                    "none_haltig": None,
                    "txt": "alpha",
                    "zahl": 10,
                    "fl": 0.5,
                    "ts": datetime(2026, 1, 1, 8, 0),
                },
            ),
            DatasetRow(
                row_id=3,
                values={
                    "mixed": 5.0,
                    "none_haltig": "b",
                    "txt": "delta",
                    "zahl": 20,
                    "fl": 1.5,
                    "ts": datetime(2026, 2, 1, 8, 0),
                },
            ),
            DatasetRow(
                row_id=4,
                values={
                    "mixed": True,
                    "none_haltig": None,
                    "txt": "charlie",
                    "zahl": 10,
                    "fl": 2.5,
                    "ts": datetime(2026, 1, 1, 8, 0),
                },
            ),
            DatasetRow(
                row_id=5,
                values={
                    "mixed": "apfel",
                    "none_haltig": "a",
                    "txt": "bravo",
                    "zahl": 30,
                    "fl": 0.5,
                    "ts": datetime(2026, 3, 1, 8, 0),
                },
            ),
            DatasetRow(
                row_id=6,
                values={
                    "mixed": None,
                    "none_haltig": "c",
                    "txt": "alpha",
                    "zahl": 40,
                    "fl": 3.5,
                    "ts": datetime(2026, 4, 1, 8, 0),
                },
            ),
            DatasetRow(
                row_id=7,
                values={
                    "mixed": "5",
                    "none_haltig": None,
                    "txt": "delta",
                    "zahl": 20,
                    "fl": 1.5,
                    "ts": datetime(2026, 2, 1, 8, 0),
                },
            ),
            DatasetRow(
                row_id=8,
                values={
                    "mixed": 10,
                    "none_haltig": "a",
                    "txt": "echo",
                    "zahl": 50,
                    "fl": 2.5,
                    "ts": datetime(2026, 5, 1, 8, 0),
                },
            ),
        ]
        columns = ("mixed", "none_haltig", "txt", "zahl", "fl", "ts")
        ds_id = _persist(db, eng, rows, columns)
        repo = DatasetRepo(db.connect())
        for field in columns:
            assert repo.distinct_values(ds_id, field) == _reference_distinct(rows, field), field
