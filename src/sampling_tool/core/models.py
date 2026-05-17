"""Domain-Modelle: frozen Dataclasses + Enums.

Alle Modelle sind unveränderlich (`frozen=True, slots=True`), damit Stichproben
bit-genau reproduzierbar bleiben (ISAE-3402-Anforderung) und keine impliziten
Mutationen die Audit-Trail-Hash-Chain brechen.

DB-Identitäten werden als optionale Integer (`id: int | None = None`) abgebildet:
beim ersten Persistieren noch `None`, danach setzt das Repository den vom
SQLite-AUTOINCREMENT vergebenen Wert via `dataclasses.replace`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def _utcnow() -> datetime:
    """Aktueller UTC-Zeitstempel (timezone-aware)."""
    return datetime.now(UTC)


def _empty_details() -> dict[str, Any]:
    """Default-Factory für `AuditEvent.details` – typisiert für mypy/pyright."""
    return {}


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


class UndoStack(StrEnum):
    """Stack-Identifier für `UndoManager` / `undo_snapshots`."""

    UNDO = "undo"
    REDO = "redo"


# ---------------------------------------------------------------------------
# Daten-Modelle
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Engagement:
    """Ein Audit-Mandat (Auditor + Mandant + Prüfungstyp).

    Pro SQLite-Datei existiert genau ein Engagement (Mandanten-Trennung).
    """

    auditor_name: str
    client_name: str
    auditor_position: str = ""
    audit_type: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    id: int | None = None


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
    """Eine importierte Datenmenge innerhalb eines Engagements.

    **Streaming-Architektur (Sprint 11.x):** Das Dataset hält KEINE rows
    mehr – nur Metadaten (Spalten, row_count, source_file, Engagement-FK).
    Rows leben in `dataset_rows` und werden bei Bedarf via `DatasetRepo`
    geladen (`get_row`, `iter_rows`, `get_rows_in_range`,
    `get_rows_by_ids`, `iter_row_ids`). `get_all_rows` ist nur für
    Tests / SamplingDialog-Advanced-Mode legitim, sonst Streaming.

    Hintergrund: bei realistischen Audit-Dateien (1M+ Buchungssätze)
    sprengt das Laden aller Rows als Python-Dicts den RAM (siehe
    PERFORMANCE.md).
    """

    name: str
    columns: tuple[str, ...]
    row_count: int = 0
    source_file: str = ""
    imported_at: datetime = field(default_factory=_utcnow)
    engagement_id: int | None = None
    id: int | None = None

    def __len__(self) -> int:
        return self.row_count


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
    parent_sample_id: int | None = None
    created_by: str = "system"
    id: int | None = None

    @property
    def actual_size(self) -> int:
        """Tatsächliche Anzahl gezogener Zeilen (kann bei Cluster > config.size sein)."""
        return len(self.selected_row_ids)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Ein Eintrag im append-only Audit-Log.

    Die expliziten Felder (`sample_size`, `seed`, `import_file`, …) decken die
    häufigsten Audit-Operationen und vermeiden Frei-JSON wo möglich.
    Zusätzlicher Kontext landet in `details` (DB: `details_json TEXT`).
    """

    event_type: str
    engagement_id: int | None = None
    user_name: str = "system"
    timestamp: datetime = field(default_factory=_utcnow)

    sample_id: int | None = None
    sample_size: int | None = None
    sample_percent: float | None = None
    total_count: int | None = None
    seed: int | None = None
    import_file: str | None = None
    export_file: str | None = None
    details: dict[str, Any] = field(default_factory=_empty_details)
    corrects_event_id: int | None = None

    id: int | None = None


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Undo-/Redo-Snapshot des Sicht-Zustands (sichtbare und markierte Zeilen)."""

    stack_type: UndoStack
    position: int
    visible_rows: tuple[int, ...] = ()
    highlighted_rows: tuple[int, ...] = ()
    sample_id: int | None = None
    engagement_id: int | None = None
    created_at: datetime = field(default_factory=_utcnow)
    id: int | None = None
