"""Unit-Tests für die Sampling-Algorithmen.

Pflichten dieser Suite:
- Reproduzierbarkeit (gleicher Seed → gleicher Output) bit-genau verifizieren
- Keine Duplikate in der Auswahl
- Filter wirken vor der Ziehung
- Klare Fehler bei Fehlkonfiguration
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from sampling_tool.core import (
    BaseSampler,
    ClusterSampler,
    DatasetRow,
    SampleConfig,
    SamplingError,
    SamplingMethod,
    SimpleSampler,
    StratifiedSampler,
    StratifyMode,
    create_sampler,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

COUNTRIES = ("AUT", "GER", "FRA")


@pytest.fixture
def rows_100() -> tuple[DatasetRow, ...]:
    """100 deterministisch erzeugte Zeilen mit Spalten Column1/2/3 + Country.

    - row_id 1..100
    - Country zyklisch AUT/GER/FRA → drei Cluster (34/33/33)
    - Column1/2/3 enthalten reproduzierbar abgeleitete Werte
    """
    return tuple(
        DatasetRow(
            row_id=i,
            values={
                "Column1": f"A{i:03d}",
                "Column2": i * 10,
                "Column3": i % 7,
                "Country": COUNTRIES[(i - 1) % len(COUNTRIES)],
            },
        )
        for i in range(1, 101)
    )


# Sprint 11.1: Sampler arbeiten direkt auf rows-Tuples – die alte
# `dataset_100`-Fixture wurde entfernt.


# ---------------------------------------------------------------------------
# SimpleSampler
# ---------------------------------------------------------------------------


class TestSimpleSampler:
    def test_returns_correct_size(self, rows_100: tuple[DatasetRow, ...]) -> None:
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=25, seed=42)
        result = SimpleSampler(cfg).sample(rows_100)

        assert result.actual_size == 25
        assert result.population_size == 100

    def test_reproducible_with_same_seed(self, rows_100: tuple[DatasetRow, ...]) -> None:
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=30, seed=12345)

        first = SimpleSampler(cfg).sample(rows_100).selected_row_ids
        second = SimpleSampler(cfg).sample(rows_100).selected_row_ids

        assert first == second  # bit-genau identisch

    def test_different_seed_yields_different_result(self, rows_100: tuple[DatasetRow, ...]) -> None:
        cfg_a = SampleConfig(method=SamplingMethod.SIMPLE, size=30, seed=1)
        cfg_b = SampleConfig(method=SamplingMethod.SIMPLE, size=30, seed=2)

        a = SimpleSampler(cfg_a).sample(rows_100).selected_row_ids
        b = SimpleSampler(cfg_b).sample(rows_100).selected_row_ids

        assert a != b

    def test_no_duplicates(self, rows_100: tuple[DatasetRow, ...]) -> None:
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=50, seed=7)
        ids = SimpleSampler(cfg).sample(rows_100).selected_row_ids

        assert len(set(ids)) == len(ids)

    def test_oversample_raises(self, rows_100: tuple[DatasetRow, ...]) -> None:
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=101, seed=42)
        with pytest.raises(SamplingError, match="größer als die verfügbare Population"):
            SimpleSampler(cfg).sample(rows_100)

    def test_filter_reduces_pool(self, rows_100: tuple[DatasetRow, ...]) -> None:
        # Country=AUT trifft jede dritte Zeile (1, 4, 7, …) → ca. 34 Stück.
        cfg = SampleConfig(
            method=SamplingMethod.SIMPLE,
            size=10,
            seed=42,
            filter_field="Country",
            filter_value="AUT",
        )
        result = SimpleSampler(cfg).sample(rows_100)
        ids = set(result.selected_row_ids)

        austria_ids = {r.row_id for r in rows_100 if r.get("Country") == "AUT"}
        assert ids.issubset(austria_ids)
        assert len(ids) == 10

    def test_invalid_size_raises(self) -> None:
        with pytest.raises(SamplingError, match="Stichprobengröße muss"):
            SimpleSampler(SampleConfig(method=SamplingMethod.SIMPLE, size=0, seed=1))


class TestSimpleSamplerIdsPath:
    """Sprint 12.1 / P-002: Spezialpfad `sample_ids` ohne DatasetRow-Materialize."""

    def test_reproducibility_matches_classic_path_unfiltered(
        self, rows_100: tuple[DatasetRow, ...]
    ) -> None:
        """`sample_ids(ids)` muss bit-genau dasselbe Ergebnis wie `sample(rows)`
        liefern – sonst wäre die ISAE-3402-Reproduzierbarkeit verletzt."""
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=30, seed=12345)
        sampler = SimpleSampler(cfg)

        classic = sampler.sample(rows_100).selected_row_ids
        ids_path = sampler.sample_ids(
            (r.row_id for r in rows_100), population_size=len(rows_100)
        ).selected_row_ids

        assert classic == ids_path

    @pytest.mark.parametrize("seed", [0, 1, 42, 12345, 2**31 - 1])
    def test_reproducibility_across_seeds(
        self, rows_100: tuple[DatasetRow, ...], seed: int
    ) -> None:
        """Bit-Gleichheit über repräsentative Seed-Werte (Edge-Cases inkl. 0)."""
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=25, seed=seed)
        sampler = SimpleSampler(cfg)

        classic = sampler.sample(rows_100).selected_row_ids
        ids_path = sampler.sample_ids(
            [r.row_id for r in rows_100], population_size=len(rows_100)
        ).selected_row_ids

        assert classic == ids_path

    def test_population_size_is_used_verbatim(self, rows_100: tuple[DatasetRow, ...]) -> None:
        """`population_size` wird 1:1 ins Result übernommen (Sub-Sampling-Dokumentation)."""
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=10, seed=7)
        result = SimpleSampler(cfg).sample_ids(
            [r.row_id for r in rows_100], population_size=999_999
        )
        assert result.population_size == 999_999

    def test_filter_field_set_rejects_ids_path(self, rows_100: tuple[DatasetRow, ...]) -> None:
        """Mit Filter ist `sample_ids` nicht erlaubt – Caller muss `sample(rows)` nehmen."""
        cfg = SampleConfig(
            method=SamplingMethod.SIMPLE,
            size=10,
            seed=42,
            filter_field="Country",
            filter_value="AUT",
        )
        with pytest.raises(SamplingError, match="sample_ids ist nur für ungefiltertes"):
            SimpleSampler(cfg).sample_ids([r.row_id for r in rows_100], population_size=100)

    def test_oversample_raises(self, rows_100: tuple[DatasetRow, ...]) -> None:
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=101, seed=42)
        with pytest.raises(SamplingError, match="größer als die verfügbare Population"):
            SimpleSampler(cfg).sample_ids(
                [r.row_id for r in rows_100], population_size=len(rows_100)
            )

    def test_empty_pool_raises(self) -> None:
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=1, seed=42)
        with pytest.raises(SamplingError, match="keine Datensätze"):
            SimpleSampler(cfg).sample_ids([], population_size=0)

    def test_accepts_generator_input(self, rows_100: tuple[DatasetRow, ...]) -> None:
        """Iterator-Konsum (einmal-konsumierbar) ist die Production-Form
        (`DatasetRepo.iter_row_ids` ist ein Generator)."""

        def _gen() -> Iterator[int]:
            for r in rows_100:
                yield r.row_id

        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=15, seed=99)
        result = SimpleSampler(cfg).sample_ids(_gen(), population_size=len(rows_100))
        assert result.actual_size == 15
        assert len(set(result.selected_row_ids)) == 15


# ---------------------------------------------------------------------------
# ClusterSampler
# ---------------------------------------------------------------------------


class TestClusterSampler:
    def test_returns_full_clusters(self, rows_100: tuple[DatasetRow, ...]) -> None:
        # 2 von 3 Clustern → es müssen ALLE Zeilen dieser zwei Cluster gezogen werden
        cfg = SampleConfig(
            method=SamplingMethod.CLUSTER,
            size=2,
            seed=42,
            cluster_field="Country",
        )
        result = ClusterSampler(cfg).sample(rows_100)
        countries_drawn = {
            r.get("Country") for r in rows_100 if r.row_id in set(result.selected_row_ids)
        }

        assert len(countries_drawn) == 2

        # Für jedes gezogene Land müssen ALLE seine Zeilen drin sein
        for country in countries_drawn:
            country_ids = {r.row_id for r in rows_100 if r.get("Country") == country}
            assert country_ids.issubset(set(result.selected_row_ids))

    def test_reproducible(self, rows_100: tuple[DatasetRow, ...]) -> None:
        cfg = SampleConfig(method=SamplingMethod.CLUSTER, size=2, seed=99, cluster_field="Country")
        a = ClusterSampler(cfg).sample(rows_100).selected_row_ids
        b = ClusterSampler(cfg).sample(rows_100).selected_row_ids
        assert a == b

    def test_too_many_clusters_raises(self, rows_100: tuple[DatasetRow, ...]) -> None:
        cfg = SampleConfig(method=SamplingMethod.CLUSTER, size=4, seed=1, cluster_field="Country")
        with pytest.raises(SamplingError, match="nur 3 sind im Datensatz"):
            ClusterSampler(cfg).sample(rows_100)

    def test_missing_cluster_field_raises(self) -> None:
        cfg = SampleConfig(method=SamplingMethod.CLUSTER, size=1, seed=1)
        with pytest.raises(SamplingError, match="Cluster-Feldes"):
            ClusterSampler(cfg)

    def test_different_seed_changes_clusters(self, rows_100: tuple[DatasetRow, ...]) -> None:
        cfg_a = SampleConfig(method=SamplingMethod.CLUSTER, size=1, seed=1, cluster_field="Country")
        cfg_b = SampleConfig(method=SamplingMethod.CLUSTER, size=1, seed=2, cluster_field="Country")

        results = {
            tuple(ClusterSampler(c).sample(rows_100).selected_row_ids) for c in (cfg_a, cfg_b)
        }
        # Mindestens ein anderer Cluster bei anderen Seeds erwartet
        assert len(results) >= 1  # immer wahr; Strenge folgt:
        a = ClusterSampler(cfg_a).sample(rows_100).selected_row_ids
        b = ClusterSampler(cfg_b).sample(rows_100).selected_row_ids
        # 1 von 3 Clustern – mit den Seeds 1 und 2 unterschiedlich (manuell verifiziert)
        assert a != b


# ---------------------------------------------------------------------------
# StratifiedSampler
# ---------------------------------------------------------------------------


class TestStratifiedSampler:
    def test_proportional_distribution(self, rows_100: tuple[DatasetRow, ...]) -> None:
        # Country: AUT 34, GER 33, FRA 33  → bei size=30 etwa 10/10/10
        cfg = SampleConfig(
            method=SamplingMethod.STRATIFIED,
            size=30,
            seed=42,
            stratum_field="Country",
            stratify_mode=StratifyMode.PROPORTIONAL,
        )
        result = StratifiedSampler(cfg).sample(rows_100)

        per_country: dict[str, int] = {c: 0 for c in COUNTRIES}
        for r in rows_100:
            if r.row_id in set(result.selected_row_ids):
                per_country[r.get("Country")] += 1

        assert sum(per_country.values()) == 30
        # proportional zu (34, 33, 33) → 10/10/10 (Largest-Remainder)
        assert per_country == {"AUT": 10, "GER": 10, "FRA": 10}

    def test_equal_distribution_yields_equal_counts(self, rows_100: tuple[DatasetRow, ...]) -> None:
        cfg = SampleConfig(
            method=SamplingMethod.STRATIFIED,
            size=30,
            seed=42,
            stratum_field="Country",
            stratify_mode=StratifyMode.EQUAL,
        )
        result = StratifiedSampler(cfg).sample(rows_100)

        per_country: dict[str, int] = {c: 0 for c in COUNTRIES}
        for r in rows_100:
            if r.row_id in set(result.selected_row_ids):
                per_country[r.get("Country")] += 1

        # 30/3 = 10 sauber → 10/10/10
        assert per_country == {"AUT": 10, "GER": 10, "FRA": 10}
        assert sum(per_country.values()) == 30

    def test_equal_distribution_handles_uneven_size(self, rows_100: tuple[DatasetRow, ...]) -> None:
        # 31 / 3 = 10.33  → Largest-Remainder: 11/10/10
        cfg = SampleConfig(
            method=SamplingMethod.STRATIFIED,
            size=31,
            seed=42,
            stratum_field="Country",
            stratify_mode=StratifyMode.EQUAL,
        )
        result = StratifiedSampler(cfg).sample(rows_100)
        assert result.actual_size == 31

    def test_reproducible(self, rows_100: tuple[DatasetRow, ...]) -> None:
        cfg = SampleConfig(
            method=SamplingMethod.STRATIFIED,
            size=30,
            seed=2024,
            stratum_field="Country",
        )
        a = StratifiedSampler(cfg).sample(rows_100).selected_row_ids
        b = StratifiedSampler(cfg).sample(rows_100).selected_row_ids
        assert a == b

    def test_size_below_strata_count_raises(self, rows_100: tuple[DatasetRow, ...]) -> None:
        # 3 Schichten, size=2 → unmöglich
        cfg = SampleConfig(
            method=SamplingMethod.STRATIFIED,
            size=2,
            seed=1,
            stratum_field="Country",
        )
        with pytest.raises(SamplingError, match="kleiner als die Anzahl der Schichten"):
            StratifiedSampler(cfg).sample(rows_100)

    def test_missing_stratum_field_raises(self) -> None:
        cfg = SampleConfig(method=SamplingMethod.STRATIFIED, size=10, seed=1)
        with pytest.raises(SamplingError, match="Schicht-Feldes"):
            StratifiedSampler(cfg)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestStreamingIteratorInput:
    """Sprint 11.4: BaseSampler.sample akzeptiert einmal-konsumierbare Iteratoren."""

    def test_simple_sampler_konsumiert_generator(self, rows_100: tuple[DatasetRow, ...]) -> None:
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=10, seed=42)
        gen = (r for r in rows_100)
        result = SimpleSampler(cfg).sample(gen)
        assert result.actual_size == 10
        assert result.population_size == 100

    def test_stratified_sampler_konsumiert_generator(
        self, rows_100: tuple[DatasetRow, ...]
    ) -> None:
        cfg = SampleConfig(
            method=SamplingMethod.STRATIFIED,
            size=30,
            seed=42,
            stratum_field="Country",
        )
        gen = (r for r in rows_100)
        result = StratifiedSampler(cfg).sample(gen)
        assert result.actual_size == 30

    def test_population_size_override_dokumentiert_dataset_groesse(
        self, rows_100: tuple[DatasetRow, ...]
    ) -> None:
        """Sub-Sampling: rows ist eine Teilmenge, aber population_size
        dokumentiert die ursprüngliche Dataset-Größe."""
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=5, seed=1)
        subset = rows_100[:20]
        result = SimpleSampler(cfg).sample(subset, population_size=100)
        assert result.actual_size == 5
        assert result.population_size == 100  # override sticht

    def test_single_pass_filter_zaehlt_pre_filter_total(
        self, rows_100: tuple[DatasetRow, ...]
    ) -> None:
        """Ohne expliziten population_size wird der Pre-Filter-Count
        verwendet, nicht der Post-Filter-Count."""
        cfg = SampleConfig(
            method=SamplingMethod.SIMPLE,
            size=5,
            seed=1,
            filter_field="Country",
            filter_value="AUT",
        )
        result = SimpleSampler(cfg).sample(iter(rows_100))
        # Population = 100 (alle Rows durchgereicht), nicht 34 (Filter-Pool)
        assert result.population_size == 100


class TestCreateSampler:
    def test_simple(self) -> None:
        sampler = create_sampler(SampleConfig(method=SamplingMethod.SIMPLE, size=1, seed=1))
        assert isinstance(sampler, SimpleSampler)
        assert isinstance(sampler, BaseSampler)

    def test_cluster(self) -> None:
        sampler = create_sampler(
            SampleConfig(method=SamplingMethod.CLUSTER, size=1, seed=1, cluster_field="Country")
        )
        assert isinstance(sampler, ClusterSampler)

    def test_stratified(self) -> None:
        sampler = create_sampler(
            SampleConfig(method=SamplingMethod.STRATIFIED, size=3, seed=1, stratum_field="Country")
        )
        assert isinstance(sampler, StratifiedSampler)

    def test_factory_propagates_validation_errors(self) -> None:
        # Cluster ohne cluster_field → Subtyp-Validierung muss greifen
        with pytest.raises(SamplingError):
            create_sampler(SampleConfig(method=SamplingMethod.CLUSTER, size=1, seed=1))
