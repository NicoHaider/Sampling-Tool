"""Smoke-Test: scripts/bench_import.py läuft mit kleiner Größe ohne Crash.

Stellt sicher, dass der Sprint-26-Import-Benchmark lauffähig bleibt, wenn
sich Importer-/Persistenz-Signaturen ändern. Wir testen NICHT die
Performance selbst – das ist Discovery, gehört nicht in den CI-Lauf
(analog `test_perf_probe_runs.py`).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_bench_import_quick_laeuft_durch(tmp_path: Path) -> None:
    """Mit `--quick` (1000 Zeilen, 1 Lauf) beide Formate <1 Minute."""
    # Umgebung erben (nicht neu bauen): ohne `USERPROFILE` bricht `Path.home()`
    # auf Windows schon beim Import von `config` mit RuntimeError ab.
    #
    # Sprint 75 / Befund A: hier stand zusaetzlich `PYTHONIOENCODING=utf-8`, weil
    # `bench_import.py` Kaesten-/Sigma-Zeichen (Σ → ─ └ ├) nach stdout schreibt,
    # die cp1252 nicht kodieren kann – bei umgeleitetem stdout starb das Skript
    # sonst mit UnicodeEncodeError. Das war eine Kruecke beim AUFRUFER; die
    # Ursache sitzt jetzt im Skript selbst (`_script_io.force_utf8_stdout`).
    # Die Kruecke ist bewusst entfernt: mit ihr wuerde dieser Test den Guard auf
    # Windows-CI nie durchlaufen und der Fix waere ungeprueft.
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "bench_import.py"),
            "--quick",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, (
        f"bench_import.py failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    # Sanity: beide Formate + alle drei Phasen tauchen im Bericht auf.
    out = result.stdout
    assert "XLSX" in out
    assert "CSV" in out
    assert "Parse" in out
    assert "Encode" in out
    assert "Write" in out
    assert "Dominant" in out
