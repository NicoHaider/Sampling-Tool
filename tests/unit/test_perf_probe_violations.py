"""Unit-Tests für `detect_violations` aus `scripts/perf_probe.py`.

Sprint 12.1 / P-007 hat Import + DB-Speicherung zu einem Pipeline-Total
konsolidiert (Streaming-Verlagerung). Pass-4 T-004: dieser Test
verifiziert die Aggregations-Logik – Einzelphasen Import/DB werden
NICHT mehr als Verfehlung gemeldet, nur das Pipeline-Total.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from perf_probe import (  # type: ignore[import-not-found]  # noqa: E402
    PIPELINE_TOTAL_LABEL,
    Measurement,
    SizeResult,
    detect_violations,
)


def _result(size: int, *phases: tuple[str, float]) -> SizeResult:
    """Hilfsfunktion: SizeResult mit gegebenen (label, elapsed_s)-Tupeln."""
    r = SizeResult(size=size)
    for label, elapsed in phases:
        r.measurements.append(Measurement(label=label, elapsed_s=elapsed))
    return r


class TestPipelineTotalAggregation:
    """Sprint 12.1 / P-007: Import+DB werden zum Pipeline-Total aggregiert."""

    def test_pipeline_unter_target_keine_verfehlung(self) -> None:
        # Import 7s + DB 50s = 57s < 90s → keine Verfehlung
        results = [_result(1_000_000, ("Import", 7.0), ("DB-Speicherung", 50.0))]
        assert detect_violations(results) == []

    def test_pipeline_ueber_target_meldet_pipeline_total(self) -> None:
        # Import 10s + DB 90s = 100s > 90s → eine Verfehlung als Pipeline-Total
        results = [_result(1_000_000, ("Import", 10.0), ("DB-Speicherung", 90.0))]
        violations = detect_violations(results)
        assert len(violations) == 1
        _size, label, measured, target = violations[0]
        assert label == PIPELINE_TOTAL_LABEL
        assert measured == 100.0
        assert target == 90.0

    def test_einzelphase_db_ueber_30s_aber_pipeline_unter_90s_keine_verfehlung(self) -> None:
        """DB 53s war Sprint 10.x-Verfehlung, ist Sprint 11.3+ legitim
        (Coercion verlagerte sich aus Import). Soll NICHT mehr gemeldet werden."""
        results = [_result(1_000_000, ("Import", 7.6), ("DB-Speicherung", 53.4))]
        # Pipeline-Total 61s < 90s → keine Verfehlung
        violations = detect_violations(results)
        assert violations == []

    def test_einzelphase_import_ueber_60s_aber_pipeline_unter_90s_keine_verfehlung(self) -> None:
        """Spiegelfall: Import 65s einzeln, DB 20s, gesamt 85s → ok."""
        results = [_result(1_000_000, ("Import", 65.0), ("DB-Speicherung", 20.0))]
        assert detect_violations(results) == []

    def test_einzelphase_wird_nicht_als_verfehlung_aufgefuehrt(self) -> None:
        """Selbst bei Pipeline-Verfehlung tauchen Import/DB nicht als eigene Verfehlung auf."""
        results = [_result(1_000_000, ("Import", 60.0), ("DB-Speicherung", 60.0))]
        violations = detect_violations(results)
        labels = [v[1] for v in violations]
        assert "Import" not in labels
        assert "DB-Speicherung" not in labels
        assert PIPELINE_TOTAL_LABEL in labels


class TestPartialPhasen:
    def test_ohne_import_keine_pipeline_pruefung(self) -> None:
        """Wenn Import-Messung fehlt, wird Pipeline-Total NICHT aggregiert."""
        results = [_result(1_000_000, ("DB-Speicherung", 1000.0))]
        violations = detect_violations(results)
        # Kein Pipeline-Total – DB allein wird auch nicht gemeldet (kein Einzeltarget mehr).
        assert violations == []

    def test_ohne_db_keine_pipeline_pruefung(self) -> None:
        results = [_result(1_000_000, ("Import", 1000.0))]
        violations = detect_violations(results)
        assert violations == []


class TestAndereSoftTargets:
    """Sicherstellen, dass die Pipeline-Spezial-Logik andere Targets nicht stört."""

    def test_tabelle_anzeige_ueber_target_wird_weiterhin_gemeldet(self) -> None:
        results = [
            _result(
                1_000_000,
                ("Import", 7.0),
                ("DB-Speicherung", 50.0),
                ("Tabelle-Anzeige", 20.0),  # > 5s Target
            )
        ]
        violations = detect_violations(results)
        labels = [v[1] for v in violations]
        assert "Tabelle-Anzeige" in labels
        assert PIPELINE_TOTAL_LABEL not in labels  # Pipeline 57s < 90s

    def test_lineare_skalierung_bei_kleineren_groessen(self) -> None:
        """Bei 100k Rows ist das skalierte Pipeline-Target 9s (10% von 90s)."""
        results = [_result(100_000, ("Import", 5.0), ("DB-Speicherung", 10.0))]
        # 15s > 9s skaliert → Verfehlung
        violations = detect_violations(results)
        assert len(violations) == 1
        assert violations[0][1] == PIPELINE_TOTAL_LABEL
