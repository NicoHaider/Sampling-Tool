"""Integration: UndoManager + UndoRepo – persistierter Undo-/Redo-Stack.

Sprint 12.2 / F-002: `UndoManager` ist jetzt SQL-frei und delegiert an
`UndoRepo`. Diese Tests verifizieren das End-to-End-Zusammenspiel
(Manager → Repo → SQLite). DB-freie Manager-Logik-Tests siehe
`tests/unit/test_undo.py`.
"""

from __future__ import annotations

from pathlib import Path

from sampling_tool.core.models import Engagement, UndoStack
from sampling_tool.core.undo import UndoManager
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import EngagementRepo, UndoRepo


def _mgr(db: Database, engagement_id: int) -> UndoManager:
    """Production-Konstruktion: UndoManager mit echter UndoRepo."""
    return UndoManager(UndoRepo(db.connect(), engagement_id))


class TestPushUndoRedo:
    def test_push_creates_undo_snapshot(
        self, db: Database, engagement_id: int, sample_id: int
    ) -> None:
        mgr = _mgr(db, engagement_id)
        snap = mgr.push(sample_id=sample_id, visible_rows=[1, 2, 3], highlighted_rows=[2])
        assert snap.stack_type == UndoStack.UNDO
        assert snap.visible_rows == (1, 2, 3)
        assert snap.highlighted_rows == (2,)
        assert snap.sample_id == sample_id
        assert mgr.can_undo() is True
        assert mgr.can_redo() is False

    def test_undo_then_redo_cycle(self, db: Database, engagement_id: int) -> None:
        mgr = _mgr(db, engagement_id)
        # sample_id=None ist erlaubt – Spalte ist nullable.
        mgr.push(sample_id=None, visible_rows=[1, 2], highlighted_rows=[])
        mgr.push(sample_id=None, visible_rows=[3, 4], highlighted_rows=[])

        undone = mgr.undo()
        assert undone is not None
        assert undone.stack_type == UndoStack.REDO
        assert undone.visible_rows == (3, 4)
        assert mgr.can_redo() is True

        redone = mgr.redo()
        assert redone is not None
        assert redone.stack_type == UndoStack.UNDO
        assert redone.visible_rows == (3, 4)
        assert mgr.can_redo() is False

    def test_undo_on_empty_stack_returns_none(self, db: Database, engagement_id: int) -> None:
        mgr = _mgr(db, engagement_id)
        assert mgr.undo() is None
        assert mgr.redo() is None

    def test_push_clears_redo_stack(self, db: Database, engagement_id: int) -> None:
        mgr = _mgr(db, engagement_id)
        mgr.push(sample_id=None, visible_rows=[1], highlighted_rows=[])
        mgr.push(sample_id=None, visible_rows=[2], highlighted_rows=[])
        mgr.undo()  # zweiter Push wandert in den Redo-Stack
        assert mgr.can_redo() is True

        mgr.push(sample_id=None, visible_rows=[3], highlighted_rows=[])
        # Standard-Editor-Verhalten: ein neuer push leert den Redo-Stack
        assert mgr.can_redo() is False

    def test_clear_empties_both_stacks(self, db: Database, engagement_id: int) -> None:
        mgr = _mgr(db, engagement_id)
        mgr.push(sample_id=None, visible_rows=[1], highlighted_rows=[])
        mgr.push(sample_id=None, visible_rows=[2], highlighted_rows=[])
        mgr.undo()
        mgr.clear()
        assert mgr.can_undo() is False
        assert mgr.can_redo() is False


class TestMaxDepth:
    def test_pushes_above_max_drop_oldest(self, db: Database, engagement_id: int) -> None:
        mgr = _mgr(db, engagement_id)
        for i in range(UndoManager.MAX_DEPTH + 5):
            mgr.push(sample_id=None, visible_rows=[i], highlighted_rows=[])

        count = (
            db.connect()
            .execute(
                "SELECT COUNT(*) AS c FROM undo_snapshots "
                "WHERE engagement_id = ? AND stack_type = 'undo'",
                (engagement_id,),
            )
            .fetchone()
        )
        assert count["c"] == UndoManager.MAX_DEPTH

        # Top-Snapshot ist der zuletzt gepushte (visible_rows enthält i).
        top = mgr.undo()
        assert top is not None
        assert top.visible_rows == (UndoManager.MAX_DEPTH + 4,)

    def test_oldest_pushed_is_dropped_first(self, db: Database, engagement_id: int) -> None:
        mgr = _mgr(db, engagement_id)
        # MAX_DEPTH+1 pushes; visible_rows=[i] dient als Identifier.
        for i in range(UndoManager.MAX_DEPTH + 1):
            mgr.push(sample_id=None, visible_rows=[i], highlighted_rows=[])

        rows = (
            db.connect()
            .execute(
                "SELECT visible_rows FROM undo_snapshots WHERE engagement_id = ?",
                (engagement_id,),
            )
            .fetchall()
        )
        # Aus "[i]" zurückparsen – wir wollen wissen, welche i drinbleiben.
        kept = {int(r["visible_rows"].strip("[]")) for r in rows}
        assert 0 not in kept  # ältester wurde verworfen
        assert UndoManager.MAX_DEPTH in kept  # neuester ist drin


class TestPersistence:
    def test_snapshots_survive_connection_close(self, tmp_path: Path) -> None:
        db_path = tmp_path / "undo.db"

        db1 = Database(db_path)
        db1.migrate()
        eng = EngagementRepo(db1.connect()).get_or_create(
            Engagement(auditor_name="A", client_name="X")
        )
        assert eng.id is not None
        UndoManager(UndoRepo(db1.connect(), eng.id)).push(
            sample_id=None, visible_rows=[1, 2, 3], highlighted_rows=[2]
        )
        db1.close()

        db2 = Database(db_path)
        try:
            mgr = UndoManager(UndoRepo(db2.connect(), eng.id))
            assert mgr.can_undo() is True
            snap = mgr.undo()
            assert snap is not None
            assert snap.visible_rows == (1, 2, 3)
            assert snap.highlighted_rows == (2,)
        finally:
            db2.close()
