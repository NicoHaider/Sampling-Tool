"""Smoke-Test: scripts/bench_sampling.py läuft mit kleiner Größe ohne Crash.

Stellt sicher, dass der Sprint-98-Stichproben-Benchmark lauffähig bleibt. Die
Performance selbst wird NICHT geprüft; der Vergleich vorher/nachher je Phase
(Exit 1 bei Abweichung) läuft dabei mit.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_bench_sampling_quick_laeuft_durch(tmp_path: Path) -> None:
    """Mit `--quick` (2000 Zeilen, 1 Lauf) alle Phasen in der Tabelle."""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    work_dir = tmp_path / "work"
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "bench_sampling.py"),
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
        f"bench_sampling.py failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    out = result.stdout
    assert "Ergebnisse vorher/nachher je Lauf verglichen: identisch" in out
    for phase in (
        "Einfache Ziehung, 2 Filter",
        "Cluster-Ziehung, 1 Filter",
        "Ergänzen, ohne Filter",
        "Werteliste",
        "Trefferzahl 1 Filter, erster Wert",
        "Trefferzahl 2 Filter",
        "Gruppenzahl kostenstelle",
    ):
        assert f"| {phase}" in out, phase
    assert not work_dir.exists() or not any(work_dir.iterdir())
