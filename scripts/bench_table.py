"""Tabellen- und Zeilenzugriffs-Benchmark (Sprint 94) – Profiling-first.

Misst die Lesepfade von ``DatasetRepo`` und das, was der Anwender in der
Datentabelle tatsächlich sieht: Die ``DataTableView`` wird angezeigt und nach
jeder Aktion gezeichnet (``show()``, ``viewport().repaint()``,
``processEvents()``). Ohne Zeichnen fragt Qt kein ``data()`` ab, es liefe also
kein SQL – genau deshalb hat ``perf_probe.py`` die Kosten der gefilterten
Stichproben-Ansicht bis Sprint 94 nie gesehen.

Die Projektdatei wird über die echten Klassen gebaut (``Database.migrate``,
``EngagementRepo.get_or_create``, ``DatasetRepo.create``), ohne xlsx-Umweg:
15 gemischte Spalten wie in ``perf_probe.py``, ``row_id`` 1-basiert wie der
Importer, Seed fix. Sie liegt unter ``--work-dir`` (Default ``tmp/perf/``,
gitignored) und wird nach dem Lauf gelöscht.

Je UI-Aktion zählt das Skript die Repo-Aufrufe (``get_rows_in_range`` und
``get_rows_by_ids``). Die Ausgabe ist eine Markdown-Tabelle auf stdout;
``PERFORMANCE.md`` wird nie automatisch geschrieben.

Aufruf:
    python scripts/bench_table.py                  # 1M Zeilen, 3 Läufe
    python scripts/bench_table.py --rows 200000 --runs 5
    python scripts/bench_table.py --quick          # 2000 Zeilen, 1 Lauf (Smoke)
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

# Offscreen-Plattform MUSS gesetzt sein, bevor PyQt6 geladen wird.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from _script_io import force_utf8_stdout

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from PyQt6.QtCore import QCoreApplication  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sampling_tool.core.models import Dataset, DatasetRow, Engagement  # noqa: E402
from sampling_tool.persistence.database import Database  # noqa: E402
from sampling_tool.persistence.dataset_repo import DatasetRepo  # noqa: E402
from sampling_tool.persistence.engagement_repo import EngagementRepo  # noqa: E402
from sampling_tool.ui.widgets.data_table import DatasetTableModel, DataTableView  # noqa: E402

# Wie perf_probe.py: 15 Spalten gemischt int/float/datetime/Text.
COLUMN_NAMES: tuple[str, ...] = (
    "buchung_id",
    "konto",
    "gegenkonto",
    "betrag",
    "soll_haben",
    "buchungsdatum",
    "valuta",
    "beleg_datum",
    "buchungstext",
    "belegnummer",
    "kostenstelle",
    "auftrag",
    "steuersatz",
    "waehrung",
    "status",
)
_STATUSES: tuple[str, ...] = ("offen", "bezahlt", "verbucht", "storniert", "geprüft")
_KOSTENSTELLEN: tuple[str, ...] = tuple(f"KS{i:02d}" for i in range(1, 11))
_WAEHRUNGEN: tuple[str, ...] = ("EUR", "USD", "CHF", "GBP")
_SOLL_HABEN: tuple[str, ...] = ("S", "H")

_SEED = 42
_SAMPLE_IDS = 500
_LARGE_ID_COUNT = 5000
_VIEW_WIDTH = 1200
_VIEW_HEIGHT = 800
_DRAG_POSITIONS = 20
_INDEX_NAME = "idx_dataset_rows_dataset_row"


def _git_short_rev() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unbekannt"


# ---------------------------------------------------------------------------
# Projektdatei
# ---------------------------------------------------------------------------


def _generate_rows(n_rows: int, seed: int) -> Iterator[DatasetRow]:
    """Seeded Buchungssätze; Datumsspalten als ``datetime`` wie nach dem Import."""
    rng = np.random.default_rng(seed)
    base = datetime(2025, 1, 1)
    konten = rng.integers(4000, 8000, size=n_rows)
    gegenkonten = rng.integers(4000, 8000, size=n_rows)
    betraege = rng.uniform(10.0, 9999.99, size=n_rows).round(2)
    soll_haben = rng.choice(_SOLL_HABEN, size=n_rows)
    bu_offsets = rng.integers(0, 365, size=n_rows)
    valuta_offsets = bu_offsets + rng.integers(0, 7, size=n_rows)
    beleg_offsets = bu_offsets - rng.integers(0, 5, size=n_rows)
    belegnummern = rng.integers(100000, 999999, size=n_rows)
    kostenstellen = rng.choice(_KOSTENSTELLEN, size=n_rows)
    auftrag_ids = rng.integers(1000, 9999, size=n_rows)
    steuersaetze = rng.choice([0.0, 7.0, 10.0, 13.0, 20.0], size=n_rows)
    waehrungen = rng.choice(_WAEHRUNGEN, size=n_rows)
    status = rng.choice(_STATUSES, size=n_rows)
    for i in range(n_rows):
        values = (
            i + 1,
            int(konten[i]),
            int(gegenkonten[i]),
            float(betraege[i]),
            str(soll_haben[i]),
            base + timedelta(days=int(bu_offsets[i])),
            base + timedelta(days=int(valuta_offsets[i])),
            base + timedelta(days=int(beleg_offsets[i])),
            f"Buchung Nr. {i + 1}",
            f"BN{int(belegnummern[i])}",
            str(kostenstellen[i]),
            f"AUF{int(auftrag_ids[i])}",
            float(steuersaetze[i]),
            str(waehrungen[i]),
            str(status[i]),
        )
        yield DatasetRow(row_id=i + 1, values=dict(zip(COLUMN_NAMES, values, strict=True)))


def _build_project(db_path: Path, n_rows: int) -> tuple[Database, Dataset]:
    db = Database(db_path)
    db.migrate()
    engagement = EngagementRepo(db.connect()).get_or_create(
        Engagement(
            auditor_name="Bench",
            client_name="Bench GmbH",
            auditor_position="Prüfer",
            audit_type="ISAE 3402",
        )
    )
    dataset = DatasetRepo(db.connect()).create(
        Dataset(
            name="bench",
            columns=COLUMN_NAMES,
            row_count=n_rows,
            engagement_id=engagement.id,
        ),
        _generate_rows(n_rows, _SEED),
    )
    return db, dataset


def _has_row_index(db: Database) -> bool:
    row = (
        db.connect()
        .execute("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?", (_INDEX_NAME,))
        .fetchone()
    )
    return row is not None


def _scattered_ids(n_rows: int, count: int, seed: int) -> list[int]:
    """Über den ganzen Datensatz verteilte IDs, sortiert wie ein Stichprobenergebnis."""
    rng = np.random.default_rng(seed)
    picked = rng.choice(n_rows, size=min(count, n_rows), replace=False)
    return sorted(int(i) + 1 for i in picked)


# ---------------------------------------------------------------------------
# Messung
# ---------------------------------------------------------------------------


class CountingRepo(DatasetRepo):
    """``DatasetRepo``, das die Ladeaufrufe der Tabelle mitzählt."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__(conn)
        self.range_calls = 0
        self.id_calls = 0

    def reset(self) -> None:
        self.range_calls = 0
        self.id_calls = 0

    def get_rows_in_range(self, dataset_id: int, start: int, end: int) -> list[DatasetRow]:
        self.range_calls += 1
        return super().get_rows_in_range(dataset_id, start, end)

    def get_rows_by_ids(self, dataset_id: int, row_ids: Sequence[int]) -> list[DatasetRow]:
        self.id_calls += 1
        return super().get_rows_by_ids(dataset_id, row_ids)


@dataclass
class Phase:
    """Messwerte einer Phase über alle Läufe."""

    label: str
    times_s: list[float] = field(default_factory=list)
    range_calls: int | None = None
    id_calls: int | None = None

    @property
    def median_s(self) -> float:
        return statistics.median(self.times_s)


def _timed(fn: Callable[[], object]) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def _consume(it: Iterator[object]) -> None:
    for _ in it:
        pass


def _repo_phases(
    repo: DatasetRepo, dataset_id: int, n_rows: int
) -> list[tuple[str, Callable[[], object]]]:
    window = 2 * DatasetTableModel.BULK_LOAD_HALF_WINDOW + 1
    middle = max(1, n_rows // 2 - DatasetTableModel.BULK_LOAD_HALF_WINDOW)
    end_start = max(1, n_rows + 1 - window)
    ids_500 = _scattered_ids(n_rows, _SAMPLE_IDS, _SEED + 1)
    ids_5000 = _scattered_ids(n_rows, _LARGE_ID_COUNT, _SEED + 2)
    return [
        ("get_rows_in_range Anfang", lambda: repo.get_rows_in_range(dataset_id, 1, 1 + window)),
        (
            "get_rows_in_range Mitte",
            lambda: repo.get_rows_in_range(dataset_id, middle, middle + window),
        ),
        (
            "get_rows_in_range Ende",
            lambda: repo.get_rows_in_range(dataset_id, end_start, end_start + window),
        ),
        ("get_row Mitte", lambda: repo.get_row(dataset_id, max(1, n_rows // 2))),
        (f"get_rows_by_ids {len(ids_500)}", lambda: repo.get_rows_by_ids(dataset_id, ids_500)),
        (
            f"get_rows_by_ids {len(ids_5000)}",
            lambda: repo.get_rows_by_ids(dataset_id, ids_5000),
        ),
        ("iter_row_ids", lambda: _consume(repo.iter_row_ids(dataset_id))),
        (
            "iter_row_field_pairs",
            lambda: _consume(repo.iter_row_field_pairs(dataset_id, "kostenstelle")),
        ),
    ]


def _paint(view: DataTableView) -> None:
    viewport = view.viewport()
    assert viewport is not None
    viewport.repaint()
    app = QCoreApplication.instance()
    if app is not None:
        for _ in range(3):
            app.processEvents()


def _ui_run(
    repo: CountingRepo, dataset: Dataset, sample_ids: list[int]
) -> list[tuple[str, float, int, int]]:
    """Ein UI-Durchlauf mit frischer View (leerer Cache)."""
    view = DataTableView()
    view.setFixedSize(_VIEW_WIDTH, _VIEW_HEIGHT)
    view.show()
    _paint(view)
    bar = view.verticalScrollBar()
    assert bar is not None
    results: list[tuple[str, float, int, int]] = []

    def step(label: str, action: Callable[[], object]) -> None:
        repo.reset()

        def run() -> None:
            action()
            _paint(view)

        elapsed = _timed(run)
        results.append((label, elapsed, repo.range_calls, repo.id_calls))

    step("Datensatz anzeigen", lambda: view.set_dataset(dataset, repo))
    for pct in (25, 50, 75, 100):
        step(f"Scrollbar-Sprung {pct} %", lambda pct=pct: bar.setValue(bar.maximum() * pct // 100))

    def drag() -> None:
        maximum = bar.maximum()
        for k in range(_DRAG_POSITIONS):
            bar.setValue(maximum * k // (_DRAG_POSITIONS - 1))
            _paint(view)

    step(f"Scrollbar ziehen ({_DRAG_POSITIONS} Positionen)", drag)
    step(f"highlight_rows ({len(sample_ids)} IDs)", lambda: view.highlight_rows(sample_ids))
    step(
        f"Nur Stichprobe anzeigen ({len(sample_ids)} IDs)", lambda: view.filter_to_rows(sample_ids)
    )
    step("darin ans Ende scrollen", view.scrollToBottom)
    view.close()
    view.deleteLater()
    return results


def run_bench(n_rows: int, runs: int, work_dir: Path) -> tuple[list[Phase], list[Phase], bool]:
    work_dir.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="bench_table_", dir=work_dir))
    try:
        print(f"[bench_table] Baue Projektdatei mit {n_rows:,} Zeilen ...", file=sys.stderr)
        db, dataset = _build_project(run_dir / "bench.db", n_rows)
        try:
            assert dataset.id is not None
            has_index = _has_row_index(db)
            repo = CountingRepo(db.connect())

            repo_phases: list[Phase] = []
            for label, fn in _repo_phases(repo, dataset.id, n_rows):
                phase = Phase(label)
                for _ in range(runs):
                    phase.times_s.append(_timed(fn))
                repo_phases.append(phase)

            sample_ids = _scattered_ids(n_rows, _SAMPLE_IDS, _SEED + 1)
            ui_by_label: dict[str, Phase] = {}
            for _ in range(runs):
                for label, elapsed, range_calls, id_calls in _ui_run(repo, dataset, sample_ids):
                    phase = ui_by_label.setdefault(label, Phase(label))
                    phase.times_s.append(elapsed)
                    # Die Aufrufzahl ist je Lauf deterministisch; die erste zählt.
                    if phase.range_calls is None:
                        phase.range_calls = range_calls
                        phase.id_calls = id_calls
            return repo_phases, list(ui_by_label.values()), has_index
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


def render_report(
    repo_phases: list[Phase], ui_phases: list[Phase], *, n_rows: int, runs: int, has_index: bool
) -> str:
    lines = [
        "# Tabellen-Benchmark (bench_table.py)",
        "",
        f"- Zeilen: {n_rows:,} × {len(COLUMN_NAMES)} Spalten, Läufe: {runs} (Median)",
        f"- Maschine: {platform.system()} {platform.release()} ({platform.machine()}), "
        f"Python {sys.version.split()[0]}, Qt-Plattform {os.environ.get('QT_QPA_PLATFORM')}",
        f"- Rev: {_git_short_rev()}",
        f"- Index `{_INDEX_NAME}`: {'ja' if has_index else 'nein'}",
        "",
        "## Repo-Ebene",
        "",
        "| Phase | Median |",
        "|-------|-------:|",
    ]
    lines += [f"| {p.label} | {_format_ms(p.median_s)} |" for p in repo_phases]
    lines += [
        "",
        f"## UI-Ebene (angezeigt und gezeichnet, {_VIEW_WIDTH}×{_VIEW_HEIGHT})",
        "",
        "| Phase | Median | get_rows_in_range | get_rows_by_ids |",
        "|-------|-------:|------------------:|----------------:|",
    ]
    lines += [
        f"| {p.label} | {_format_ms(p.median_s)} | {p.range_calls} | {p.id_calls} |"
        for p in ui_phases
    ]
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
    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert app is not None
    work_dir = args.work_dir or (_REPO_ROOT / "tmp" / "perf")
    repo_phases, ui_phases, has_index = run_bench(n_rows, runs, work_dir)
    print(render_report(repo_phases, ui_phases, n_rows=n_rows, runs=runs, has_index=has_index))
    return 0


if __name__ == "__main__":
    sys.exit(main())
