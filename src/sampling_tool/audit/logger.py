"""High-Level-Wrapper um `AuditRepo` – baut typisierte Events pro Aktion.

Jede `log_*`-Methode konstruiert den passenden `AuditEvent` und schreibt ihn
über das Repo. Damit hat aufrufender Code keine Berührung mit dem rohen
`event_type`-String und vergisst keine Pflichtfelder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sampling_tool import __version__
from sampling_tool.core.models import AuditEvent, Dataset, SampleResult
from sampling_tool.core.provenance import SamplingProvenance
from sampling_tool.persistence.repositories import AuditRepo


class AuditLogger:
    """Schreibt strukturierte Audit-Events an `AuditRepo`."""

    def __init__(
        self,
        audit_repo: AuditRepo,
        user_name: str,
        engagement_id: int,
    ) -> None:
        self.repo = audit_repo
        self.user_name = user_name
        self.engagement_id = engagement_id

    # ---- Sampling -------------------------------------------------------

    def log_sampling(self, sample: SampleResult, sample_id: int, dataset_id: int) -> AuditEvent:
        """Stichprobe gezogen – inkl. Größe, Population, Anteil, Seed, Methode
        sowie der vollen Reproduktions-Provenienz (Sprint 43 / A-001: Operator,
        Parent-Sample, Algorithmus-/App-Version, angeforderte Größe, Ersteller)."""
        percent = (
            sample.actual_size / sample.population_size * 100.0 if sample.population_size else 0.0
        )
        provenance = SamplingProvenance.from_sample_result(
            sample, dataset_id=dataset_id, app_version=__version__
        )
        event = AuditEvent(
            event_type="sampling",
            engagement_id=self.engagement_id,
            user_name=self.user_name,
            sample_id=sample_id,
            sample_size=sample.actual_size,
            sample_percent=percent,
            total_count=sample.population_size,
            seed=sample.config.seed,
            details=provenance.to_audit_details(),
        )
        return self.repo.log(event)

    # ---- Import / Export ------------------------------------------------

    def log_import(self, dataset: Dataset) -> AuditEvent:
        """Datenimport – Datei, Zeilenzahl, Spaltennamen."""
        details: dict[str, Any] = {
            "dataset_name": dataset.name,
            "columns": list(dataset.columns),
            "dataset_id": dataset.id,
        }
        event = AuditEvent(
            event_type="import",
            engagement_id=self.engagement_id,
            user_name=self.user_name,
            import_file=dataset.source_file,
            total_count=len(dataset),
            details=details,
        )
        return self.repo.log(event)

    def log_export(
        self,
        sample_id: int,
        export_file: Path,
        row_count: int,
    ) -> AuditEvent:
        """Export einer Stichprobe – Ziel-Datei und exportierte Zeilenzahl."""
        event = AuditEvent(
            event_type="export",
            engagement_id=self.engagement_id,
            user_name=self.user_name,
            sample_id=sample_id,
            sample_size=row_count,
            export_file=str(export_file),
        )
        return self.repo.log(event)

    # ---- Undo / Redo / Reset -------------------------------------------

    def log_undo(self, sample_id: int | None) -> AuditEvent:
        """Undo einer Stichproben-Aktion. `sample_id=None` beim Undo auf den
        leeren Zielzustand (z. B. die allererste Ziehung) – der Event wird
        trotzdem geschrieben (ISAE-3402: jede Undo-Aktion ist trailpflichtig)."""
        event = AuditEvent(
            event_type="undo",
            engagement_id=self.engagement_id,
            user_name=self.user_name,
            sample_id=sample_id,
            details={"restored": "empty"} if sample_id is None else {},
        )
        return self.repo.log(event)

    def log_redo(self, sample_id: int | None) -> AuditEvent:
        """Redo einer rückgängig gemachten Aktion. `sample_id=None` analog `log_undo`."""
        event = AuditEvent(
            event_type="redo",
            engagement_id=self.engagement_id,
            user_name=self.user_name,
            sample_id=sample_id,
            details={"restored": "empty"} if sample_id is None else {},
        )
        return self.repo.log(event)

    def log_reset(self, dataset_id: int) -> AuditEvent:
        """Reset eines Datasets (alle Auswahlmarkierungen zurücksetzen)."""
        event = AuditEvent(
            event_type="reset",
            engagement_id=self.engagement_id,
            user_name=self.user_name,
            details={"dataset_id": dataset_id},
        )
        return self.repo.log(event)

    # ---- Korrektur ------------------------------------------------------

    def log_correction(self, original_event_id: int, reason: str) -> AuditEvent:
        """Korrigiert einen vorherigen Event (append-only Schema-konform)."""
        correction = AuditEvent(
            event_type="correction",
            engagement_id=self.engagement_id,
            user_name=self.user_name,
            details={"reason": reason},
            corrects_event_id=original_event_id,
        )
        return self.repo.correct(original_event_id, correction)
