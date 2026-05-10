"""Undo-/Redo-Manager mit SQLite-Persistenz.

Standard-Editor-Verhalten:
- `push` legt einen neuen Snapshot oben auf den Undo-Stack und LÖSCHT den Redo-Stack.
- `undo` verschiebt das oberste Undo-Element auf den Redo-Stack.
- `redo` verschiebt das oberste Redo-Element zurück auf den Undo-Stack.

Die Stack-Tiefe ist auf `MAX_DEPTH = 20` begrenzt; ältere Einträge werden FIFO
verworfen. Snapshots überleben Connection-Wechsel, weil alles in
`undo_snapshots` persistiert wird (kein In-Memory-State).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Final

from sampling_tool.core.models import Snapshot, UndoStack
from sampling_tool.persistence.database import Database, savepoint


class UndoManager:
    """Persistierter Undo-/Redo-Stack pro Engagement."""

    MAX_DEPTH: Final[int] = 20

    def __init__(self, db: Database, engagement_id: int) -> None:
        self.db = db
        self.engagement_id = engagement_id

    # ---- Public API -----------------------------------------------------

    def push(
        self,
        sample_id: int | None,
        visible_rows: Sequence[int],
        highlighted_rows: Sequence[int],
    ) -> Snapshot:
        """Neuer Snapshot auf den Undo-Stack; Redo-Stack wird gelöscht."""
        conn = self.db.connect()
        with savepoint(conn, "undo_push"):
            conn.execute(
                "DELETE FROM undo_snapshots WHERE engagement_id = ? AND stack_type = ?",
                (self.engagement_id, UndoStack.REDO.value),
            )
            position = self._next_position(UndoStack.UNDO)
            cur = conn.execute(
                "INSERT INTO undo_snapshots "
                "(engagement_id, stack_type, position, sample_id, "
                " visible_rows, highlighted_rows) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self.engagement_id,
                    UndoStack.UNDO.value,
                    position,
                    sample_id,
                    json.dumps(list(visible_rows)),
                    json.dumps(list(highlighted_rows)),
                ),
            )
            new_id = cur.lastrowid
            self._enforce_max_depth(UndoStack.UNDO)

        return Snapshot(
            stack_type=UndoStack.UNDO,
            position=position,
            visible_rows=tuple(visible_rows),
            highlighted_rows=tuple(highlighted_rows),
            sample_id=sample_id,
            engagement_id=self.engagement_id,
            id=new_id,
        )

    def undo(self) -> Snapshot | None:
        """Top-Element vom Undo-Stack auf den Redo-Stack verschieben."""
        return self._move_top(from_stack=UndoStack.UNDO, to_stack=UndoStack.REDO)

    def redo(self) -> Snapshot | None:
        """Top-Element vom Redo-Stack auf den Undo-Stack verschieben."""
        return self._move_top(from_stack=UndoStack.REDO, to_stack=UndoStack.UNDO)

    def can_undo(self) -> bool:
        return self._stack_size(UndoStack.UNDO) > 0

    def can_redo(self) -> bool:
        return self._stack_size(UndoStack.REDO) > 0

    def clear(self) -> None:
        """Beide Stacks komplett leeren."""
        conn = self.db.connect()
        with savepoint(conn, "undo_clear"):
            conn.execute(
                "DELETE FROM undo_snapshots WHERE engagement_id = ?",
                (self.engagement_id,),
            )

    # ---- intern ---------------------------------------------------------

    def _move_top(self, from_stack: UndoStack, to_stack: UndoStack) -> Snapshot | None:
        conn = self.db.connect()
        row = conn.execute(
            "SELECT * FROM undo_snapshots "
            "WHERE engagement_id = ? AND stack_type = ? "
            "ORDER BY position DESC LIMIT 1",
            (self.engagement_id, from_stack.value),
        ).fetchone()
        if row is None:
            return None

        with savepoint(conn, "undo_move"):
            conn.execute("DELETE FROM undo_snapshots WHERE id = ?", (row["id"],))
            new_position = self._next_position(to_stack)
            cur = conn.execute(
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
            visible_rows=tuple(json.loads(row["visible_rows"])),
            highlighted_rows=tuple(json.loads(row["highlighted_rows"])),
            sample_id=row["sample_id"],
            engagement_id=self.engagement_id,
            created_at=row["created_at"],
            id=new_id,
        )

    def _next_position(self, stack: UndoStack) -> int:
        row = (
            self.db.connect()
            .execute(
                "SELECT MAX(position) AS p FROM undo_snapshots "
                "WHERE engagement_id = ? AND stack_type = ?",
                (self.engagement_id, stack.value),
            )
            .fetchone()
        )
        return (int(row["p"]) + 1) if row["p"] is not None else 1

    def _stack_size(self, stack: UndoStack) -> int:
        row = (
            self.db.connect()
            .execute(
                "SELECT COUNT(*) AS c FROM undo_snapshots "
                "WHERE engagement_id = ? AND stack_type = ?",
                (self.engagement_id, stack.value),
            )
            .fetchone()
        )
        return int(row["c"])

    def _enforce_max_depth(self, stack: UndoStack) -> None:
        """FIFO-Trimm: ältere Snapshots oberhalb des Limits löschen."""
        size = self._stack_size(stack)
        excess = size - self.MAX_DEPTH
        if excess <= 0:
            return
        self.db.connect().execute(
            "DELETE FROM undo_snapshots WHERE id IN ("
            "  SELECT id FROM undo_snapshots "
            "  WHERE engagement_id = ? AND stack_type = ? "
            "  ORDER BY position ASC LIMIT ?"
            ")",
            (self.engagement_id, stack.value, excess),
        )
