"""AuditRepo – append-only Audit-Log (Sprint 19 / F-007-Split)."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from typing import Any

from sampling_tool.core.models import AuditEvent
from sampling_tool.persistence._json import _json_dumps, _json_loads


class AuditRepo:
    """Append-only Audit-Log. UPDATE/DELETE werden vom DB-Trigger geblockt."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def log(self, event: AuditEvent) -> AuditEvent:
        """Schreibt einen neuen Audit-Eintrag und gibt ihn mit gesetzter `id` zurück."""
        if event.engagement_id is None:
            raise ValueError("AuditEvent.engagement_id muss gesetzt sein.")

        cur = self.conn.execute(
            "INSERT INTO audit_events "
            "(engagement_id, timestamp, event_type, user_name, sample_id, "
            " sample_size, sample_percent, total_count, seed, import_file, "
            " export_file, details_json, corrects_event_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.engagement_id,
                event.timestamp,
                event.event_type,
                event.user_name,
                event.sample_id,
                event.sample_size,
                event.sample_percent,
                event.total_count,
                event.seed,
                event.import_file,
                event.export_file,
                _json_dumps(event.details) if event.details else None,
                event.corrects_event_id,
            ),
        )
        return replace(event, id=cur.lastrowid)

    def list_for_engagement(
        self,
        engagement_id: int,
        limit: int = 100,
    ) -> list[AuditEvent]:
        cursor = self.conn.execute(
            "SELECT * FROM audit_events WHERE engagement_id = ? "
            "ORDER BY timestamp DESC, id DESC LIMIT ?",
            (engagement_id, limit),
        )
        return [self._to_model(r) for r in cursor]

    def correct(self, original_id: int, corrected_event: AuditEvent) -> AuditEvent:
        """Schreibt einen Korrektur-Event (event_type='correction', verweist auf Original)."""
        patched = replace(
            corrected_event,
            event_type="correction",
            corrects_event_id=original_id,
        )
        return self.log(patched)

    # ---- intern ---------------------------------------------------------

    @staticmethod
    def _to_model(row: sqlite3.Row) -> AuditEvent:
        details_raw = row["details_json"]
        details: dict[str, Any] = _json_loads(details_raw) if details_raw else {}
        return AuditEvent(
            event_type=row["event_type"],
            engagement_id=row["engagement_id"],
            user_name=row["user_name"],
            timestamp=row["timestamp"],
            sample_id=row["sample_id"],
            sample_size=row["sample_size"],
            sample_percent=row["sample_percent"],
            total_count=row["total_count"],
            seed=row["seed"],
            import_file=row["import_file"],
            export_file=row["export_file"],
            details=details,
            corrects_event_id=row["corrects_event_id"],
            id=row["id"],
        )
