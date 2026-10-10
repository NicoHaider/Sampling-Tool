"""Bit-Identität der Ziehung mit genau einem Filter (Sprint 92).

Die Golden-Werte unten wurden auf `main` = b3582d7 (Sprint 91, vor dem
Mehrfachfilter-Umbau) mit dem damaligen Einzelfilter-Modell erzeugt und
eingefroren. Wird ein Test rot, zieht ein Einzelfilter nach dem Umbau nicht
mehr bit-identisch – STOPP, NIEMALS die Werte an geänderten Output anpassen.
"""

from __future__ import annotations

from typing import Any

import pytest

from sampling_tool.core.models import (
    FilterCondition,
    FilterOperator,
    SampleConfig,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.core.sampling import (
    ClusterSampler,
    SimpleSampler,
    StratifiedSampler,
    create_sampler,
)
from tests.unit.test_golden_vectors import (
    GOLDEN_CLUSTER,
    GOLDEN_SIMPLE,
    GOLDEN_STRATIFIED_PROPORTIONAL,
    SEEDS,
    _population,
)


def _single_filter_config(
    field: str, operator: FilterOperator, value: Any, **kwargs: Any
) -> SampleConfig:
    return SampleConfig(filters=(FilterCondition(field, operator, value),), **kwargs)


GOLDEN_SINGLE_FILTER_SIMPLE: dict[int, tuple[int, ...]] = {
    0: (5, 12, 14, 22, 23, 24, 29),
    1: (3, 11, 12, 13, 16, 23, 25),
    42: (1, 7, 9, 10, 15, 18, 24),
    12345: (1, 2, 5, 13, 14, 19, 26),
    2147483647: (4, 7, 16, 18, 19, 20, 28),
}

_AUT_WITHOUT_LOW = (3, 4, 5, 6, 9, 10, 11, 12, 15, 16, 17, 18, 21, 22, 23, 24, 27, 28, 29, 30)
_GER_WITHOUT_LOW = (33, 34, 35, 36, 39, 40, 41, 42, 45, 46, 47, 48)
_FRA_WITHOUT_LOW = (51, 52, 53, 54, 57, 58, 59, 60)

GOLDEN_SINGLE_FILTER_CLUSTER: dict[int, tuple[int, ...]] = {
    0: _AUT_WITHOUT_LOW + _FRA_WITHOUT_LOW,
    1: _AUT_WITHOUT_LOW + _GER_WITHOUT_LOW,
    42: _GER_WITHOUT_LOW + _FRA_WITHOUT_LOW,
    12345: _AUT_WITHOUT_LOW + _FRA_WITHOUT_LOW,
    2147483647: _AUT_WITHOUT_LOW + _FRA_WITHOUT_LOW,
}

GOLDEN_SINGLE_FILTER_STRATIFIED_PROPORTIONAL: dict[int, tuple[int, ...]] = {
    0: (4, 16, 20, 27, 28, 33, 34, 44, 50, 51, 57),
    1: (7, 9, 10, 22, 27, 39, 44, 45, 49, 52, 58),
    42: (1, 4, 15, 22, 26, 39, 40, 46, 50, 56, 57),
    12345: (1, 9, 14, 22, 25, 37, 38, 40, 50, 52, 57),
    2147483647: (3, 14, 15, 20, 21, 31, 34, 40, 44, 55, 56),
}

GOLDEN_SINGLE_FILTER_STRATIFIED_EQUAL: dict[int, tuple[int, ...]] = {
    0: (18, 21, 22, 34, 48, 49, 52, 55, 57),
    1: (3, 11, 13, 35, 39, 41, 57, 58, 60),
    42: (1, 11, 21, 35, 39, 45, 51, 54, 60),
    12345: (11, 12, 24, 35, 46, 48, 53, 54, 59),
    2147483647: (5, 16, 28, 33, 37, 48, 53, 55, 58),
}


class TestSingleFilterReproducibility:
    """Gleicher Seed + genau ein Filter ⇒ exakt die Zeilen-IDs von Sprint 91."""

    @pytest.mark.parametrize("seed", SEEDS)
    def test_simple_with_one_filter(self, seed: int) -> None:
        cfg = _single_filter_config(
            "Country", FilterOperator.EQ, "AUT", method=SamplingMethod.SIMPLE, size=7, seed=seed
        )
        result = create_sampler(cfg).sample(_population())
        assert result.selected_row_ids == GOLDEN_SINGLE_FILTER_SIMPLE[seed]

    @pytest.mark.parametrize("seed", SEEDS)
    def test_cluster_with_one_filter(self, seed: int) -> None:
        cfg = _single_filter_config(
            "Bucket",
            FilterOperator.GTE,
            30,
            method=SamplingMethod.CLUSTER,
            size=2,
            seed=seed,
            cluster_field="Country",
        )
        result = create_sampler(cfg).sample(_population())
        assert result.selected_row_ids == GOLDEN_SINGLE_FILTER_CLUSTER[seed]

    @pytest.mark.parametrize("seed", SEEDS)
    def test_stratified_proportional_with_one_filter(self, seed: int) -> None:
        cfg = _single_filter_config(
            "Bucket",
            FilterOperator.LT,
            50,
            method=SamplingMethod.STRATIFIED,
            size=11,
            seed=seed,
            stratum_field="Country",
        )
        result = create_sampler(cfg).sample(_population())
        assert result.selected_row_ids == GOLDEN_SINGLE_FILTER_STRATIFIED_PROPORTIONAL[seed]

    @pytest.mark.parametrize("seed", SEEDS)
    def test_stratified_equal_with_one_filter(self, seed: int) -> None:
        cfg = _single_filter_config(
            "Bucket",
            FilterOperator.NE,
            20,
            method=SamplingMethod.STRATIFIED,
            size=9,
            seed=seed,
            stratum_field="Country",
            stratify_mode=StratifyMode.EQUAL,
        )
        result = create_sampler(cfg).sample(_population())
        assert result.selected_row_ids == GOLDEN_SINGLE_FILTER_STRATIFIED_EQUAL[seed]

    @pytest.mark.parametrize("seed", SEEDS)
    def test_unfiltered_fastpaths_unchanged(self, seed: int) -> None:
        rows = _population()
        simple = SimpleSampler(SampleConfig(method=SamplingMethod.SIMPLE, size=15, seed=seed))
        assert (
            simple.sample_ids((r.row_id for r in rows), 60).selected_row_ids
            == (GOLDEN_SIMPLE[seed])
        )
        cluster = ClusterSampler(
            SampleConfig(method=SamplingMethod.CLUSTER, size=2, seed=seed, cluster_field="Country")
        )
        pairs = [(r.row_id, r.get("Country")) for r in rows]
        assert cluster.sample_pairs(pairs, 60).selected_row_ids == GOLDEN_CLUSTER[seed]
        stratified = StratifiedSampler(
            SampleConfig(
                method=SamplingMethod.STRATIFIED, size=15, seed=seed, stratum_field="Country"
            )
        )
        assert (
            stratified.sample_pairs(pairs, 60).selected_row_ids
            == (GOLDEN_STRATIFIED_PROPORTIONAL[seed])
        )
