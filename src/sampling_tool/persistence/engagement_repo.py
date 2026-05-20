"""EngagementRepo – 1 Zeile pro DB-Datei (Sprint 19 / F-007-Split)."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

from sampling_tool.core.models import Engagement
from sampling_tool.persistence.database import savepoint


class EngagementRepo:
    """1 Zeile pro DB-Datei – `get_or_create` ist die übliche Eintrittstür."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self) -> Engagement | None:
        """Liefert das Engagement der DB (oder `None`, falls noch keins existiert)."""
        row = self.conn.execute("SELECT * FROM engagements ORDER BY id LIMIT 1").fetchone()
        return self._to_model(row) if row is not None else None

    def get_or_create(self, engagement: Engagement) -> Engagement:
        """Idempotent: gibt das vorhandene Engagement zurück oder legt neu an."""
        existing = self.get()
        if existing is not None:
            return existing

        with savepoint(self.conn, "engagement_create"):
            cur = self.conn.execute(
                "INSERT INTO engagements "
                "(auditor_name, auditor_position, client_name, audit_type, "
                " created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    engagement.auditor_name,
                    engagement.auditor_position,
                    engagement.client_name,
                    engagement.audit_type,
                    engagement.created_at,
                    engagement.updated_at,
                ),
            )
        new_id = cur.lastrowid
        return replace(engagement, id=new_id)

    def update_metadata(
        self,
        engagement_id: int,
        *,
        auditor_name: str | None = None,
        auditor_position: str | None = None,
        client_name: str | None = None,
        audit_type: str | None = None,
    ) -> Engagement:
        """Patch-Update einzelner Metadaten-Felder. `updated_at` wird automatisch gesetzt."""
        current = self._get_by_id(engagement_id)
        if current is None:
            raise LookupError(f"Engagement {engagement_id} existiert nicht.")

        new = replace(
            current,
            auditor_name=auditor_name if auditor_name is not None else current.auditor_name,
            auditor_position=auditor_position
            if auditor_position is not None
            else current.auditor_position,
            client_name=client_name if client_name is not None else current.client_name,
            audit_type=audit_type if audit_type is not None else current.audit_type,
            updated_at=datetime.now(UTC),
        )

        with savepoint(self.conn, "engagement_update"):
            self.conn.execute(
                "UPDATE engagements "
                "SET auditor_name=?, auditor_position=?, client_name=?, "
                "    audit_type=?, updated_at=? "
                "WHERE id=?",
                (
                    new.auditor_name,
                    new.auditor_position,
                    new.client_name,
                    new.audit_type,
                    new.updated_at,
                    engagement_id,
                ),
            )
        return new

    # ---- intern ---------------------------------------------------------

    def _get_by_id(self, engagement_id: int) -> Engagement | None:
        row = self.conn.execute(
            "SELECT * FROM engagements WHERE id = ?", (engagement_id,)
        ).fetchone()
        return self._to_model(row) if row is not None else None

    @staticmethod
    def _to_model(row: sqlite3.Row) -> Engagement:
        return Engagement(
            auditor_name=row["auditor_name"],
            auditor_position=row["auditor_position"],
            client_name=row["client_name"],
            audit_type=row["audit_type"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            id=row["id"],
        )
