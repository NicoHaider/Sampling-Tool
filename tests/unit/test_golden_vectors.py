"""Golden-Vektoren: bit-genaue Referenz-Row-IDs (Sprint 39 / S1.2, R-001).

Diese Werte wurden mit dem damaligen `np.random.default_rng(seed)`-Pfad
(vor dem Umstieg auf `Generator(PCG64(seed))`) erzeugt und danach eingefroren.
Bleibt dieser Test nach dem Refactor grün, ist die Output-Identität bewiesen.
Wird er rot: `Generator(PCG64(seed))` ist NICHT output-identisch zu
`default_rng(seed)` – dann STOPP und an Nico melden, NIEMALS die Werte an
geänderten Output anpassen (siehe SPRINT_39_PROMPT.md Abschnitt 5/11).

Läuft dank S1.1 automatisch auf Ubuntu/Windows/macOS in CI – weichen die
Row-IDs zwischen den OS ab, ist das ein vorbestehender P0-Cross-Platform-Bug,
kein Test-Detail (Golden-Werte NICHT pro OS aufspalten).
"""

from __future__ import annotations

import pytest

from sampling_tool.core.models import (
    DatasetRow,
    FilterOperator,
    SampleConfig,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.core.sampling import ClusterSampler, SimpleSampler, StratifiedSampler

SEEDS = (0, 1, 42, 12345, 2**31 - 1)


def _country(row_id: int) -> str:
    """Bewusst uneben (30/20/10) – trennt PROPORTIONAL von EQUAL (Largest-Remainder):
    bei gleich großen Schichten liefern beide Modi zufällig dieselben Zielgrößen."""
    if row_id <= 30:
        return "AUT"
    if row_id <= 50:
        return "GER"
    return "FRA"


def _population() -> tuple[DatasetRow, ...]:
    """60 Zeilen: `Country` (30/20/10 uneben) für Cluster/Stratified,
    `Bucket` (10..60, je 10 Zeilen) für die Filter-Operator-Matrix."""
    return tuple(
        DatasetRow(
            row_id=i,
            values={"Country": _country(i), "Bucket": (((i - 1) % 6) + 1) * 10},
        )
        for i in range(1, 61)
    )


# ---------------------------------------------------------------------------
# Committete Referenz (aus dem Pre-Refactor-Code erzeugt)
# ---------------------------------------------------------------------------

GOLDEN_SIMPLE: dict[int, tuple[int, ...]] = {
    0: (4, 8, 13, 17, 20, 22, 27, 35, 36, 40, 41, 47, 54, 57, 60),
    1: (3, 7, 9, 17, 18, 25, 26, 33, 34, 37, 43, 49, 50, 52, 54),
    42: (1, 8, 9, 10, 12, 16, 17, 32, 33, 41, 43, 51, 52, 53, 57),
    12345: (1, 7, 13, 16, 21, 22, 23, 25, 33, 37, 40, 41, 48, 51, 55),
    2147483647: (2, 3, 10, 11, 15, 17, 19, 21, 31, 33, 41, 42, 47, 55, 58),
}

GOLDEN_CLUSTER: dict[int, tuple[int, ...]] = {
    0: tuple(range(1, 31)) + tuple(range(51, 61)),
    1: tuple(range(1, 51)),
    42: tuple(range(31, 61)),
    12345: tuple(range(1, 31)) + tuple(range(51, 61)),
    2147483647: tuple(range(1, 31)) + tuple(range(51, 61)),
}

GOLDEN_STRATIFIED_PROPORTIONAL: dict[int, tuple[int, ...]] = {
    0: (5, 6, 12, 14, 22, 23, 24, 29, 34, 35, 43, 44, 45, 54, 59),
    1: (3, 11, 12, 13, 14, 16, 23, 25, 33, 34, 40, 45, 47, 56, 58),
    42: (1, 7, 9, 10, 15, 18, 24, 29, 34, 35, 39, 44, 46, 56, 58),
    12345: (1, 2, 5, 10, 13, 14, 19, 26, 31, 34, 38, 47, 50, 53, 57),
    2147483647: (4, 7, 13, 16, 18, 19, 20, 28, 31, 32, 37, 40, 50, 54, 59),
}

GOLDEN_STRATIFIED_EQUAL: dict[int, tuple[int, ...]] = {
    0: (5, 12, 14, 22, 24, 34, 35, 43, 44, 45, 53, 54, 55, 57, 59),
    1: (3, 11, 12, 13, 23, 33, 34, 40, 45, 47, 53, 55, 56, 58, 59),
    42: (1, 9, 10, 18, 24, 34, 35, 39, 44, 46, 53, 56, 57, 58, 59),
    12345: (1, 2, 13, 14, 26, 31, 34, 38, 47, 50, 52, 53, 56, 57, 59),
    2147483647: (7, 16, 18, 20, 28, 31, 32, 37, 40, 50, 51, 53, 54, 56, 59),
}

GOLDEN_SUPPLEMENT: dict[int, tuple[int, ...]] = {
    0: (13, 17, 20, 22, 31, 41, 48, 49, 52, 57),
    1: (14, 15, 16, 18, 22, 33, 38, 46, 54, 56),
    42: (13, 18, 33, 35, 41, 44, 45, 50, 52, 53),
    12345: (11, 21, 24, 26, 28, 29, 41, 54, 57, 60),
    2147483647: (12, 16, 19, 32, 35, 36, 47, 49, 56, 57),
}

GOLDEN_FILTER: dict[FilterOperator, dict[int, tuple[int, ...]]] = {
    FilterOperator.EQ: {
        0: (3, 15, 21, 45, 57),
        1: (9, 15, 21, 33, 51),
        42: (9, 27, 45, 51, 57),
        12345: (3, 21, 27, 33, 45),
        2147483647: (3, 27, 33, 45, 57),
    },
    FilterOperator.NE: {
        0: (4, 12, 14, 37, 56),
        1: (5, 6, 7, 10, 28),
        42: (10, 28, 30, 48, 50),
        12345: (13, 22, 23, 37, 60),
        2147483647: (2, 26, 30, 47, 56),
    },
    FilterOperator.GT: {
        0: (11, 24, 29, 46, 48),
        1: (6, 23, 24, 28, 47),
        42: (4, 18, 22, 36, 48),
        12345: (4, 5, 28, 29, 53),
        2147483647: (16, 34, 36, 41, 58),
    },
    FilterOperator.GTE: {
        0: (6, 9, 33, 52, 54),
        1: (15, 27, 46, 53, 59),
        42: (4, 15, 18, 23, 34),
        12345: (5, 11, 36, 45, 59),
        2147483647: (6, 23, 35, 41, 45),
    },
    FilterOperator.LT: {
        0: (8, 32, 38, 55, 56),
        1: (13, 19, 20, 44, 55),
        42: (1, 8, 31, 44, 50),
        12345: (1, 19, 26, 44, 49),
        2147483647: (7, 26, 31, 38, 43),
    },
    FilterOperator.LTE: {
        0: (8, 21, 26, 43, 45),
        1: (3, 20, 21, 25, 44),
        42: (1, 15, 19, 33, 45),
        12345: (1, 2, 25, 26, 50),
        2147483647: (13, 31, 33, 38, 55),
    },
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGoldenSimple:
    """SimpleSampler ohne Filter – size=15 von 60."""

    @pytest.mark.parametrize("seed", SEEDS)
    def test_golden_simple(self, seed: int) -> None:
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=15, seed=seed)
        result = SimpleSampler(cfg).sample(_population())
        assert result.selected_row_ids == GOLDEN_SIMPLE[seed]


class TestGoldenCluster:
    """ClusterSampler – 2 von 3 Ländern (Country: 30/20/10 uneben)."""

    @pytest.mark.parametrize("seed", SEEDS)
    def test_golden_cluster(self, seed: int) -> None:
        cfg = SampleConfig(
            method=SamplingMethod.CLUSTER, size=2, seed=seed, cluster_field="Country"
        )
        result = ClusterSampler(cfg).sample(_population())
        assert result.selected_row_ids == GOLDEN_CLUSTER[seed]


class TestGoldenStratified:
    """StratifiedSampler – size=15, je Country, für beide StratifyMode-Werte."""

    @pytest.mark.parametrize("seed", SEEDS)
    def test_golden_stratified_proportional(self, seed: int) -> None:
        cfg = SampleConfig(
            method=SamplingMethod.STRATIFIED,
            size=15,
            seed=seed,
            stratum_field="Country",
            stratify_mode=StratifyMode.PROPORTIONAL,
        )
        result = StratifiedSampler(cfg).sample(_population())
        assert result.selected_row_ids == GOLDEN_STRATIFIED_PROPORTIONAL[seed]

    @pytest.mark.parametrize("seed", SEEDS)
    def test_golden_stratified_equal(self, seed: int) -> None:
        cfg = SampleConfig(
            method=SamplingMethod.STRATIFIED,
            size=15,
            seed=seed,
            stratum_field="Country",
            stratify_mode=StratifyMode.EQUAL,
        )
        result = StratifiedSampler(cfg).sample(_population())
        assert result.selected_row_ids == GOLDEN_STRATIFIED_EQUAL[seed]


class TestGoldenFilterOperators:
    """SimpleSampler mit jedem FilterOperator auf `Bucket` (Schwellenwert 30)."""

    @pytest.mark.parametrize("operator", list(FilterOperator))
    @pytest.mark.parametrize("seed", SEEDS)
    def test_golden_filter_operator(self, seed: int, operator: FilterOperator) -> None:
        cfg = SampleConfig(
            method=SamplingMethod.SIMPLE,
            size=5,
            seed=seed,
            filter_field="Bucket",
            filter_value=30,
            filter_operator=operator,
        )
        result = SimpleSampler(cfg).sample(_population())
        assert result.selected_row_ids == GOLDEN_FILTER[operator][seed]


class TestGoldenSupplement:
    """Nachstichprobe (Sprint 36): Ziehung aus Population MINUS bereits gezogener IDs.

    Der Controller baut den Ausschluss-Pool und zieht immer über den
    klassischen `sample()`-Pfad (siehe `_build_supplement_iterator`) – hier
    auf Core-Ebene nachgebildet: row_ids 1..10 gelten als bereits gezogen.
    """

    @pytest.mark.parametrize("seed", SEEDS)
    def test_golden_supplement(self, seed: int) -> None:
        already_drawn = frozenset(range(1, 11))
        remaining = tuple(r for r in _population() if r.row_id not in already_drawn)
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=10, seed=seed)
        result = SimpleSampler(cfg).sample(remaining)
        assert result.selected_row_ids == GOLDEN_SUPPLEMENT[seed]
