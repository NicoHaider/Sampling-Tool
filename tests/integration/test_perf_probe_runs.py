"""Smoke-Test: scripts/perf_probe.py läuft mit kleiner Größe ohne Crash.

Stellt sicher, dass das Script lauffähig bleibt, wenn sich
Importer-/Exporter-/Sampler-Signaturen ändern. Wir testen NICHT die
Performance selbst – das ist Discovery, gehört nicht in den CI-Lauf.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_perf_probe_kleine_groesse_laeuft_durch(tmp_path: Path) -> None:
    """Mit `--sizes 100 --quick --audit-events 10` <1 Minute."""
    output = tmp_path / "PERFORMANCE.md"
    work_dir = tmp_path / "perf_work"
    # Die Umgebung wird geerbt, nicht neu gebaut: ein gestripptes env hat auf
    # Windows kein `USERPROFILE`, womit `Path.home()` beim blossen Import von
    # `config` mit RuntimeError abbricht (POSIX faellt auf die pwd-DB zurueck
    # und verdeckt das). Es ist ein reiner Smoke-Test, keine Messung.
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "perf_probe.py"),
            "--sizes",
            "100",
            "--quick",
            "--audit-events",
            "10",
            "--output",
            str(output),
            "--work-dir",
            str(work_dir),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"perf_probe.py failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert output.exists(), "PERFORMANCE.md wurde nicht geschrieben"
    content = output.read_text(encoding="utf-8")
    assert "# Performance-Probe" in content
    assert "Messung 100 Zeilen" in content
    # Sanity: alle Hauptphasen tauchen im Bericht auf.
    assert "Import" in content
    assert "DB-Speicherung" in content
    assert "Sampling Simple" in content
    assert "Excel-Export (Sample)" in content
    assert "AuditTrail-PDF" in content
