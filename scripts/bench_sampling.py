"""Stichproben-Benchmark (Sprint 98) – Ziehung und Dialog-Zählungen, vorher/nachher.

Misst je Phase den Weg von vor Sprint 98 („vorher", eingefrorene Kopie der
Controller-Logik von ``bbb2d57``) und den Weg über ``ui/controllers/
sampling_paths.py`` („nachher") auf derselben Projektdatei. ``core/`` und die
bestehenden ``DatasetRepo``-Methoden sind unverändert, „vorher" ist also genau
der Pfad von ``main``. Je Phase prüft das Skript, dass beide Wege dasselbe
Ergebnis liefern (gleiche Zeilen-IDs, Population, Zahlen) – sonst Exit 1.

Gemessen wird mit ``time.perf_counter`` ohne ``tracemalloc`` (das bläht die
Zeiten auf, siehe PERFORMANCE.md), Median über ``--runs`` Läufe. Die
Projektdatei baut ``bench_table._build_project`` (15 gemischte Spalten wie
``perf_probe.py``, Seed fix) unter ``--work-dir`` (Default ``tmp/perf/``,
gitignored); sie wird nach dem Lauf gelöscht. Ausgabe nur auf stdout.

Aufruf:
    python scripts/bench_sampling.py                  # 1M Zeilen, 3 Läufe
    python scripts/bench_sampling.py --rows 200000 --runs 5
    python scripts/bench_sampling.py --quick          # 2000 Zeilen, 1 Lauf (Smoke)
"""

from __future__ import annotations

import argparse
import platform
import shutil
import statistics
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from _script_io import force_utf8_stdout
from bench_table import COLUMN_NAMES, _build_project, _git_short_rev

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from sampling_tool.core.models import (  # noqa: E402
    Dataset,
    DatasetRow,
    FilterCondition,
    FilterOperator,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.core.sampling import (  # noqa: E402
    ClusterSampler,
    SimpleSampler,
    StratifiedSampler,
    create_sampler,
    matches_all,
    matches_filter,
)
from sampling_tool.persistence.dataset_repo import DatasetRepo  # noqa: E402
from sampling_tool.ui.controllers.sampling_paths import (  # noqa: E402
    count_filter_matches,
    count_groups,
    draw_sample,
    field_value_stats,
    hits_from_counts,
)

_PARENT_SIZE = 500
_FILTER_WAEHRUNG = FilterCondition("waehrung", FilterOperator.EQ, "EUR")
_FILTER_STEUER = FilterCondition("steuersatz", FilterOperator.GTE, 10.0)
_TWO_FILTERS = (_FILTER_WAEHRUNG, _FILTER_STEUER)
# Wertwechsel bei einem Filter: alle Währungen nacheinander.
_WAEHRUNGEN = ("EUR", "USD", "CHF", "GBP")


@dataclass(frozen=True, slots=True)
class _Request:
    config: SampleConfig
    from_sample_only: bool = False
    exclude_sample_ids: bool = False


@dataclass
class Phase:
    label: str
    before_s: list[float] = field(default_factory=list)
    after_s: list[float] = field(default_factory=list)

    @property
    def before(self) -> float:
        return statistics.median(self.before_s)

    @property
    def after(self) -> float:
        return statistics.median(self.after_s)


# ---------------------------------------------------------------------------
# „vorher": eingefrorene Controller-Logik von bbb2d57
# ---------------------------------------------------------------------------


class _OldPoolCounter:
    def __init__(self, config: SampleConfig) -> None:
        self._config = config
        self.count = 0

    def wrap(self, rows: Iterable[DatasetRow]) -> Iterator[DatasetRow]:
        for row in rows:
            if matches_all(row, self._config.filters):
                self.count += 1
            yield row


def _old_draw(
    repo: DatasetRepo, dataset: Dataset, request: _Request, parent_ids: tuple[int, ...] | None
) -> SampleResult:
    assert dataset.id is not None
    config = request.config
    sampler = create_sampler(config)
    unfiltered = (
        not config.has_filter and not request.from_sample_only and not request.exclude_sample_ids
    )
    if isinstance(sampler, SimpleSampler) and unfiltered:
        return sampler.sample_ids(repo.iter_row_ids(dataset.id), population_size=dataset.row_count)
    if isinstance(sampler, ClusterSampler | StratifiedSampler) and unfiltered:
        column = config.cluster_field if isinstance(sampler, ClusterSampler) else None
        column = column or config.stratum_field
        if column is not None and DatasetRepo.supports_field_pairs(column):
            return sampler.sample_pairs(
                repo.iter_row_field_pairs(dataset.id, column), population_size=dataset.row_count
            )
    rows: Iterable[DatasetRow]
    if request.exclude_sample_ids and parent_ids is not None:
        exclude = frozenset(parent_ids)
        rows = (r for r in repo.iter_rows(dataset.id) if r.row_id not in exclude)
        population = dataset.row_count - len(exclude)
    elif request.from_sample_only and parent_ids is not None:
        rows = repo.get_rows_by_ids(dataset.id, list(parent_ids))
        population = len(parent_ids)
    else:
        rows = repo.iter_rows(dataset.id)
        population = dataset.row_count
    pool = _OldPoolCounter(config)
    drawn = sampler.sample(pool.wrap(rows), population_size=population)
    return replace(drawn, population_size=pool.count)


def _old_count(repo: DatasetRepo, dataset_id: int, filters: Sequence[FilterCondition]) -> int:
    if len(filters) == 1 and DatasetRepo.supports_field_pairs(filters[0].field):
        (only,) = filters
        pairs = repo.iter_row_field_pairs(dataset_id, only.field)
        return sum(1 for _, v in pairs if matches_filter(v, only.operator, only.value))
    return sum(1 for r in repo.iter_rows(dataset_id) if matches_all(r, filters))


def _old_groups(repo: DatasetRepo, dataset_id: int, column: str) -> int:
    return len({value for _, value in repo.iter_row_field_pairs(dataset_id, column)})


# ---------------------------------------------------------------------------
# Messung
# ---------------------------------------------------------------------------


def _timed(fn: Callable[[], Any]) -> tuple[float, Any]:
    start = time.perf_counter()
    result = fn()
    return time.perf_counter() - start, result


def _draw_key(result: SampleResult) -> tuple[Any, ...]:
    return (result.selected_row_ids, result.population_size, result.config)


def _phases(
    repo: DatasetRepo, dataset: Dataset, parent_ids: tuple[int, ...]
) -> list[tuple[str, Callable[[], Any], Callable[[], Any]]]:
    """(Label, vorher, nachher) – beide liefern ein vergleichbares Ergebnis."""
    assert dataset.id is not None
    ds_id = dataset.id

    def draws(request: _Request, parents: tuple[int, ...] | None = None) -> tuple[Any, Any]:
        return (
            lambda: _draw_key(_old_draw(repo, dataset, request, parents)),
            lambda: _draw_key(draw_sample(repo, dataset, request, parents)),
        )

    def single_filter_value_changes_old() -> list[int]:
        return [
            _old_count(repo, ds_id, (FilterCondition("waehrung", FilterOperator.EQ, w),))
            for w in _WAEHRUNGEN
        ]

    stats_cache = field_value_stats(repo, ds_id, "waehrung")
    assert stats_cache.counts is not None
    counts = stats_cache.counts

    def single_filter_value_changes_new() -> list[int]:
        return [
            hits_from_counts(counts, FilterCondition("waehrung", FilterOperator.EQ, w))
            for w in _WAEHRUNGEN
        ]

    simple_filtered = _Request(
        SampleConfig(method=SamplingMethod.SIMPLE, size=100, seed=4711, filters=_TWO_FILTERS)
    )
    cluster_filtered = _Request(
        SampleConfig(
            method=SamplingMethod.CLUSTER,
            size=3,
            seed=4711,
            cluster_field="kostenstelle",
            filters=(_FILTER_WAEHRUNG,),
        )
    )
    supplement = _Request(
        SampleConfig(method=SamplingMethod.SIMPLE, size=100, seed=4711), exclude_sample_ids=True
    )
    supplement_filtered = _Request(
        SampleConfig(
            method=SamplingMethod.SIMPLE, size=100, seed=4711, filters=(_FILTER_WAEHRUNG,)
        ),
        exclude_sample_ids=True,
    )
    simple_plain = _Request(SampleConfig(method=SamplingMethod.SIMPLE, size=100, seed=4711))
    cluster_plain = _Request(
        SampleConfig(method=SamplingMethod.CLUSTER, size=3, seed=4711, cluster_field="kostenstelle")
    )
    return [
        ("Einfache Ziehung, 2 Filter", *draws(simple_filtered)),
        ("Cluster-Ziehung, 1 Filter", *draws(cluster_filtered)),
        ("Ergänzen, ohne Filter", *draws(supplement, parent_ids)),
        ("Ergänzen, 1 Filter", *draws(supplement_filtered, parent_ids)),
        ("Einfache Ziehung ohne Filter (unverändert)", *draws(simple_plain)),
        ("Cluster-Ziehung ohne Filter (unverändert)", *draws(cluster_plain)),
        (
            "Werteliste (vorher distinct_values, nachher + Zählung)",
            lambda: repo.distinct_values(ds_id, "waehrung"),
            lambda: list(field_value_stats(repo, ds_id, "waehrung").values),
        ),
        (
            "Trefferzahl 1 Filter, erster Wert",
            lambda: _old_count(repo, ds_id, (_FILTER_WAEHRUNG,)),
            lambda: count_filter_matches(repo, ds_id, (_FILTER_WAEHRUNG,), None),
        ),
        (
            f"Trefferzahl 1 Filter, {len(_WAEHRUNGEN)} Wertwechsel (nachher aus Zählung)",
            single_filter_value_changes_old,
            single_filter_value_changes_new,
        ),
        (
            "Trefferzahl 2 Filter",
            lambda: _old_count(repo, ds_id, _TWO_FILTERS),
            lambda: count_filter_matches(repo, ds_id, _TWO_FILTERS, None),
        ),
        (
            "Gruppenzahl kostenstelle",
            lambda: _old_groups(repo, ds_id, "kostenstelle"),
            lambda: count_groups(repo, ds_id, "kostenstelle"),
        ),
    ]


def run_bench(n_rows: int, runs: int, work_dir: Path) -> list[Phase]:
    work_dir.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="bench_sampling_", dir=work_dir))
    try:
        print(f"[bench_sampling] Baue Projektdatei mit {n_rows:,} Zeilen ...", file=sys.stderr)
        db, dataset = _build_project(run_dir / "bench.db", n_rows)
        try:
            repo = DatasetRepo(db.connect())
            step = max(n_rows // _PARENT_SIZE, 1)
            parent_ids = tuple(range(1, n_rows + 1, step))[:_PARENT_SIZE]
            phases: list[Phase] = []
            for label, before, after in _phases(repo, dataset, parent_ids):
                phase = Phase(label)
                print(f"[bench_sampling] {label} ...", file=sys.stderr)
                for _ in range(runs):
                    t_before, r_before = _timed(before)
                    t_after, r_after = _timed(after)
                    if r_before != r_after:
                        raise SystemExit(f"Ergebnis weicht ab: {label}")
                    phase.before_s.append(t_before)
                    phase.after_s.append(t_after)
                phases.append(phase)
            return phases
        finally:
            db.close()
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
        if work_dir.exists() and not any(work_dir.iterdir()):
            work_dir.rmdir()


def _format_ms(seconds: float) -> str:
    ms = seconds * 1000
    if ms >= 1000:
        return f"{ms / 1000:.2f} s"
    if ms >= 10:
        return f"{ms:.0f} ms"
    return f"{ms:.2f} ms"


def render_report(phases: list[Phase], *, n_rows: int, runs: int) -> str:
    lines = [
        "# Stichproben-Benchmark (bench_sampling.py)",
        "",
        f"- Zeilen: {n_rows:,} × {len(COLUMN_NAMES)} Spalten, Läufe: {runs} (Median), "
        "ohne tracemalloc",
        f"- Maschine: {platform.system()} {platform.release()} ({platform.machine()}), "
        f"Python {sys.version.split()[0]}",
        f"- Rev: {_git_short_rev()}",
        "- Ergebnisse vorher/nachher je Lauf verglichen: identisch",
        "",
        "| Phase | vorher | nachher | Faktor |",
        "|-------|-------:|--------:|-------:|",
    ]
    for p in phases:
        factor = p.before / p.after if p.after > 0 else float("inf")
        lines.append(
            f"| {p.label} | {_format_ms(p.before)} | {_format_ms(p.after)} | {factor:.2f}× |"
        )
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--rows", type=int, default=1_000_000, help="Zeilen im Datensatz.")
    parser.add_argument("--runs", type=int, default=3, help="Läufe je Phase (Median).")
    parser.add_argument("--quick", action="store_true", help="2000 Zeilen, 1 Lauf (Smoke).")
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Arbeitsordner für die Projektdatei (Default: tmp/perf/).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdout()
    args = _build_parser().parse_args(argv)
    n_rows, runs = (2000, 1) if args.quick else (args.rows, args.runs)
    work_dir = args.work_dir or (_REPO_ROOT / "tmp" / "perf")
    phases = run_bench(n_rows, runs, work_dir)
    print(render_report(phases, n_rows=n_rows, runs=runs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
