"""Domain-Modelle: frozen Dataclasses + Enums.

Alle Modelle sind unveränderlich (`frozen=True, slots=True`), damit Stichproben
bit-genau reproduzierbar bleiben (ISAE-3402-Anforderung) und keine impliziten
Mutationen die Audit-Trail-Hash-Chain brechen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


def _utcnow() -> datetime:
    """Aktueller UTC-Zeitstempel (timezone-aware)."""
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SamplingMethod(StrEnum):
    """Unterstützte Stichprobenverfahren."""

    SIMPLE = "simple"
    CLUSTER = "cluster"
    STRATIFIED = "stratified"


class StratifyMode(StrEnum):
    """Verteilungsstrategie für `StratifiedSampler`."""

    PROPORTIONAL = "proportional"
    """Größe pro Schicht ∝ Schichtgröße (Largest-Remainder bei Rundung)."""

    EQUAL = "equal"
    """Gleichviele pro Schicht (Largest-Remainder bei Rundung)."""


# ---------------------------------------------------------------------------
# Daten-Modelle
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Engagement:
    """Ein Audit-Mandat (Mandant + Prüfungszeitraum)."""

    name: str
    client: str
    period_start: datetime
    period_end: datetime
    id: UUID = field(default_factory=uuid4)
    notes: str = ""


@dataclass(frozen=True, slots=True)
class DatasetRow:
    """Eine einzelne Zeile aus dem importierten Massendatenbestand.

    `row_id` ist die stabile, deterministische Zeilen-ID (typischerweise die
    1-basierte Zeilennummer aus dem Quell-Excel). Sie wird zum Sortieren vor
    der Stichprobenziehung verwendet → garantiert Reproduzierbarkeit.
    """

    row_id: int
    values: dict[str, Any]

    def get(self, column: str, default: Any = None) -> Any:
        """Liefert den Wert einer Spalte oder `default`, falls nicht vorhanden."""
        return self.values.get(column, default)


@dataclass(frozen=True, slots=True)
class Dataset:
    """Eine importierte Datenmenge innerhalb eines Engagements."""

    name: str
    columns: tuple[str, ...]
    rows: tuple[DatasetRow, ...]
    source_file: str = ""
    id: UUID = field(default_factory=uuid4)

    def __len__(self) -> int:
        return len(self.rows)


@dataclass(frozen=True, slots=True)
class SampleConfig:
    """Konfiguration einer Stichprobenziehung – persistierter Audit-Input."""

    method: SamplingMethod
    size: int
    seed: int

    # Optional – je nach Methode genutzt:
    cluster_field: str | None = None
    stratum_field: str | None = None
    stratify_mode: StratifyMode = StratifyMode.PROPORTIONAL

    # Optionaler Vorfilter (z. B. Country == "AUT")
    filter_field: str | None = None
    filter_value: Any = None

    description: str = ""


@dataclass(frozen=True, slots=True)
class SampleResult:
    """Ergebnis einer Ziehung. `selected_row_ids` ist sortiert für stabile Hashes."""

    config: SampleConfig
    selected_row_ids: tuple[int, ...]
    population_size: int
    drawn_at: datetime = field(default_factory=_utcnow)
    id: UUID = field(default_factory=uuid4)

    @property
    def actual_size(self) -> int:
        """Tatsächliche Anzahl gezogener Zeilen (kann bei Cluster > config.size sein)."""
        return len(self.selected_row_ids)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Ein einzelner Eintrag im append-only Audit-Log (Hash-Chain folgt in Sprint 2)."""

    event_type: str
    payload: dict[str, Any]
    timestamp: datetime = field(default_factory=_utcnow)
    id: UUID = field(default_factory=uuid4)
    actor: str = "system"
