"""DatasetRepo.iter_row_field_pairs – (row_id, Wert)-Stream für den Pairs-Pfad (Sprint 35 / P-003)."""

from __future__ import annotations

from datetime import date, datetime, time

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


_COLUMNS = ("txt", "zahl", "fl", "wahr", "leer", "ts", "d", "t", "gemischt")


def _mixed_rows() -> list[DatasetRow]:
    """Alle Werttypen, die der Import erzeugen kann – inkl. None, Umlaute,
    int-vs-float-Grenzfall, bool und fehlendem Key (row 4 hat kein 'gemischt')."""
    return [
        DatasetRow(
            row_id=1,
            values={
                "txt": "Größe ß",
                "zahl": 5,
                "fl": 5.0,
                "wahr": True,
                "leer": None,
                "ts": datetime(2026, 3, 1, 8, 30, 15),
                "d": date(2026, 3, 1),
                "t": time(8, 30),
                "gemischt": 5,
            },
        ),
        DatasetRow(
            row_id=2,
            values={
                "txt": "alpha",
                "zahl": -3,
                "fl": 0.25,
                "wahr": False,
                "leer": "doch was",
                "ts": datetime(2026, 1, 1, 0, 0, 0),
                "d": date(2026, 1, 1),
                "t": time(23, 59, 59),
                "gemischt": "5",
            },
        ),
        DatasetRow(
            row_id=3,
            values={
                "txt": "",
                "zahl": 0,
                "fl": -1.5,
                "wahr": True,
                "leer": None,
                "ts": datetime(2026, 2, 15, 12, 0, 0),
                "d": date(2026, 2, 15),
                "t": time(0, 0),
                "gemischt": None,
            },
        ),
        DatasetRow(
            row_id=4,
            values={
                "txt": "Ünïcode / Pfad\\mit\"Quote",
                "zahl": 2**40,
                "fl": 3.14159,
                "wahr": False,
                "leer": None,
                "ts": datetime(2026, 12, 31, 23, 59, 59),
                "d": date(2026, 12, 31),
                "t": time(6, 15, 30),
            },
        ),
    ]


class TestIterRowFieldPairs:
    """Decode-Oracle: der Pairs-Stream muss bit-identisch zu `iter_rows` +
    `DatasetRow.get(column)` decodieren (gleiche Werte UND gleiche Typen)."""

    def test_pairs_match_iter_rows_for_all_columns(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = _mixed_rows()
        ds_id = _persist(db, eng, rows, _COLUMNS)
        repo = DatasetRepo(db.connect())
        for column in _COLUMNS:
            expected = [(r.row_id, r.get(column)) for r in repo.iter_rows(ds_id)]
            got = list(repo.iter_row_field_pairs(ds_id, column))
            assert got == expected, column
            # `==` allein reicht nicht: True == 1 und 5 == 5.0 – Typen explizit.
            assert [type(v) for _, v in got] == [type(v) for _, v in expected], column

    def test_pairs_sorted_by_row_index(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = list(reversed(_mixed_rows()))  # absteigend übergeben
        ds_id = _persist(db, eng, rows, _COLUMNS)
        got = list(DatasetRepo(db.connect()).iter_row_field_pairs(ds_id, "txt"))
        assert [rid for rid, _ in got] == sorted(rid for rid, _ in got)

    def test_missing_column_yields_none_per_row(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = _mixed_rows()
        ds_id = _persist(db, eng, rows, _COLUMNS)
        got = list(DatasetRepo(db.connect()).iter_row_field_pairs(ds_id, "GibtsNicht"))
        assert got == [(r.row_id, None) for r in rows]

    def test_empty_dataset_yields_nothing(self, db: Database) -> None:
        eng = _engagement_id(db)
        ds_id = _persist(db, eng, [], ("Land",))
        assert list(DatasetRepo(db.connect()).iter_row_field_pairs(ds_id, "Land")) == []
