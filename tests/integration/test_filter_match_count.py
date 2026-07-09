"""_count_filter_matches – Vorschau-Zähler teilt matches_filter mit dem Sampler (Sprint 36 / T5)."""

from __future__ import annotations

from typing import Any

import pytest

from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    Engagement,
    FilterOperator,
    SampleConfig,
    SamplingMethod,
)
from sampling_tool.core.sampling import SimpleSampler
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import DatasetRepo, EngagementRepo
from sampling_tool.ui.controllers.workspace_controller import _count_filter_matches

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


_NUM_COLUMN = "betrag"
_STR_COLUMN = "land"

# betrag mit Duplikat bei 30 → EQ/GTE/LTE liefern > 1; land deckt Strings ab.
_MIXED_DATA: list[tuple[int, str]] = [
    (10, "AUT"),
    (20, "DEU"),
    (30, "AUT"),
    (30, "CHE"),
    (40, "DEU"),
    (50, "AUT"),
]


def _mixed_rows() -> list[DatasetRow]:
    return [
        DatasetRow(row_id=i, values={_NUM_COLUMN: betrag, _STR_COLUMN: land})
        for i, (betrag, land) in enumerate(_MIXED_DATA, start=1)
    ]


class TestFilterMatchCount:
    def test_all_six_operators_over_numeric_column(self, db: Database) -> None:
        eng = _engagement_id(db)
        ds_id = _persist(db, eng, _mixed_rows(), (_NUM_COLUMN, _STR_COLUMN))
        repo = DatasetRepo(db.connect())
        # Werte: 10,20,30,30,40,50; Filter-Wert 30.
        expected = {
            FilterOperator.EQ: 2,  # 30,30
            FilterOperator.NE: 4,  # 10,20,40,50
            FilterOperator.GT: 2,  # 40,50
            FilterOperator.GTE: 4,  # 30,30,40,50
            FilterOperator.LT: 2,  # 10,20
            FilterOperator.LTE: 4,  # 10,20,30,30
        }
        for op, want in expected.items():
            got = _count_filter_matches(repo, ds_id, _NUM_COLUMN, op, 30, None)
            assert got == want, op

    def test_restrict_to_ids_counts_only_within_subset(self, db: Database) -> None:
        eng = _engagement_id(db)
        ds_id = _persist(db, eng, _mixed_rows(), (_NUM_COLUMN, _STR_COLUMN))
        repo = DatasetRepo(db.connect())
        # Teilmenge row_ids 1,2,3 → betrag 10,20,30. GT 15 → 20,30 = 2.
        within = _count_filter_matches(repo, ds_id, _NUM_COLUMN, FilterOperator.GT, 15, [1, 2, 3])
        assert within == 2
        # Volle Tabelle GT 15 → 20,30,30,40,50 = 5.
        whole = _count_filter_matches(repo, ds_id, _NUM_COLUMN, FilterOperator.GT, 15, None)
        assert whole == 5

    def test_empty_restrict_to_ids_counts_zero(self, db: Database) -> None:
        eng = _engagement_id(db)
        ds_id = _persist(db, eng, _mixed_rows(), (_NUM_COLUMN, _STR_COLUMN))
        repo = DatasetRepo(db.connect())
        # Leere Auswahl (nicht None) → Zählung innerhalb der leeren Menge = 0.
        assert _count_filter_matches(repo, ds_id, _NUM_COLUMN, FilterOperator.GT, 0, []) == 0

    def test_pathological_column_name_uses_iter_rows_fallback(self, db: Database) -> None:
        """Spalten mit `"`/`\\` können den json_extract-Pfad nicht → Fallback iter_rows.

        `iter_row_field_pairs` würde für solche Spalten ValueError werfen; dass die
        Zählung ein Ergebnis liefert (statt zu crashen), beweist den Fallback-Pfad.
        """
        eng = _engagement_id(db)
        col_quote = 'Betrag "EUR"'
        col_backslash = "Soll\\Haben"
        rows = [
            DatasetRow(row_id=1, values={col_quote: 10, col_backslash: 100}),
            DatasetRow(row_id=2, values={col_quote: 20, col_backslash: 200}),
            DatasetRow(row_id=3, values={col_quote: 30, col_backslash: 300}),
        ]
        ds_id = _persist(db, eng, rows, (col_quote, col_backslash))
        repo = DatasetRepo(db.connect())
        assert DatasetRepo.supports_field_pairs(col_quote) is False
        assert DatasetRepo.supports_field_pairs(col_backslash) is False
        # Darf NICHT raisen und muss korrekt über iter_rows zählen.
        assert _count_filter_matches(repo, ds_id, col_quote, FilterOperator.GTE, 20, None) == 2
        assert _count_filter_matches(repo, ds_id, col_backslash, FilterOperator.LT, 300, None) == 2

    def test_consistency_oracle_count_equals_collect_pool(self, db: Database) -> None:
        """Zähler == Größe des Pools, den `_collect_pool` für dieselbe Filter-Config sammelt.

        Bindet die Vorschau-Zahl an das, was eine echte Ziehung tatsächlich einsammeln
        würde – über mehrere Operatoren inkl. eines Ordnungsoperators.
        """
        eng = _engagement_id(db)
        ds_id = _persist(db, eng, _mixed_rows(), (_NUM_COLUMN, _STR_COLUMN))
        repo = DatasetRepo(db.connect())
        cases: list[tuple[str, FilterOperator, Any]] = [
            (_NUM_COLUMN, FilterOperator.EQ, 30),
            (_NUM_COLUMN, FilterOperator.NE, 30),
            (_NUM_COLUMN, FilterOperator.GT, 25),
            (_NUM_COLUMN, FilterOperator.GTE, 30),
            (_NUM_COLUMN, FilterOperator.LT, 25),
            (_NUM_COLUMN, FilterOperator.LTE, 30),
            (_STR_COLUMN, FilterOperator.EQ, "AUT"),
            (_STR_COLUMN, FilterOperator.NE, "AUT"),
        ]
        for column, op, value in cases:
            cfg = SampleConfig(
                method=SamplingMethod.SIMPLE,
                size=1,
                seed=1,
                filter_field=column,
                filter_value=value,
                filter_operator=op,
            )
            pool, _total = SimpleSampler(cfg)._collect_pool(repo.iter_rows(ds_id))
            count = _count_filter_matches(repo, ds_id, column, op, value, None)
            assert count == len(pool), (column, op, value)
