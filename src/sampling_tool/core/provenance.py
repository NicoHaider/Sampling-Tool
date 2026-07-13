"""Kanonisches Reproduktions-Provenienz-Modell für eine gezogene Stichprobe.

EINE Serialisierung speist Audit-Event UND alle fünf Export-Flächen (Sample-
XLSX, Projekt-XLSX-Samples, Projekt-XLSX-AuditTrail, PDF, HTML) – Sprint 43 /
S1.5b, A-001. Vorher baute jede Fläche ihre Provenienz-Zeilen unabhängig, was
Felder wie `filter_operator`/`parent_sample_id`/`algorithm_version` in einem
Teil der Flächen driften ließ (im Audit-Event fehlten sie komplett).

Nur von `core.models` + `core.formatting` abhängig – keine IO-/Persistenz-/
UI-Importe, damit die strikte Layer-Trennung (CLAUDE.md „Architektur") erhalten
bleibt. `app_version` wird von jedem Aufrufer explizit übergeben
(`sampling_tool.__version__`) statt hier importiert zu werden.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from sampling_tool.core.formatting import format_optional_timestamp
from sampling_tool.core.models import SampleResult

_MISSING: Final[str] = "—"

_OPERATOR_SYMBOLS: Final[dict[str, str]] = {
    "eq": "=",
    "ne": "≠",
    "gt": ">",
    "gte": "≥",
    "lt": "<",
    "lte": "≤",
}


@dataclass(frozen=True, slots=True)
class SamplingProvenance:
    """Vollständiger Reproduktions-Fußabdruck einer Stichprobe.

    Deckt die Mindest-Feldliste aus REVIEW_CODEBASE_2026-07.md (A-001) ab:
    Dataset, Methode, angeforderte/tatsächliche Größe, Population, Seed,
    Filter (Feld/Operator/Wert), Cluster-/Stratum-Feld, Stratify-Modus,
    Parent-Sample, Algorithmus-/App-Version, Ersteller/Zeitpunkt.
    """

    dataset_id: int | None
    method: str
    size_requested: int
    size_actual: int
    population_size: int
    seed: int
    filter_field: str | None
    filter_operator: str
    filter_value: Any
    cluster_field: str | None
    stratum_field: str | None
    stratify_mode: str
    parent_sample_id: int | None
    algorithm_version: str
    app_version: str
    created_by: str
    drawn_at: datetime

    @classmethod
    def from_sample_result(
        cls,
        result: SampleResult,
        *,
        dataset_id: int | None,
        app_version: str,
    ) -> SamplingProvenance:
        """Baut die Provenienz aus einem persistierten `SampleResult`.

        `dataset_id` wird vom Aufrufer gereicht statt aus `result` gelesen –
        `SampleResult` kennt sein Dataset nicht (`SampleRepo.list_for_dataset`
        verwirft die Zuordnung nach dem Laden). Aufrufer ohne eine belastbare
        Zuordnung (z. B. eine Projekt-weite Samples-Tabelle ohne mitgereichte
        Zuordnung) reichen `None` – das Feld zeigt dann `"—"` statt eines
        geschätzten Werts.
        """
        cfg = result.config
        return cls(
            dataset_id=dataset_id,
            method=cfg.method.value,
            size_requested=cfg.size,
            size_actual=result.actual_size,
            population_size=result.population_size,
            seed=cfg.seed,
            filter_field=cfg.filter_field,
            filter_operator=cfg.filter_operator.value,
            filter_value=cfg.filter_value,
            cluster_field=cfg.cluster_field,
            stratum_field=cfg.stratum_field,
            stratify_mode=cfg.stratify_mode.value,
            parent_sample_id=result.parent_sample_id,
            algorithm_version=result.algorithm_version,
            app_version=app_version,
            created_by=result.created_by,
            drawn_at=result.drawn_at,
        )

    @property
    def filter_operator_symbol(self) -> str:
        """Menschenlesbares Operator-Symbol (`=`/`≠`/`>`/`≥`/`<`/`≤`).

        Fällt auf den rohen Wert zurück, falls ein zukünftiger Operator noch
        keine Symbol-Zuordnung hat (nie stillschweigend verschlucken)."""
        return _OPERATOR_SYMBOLS.get(self.filter_operator, self.filter_operator)

    def to_ordered_fields(self) -> list[tuple[str, str]]:
        """Kanonische, geordnete (Label, Wert)-Liste für menschenlesbare
        Sample-Ebenen-Anzeigen (Sample-XLSX-Metadaten). Fehlende Werte werden
        explizit als `"—"` dargestellt, nie geschätzt."""
        return [
            ("Dataset-ID", _or_dash(self.dataset_id)),
            ("Sampling-Methode", self.method),
            ("Angeforderte Größe", str(self.size_requested)),
            ("Tatsächliche Größe", str(self.size_actual)),
            ("Population (Zeilen)", str(self.population_size)),
            ("Seed", str(self.seed)),
            ("Filter-Feld", _or_dash(self.filter_field)),
            ("Filter-Operator", self.filter_operator_symbol),
            ("Filter-Wert", _or_dash(self.filter_value)),
            ("Cluster-Feld", _or_dash(self.cluster_field)),
            ("Stratum-Feld", _or_dash(self.stratum_field)),
            ("Stratify-Mode", self.stratify_mode),
            ("Parent-Sample-ID", _or_dash(self.parent_sample_id)),
            ("Algorithmus-Version", self.algorithm_version),
            ("App-Version", self.app_version),
            ("Erstellt von", self.created_by),
            ("Gezogen am", format_optional_timestamp(self.drawn_at)),
        ]

    def to_audit_details(self) -> dict[str, Any]:
        """Dict für `AuditEvent.details` (→ `details_json`). Ergänzt die
        bisherigen Schlüssel (`method`/`filter_field`/`filter_value`/
        `cluster_field`/`stratum_field`/`stratify_mode`) um die zuvor
        fehlenden Reproduktionsparameter (A-001). Native Typen (kein
        String-Formatting) – im Unterschied zu `to_ordered_fields`."""
        return {
            "dataset_id": self.dataset_id,
            "method": self.method,
            "size_requested": self.size_requested,
            "filter_field": self.filter_field,
            "filter_value": self.filter_value,
            "filter_operator": self.filter_operator,
            "cluster_field": self.cluster_field,
            "stratum_field": self.stratum_field,
            "stratify_mode": self.stratify_mode,
            "parent_sample_id": self.parent_sample_id,
            "algorithm_version": self.algorithm_version,
            "app_version": self.app_version,
            "created_by": self.created_by,
        }


def _or_dash(value: Any) -> str:
    """`"—"` für `None`, sonst `str(value)` – Legacy-treue Darstellung."""
    return _MISSING if value is None else str(value)
