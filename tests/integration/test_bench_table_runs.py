"""Smoke-Test: scripts/bench_table.py läuft mit kleiner Größe ohne Crash.

Stellt sicher, dass der Sprint-94-Tabellen-Benchmark lauffähig bleibt, wenn
sich Repo- oder Tabellen-Signaturen ändern. Die Performance selbst wird NICHT
geprüft (analog `test_bench_import_runs.py`).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_bench_table_quick_laeuft_durch(tmp_path: Path) -> None:
    """Mit `--quick` (2000 Zeilen, 1 Lauf) alle Phasen in der Tabelle."""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    work_dir = tmp_path / "work"
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "bench_table.py"),
            "--quick",
            "--work-dir",
            str(work_dir),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, (
        f"bench_table.py failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    out = result.stdout
    for phase in (
        "get_rows_in_range Anfang",
        "get_rows_in_range Mitte",
        "get_rows_in_range Ende",
        "get_row Mitte",
        "get_rows_by_ids",
        "iter_row_ids",
        "iter_row_field_pairs",
        "Datensatz anzeigen",
        "Scrollbar-Sprung 25 %",
        "Scrollbar-Sprung 100 %",
        "Scrollbar ziehen",
        "highlight_rows",
        "Nur Stichprobe anzeigen",
        "darin ans Ende scrollen",
    ):
        assert f"| {phase}" in out, phase
    # Die Projektdatei wird nach dem Lauf weggeräumt.
    assert not work_dir.exists() or not any(work_dir.iterdir())
