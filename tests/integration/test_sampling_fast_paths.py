"""Sprint 98: Schnellpfade der Ziehung und der Dialog-Zählungen – bit-identisch zu heute.

Kern (`TestFastPathEquivalenceOracle`): `sampling_paths.draw_sample` liefert für
jede Kombination aus Methode, Filtern (alle Operatoren), Einschränken/Ergänzen
und Seed dasselbe `SampleResult` wie der Pfad von vor Sprint 98 – oder dieselbe
`SamplingError`-Meldung. Die Referenz ist eine eingefrorene Kopie der
Controller-Logik von `bbb2d57` (`_draw_sample_result`, `_PoolCounter`,
`_count_filter_matches`, `_count_groups`).

Die Daten mischen alle Typen, an denen Gleichheit und Decode kippen könnten:
`1`/`1.0`/`True`, `"1"`, `None`, fehlender Schlüssel, datetime, u64 > 2^63
(darunter zwei Werte, die gerundet zusammenfallen).
"""

from __future__ import annotations

import itertools
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any

import pytest

from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    Engagement,
    FilterCondition,
    FilterOperator,
    SampleConfig,
    SampleResult,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.core.sampling import (
    ClusterSampler,
    SamplingError,
    SimpleSampler,
    StratifiedSampler,
    create_sampler,
    matches_all,
    matches_filter,
)
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import DatasetRepo, EngagementRepo
from sampling_tool.ui.controllers.sampling_paths import (
    count_filter_matches,
    count_groups,
    draw_sample,
    field_value_stats,
    hits_from_counts,
)
from sampling_tool.ui.dialogs.sampling_dialog import SamplingDialogResult

pytestmark = pytest.mark.integration

_EQ, _NE = FilterOperator.EQ, FilterOperator.NE
_GT, _GTE = FilterOperator.GT, FilterOperator.GTE
_LT, _LTE = FilterOperator.LT, FilterOperator.LTE

_U64_A = 2**63 + 1
_U64_B = 2**63 + 2  # rundet als REAL auf denselben Wert wie _U64_A
_U64_MAX = 2**64 - 1
_QUOTE_COLUMN = 'Kon"to'
_MISSING = object()

_COLUMNS = ("a", "f", "s", "dt", "u", "mix", "grp", _QUOTE_COLUMN)
_N_ROWS = 80
_SEEDS = (0, 1, 7, 4711, 2_147_483_647)
_PARENT_IDS = tuple(range(3, _N_ROWS + 1, 4))


# JSON-Text, an dem ein Neu-Rendern durch SQLite auffiele: Escapes, Steuerzeichen,
# Exponent-Schreibweise, negative Null.
_STRINGS = ("Alpha", "beta", "Gamma", "", "ß", "beta", 'a"b\\c\nd\t\u0001 €', "😀/\\u00e9")
_SPECIAL_FLOATS = (1e-7, 1e22, -0.0, 12345678.9)


def _rows() -> list[DatasetRow]:
    mix_cycle: list[Any] = [1, 1.0, True, "1", 2, None, _MISSING, _U64_A, _U64_B, 0, False, "x"]
    grp_cycle: list[Any] = [1, 1.0, True, "A", "b", None, _MISSING, _U64_A, _U64_B, 3, "A"]
    rows = []
    for i in range(1, _N_ROWS + 1):
        values: dict[str, Any] = {
            "a": (i * 7) % 5 if i % 11 else None,
            "f": round((i * 13 % 17) / 4, 2) if i % 10 else _SPECIAL_FLOATS[i // 10 % 4],
            "s": _STRINGS[i % len(_STRINGS)],
            "dt": datetime(2026, 1, 1 + i % 28, i % 24) if i % 9 else None,
            "u": [_U64_A, _U64_B, _U64_MAX, 5, _U64_A, -3][i % 6],
            _QUOTE_COLUMN: f"K{i % 4}",
        }
        if i % 13 == 0:
            del values["a"]
        mix = mix_cycle[i % len(mix_cycle)]
        if mix is not _MISSING:
            values["mix"] = mix
        grp = grp_cycle[i % len(grp_cycle)]
        if grp is not _MISSING:
            values["grp"] = grp
        rows.append(DatasetRow(row_id=i, values=values))
    return rows


_CONDITIONS: tuple[FilterCondition, ...] = (
    FilterCondition("a", _EQ, 2),
    FilterCondition("a", _NE, 3),
    FilterCondition("a", _GT, 1),
    FilterCondition("a", _GTE, 2),
    FilterCondition("a", _LT, 3),
    FilterCondition("a", _LTE, 2),
    FilterCondition("mix", _EQ, 1),
    FilterCondition("mix", _NE, "1"),
    FilterCondition("mix", _GT, 0),
    FilterCondition("mix", _EQ, _U64_A),
    FilterCondition("f", _GT, 1.5),
    FilterCondition("f", _LTE, 2.5),
    FilterCondition("s", _EQ, "beta"),
    FilterCondition("s", _GTE, "B"),
    FilterCondition("s", _NE, ""),
    FilterCondition("dt", _GT, datetime(2026, 1, 10)),
    FilterCondition("dt", _LT, datetime(2026, 1, 20, 12)),
    FilterCondition("u", _EQ, _U64_B),
    FilterCondition("u", _GT, 2**63),
    FilterCondition("u", _LT, 10),
    FilterCondition("grp", _NE, None),
    FilterCondition("s", _EQ, "trifft nichts"),
)


def _filter_combos() -> list[tuple[FilterCondition, ...]]:
    n = len(_CONDITIONS)
    singles = [(c,) for c in _CONDITIONS]
    pairs = [(_CONDITIONS[i], _CONDITIONS[(i * 5 + 3) % n]) for i in range(0, n, 2)]
    triples = [
        (_CONDITIONS[i], _CONDITIONS[(i + 7) % n], _CONDITIONS[(i * 3 + 11) % n])
        for i in range(0, n, 3)
    ]
    return [(), *singles, *pairs, *triples]


_METHOD_CONFIGS: dict[str, dict[str, Any]] = {
    "simple": {"method": SamplingMethod.SIMPLE, "size": 5},
    "cluster": {"method": SamplingMethod.CLUSTER, "size": 3, "cluster_field": "grp"},
    "stratified_prop": {
        "method": SamplingMethod.STRATIFIED,
        "size": 8,
        "stratum_field": "grp",
        "stratify_mode": StratifyMode.PROPORTIONAL,
    },
    "stratified_equal": {
        "method": SamplingMethod.STRATIFIED,
        "size": 8,
        "stratum_field": "grp",
        "stratify_mode": StratifyMode.EQUAL,
    },
}


@pytest.fixture
def dataset(db: Database) -> Dataset:
    eng = EngagementRepo(db.connect()).get_or_create(
        Engagement(auditor_name="A", client_name="C", auditor_position="S", audit_type="ISAE 3402")
    )
    stored = DatasetRepo(db.connect()).create(
        Dataset(name="t", columns=_COLUMNS, engagement_id=eng.id), tuple(_rows())
    )
    assert stored.id is not None
    return stored


# ---------------------------------------------------------------------------
# Eingefrorene Referenz (Controller-Logik auf bbb2d57)
# ---------------------------------------------------------------------------


class _RefPoolCounter:
    def __init__(self, config: SampleConfig) -> None:
        self._config = config
        self.count = 0

    def wrap(self, rows: Iterable[DatasetRow]) -> Iterator[DatasetRow]:
        filters = self._config.filters
        for row in rows:
            if matches_all(row, filters):
                self.count += 1
            yield row


def _reference_draw(
    repo: DatasetRepo,
    dataset: Dataset,
    result: SamplingDialogResult,
    parent_ids: tuple[int, ...] | None,
) -> SampleResult:
    assert dataset.id is not None
    sampler = create_sampler(result.config)
    unfiltered_full_population = (
        not result.config.has_filter
        and not result.from_sample_only
        and not result.exclude_sample_ids
    )
    if isinstance(sampler, SimpleSampler) and unfiltered_full_population:
        return sampler.sample_ids(repo.iter_row_ids(dataset.id), population_size=dataset.row_count)
    if (
        isinstance(sampler, ClusterSampler)
        and unfiltered_full_population
        and result.config.cluster_field is not None
        and DatasetRepo.supports_field_pairs(result.config.cluster_field)
    ):
        return sampler.sample_pairs(
            repo.iter_row_field_pairs(dataset.id, result.config.cluster_field),
            population_size=dataset.row_count,
        )
    if (
        isinstance(sampler, StratifiedSampler)
        and unfiltered_full_population
        and result.config.stratum_field is not None
        and DatasetRepo.supports_field_pairs(result.config.stratum_field)
    ):
        return sampler.sample_pairs(
            repo.iter_row_field_pairs(dataset.id, result.config.stratum_field),
            population_size=dataset.row_count,
        )
    effective_rows: Iterable[DatasetRow]
    if result.exclude_sample_ids and parent_ids is not None:
        exclude_set = frozenset(parent_ids)
        effective_rows = (r for r in repo.iter_rows(dataset.id) if r.row_id not in exclude_set)
        population_size = dataset.row_count - len(exclude_set)
    elif result.from_sample_only and parent_ids is not None:
        effective_rows = repo.get_rows_by_ids(dataset.id, list(parent_ids))
        population_size = len(parent_ids)
    else:
        effective_rows = repo.iter_rows(dataset.id)
        population_size = dataset.row_count
    pool = _RefPoolCounter(result.config)
    drawn = sampler.sample(pool.wrap(effective_rows), population_size=population_size)
    return replace(drawn, population_size=pool.count)


def _reference_count_filter_matches(
    repo: DatasetRepo,
    dataset_id: int,
    filters: Sequence[FilterCondition],
    restrict_to_ids: Sequence[int] | None,
) -> int:
    if restrict_to_ids is not None:
        rows = repo.get_rows_by_ids(dataset_id, restrict_to_ids)
        return sum(1 for r in rows if matches_all(r, filters))
    if len(filters) == 1 and DatasetRepo.supports_field_pairs(filters[0].field):
        (only,) = filters
        pairs = repo.iter_row_field_pairs(dataset_id, only.field)
        return sum(1 for _, v in pairs if matches_filter(v, only.operator, only.value))
    return sum(1 for r in repo.iter_rows(dataset_id) if matches_all(r, filters))


def _reference_count_groups(repo: DatasetRepo, dataset_id: int, column: str) -> int:
    if DatasetRepo.supports_field_pairs(column):
        return len({value for _, value in repo.iter_row_field_pairs(dataset_id, column)})
    return len({row.get(column) for row in repo.iter_rows(dataset_id)})


def _outcome(draw: Any, *args: Any) -> tuple[str, Any]:
    try:
        result = draw(*args)
    except SamplingError as exc:
        return ("error", str(exc))
    return (
        "ok",
        (result.selected_row_ids, result.population_size, result.config, result.algorithm_version),
    )


class _IterRowsSpy:
    """Zählt Aufrufe von `iter_rows` an einem Repo-Exemplar."""

    def __init__(self, repo: DatasetRepo) -> None:
        self.calls = 0
        original = repo.iter_rows

        def spy(dataset_id: int) -> Iterator[DatasetRow]:
            self.calls += 1
            return original(dataset_id)

        repo.iter_rows = spy  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# Ziehung
# ---------------------------------------------------------------------------


class TestFastPathEquivalenceOracle:
    @pytest.mark.parametrize("method", list(_METHOD_CONFIGS))
    @pytest.mark.parametrize("mode", ["full", "supplement", "restrict"])
    def test_draw_identical_to_classic(
        self, db: Database, dataset: Dataset, method: str, mode: str
    ) -> None:
        repo = DatasetRepo(db.connect())
        spy = _IterRowsSpy(repo)
        outcomes: Counter[str] = Counter()
        for filters in _filter_combos():
            for seed in _SEEDS:
                config = SampleConfig(seed=seed, filters=filters, **_METHOD_CONFIGS[method])
                request = SamplingDialogResult(
                    config=config,
                    from_sample_only=mode == "restrict",
                    exclude_sample_ids=mode == "supplement",
                )
                expected = _outcome(_reference_draw, repo, dataset, request, _PARENT_IDS)
                calls_before = spy.calls
                got = _outcome(draw_sample, repo, dataset, request, _PARENT_IDS)
                assert got == expected, (method, mode, filters, seed)
                if mode != "restrict":
                    # Alle Spalten hier sind Pairs-fähig → nie der volle Zeilen-Decode.
                    assert spy.calls == calls_before, (method, mode, filters, seed)
                outcomes[got[0]] += 1
        # Beide Ausgänge kommen vor – sonst prüfte das Oracle nur eine Hälfte.
        assert outcomes["ok"] > 0
        assert outcomes["error"] > 0

    @pytest.mark.parametrize("method", list(_METHOD_CONFIGS))
    def test_flags_without_active_sample(self, db: Database, dataset: Dataset, method: str) -> None:
        """Einschränken/Ergänzen ohne aktive Stichprobe ziehen aus dem ganzen Datensatz."""
        repo = DatasetRepo(db.connect())
        for filters, seed, restrict in itertools.product(
            _filter_combos()[:8], _SEEDS, (False, True)
        ):
            request = SamplingDialogResult(
                config=SampleConfig(seed=seed, filters=filters, **_METHOD_CONFIGS[method]),
                from_sample_only=restrict,
                exclude_sample_ids=not restrict,
            )
            expected = _outcome(_reference_draw, repo, dataset, request, None)
            assert _outcome(draw_sample, repo, dataset, request, None) == expected

    def test_error_messages_identical(self, db: Database, dataset: Dataset) -> None:
        repo = DatasetRepo(db.connect())
        nothing = (FilterCondition("s", _EQ, "gibt es nicht"),)
        cases = [
            SampleConfig(method=SamplingMethod.SIMPLE, size=1, seed=1, filters=nothing),
            SampleConfig(
                method=SamplingMethod.SIMPLE,
                size=_N_ROWS,
                seed=1,
                filters=(FilterCondition("s", _EQ, "beta"),),
            ),
            SampleConfig(
                method=SamplingMethod.CLUSTER,
                size=50,
                seed=1,
                cluster_field="grp",
                filters=(FilterCondition("a", _GT, 0),),
            ),
            SampleConfig(
                method=SamplingMethod.STRATIFIED,
                size=1,
                seed=1,
                stratum_field="grp",
                filters=(FilterCondition("a", _GT, 0),),
            ),
        ]
        messages = []
        for config in cases:
            request = SamplingDialogResult(config=config)
            expected = _outcome(_reference_draw, repo, dataset, request, None)
            got = _outcome(draw_sample, repo, dataset, request, None)
            assert got == expected
            assert got[0] == "error"
            messages.append(got[1])
        assert messages[0] == "Nach Anwendung des Filters sind keine Datensätze mehr verfügbar."
        assert messages[1].startswith(f"Stichprobengröße ({_N_ROWS}) ist größer")


def test_quote_in_column_name_uses_classic_path(db: Database, dataset: Dataset) -> None:
    repo = DatasetRepo(db.connect())
    spy = _IterRowsSpy(repo)
    multi_calls: list[Sequence[str]] = []
    original_multi = repo.iter_row_multi_field_values

    def multi_spy(dataset_id: int, columns: Sequence[str]) -> Any:
        multi_calls.append(columns)
        return original_multi(dataset_id, columns)

    repo.iter_row_multi_field_values = multi_spy  # type: ignore[method-assign]
    for config in (
        SampleConfig(
            method=SamplingMethod.SIMPLE,
            size=3,
            seed=5,
            filters=(FilterCondition(_QUOTE_COLUMN, _EQ, "K1"),),
        ),
        SampleConfig(
            method=SamplingMethod.CLUSTER,
            size=1,
            seed=5,
            cluster_field=_QUOTE_COLUMN,
            filters=(FilterCondition("a", _GT, 0),),
        ),
    ):
        request = SamplingDialogResult(config=config)
        before = spy.calls
        got = _outcome(draw_sample, repo, dataset, request, None)
        assert spy.calls == before + 1, "klassischer Pfad über iter_rows"
        assert got == _outcome(_reference_draw, repo, dataset, request, None)
        assert got[0] == "ok"
    assert multi_calls == []


# ---------------------------------------------------------------------------
# Neue Repo-Methoden
# ---------------------------------------------------------------------------


def _typed(value: Any) -> tuple[str, str]:
    """Typ-strenger Schlüssel: `1`, `1.0` und `True` bleiben verschieden."""
    return (type(value).__name__, repr(value))


class TestRepoNewMethods:
    def test_multi_field_values_match_dataset_row_get(self, db: Database, dataset: Dataset) -> None:
        assert dataset.id is not None
        repo = DatasetRepo(db.connect())
        rows = list(repo.iter_rows(dataset.id))
        supported = [c for c in _COLUMNS if DatasetRepo.supports_field_pairs(c)]
        for columns in (supported, ["u"], ["mix", "u", "mix"], [], ["fehlt", "a"]):
            got = list(repo.iter_row_multi_field_values(dataset.id, columns))
            expected = [(r.row_id, tuple(r.get(c) for c in columns)) for r in rows]
            assert got == expected, columns
            assert [[_typed(v) for v in values] for _, values in got] == [
                [_typed(v) for v in values] for _, values in expected
            ], columns

    def test_multi_field_values_reject_quote_column(self, db: Database, dataset: Dataset) -> None:
        assert dataset.id is not None
        with pytest.raises(ValueError, match="supports_field_pairs"):
            list(DatasetRepo(db.connect()).iter_row_multi_field_values(dataset.id, ["a", 'x"y']))

    @pytest.mark.parametrize("column", ["a", "f", "s", "dt", "u", "mix", "grp", "fehlt"])
    def test_value_counts_match_counter(self, db: Database, dataset: Dataset, column: str) -> None:
        assert dataset.id is not None
        repo = DatasetRepo(db.connect())
        counts = repo.value_counts(dataset.id, column)
        decoded = [r.get(column) for r in repo.iter_rows(dataset.id)]
        plain: Counter[Any] = Counter()
        for value, n in counts:
            plain[value] += n
        assert plain == Counter(decoded)
        # Typ-streng: 1, 1.0, True und -0.0/0.0 bleiben getrennt.
        expected = Counter(_typed(v) for v in decoded)
        got: Counter[tuple[str, str]] = Counter()
        for value, n in counts:
            got[_typed(value)] += n
        assert got == expected
        # Ein `None`-Eintrag (fehlender Key und JSON-null zusammen), keine Null-Zähler.
        assert sum(1 for value, _ in counts if value is None) <= 1
        assert all(n > 0 for _, n in counts)
        # Reihenfolge = erstes Vorkommen.
        first_seen: list[tuple[str, str]] = []
        for value in decoded:
            if _typed(value) not in first_seen:
                first_seen.append(_typed(value))
        assert [_typed(v) for v, _ in counts] == first_seen

    def test_value_counts_u64_exact(self, db: Database, dataset: Dataset) -> None:
        assert dataset.id is not None
        counts = dict(DatasetRepo(db.connect()).value_counts(dataset.id, "u"))
        rows = list(DatasetRepo(db.connect()).iter_rows(dataset.id))
        for value in (_U64_A, _U64_B, _U64_MAX):
            assert counts[value] == sum(1 for r in rows if r.get("u") == value)

    def test_value_counts_reject_quote_column(self, db: Database, dataset: Dataset) -> None:
        assert dataset.id is not None
        with pytest.raises(ValueError, match="supports_field_pairs"):
            DatasetRepo(db.connect()).value_counts(dataset.id, _QUOTE_COLUMN)


# ---------------------------------------------------------------------------
# Zählungen
# ---------------------------------------------------------------------------


class TestCountsEquivalence:
    def test_filter_counts_identical(self, db: Database, dataset: Dataset) -> None:
        assert dataset.id is not None
        repo = DatasetRepo(db.connect())
        combos = [c for c in _filter_combos() if c]
        combos.append((FilterCondition(_QUOTE_COLUMN, _EQ, "K2"),))
        combos.append((FilterCondition(_QUOTE_COLUMN, _NE, "K2"), FilterCondition("a", _GT, 1)))
        for filters in combos:
            for restrict in (None, list(_PARENT_IDS)):
                expected = _reference_count_filter_matches(repo, dataset.id, filters, restrict)
                assert count_filter_matches(repo, dataset.id, filters, restrict) == expected, (
                    filters,
                    restrict,
                )

    def test_single_filter_counts_from_field_stats(self, db: Database, dataset: Dataset) -> None:
        assert dataset.id is not None
        repo = DatasetRepo(db.connect())
        for condition in _CONDITIONS:
            stats = field_value_stats(repo, dataset.id, condition.field)
            assert stats.counts is not None
            expected = _reference_count_filter_matches(repo, dataset.id, (condition,), None)
            assert hits_from_counts(stats.counts, condition) == expected, condition

    @pytest.mark.parametrize("column", [*_COLUMNS, "fehlt"])
    def test_value_list_identical_to_distinct_values(
        self, db: Database, dataset: Dataset, column: str
    ) -> None:
        assert dataset.id is not None
        repo = DatasetRepo(db.connect())
        stats = field_value_stats(repo, dataset.id, column)
        expected = repo.distinct_values(dataset.id, column)
        assert list(stats.values) == expected
        assert [_typed(v) for v in stats.values] == [_typed(v) for v in expected]
        assert (stats.counts is None) == (column == _QUOTE_COLUMN)

    def test_value_list_single_scan_without_u64(self, db: Database, dataset: Dataset) -> None:
        """Ohne u64 und ohne repr-Kollision braucht die Werteliste keinen zweiten Scan."""
        assert dataset.id is not None
        repo = DatasetRepo(db.connect())
        calls: list[str] = []
        original = repo.distinct_values

        def spy(dataset_id: int, column: str) -> list[Any]:
            calls.append(column)
            return original(dataset_id, column)

        repo.distinct_values = spy  # type: ignore[method-assign]
        for column in ("a", "s", "dt", "fehlt"):
            field_value_stats(repo, dataset.id, column)
        # u64 ("u") und -0.0 ("f") lesen die Liste über distinct_values nach.
        field_value_stats(repo, dataset.id, "u")
        field_value_stats(repo, dataset.id, "f")
        assert calls == ["u", "f"]

    @pytest.mark.parametrize("column", [*_COLUMNS, "fehlt"])
    def test_group_count_identical(self, db: Database, dataset: Dataset, column: str) -> None:
        assert dataset.id is not None
        repo = DatasetRepo(db.connect())
        expected = _reference_count_groups(repo, dataset.id, column)
        assert count_groups(repo, dataset.id, column) == expected

    def test_group_count_merges_one_float_true_like_sampler(
        self, db: Database, dataset: Dataset
    ) -> None:
        """Oracle mit genau den kritischen Werten: SQL trennt sie, das `set` fasst zusammen."""
        assert dataset.id is not None
        repo = DatasetRepo(db.connect())
        separate = {_typed(v) for v, _ in repo.value_counts(dataset.id, "grp")}
        assert {("int", "1"), ("float", "1.0"), ("bool", "True")} <= separate
        assert {("int", repr(_U64_A)), ("int", repr(_U64_B))} <= separate
        # {1/1.0/True, "A", "b", None, u64_a, u64_b, 3} = 7 Gruppen wie im Sampler.
        assert count_groups(repo, dataset.id, "grp") == 7
        assert _reference_count_groups(repo, dataset.id, "grp") == 7
