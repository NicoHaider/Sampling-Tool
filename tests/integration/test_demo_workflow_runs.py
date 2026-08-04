"""Smoke-Test: scripts/demo_full_workflow.py läuft End-to-End durch.

Das Skript war seit Sprint 11.5 kaputt (entfernte `ImportResult`-Compat-
Properties, Iterator-Doppelkonsum, geänderte `export_sample`-/
`log_sampling`-Signaturen) und ist es unbemerkt geblieben, weil es –
anders als seine beiden Schwester-Skripte – von keinem Test und keinem
CI-Job berührt wurde. Genau diese Lücke schließt dieser Test.

Vorbild ist `test_perf_probe_runs.py`, inklusive dessen Env-Behandlung.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

pytestmark = pytest.mark.integration


class TestDemoFullWorkflowRuns:
    def test_demo_workflow_erzeugt_alle_artefakte(self, tmp_path: Path) -> None:
        output = tmp_path / "demo"
        # Die Umgebung wird geerbt, nicht neu gebaut: ein gestripptes env hat
        # auf Windows kein `USERPROFILE`, womit `Path.home()` beim blossen
        # Import von `config` mit RuntimeError abbricht.
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "demo_full_workflow.py"),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, (
            f"demo_full_workflow.py failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        )

        assert (output / "engagement.db").exists(), "SQLite-Datei fehlt"
        assert (output / "source_data.xlsx").exists(), "generierte Quelldatei fehlt"
        assert (output / "audit_trail.pdf").exists(), "AuditTrail-PDF fehlt"

        exports = sorted(output.glob("*_BDO_sampling_*.xlsx"))
        assert len(exports) == 2, f"erwarte 2 Sample-Exporte, gefunden: {[p.name for p in exports]}"
        assert any(p.name.startswith("DemoSimple_ID001_") for p in exports)
        assert any(p.name.startswith("DemoStratified_ID002_") for p in exports)

        # Alle acht Schritte müssen gelaufen sein – ein stiller Teil-Abbruch
        # mit Exit-Code 0 würde sonst durchrutschen.
        assert "[8] Demo abgeschlossen" in result.stdout
        assert "gezogen: 25 Zeilen" in result.stdout
        assert "gezogen: 15 Zeilen" in result.stdout

    def test_demo_workflow_verschmutzt_das_repo_nicht(self, tmp_path: Path) -> None:
        """`--output` lenkt wirklich um – im Repo-Root entsteht kein
        `demo_output/`, wenn das Verzeichnis vorher nicht existierte."""
        repo_demo_dir = REPO_ROOT / "demo_output"
        existed_before = repo_demo_dir.exists()

        output = tmp_path / "woanders"
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "demo_full_workflow.py"),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stderr
        assert output.is_dir()
        if not existed_before:
            assert not repo_demo_dir.exists(), (
                "--output wurde ignoriert, das Skript hat ins Repo geschrieben"
            )
