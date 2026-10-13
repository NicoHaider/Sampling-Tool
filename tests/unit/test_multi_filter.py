"""Mehrere Filter je Stichprobe, UND-verknüpft (Sprint 92 / A)."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime

import pytest

from sampling_tool.core.formatting import format_filters
from sampling_tool.core.models import (
    DatasetRow,
    FilterCondition,
    FilterOperator,
    SampleConfig,
    SamplingMethod,
)
from sampling_tool.core.sampling import (
    SamplingError,
    SimpleSampler,
    create_sampler,
    matches_all,
)


def _rows() -> tuple[DatasetRow, ...]:
    """40 Zeilen: Kostenstelle (Vertrieb/Einkauf im Wechsel), Betrag 100..4000."""
    return tuple(
        DatasetRow(
            row_id=i,
            values={
                "Kostenstelle": "Vertrieb" if i % 2 else "Einkauf",
                "Betrag": i * 100,
            },
        )
        for i in range(1, 41)
    )


def _config(*filters: FilterCondition, size: int = 3, seed: int = 7) -> SampleConfig:
    return SampleConfig(method=SamplingMethod.SIMPLE, size=size, seed=seed, filters=filters)


VERTRIEB = FilterCondition("Kostenstelle", FilterOperator.EQ, "Vertrieb")
AB_1000 = FilterCondition("Betrag", FilterOperator.GTE, 1000)
UNTER_2500 = FilterCondition("Betrag", FilterOperator.LT, 2500)


class TestFilterConditionModel:
    def test_equal_conditions_are_equal(self) -> None:
        assert FilterCondition("A", FilterOperator.EQ, 1) == FilterCondition(
            "A", FilterOperator.EQ, 1
        )
        assert FilterCondition("A", FilterOperator.EQ, 1) != FilterCondition(
            "A", FilterOperator.NE, 1
        )

    def test_is_frozen(self) -> None:
        cond = FilterCondition("A", FilterOperator.EQ, 1)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cond.field = "B"  # type: ignore[misc]

    def test_date_values_keep_their_type(self) -> None:
        cond = FilterCondition("Datum", FilterOperator.GTE, datetime(2026, 1, 1))
        assert isinstance(cond.value, datetime)
        assert FilterCondition("Datum", FilterOperator.EQ, date(2026, 1, 1)).value == date(
            2026, 1, 1
        )

    def test_config_without_filters_has_no_filter(self) -> None:
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=1, seed=0)
        assert cfg.filters == ()
        assert cfg.has_filter is False
        assert _config(VERTRIEB).has_filter is True


class TestMultiFilterPool:
    def test_two_conditions_on_different_columns(self) -> None:
        rows = _rows()
        pool = [r.row_id for r in rows if matches_all(r, (VERTRIEB, AB_1000))]
        assert pool == [i for i in range(10, 41) if i % 2]
        result = create_sampler(_config(VERTRIEB, AB_1000, size=15)).sample(rows)
        assert set(result.selected_row_ids) == set(pool)

    def test_two_conditions_on_same_column_form_a_range(self) -> None:
        rows = _rows()
        result = create_sampler(_config(AB_1000, UNTER_2500, size=15)).sample(rows)
        assert result.selected_row_ids == tuple(range(10, 25))

    def test_five_conditions(self) -> None:
        conds = (
            VERTRIEB,
            AB_1000,
            UNTER_2500,
            FilterCondition("Betrag", FilterOperator.NE, 1500),
            FilterCondition("Betrag", FilterOperator.LTE, 2100),
        )
        result = create_sampler(_config(*conds, size=5)).sample(_rows())
        assert result.selected_row_ids == (11, 13, 17, 19, 21)

    def test_empty_filters_is_unfiltered(self) -> None:
        rows = _rows()
        assert all(matches_all(r, ()) for r in rows)
        unfiltered = SimpleSampler(_config(size=5)).sample(rows)
        via_ids = SimpleSampler(_config(size=5)).sample_ids((r.row_id for r in rows), len(rows))
        assert unfiltered.selected_row_ids == via_ids.selected_row_ids

    def test_no_match_raises(self) -> None:
        nobody = FilterCondition("Betrag", FilterOperator.GT, 10**9)
        with pytest.raises(SamplingError):
            create_sampler(_config(VERTRIEB, nobody)).sample(_rows())

    def test_fastpaths_reject_filters(self) -> None:
        sampler = SimpleSampler(_config(VERTRIEB, AB_1000))
        with pytest.raises(SamplingError):
            sampler.sample_ids(iter([1, 2, 3]), 3)


class TestMultiFilterReproducibility:
    def test_same_seed_same_result(self) -> None:
        first = create_sampler(_config(VERTRIEB, AB_1000, size=6, seed=4711)).sample(_rows())
        second = create_sampler(_config(VERTRIEB, AB_1000, size=6, seed=4711)).sample(_rows())
        assert first.selected_row_ids == second.selected_row_ids

    def test_condition_order_does_not_matter(self) -> None:
        a = create_sampler(_config(VERTRIEB, AB_1000, size=6, seed=99)).sample(_rows())
        b = create_sampler(_config(AB_1000, VERTRIEB, size=6, seed=99)).sample(_rows())
        assert a.selected_row_ids == b.selected_row_ids


class TestFormatFilters:
    def test_no_filter_is_dash(self) -> None:
        assert format_filters(()) == "—"

    def test_conditions_joined_with_und(self) -> None:
        text = format_filters((VERTRIEB, AB_1000))
        assert text == "Kostenstelle = „Vertrieb“ UND Betrag ≥ 1000"

    def test_dates_and_none(self) -> None:
        text = format_filters(
            (
                FilterCondition("Datum", FilterOperator.LT, datetime(2026, 6, 30)),
                FilterCondition("Notiz", FilterOperator.EQ, None),
            )
        )
        assert text == "Datum < 2026-06-30 UND Notiz = (kein Wert)"
