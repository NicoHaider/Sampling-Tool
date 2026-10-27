"""Zieh- und Zähllogik des Stichproben-Dialogs – Qt-frei, läuft im Worker (Sprint 98).

Bekommt ein `DatasetRepo` statt der Session, damit die Funktionen im Worker-
Thread mit einer eigenen Verbindung laufen (`ui/workers/tasks.py`). Der
Controller ermittelt alles, was die Session kennt (z. B. die Zeilen-IDs der
aktiven Stichprobe), vorher auf dem UI-Thread.

Rote Linie: jede Ziehung ist bit-identisch zum klassischen Pfad
`sample(iter_rows)` mit `PoolCounter` (Oracle:
`tests/integration/test_sampling_fast_paths.py`, Golden-Vektoren unverändert).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from itertools import islice
from typing import Any, Final, Protocol, TypeVar

from sampling_tool.core.cancellation import CancellationToken
from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    FilterCondition,
    SampleConfig,
    SampleResult,
)
from sampling_tool.core.sampling import (
    BaseSampler,
    ClusterSampler,
    SimpleSampler,
    StratifiedSampler,
    create_sampler,
    matches_all,
    matches_filter,
)
from sampling_tool.persistence.repositories import DatasetRepo

T = TypeVar("T")

#: Alle so viele Zeilen prüfen die Schleifen das Abbruch-Token.
CANCEL_CHECK_INTERVAL: Final[int] = 10_000

# JSON-Ganzzahlen außerhalb von int64 liest `json_extract` nur gerundet (u64-Fall).
_INT64_MIN: Final[int] = -(2**63)
_INT64_MAX: Final[int] = 2**63 - 1


class DrawRequest(Protocol):
    """Was eine Ziehung vom Dialog braucht (erfüllt von `SamplingDialogResult`)."""

    @property
    def config(self) -> SampleConfig: ...

    @property
    def from_sample_only(self) -> bool: ...

    @property
    def exclude_sample_ids(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class FieldValueStats:
    """Werteliste und Wertzählung einer Spalte für den Filter des Dialogs.

    `values` ist identisch zu `DatasetRepo.distinct_values`. `counts` ist
    `DatasetRepo.value_counts` – `None` für Spalten, die `supports_field_pairs`
    nicht erfüllen (dort zählt der klassische Pfad).
    """

    values: tuple[Any, ...]
    counts: tuple[tuple[Any, int], ...] | None


class PoolCounter:
    """Zählt beim Durchreichen die Zeilen, aus denen der Sampler zieht (Sprint 89 / B2).

    Dieselbe `matches_all`-Prüfung wie `BaseSampler._collect_pool`; die
    Zeilen selbst laufen unverändert und in derselben Reihenfolge durch – die
    Ziehung bleibt bit-identisch, nur die dokumentierte Population ändert sich.
    """

    def __init__(self, config: SampleConfig) -> None:
        self._config = config
        self.count = 0

    def wrap(self, rows: Iterable[DatasetRow]) -> Iterator[DatasetRow]:
        filters = self._config.filters
        for row in rows:
            if matches_all(row, filters):
                self.count += 1
            yield row


def checked(items: Iterable[T], cancellation: CancellationToken | None) -> Iterator[T]:
    """Reicht `items` durch und prüft vor je `CANCEL_CHECK_INTERVAL` Elementen das Token."""
    if cancellation is None:
        return iter(items)
    return _checked_chunks(iter(items), cancellation)


def _checked_chunks(items: Iterator[T], cancellation: CancellationToken) -> Iterator[T]:
    # Blockweise statt je Element: hält den Overhead bei 1 Mio. Zeilen klein.
    while chunk := list(islice(items, CANCEL_CHECK_INTERVAL)):
        cancellation.raise_if_cancelled()
        yield from chunk


# ---------------------------------------------------------------------------
# Zählungen
# ---------------------------------------------------------------------------


def field_value_stats(
    repo: DatasetRepo,
    dataset_id: int,
    column: str,
    cancellation: CancellationToken | None = None,
) -> FieldValueStats:
    """Werteliste (wie `distinct_values`) und Wertzählung aus EINEM Scan.

    Die Liste entsteht aus `value_counts` nach den Regeln von `distinct_values`:
    `None` auslassen, nach `repr` deduplizieren, nach `str` sortieren, bei
    Gleichstand das frühere erste Vorkommen zuerst. `distinct_values` gruppiert
    nach SQL-Rohwert und JSON-Typ, `value_counts` nach JSON-Text – das fällt
    zusammen, außer bei u64-Werten (`distinct_values` zeigt sie gerundet) und
    `-0.0` (dort mit `0.0` zusammengefasst). Nur dann, oder bei einer
    `repr`-Kollision, liest ein zweiter Scan die Liste über `distinct_values`
    selbst – in echten Daten praktisch nie.
    """
    if not DatasetRepo.supports_field_pairs(column):
        return FieldValueStats(values=tuple(repo.distinct_values(dataset_id, column)), counts=None)
    counts = tuple(repo.value_counts(dataset_id, column))
    if cancellation is not None:
        cancellation.raise_if_cancelled()
    values = _distinct_from_counts(counts)
    if values is None:
        values = tuple(repo.distinct_values(dataset_id, column))
    return FieldValueStats(values=values, counts=counts)


def _distinct_from_counts(counts: Sequence[tuple[Any, int]]) -> tuple[Any, ...] | None:
    """Werteliste nach `distinct_values`-Regeln, `None` für die zwei Sonderfälle."""
    seen: set[str] = set()
    values: list[Any] = []
    # `counts` steht in der Reihenfolge des ersten Vorkommens, die stabile
    # Sortierung nach `str` ergibt also `distinct_values`' (str, first_idx).
    for value, _count in counts:
        if value is None:
            continue
        if type(value) is int and not _INT64_MIN <= value <= _INT64_MAX:
            return None
        if type(value) is float and value == 0.0 and math.copysign(1.0, value) < 0:
            return None
        key = repr(value)
        if key in seen:
            return None
        seen.add(key)
        values.append(value)
    values.sort(key=str)
    return tuple(values)


def hits_from_counts(counts: Iterable[tuple[Any, int]], condition: FilterCondition) -> int:
    """Trefferzahl EINER Bedingung aus einer Wertzählung – `matches_filter` je Wert."""
    return sum(
        count
        for value, count in counts
        if matches_filter(value, condition.operator, condition.value)
    )


def count_filter_matches(
    repo: DatasetRepo,
    dataset_id: int,
    filters: Sequence[FilterCondition],
    restrict_to_ids: Sequence[int] | None,
    cancellation: CancellationToken | None = None,
) -> int:
    """Zählt Rows, die alle Filter erfüllen – dieselbe Prüfung wie die Ziehung.

    `restrict_to_ids` (gesetzt bei Einschränken/Ergänzen): zählt innerhalb der
    bestehenden Stichprobe (kleine Menge → `get_rows_by_ids`). Sonst: eine
    Bedingung über `value_counts` (je Wert einmal `matches_filter`, Summe der
    Anzahlen – dieselbe Zahl wie die Prüfung je Zeile, weil jede Zeile genau
    einem Eintrag angehört und dessen Wert ihr decodierter Wert ist), mehrere über `iter_row_multi_field_values` (nur die
    Filterfelder). Spalten mit `"`/`\\` im Namen → `iter_rows`.
    """
    if restrict_to_ids is not None:
        rows = repo.get_rows_by_ids(dataset_id, restrict_to_ids)
        return sum(1 for r in rows if matches_all(r, filters))
    fields = [c.field for c in filters]
    if all(DatasetRepo.supports_field_pairs(f) for f in fields):
        if len(filters) == 1:
            return hits_from_counts(repo.value_counts(dataset_id, fields[0]), filters[0])
        values_iter = checked(repo.iter_row_multi_field_values(dataset_id, fields), cancellation)
        return sum(1 for _, values in values_iter if _matches_values(values, filters))
    rows_iter = checked(repo.iter_rows(dataset_id), cancellation)
    return sum(1 for r in rows_iter if matches_all(r, filters))


def count_groups(
    repo: DatasetRepo,
    dataset_id: int,
    column: str,
    cancellation: CancellationToken | None = None,
) -> int:
    """Anzahl Cluster bzw. Schichten einer Spalte – so gezählt wie der Sampler.

    Der Sampler bildet Gruppen über `dict`-Schlüssel des Zellwerts; leere
    Zellen (auch fehlende Schlüssel) bilden eine eigene Gruppe. `value_counts`
    trennt `1`, `1.0` und `True` (gezählt wird der JSON-Text) – das `set` über
    die decodierten Werte fasst sie wie der Sampler zusammen.
    """
    if DatasetRepo.supports_field_pairs(column):
        return len({value for value, _ in repo.value_counts(dataset_id, column)})
    return len({row.get(column) for row in checked(repo.iter_rows(dataset_id), cancellation)})


def _matches_values(values: Sequence[Any], filters: Sequence[FilterCondition]) -> bool:
    """`matches_all` über vorab gelesene Feldwerte (`values[i]` gehört zu `filters[i]`)."""
    for value, condition in zip(values, filters, strict=False):
        if not matches_filter(value, condition.operator, condition.value):
            return False
    return True


# ---------------------------------------------------------------------------
# Ziehung
# ---------------------------------------------------------------------------


def draw_sample(
    repo: DatasetRepo,
    dataset: Dataset,
    request: DrawRequest,
    parent_ids: tuple[int, ...] | None,
    cancellation: CancellationToken | None = None,
) -> SampleResult:
    """Wählt den Sampler-Pfad und zieht die Stichprobe. Kann `SamplingError` werfen.

    `parent_ids` sind die Zeilen-IDs der aktiven Stichprobe dieses Datensatzes
    (`None` ohne aktive Stichprobe); Einschränken und Ergänzen wirken nur mit ihr.

    Pfade:
    - ungefiltert, ganzer Datensatz: Simple über die row_ids (Sprint 12.1 /
      P-002), Cluster/Geschichtet über (row_id, feldwert)-Pairs (Sprint 35 /
      P-003); `population_size` = `dataset.row_count`.
    - Einschränken: klassisch `sample(get_rows_by_ids(...))` (kleine Menge).
    - sonst (Filter und/oder Ergänzen, Sprint 98): sind alle beteiligten
      Spalten `supports_field_pairs`-fähig, der Schnellpfad
      `_draw_from_field_values`; sonst klassisch `sample(iter_rows)`.

    `population_size` ist außerhalb des ersten Pfads die Auswahlgrundlage – die
    Zeilen, aus denen tatsächlich gezogen wurde (Sprint 89 / B2).
    """
    assert dataset.id is not None
    config = request.config
    sampler = create_sampler(config)
    unfiltered_full_population = (
        not config.has_filter and not request.from_sample_only and not request.exclude_sample_ids
    )
    if unfiltered_full_population:
        drawn = _draw_unfiltered(repo, dataset, sampler, cancellation)
        if drawn is not None:
            return drawn

    supplement = request.exclude_sample_ids and parent_ids is not None
    if not supplement and request.from_sample_only and parent_ids is not None:
        rows = repo.get_rows_by_ids(dataset.id, list(parent_ids))
        return _draw_classic(sampler, config, rows, len(parent_ids))

    exclude = frozenset(parent_ids) if supplement and parent_ids is not None else frozenset()
    if all(DatasetRepo.supports_field_pairs(c) for c in _involved_columns(sampler, config)):
        return _draw_from_field_values(repo, dataset.id, sampler, config, exclude, cancellation)

    rows_iter: Iterable[DatasetRow] = repo.iter_rows(dataset.id)
    population_size = dataset.row_count
    if supplement:
        rows_iter = (row for row in rows_iter if row.row_id not in exclude)
        # Invariante: die aktive Stichprobe gehört zu diesem Datensatz, Zeilen
        # werden nie gelöscht → len(exclude) zählt genau die ausgeschlossenen.
        population_size = dataset.row_count - len(exclude)
    return _draw_classic(sampler, config, checked(rows_iter, cancellation), population_size)


def _draw_unfiltered(
    repo: DatasetRepo,
    dataset: Dataset,
    sampler: BaseSampler,
    cancellation: CancellationToken | None,
) -> SampleResult | None:
    """P-002/P-003 ohne Filter über den ganzen Datensatz; `None` = nicht anwendbar."""
    assert dataset.id is not None
    config = sampler.config
    if isinstance(sampler, SimpleSampler):
        return sampler.sample_ids(
            checked(repo.iter_row_ids(dataset.id), cancellation),
            population_size=dataset.row_count,
        )
    if isinstance(sampler, ClusterSampler | StratifiedSampler):
        column = (
            config.cluster_field if isinstance(sampler, ClusterSampler) else config.stratum_field
        )
        if column is not None and DatasetRepo.supports_field_pairs(column):
            return sampler.sample_pairs(
                checked(repo.iter_row_field_pairs(dataset.id, column), cancellation),
                population_size=dataset.row_count,
            )
    return None


def _draw_classic(
    sampler: BaseSampler,
    config: SampleConfig,
    rows: Iterable[DatasetRow],
    population_size: int,
) -> SampleResult:
    """Klassischer Pfad: ganze Zeilen durch `sample()`, Population = gezählter Pool."""
    pool = PoolCounter(config)
    drawn = sampler.sample(pool.wrap(rows), population_size=population_size)
    return replace(drawn, population_size=pool.count)


def _group_column(sampler: BaseSampler, config: SampleConfig) -> str | None:
    if isinstance(sampler, ClusterSampler):
        return config.cluster_field
    if isinstance(sampler, StratifiedSampler):
        return config.stratum_field
    return None


def _involved_columns(sampler: BaseSampler, config: SampleConfig) -> list[str]:
    """Filterfelder plus Cluster-/Schichtfeld – alle Spalten, die die Ziehung liest."""
    columns = [c.field for c in config.filters]
    group = _group_column(sampler, config)
    if group is not None:
        columns.append(group)
    return columns


def _draw_from_field_values(
    repo: DatasetRepo,
    dataset_id: int,
    sampler: BaseSampler,
    config: SampleConfig,
    exclude: frozenset[int],
    cancellation: CancellationToken | None,
) -> SampleResult:
    """Gefilterte Ziehung bzw. Ergänzen über nur die beteiligten Felder (Sprint 98).

    Bit-identisch zu `sample(rows)` mit `PoolCounter`, weil:
    - der Pool dieselben Zeilen enthält: `iter_row_multi_field_values`
      decodiert jeden Feldwert wie `DatasetRow.get` (Oracle), die Bedingungen
      laufen wie in `matches_all` UND-verknüpft über `matches_filter`, der
      Ausschluss der aktiven Stichprobe ist derselbe `row_id`-Test;
    - `sample()` sortiert den Pool nach `row_id`, `sample_ids`/`sample_pairs`
      ebenso – die Reihenfolge der Eingabe spielt keine Rolle;
    - der Shuffle hängt nur an der Pool-Länge (Simple liest danach nur die
      `row_id`), Cluster/Schichten bilden sich aus (row_id, feldwert) in
      row_id-Reihenfolge wie in `_select` (Pairs-Oracles aus Sprint 35);
    - die Fehlermeldungen (leerer Pool, zu große Stichprobe, zu viele
      Cluster/Schichten) stehen wortgleich und in derselben Prüfreihenfolge
      in `sample_ids`/`sample_pairs` wie in `sample()`/`_select`.
    Der Sampler bekommt die Konfiguration ohne Filter nur, weil
    `sample_ids`/`sample_pairs` gefilterte Konfigurationen ablehnen; das
    Ergebnis trägt wieder die originale Konfiguration (mit Filtern) und die
    `population_size` des Pools – wie `PoolCounter.count`.
    """
    filters = config.filters
    group = _group_column(sampler, config)
    columns = [c.field for c in filters]
    if group is not None:
        columns.append(group)
    unfiltered = create_sampler(replace(config, filters=()))

    if not columns:
        # Ergänzen ohne Filter (Simple): nur die IDs.
        ids = [
            rid
            for rid in checked(repo.iter_row_ids(dataset_id), cancellation)
            if rid not in exclude
        ]
        assert isinstance(unfiltered, SimpleSampler)
        drawn = unfiltered.sample_ids(ids, population_size=len(ids))
        return replace(drawn, config=config, population_size=len(ids))

    values_iter = checked(repo.iter_row_multi_field_values(dataset_id, columns), cancellation)
    if group is None:
        ids = [
            rid
            for rid, values in values_iter
            if rid not in exclude and _matches_values(values, filters)
        ]
        assert isinstance(unfiltered, SimpleSampler)
        drawn = unfiltered.sample_ids(ids, population_size=len(ids))
        return replace(drawn, config=config, population_size=len(ids))

    pairs = [
        (rid, values[-1])
        for rid, values in values_iter
        if rid not in exclude and _matches_values(values, filters)
    ]
    assert isinstance(unfiltered, ClusterSampler | StratifiedSampler)
    drawn = unfiltered.sample_pairs(pairs, population_size=len(pairs))
    return replace(drawn, config=config, population_size=len(pairs))
