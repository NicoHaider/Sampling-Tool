"""Unit-Tests für `UndoManager` – DB-frei via `FakeUndoRepo`.

Sprint 12.2 / F-002: `UndoManager` arbeitet auf der
`UndoRepoProtocol`-Schnittstelle und braucht keine SQLite mehr.
Diese Tests verifizieren die Stack-Konventionen (push-leert-Redo,
Trim auf MAX_DEPTH, can_undo/can_redo) ohne den `tmp_path`-Overhead
des Integration-Tests.

Das End-to-End-Zusammenspiel mit SQLite ist in
`tests/integration/test_undo_manager.py` getestet.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from sampling_tool.core.models import Snapshot, UndoStack
from sampling_tool.core.undo import UndoManager


@dataclass
class FakeUndoRepo:
    """In-Memory-Implementation von `UndoRepoProtocol` für DB-freie Tests."""

    engagement_id: int = 42
    _stacks: dict[UndoStack, list[Snapshot]] = field(default_factory=dict)
    _next_id: int = 1

    def __post_init__(self) -> None:
        self._stacks = {UndoStack.UNDO: [], UndoStack.REDO: []}

    # ---- Protocol-Methoden ----------------------------------------------

    def push_snapshot(
        self,
        stack: UndoStack,
        sample_id: int | None,
        visible_rows: Sequence[int],
        highlighted_rows: Sequence[int],
    ) -> Snapshot:
        position = (self._stacks[stack][-1].position + 1) if self._stacks[stack] else 1
        snap = Snapshot(
            stack_type=stack,
            position=position,
            visible_rows=tuple(visible_rows),
            highlighted_rows=tuple(highlighted_rows),
            sample_id=sample_id,
            engagement_id=self.engagement_id,
            id=self._next_id,
        )
        self._next_id += 1
        self._stacks[stack].append(snap)
        return snap

    def peek(self, stack: UndoStack) -> Snapshot | None:
        return self._stacks[stack][-1] if self._stacks[stack] else None

    def move_top(
        self,
        from_stack: UndoStack,
        to_stack: UndoStack,
    ) -> Snapshot | None:
        if not self._stacks[from_stack]:
            return None
        original = self._stacks[from_stack].pop()
        new_position = self._stacks[to_stack][-1].position + 1 if self._stacks[to_stack] else 1
        moved = Snapshot(
            stack_type=to_stack,
            position=new_position,
            visible_rows=original.visible_rows,
            highlighted_rows=original.highlighted_rows,
            sample_id=original.sample_id,
            engagement_id=original.engagement_id,
            created_at=original.created_at,  # bleibt beim Hin-Wandern erhalten
            id=self._next_id,
        )
        self._next_id += 1
        self._stacks[to_stack].append(moved)
        return moved

    def clear_stack(self, stack: UndoStack) -> None:
        self._stacks[stack].clear()

    def clear_all(self) -> None:
        for s in self._stacks.values():
            s.clear()

    def count(self, stack: UndoStack) -> int:
        return len(self._stacks[stack])

    def trim_to_depth(self, stack: UndoStack, max_depth: int) -> None:
        excess = len(self._stacks[stack]) - max_depth
        if excess > 0:
            del self._stacks[stack][:excess]


# ---------------------------------------------------------------------------
# Manager-Logik
# ---------------------------------------------------------------------------


class TestPushClearsRedo:
    def test_push_leert_redo_stack(self) -> None:
        """Standard-Editor-Verhalten: neuer push verwirft pending redos."""
        mgr = UndoManager(FakeUndoRepo())
        mgr.push(sample_id=None, visible_rows=[1], highlighted_rows=[])
        mgr.push(sample_id=None, visible_rows=[2], highlighted_rows=[])
        mgr.undo()
        assert mgr.can_redo() is True

        mgr.push(sample_id=None, visible_rows=[3], highlighted_rows=[])
        assert mgr.can_redo() is False


class TestUndoRedoRoundTrip:
    def test_undo_dann_redo_liefert_gleichen_state(self) -> None:
        mgr = UndoManager(FakeUndoRepo())
        mgr.push(sample_id=7, visible_rows=[1, 2, 3], highlighted_rows=[2])
        mgr.push(sample_id=8, visible_rows=[4, 5], highlighted_rows=[])

        undone = mgr.undo()
        assert undone is not None
        assert undone.visible_rows == (4, 5)
        assert undone.stack_type == UndoStack.REDO

        redone = mgr.redo()
        assert redone is not None
        assert redone.visible_rows == (4, 5)
        assert redone.sample_id == 8
        assert redone.stack_type == UndoStack.UNDO

    def test_undo_auf_leerem_stack_liefert_none(self) -> None:
        mgr = UndoManager(FakeUndoRepo())
        assert mgr.undo() is None
        assert mgr.redo() is None
        assert mgr.can_undo() is False
        assert mgr.can_redo() is False


class TestMaxDepth:
    def test_default_max_depth_ist_20(self) -> None:
        assert UndoManager.MAX_DEPTH == 20

    def test_pushes_oberhalb_max_droppen_aelteste(self) -> None:
        mgr = UndoManager(FakeUndoRepo(), max_depth=5)
        for i in range(10):
            mgr.push(sample_id=None, visible_rows=[i], highlighted_rows=[])

        # 10 pushes, depth=5 → die ältesten 5 (i=0..4) wurden verworfen
        top = mgr.peek_undo()
        assert top is not None
        assert top.visible_rows == (9,)
        # Stack-Größe genau auf max_depth limitiert
        assert sum(1 for _ in iter(mgr.undo, None)) == 5

    def test_aelteste_zuerst_geworfen(self) -> None:
        repo = FakeUndoRepo()
        mgr = UndoManager(repo, max_depth=3)
        for i in range(5):
            mgr.push(sample_id=None, visible_rows=[i], highlighted_rows=[])

        # Erwartung: i=0, i=1 raus; i=2, i=3, i=4 drin
        remaining = [s.visible_rows[0] for s in repo._stacks[UndoStack.UNDO]]
        assert remaining == [2, 3, 4]


class TestPeek:
    def test_peek_undo_aendert_stack_nicht(self) -> None:
        mgr = UndoManager(FakeUndoRepo())
        mgr.push(sample_id=None, visible_rows=[1], highlighted_rows=[])

        snap_a = mgr.peek_undo()
        snap_b = mgr.peek_undo()
        assert snap_a is not None
        assert snap_b is not None
        assert snap_a.visible_rows == snap_b.visible_rows
        assert mgr.can_undo() is True

    def test_peek_auf_leerem_stack(self) -> None:
        mgr = UndoManager(FakeUndoRepo())
        assert mgr.peek_undo() is None
        assert mgr.peek_redo() is None


class TestClear:
    def test_clear_leert_beide_stacks(self) -> None:
        mgr = UndoManager(FakeUndoRepo())
        mgr.push(sample_id=None, visible_rows=[1], highlighted_rows=[])
        mgr.push(sample_id=None, visible_rows=[2], highlighted_rows=[])
        mgr.undo()  # ein Element wandert in Redo

        mgr.clear()
        assert mgr.can_undo() is False
        assert mgr.can_redo() is False


class TestProtocolStructural:
    """Strukturelle Verifikation: FakeUndoRepo erfüllt das Protocol."""

    def test_fake_repo_ist_strukturell_kompatibel(self) -> None:
        from sampling_tool.core.undo import UndoRepoProtocol

        repo: UndoRepoProtocol = FakeUndoRepo()
        # mypy/pyright reicht – zur Laufzeit reicht eine triviale Assertion.
        assert repo is not None


class TestPushReturnsSnapshot:
    def test_push_liefert_snapshot_mit_id(self) -> None:
        mgr = UndoManager(FakeUndoRepo())
        snap = mgr.push(sample_id=42, visible_rows=[1, 2], highlighted_rows=[1])
        assert snap.sample_id == 42
        assert snap.visible_rows == (1, 2)
        assert snap.highlighted_rows == (1,)
        assert snap.stack_type == UndoStack.UNDO
        assert snap.id is not None


class TestCustomMaxDepth:
    @pytest.mark.parametrize("depth", [1, 5, 100])
    def test_custom_depth_wird_respektiert(self, depth: int) -> None:
        repo = FakeUndoRepo()
        mgr = UndoManager(repo, max_depth=depth)
        for i in range(depth + 3):
            mgr.push(sample_id=None, visible_rows=[i], highlighted_rows=[])
        assert repo.count(UndoStack.UNDO) == depth
