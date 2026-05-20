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
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from sampling_tool.core.models import (
    AuditEvent,
    SampleConfig,
    SampleResult,
    SamplingMethod,
    Snapshot,
    StratifyMode,
    UndoStack,
)
from sampling_tool.persistence._json import (
    _json_dumps,
    _json_loads,
    _json_or_none,
    _json_or_none_load,
)
from sampling_tool.persistence._json import (
    _values_from_json as _values_from_json,
)
from sampling_tool.persistence._json import (
    _values_to_json as _values_to_json,
)
from sampling_tool.persistence.database import savepoint
from sampling_tool.persistence.dataset_repo import DatasetRepo as DatasetRepo
from sampling_tool.persistence.engagement_repo import EngagementRepo as EngagementRepo

# ===========================================================================
# Sample
# ===========================================================================


class SampleRepo:
    """Persistiert SampleResults + die ausgewählten row_ids in `sample_rows`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create_from_result(
        self,
        result: SampleResult,
        dataset_id: int,
        created_by: str,
    ) -> int:
        """Speichert die Ziehung; gibt die DB-id der `samples`-Zeile zurück."""
        cfg = result.config
        with savepoint(self.conn, "sample_create"):
            cur = self.conn.execute(
                "INSERT INTO samples "
                "(dataset_id, method, sample_size, population_size, seed, "
                " filter_field, filter_value, cluster_field, stratum_field, "
                " stratify_mode, parent_sample_id, created_at, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    dataset_id,
                    cfg.method.value,
                    cfg.size,
                    result.population_size,
                    cfg.seed,
                    cfg.filter_field,
                    _json_or_none(cfg.filter_value),
                    cfg.cluster_field,
                    cfg.stratum_field,
                    cfg.stratify_mode.value,
                    result.parent_sample_id,
                    result.drawn_at,
                    created_by,
                ),
            )
            sample_id = cur.lastrowid
            assert sample_id is not None

            if result.selected_row_ids:
                self.conn.executemany(
                    "INSERT INTO sample_rows (sample_id, row_id) VALUES (?, ?)",
                    [(sample_id, row_id) for row_id in result.selected_row_ids],
                )

        return sample_id

    def get_by_id(self, sample_id: int) -> SampleResult | None:
        row = self.conn.execute("SELECT * FROM samples WHERE id = ?", (sample_id,)).fetchone()
        if row is None:
            return None

        row_ids = tuple(
            r["row_id"]
            for r in self.conn.execute(
                "SELECT row_id FROM sample_rows WHERE sample_id = ? ORDER BY row_id",
                (sample_id,),
            )
        )
        return self._to_model(row, row_ids)

    def list_for_dataset(self, dataset_id: int) -> list[SampleResult]:
        sample_rows = self.conn.execute(
            "SELECT * FROM samples WHERE dataset_id = ? ORDER BY created_at DESC",
            (dataset_id,),
        ).fetchall()
        results: list[SampleResult] = []
        for row in sample_rows:
            ids = tuple(
                r["row_id"]
                for r in self.conn.execute(
                    "SELECT row_id FROM sample_rows WHERE sample_id = ? ORDER BY row_id",
                    (row["id"],),
                )
            )
            results.append(self._to_model(row, ids))
        return results

    # ---- intern ---------------------------------------------------------

    @staticmethod
    def _to_model(row: sqlite3.Row, selected_row_ids: tuple[int, ...]) -> SampleResult:
        config = SampleConfig(
            method=SamplingMethod(row["method"]),
            size=row["sample_size"],
            seed=row["seed"],
            cluster_field=row["cluster_field"],
            stratum_field=row["stratum_field"],
            stratify_mode=(
                StratifyMode(row["stratify_mode"])
                if row["stratify_mode"]
                else StratifyMode.PROPORTIONAL
            ),
            filter_field=row["filter_field"],
            filter_value=_json_or_none_load(row["filter_value"]),
        )
        return SampleResult(
            config=config,
            selected_row_ids=selected_row_ids,
            population_size=row["population_size"],
            drawn_at=row["created_at"],
            parent_sample_id=row["parent_sample_id"],
            created_by=row["created_by"],
            id=row["id"],
        )


# ===========================================================================
# Audit
# ===========================================================================


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
