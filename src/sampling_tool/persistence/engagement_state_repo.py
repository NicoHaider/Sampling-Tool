"""EngagementState + EngagementStateRepo – persistierter UI-State (Sprint 19 / F-007-Split)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from sampling_tool.persistence.database import savepoint

# ===========================================================================
# EngagementState – persistierter UI-State pro Engagement (Sprint 8.2)
# ===========================================================================


@dataclass(frozen=True, slots=True)
class EngagementState:
    """Zuletzt aktiver Dataset/Sample + Filter-Status für ein Engagement.

    Wird beim Öffnen eines Engagements gelesen und nach jeder mutierenden
    UI-Aktion (Sample-Auswahl, Dataset-Wechsel, Filter-Toggle, Reset,
    Undo/Redo) per `EngagementStateRepo.upsert` neu geschrieben.
    """

    engagement_id: int
    active_dataset_id: int | None
    active_sample_id: int | None
    filter_active: bool
    updated_at: datetime


class EngagementStateRepo:
    """Genau eine Zeile pro Engagement – `INSERT OR REPLACE` als Upsert."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, engagement_id: int) -> EngagementState | None:
        """Liefert den State oder `None`, falls noch keiner persistiert wurde."""
        row = self.conn.execute(
            "SELECT engagement_id, active_dataset_id, active_sample_id, "
            "       filter_active, updated_at "
            "FROM engagement_state WHERE engagement_id = ?",
            (engagement_id,),
        ).fetchone()
        if row is None:
            return None
        return EngagementState(
            engagement_id=row["engagement_id"],
            active_dataset_id=row["active_dataset_id"],
            active_sample_id=row["active_sample_id"],
            filter_active=bool(row["filter_active"]),
            updated_at=row["updated_at"],
        )

    def upsert(
        self,
        engagement_id: int,
        active_dataset_id: int | None,
        active_sample_id: int | None,
        filter_active: bool,
    ) -> EngagementState:
        """Schreibt den State – ersetzt eine ggf. existierende Zeile atomar."""
        now = datetime.now(UTC)
        with savepoint(self.conn, "engagement_state_upsert"):
            self.conn.execute(
                "INSERT INTO engagement_state "
                "  (engagement_id, active_dataset_id, active_sample_id, "
                "   filter_active, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(engagement_id) DO UPDATE SET "
                "  active_dataset_id = excluded.active_dataset_id, "
                "  active_sample_id  = excluded.active_sample_id, "
                "  filter_active     = excluded.filter_active, "
                "  updated_at        = excluded.updated_at",
                (
                    engagement_id,
                    active_dataset_id,
                    active_sample_id,
                    1 if filter_active else 0,
                    now,
                ),
            )
        return EngagementState(
            engagement_id=engagement_id,
            active_dataset_id=active_dataset_id,
            active_sample_id=active_sample_id,
            filter_active=filter_active,
            updated_at=now,
        )

    def clear(self, engagement_id: int) -> None:
        """Entfernt den State (z. B. wenn das Engagement zurückgesetzt wird)."""
        with savepoint(self.conn, "engagement_state_clear"):
            self.conn.execute(
                "DELETE FROM engagement_state WHERE engagement_id = ?",
                (engagement_id,),
            )
