"""Gemeinsame Testdaten für „Berichte sprechen Deutsch" (Sprint 83 / D).

PDF-, HTML- und Excel-Report prüfen dieselbe Zusage gegen dieselben Daten: keine
englischen Rohschlüssel als sichtbarer Text, keine Python-Listen-Darstellung,
Einschränkung und Nachstichprobe unterscheidbar.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Final

from sampling_tool.core.models import (
    AuditEvent,
    ParentRelation,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.core.provenance import SamplingProvenance

#: Rohwerte, die vor Sprint 83 in den Berichten standen (Ereignis-, Methoden-,
#: Modus- und Ableitungs-Schlüssel). Case-sensitiv, ganzes Wort: das großgeschriebene
#: „Sampling" im Produktnamen ist kein Rohschlüssel.
RAW_WORDS: Final = (
    "simple",
    "stratified",
    "sampling",
    "undo",
    "redo",
    "proportional",
    "restrict",
    "supplement",
)

_BASE: Final = datetime(2026, 5, 11, 8, 0, 0, tzinfo=UTC)


def raw_words_in(text: str) -> list[str]:
    """Alle `RAW_WORDS`, die als ganzes Wort in ``text`` vorkommen."""
    return [word for word in RAW_WORDS if re.search(rf"\b{word}\b", text)]


def readable_samples() -> list[SampleResult]:
    """#1 einfach, #2 geschichtet + eingeschränkt auf #1, #3 Nachstichprobe zu #1."""
    simple = SampleConfig(method=SamplingMethod.SIMPLE, size=3, seed=42)
    stratified = SampleConfig(
        method=SamplingMethod.STRATIFIED, size=2, seed=7, stratum_field="Land"
    )
    return [
        SampleResult(
            config=simple,
            selected_row_ids=(1, 2, 3),
            population_size=10,
            drawn_at=_BASE,
            created_by="anna",
            id=1,
        ),
        SampleResult(
            config=stratified,
            selected_row_ids=(1, 3),
            population_size=3,
            drawn_at=_BASE + timedelta(minutes=1),
            parent_sample_id=1,
            parent_relation=ParentRelation.RESTRICT,
            created_by="anna",
            id=2,
        ),
        SampleResult(
            config=simple,
            selected_row_ids=(5, 6),
            population_size=7,
            drawn_at=_BASE + timedelta(minutes=2),
            parent_sample_id=1,
            parent_relation=ParentRelation.SUPPLEMENT,
            created_by="anna",
            id=3,
        ),
    ]


def readable_events() -> list[AuditEvent]:
    """Import, drei Ziehungen mit voller Provenienz, Undo/Redo auf leer, Reset."""
    events = [
        AuditEvent(
            event_type="import",
            engagement_id=1,
            user_name="anna",
            timestamp=_BASE - timedelta(minutes=1),
            import_file="buchungen.xlsx",
            total_count=10,
            details={
                "dataset_name": "buchungen (Buchungen)",
                "columns": ["BuchungsID", "Belegart"],
                "dataset_id": 1,
                "source_sheet": "Buchungen",
                "header_row": 5,
                "rows_above_header": 4,
            },
            id=1,
        )
    ]
    for offset, sample in enumerate(readable_samples()):
        details = SamplingProvenance.from_sample_result(
            sample, dataset_id=1, app_version="0.0.0"
        ).to_audit_details()
        events.append(
            AuditEvent(
                event_type="sampling",
                engagement_id=1,
                user_name="anna",
                timestamp=sample.drawn_at,
                sample_id=sample.id,
                sample_size=sample.actual_size,
                seed=sample.config.seed,
                details=details,
                id=2 + offset,
            )
        )
    tail = _BASE + timedelta(minutes=10)
    events += [
        AuditEvent(
            event_type="undo",
            engagement_id=1,
            user_name="anna",
            timestamp=tail,
            details={"restored": "empty"},
            id=10,
        ),
        AuditEvent(
            event_type="redo",
            engagement_id=1,
            user_name="anna",
            timestamp=tail + timedelta(seconds=1),
            details={"restored": "empty"},
            id=11,
        ),
        AuditEvent(
            event_type="reset",
            engagement_id=1,
            user_name="anna",
            timestamp=tail + timedelta(seconds=2),
            details={"dataset_id": 1},
            id=12,
        ),
    ]
    return events
