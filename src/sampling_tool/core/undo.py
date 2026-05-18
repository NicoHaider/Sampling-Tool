"""Undo-/Redo-Manager (pure Logik, persistente Operationen via Protocol).

Standard-Editor-Verhalten:
- `push` legt einen neuen Snapshot oben auf den Undo-Stack und LÖSCHT den Redo-Stack.
- `undo` verschiebt das oberste Undo-Element auf den Redo-Stack.
- `redo` verschiebt das oberste Redo-Element zurück auf den Undo-Stack.

Die Stack-Tiefe ist auf `MAX_DEPTH = 20` begrenzt; ältere Einträge werden FIFO
verworfen. Snapshots überleben Connection-Wechsel, sofern der konkrete Repo
(z. B. `sampling_tool.persistence.repositories.UndoRepo`) sie persistiert.

Sprint 12.2 / F-002: Persistenz-Operationen wurden aus dieser Datei in
`UndoRepo` (persistence-Layer) ausgelagert. `core/undo.py` ist seitdem
SQL-frei und nutzt keine `sqlite3`-/`Database`-Imports mehr – das entspricht
dem Layer-Modell aus CLAUDE.md, in dem `core/` ausschließlich stdlib +
numpy nutzen darf. Repo-Aufrufe gehen über `UndoRepoProtocol` (PEP 544),
damit Unit-Tests einen In-Memory-Fake bauen können statt SQLite hochzuziehen.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Protocol

from sampling_tool.core.models import Snapshot, UndoStack


class UndoRepoProtocol(Protocol):
    """Minimal-Schnittstelle für den persistenten Stack-Speicher.

    Atomare Multi-Statement-Operationen (`move_top`, `push_snapshot` +
    nachgelagerter Trim) müssen vom Repo selbst transaktionssicher
    umgesetzt werden – der Manager macht nur die Stack-Logik.
    """

    def push_snapshot(
        self,
        stack: UndoStack,
        sample_id: int | None,
        visible_rows: Sequence[int],
        highlighted_rows: Sequence[int],
    ) -> Snapshot:
        """Neuen Snapshot oben auf `stack` legen, persistierte Row inkl. id."""
        ...

    def peek(self, stack: UndoStack) -> Snapshot | None:
        """Top-Snapshot von `stack` ohne Modifikation."""
        ...

    def move_top(
        self,
        from_stack: UndoStack,
        to_stack: UndoStack,
    ) -> Snapshot | None:
        """Top von `from_stack` atomar auf `to_stack` verschieben."""
        ...

    def clear_stack(self, stack: UndoStack) -> None:
        """Alle Snapshots in `stack` löschen."""
        ...

    def clear_all(self) -> None:
        """Beide Stacks komplett leeren."""
        ...

    def count(self, stack: UndoStack) -> int:
        """Anzahl Snapshots in `stack`."""
        ...

    def trim_to_depth(self, stack: UndoStack, max_depth: int) -> None:
        """FIFO-Trim: ältere Snapshots oberhalb `max_depth` löschen."""
        ...


class UndoManager:
    """Persistierter Undo-/Redo-Stack pro Engagement (pure Logik).

    Persistenz wird via `UndoRepoProtocol` injiziert – der Manager kennt
    keine DB-Details. Production-Caller übergibt eine
    `sampling_tool.persistence.repositories.UndoRepo`-Instanz, Tests
    können einen In-Memory-Fake bauen.
    """

    MAX_DEPTH: Final[int] = 20

    def __init__(self, repo: UndoRepoProtocol, max_depth: int = MAX_DEPTH) -> None:
        self._repo = repo
        self._max_depth = max_depth

    # ---- Public API -----------------------------------------------------

    def push(
        self,
        sample_id: int | None,
        visible_rows: Sequence[int],
        highlighted_rows: Sequence[int],
    ) -> Snapshot:
        """Neuer Snapshot auf den Undo-Stack; Redo-Stack wird gelöscht."""
        self._repo.clear_stack(UndoStack.REDO)
        snapshot = self._repo.push_snapshot(
            UndoStack.UNDO,
            sample_id,
            visible_rows,
            highlighted_rows,
        )
        self._repo.trim_to_depth(UndoStack.UNDO, self._max_depth)
        return snapshot

    def undo(self) -> Snapshot | None:
        """Top-Element vom Undo-Stack auf den Redo-Stack verschieben."""
        return self._repo.move_top(from_stack=UndoStack.UNDO, to_stack=UndoStack.REDO)

    def redo(self) -> Snapshot | None:
        """Top-Element vom Redo-Stack auf den Undo-Stack verschieben."""
        return self._repo.move_top(from_stack=UndoStack.REDO, to_stack=UndoStack.UNDO)

    def can_undo(self) -> bool:
        return self._repo.count(UndoStack.UNDO) > 0

    def can_redo(self) -> bool:
        return self._repo.count(UndoStack.REDO) > 0

    def peek_undo(self) -> Snapshot | None:
        """Top des Undo-Stacks (ohne ihn zu verändern). Wird vom UI-Controller
        nach `undo()` benötigt, um den darunterliegenden Zustand zu rekonstruieren.
        """
        return self._repo.peek(UndoStack.UNDO)

    def peek_redo(self) -> Snapshot | None:
        """Top des Redo-Stacks (ohne ihn zu verändern)."""
        return self._repo.peek(UndoStack.REDO)

    def clear(self) -> None:
        """Beide Stacks komplett leeren."""
        self._repo.clear_all()
