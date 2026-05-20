"""Repositories – dünn, stateless, mappen Dataclasses ↔ SQLite-Rows.

Konventionen:
- Jede Repo-Klasse bekommt eine offene `sqlite3.Connection` im Konstruktor.
- Multi-Statement-Operationen laufen in einem `savepoint()` (nestbar).
- SQL ausschließlich mit `?`-Parameter-Binding – nie f-string-zusammengebaut.
- Reads liefern Domain-Modelle, nicht `sqlite3.Row`.
- `details_json`, `columns_json`, `values_json` sind JSON-serialisiert.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sampling_tool.core.models import (
    Snapshot,
    UndoStack,
)
from sampling_tool.persistence._json import (
    _json_dumps,
    _json_loads,
)
from sampling_tool.persistence._json import (
    _values_from_json as _values_from_json,
)
from sampling_tool.persistence._json import (
    _values_to_json as _values_to_json,
)
from sampling_tool.persistence.audit_repo import AuditRepo as AuditRepo
from sampling_tool.persistence.database import savepoint
from sampling_tool.persistence.dataset_repo import DatasetRepo as DatasetRepo
from sampling_tool.persistence.engagement_repo import EngagementRepo as EngagementRepo
from sampling_tool.persistence.sample_repo import SampleRepo as SampleRepo

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


# ===========================================================================
# Undo / Redo Snapshots (Sprint 12.2 / F-002)
# ===========================================================================


class UndoRepo:
    """SQL-Implementation der `UndoRepoProtocol` aus `core.undo`.

    Sprint 12.2 / F-002: vorher war die SQL-Logik direkt in
    `core/undo.py` – das verletzte das Layer-Modell (core soll SQL-frei
    sein). Der UndoRepo nimmt jetzt alle persistenten Operationen,
    `UndoManager` arbeitet nur noch auf der Protocol-Schnittstelle.

    Eine `UndoRepo`-Instanz ist an genau ein Engagement gebunden (im
    Konstruktor). Damit kann der Manager engagement-agnostisch bleiben.
    Atomare Multi-Statement-Operationen (`move_top`, `push_snapshot` +
    Trim) laufen in `savepoint()`-Blöcken.
    """

    def __init__(self, conn: sqlite3.Connection, engagement_id: int) -> None:
        self.conn = conn
        self.engagement_id = engagement_id

    def push_snapshot(
        self,
        stack: UndoStack,
        sample_id: int | None,
        visible_rows: Sequence[int],
        highlighted_rows: Sequence[int],
    ) -> Snapshot:
        """Neuen Snapshot oben auf `stack` legen. Liefert die persistierte Row inkl. id."""
        with savepoint(self.conn, "undo_push_snapshot"):
            position = self._next_position(stack)
            cur = self.conn.execute(
                "INSERT INTO undo_snapshots "
                "(engagement_id, stack_type, position, sample_id, "
                " visible_rows, highlighted_rows) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self.engagement_id,
                    stack.value,
                    position,
                    sample_id,
                    _json_dumps(list(visible_rows)),
                    _json_dumps(list(highlighted_rows)),
                ),
            )
            new_id = cur.lastrowid

        return Snapshot(
            stack_type=stack,
            position=position,
            visible_rows=tuple(visible_rows),
            highlighted_rows=tuple(highlighted_rows),
            sample_id=sample_id,
            engagement_id=self.engagement_id,
            id=new_id,
        )

    def peek(self, stack: UndoStack) -> Snapshot | None:
        """Top-Snapshot von `stack` ohne Modifikation. None bei leerem Stack."""
        row = self.conn.execute(
            "SELECT * FROM undo_snapshots "
            "WHERE engagement_id = ? AND stack_type = ? "
            "ORDER BY position DESC LIMIT 1",
            (self.engagement_id, stack.value),
        ).fetchone()
        return self._row_to_snapshot(row, stack) if row is not None else None

    def move_top(
        self,
        from_stack: UndoStack,
        to_stack: UndoStack,
    ) -> Snapshot | None:
        """Top-Snapshot von `from_stack` atomar auf `to_stack` verschieben.

        Wichtig: `created_at` der Original-Row wird beibehalten, damit
        ein Snapshot beim Hin-und-Her-Wandern zwischen Undo- und
        Redo-Stack seine ursprüngliche Entstehungszeit nicht verliert
        (Audit-Trail-Relevanz).
        """
        row = self.conn.execute(
            "SELECT * FROM undo_snapshots "
            "WHERE engagement_id = ? AND stack_type = ? "
            "ORDER BY position DESC LIMIT 1",
            (self.engagement_id, from_stack.value),
        ).fetchone()
        if row is None:
            return None

        with savepoint(self.conn, "undo_move_top"):
            self.conn.execute("DELETE FROM undo_snapshots WHERE id = ?", (row["id"],))
            new_position = self._next_position(to_stack)
            cur = self.conn.execute(
                "INSERT INTO undo_snapshots "
                "(engagement_id, stack_type, position, sample_id, "
                " visible_rows, highlighted_rows, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    self.engagement_id,
                    to_stack.value,
                    new_position,
                    row["sample_id"],
                    row["visible_rows"],
                    row["highlighted_rows"],
                    row["created_at"],
                ),
            )
            new_id = cur.lastrowid

        return Snapshot(
            stack_type=to_stack,
            position=new_position,
            visible_rows=tuple(_json_loads(row["visible_rows"])),
            highlighted_rows=tuple(_json_loads(row["highlighted_rows"])),
            sample_id=row["sample_id"],
            engagement_id=self.engagement_id,
            created_at=row["created_at"],
            id=new_id,
        )

    def clear_stack(self, stack: UndoStack) -> None:
        """Alle Snapshots in `stack` löschen."""
        with savepoint(self.conn, "undo_clear_stack"):
            self.conn.execute(
                "DELETE FROM undo_snapshots WHERE engagement_id = ? AND stack_type = ?",
                (self.engagement_id, stack.value),
            )

    def clear_all(self) -> None:
        """Beide Stacks komplett leeren."""
        with savepoint(self.conn, "undo_clear_all"):
            self.conn.execute(
                "DELETE FROM undo_snapshots WHERE engagement_id = ?",
                (self.engagement_id,),
            )

    def count(self, stack: UndoStack) -> int:
        """Anzahl Snapshots in `stack`."""
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM undo_snapshots WHERE engagement_id = ? AND stack_type = ?",
            (self.engagement_id, stack.value),
        ).fetchone()
        return int(row["c"])

    def trim_to_depth(self, stack: UndoStack, max_depth: int) -> None:
        """FIFO-Trim: ältere Snapshots oberhalb von `max_depth` löschen."""
        excess = self.count(stack) - max_depth
        if excess <= 0:
            return
        self.conn.execute(
            "DELETE FROM undo_snapshots WHERE id IN ("
            "  SELECT id FROM undo_snapshots "
            "  WHERE engagement_id = ? AND stack_type = ? "
            "  ORDER BY position ASC LIMIT ?"
            ")",
            (self.engagement_id, stack.value, excess),
        )

    # ---- intern ---------------------------------------------------------

    def _next_position(self, stack: UndoStack) -> int:
        row = self.conn.execute(
            "SELECT MAX(position) AS p FROM undo_snapshots "
            "WHERE engagement_id = ? AND stack_type = ?",
            (self.engagement_id, stack.value),
        ).fetchone()
        return (int(row["p"]) + 1) if row["p"] is not None else 1

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row, stack: UndoStack) -> Snapshot:
        return Snapshot(
            stack_type=stack,
            position=row["position"],
            visible_rows=tuple(_json_loads(row["visible_rows"])),
            highlighted_rows=tuple(_json_loads(row["highlighted_rows"])),
            sample_id=row["sample_id"],
            engagement_id=row["engagement_id"],
            created_at=row["created_at"],
            id=row["id"],
        )
