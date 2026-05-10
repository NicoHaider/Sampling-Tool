"""Repositories – dünn, stateless, mappen Dataclasses ↔ SQLite-Rows.

Konventionen:
- Jede Repo-Klasse bekommt eine offene `sqlite3.Connection` im Konstruktor.
- Multi-Statement-Operationen laufen in einem `savepoint()` (nestbar).
- SQL ausschließlich mit `?`-Parameter-Binding – nie f-string-zusammengebaut.
- Reads liefern Domain-Modelle, nicht `sqlite3.Row`.
- `details_json`, `columns_json`, `values_json` sind JSON-serialisiert.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sampling_tool.core.models import (
    AuditEvent,
    Dataset,
    DatasetRow,
    Engagement,
    SampleConfig,
    SampleResult,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.persistence.database import savepoint

# ===========================================================================
# Engagement
# ===========================================================================


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


# ===========================================================================
# Dataset
# ===========================================================================


class DatasetRepo:
    """Persistiert Datasets inkl. ihrer DatasetRows in einem atomaren Schritt."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(self, dataset: Dataset) -> Dataset:
        """Schreibt Dataset + alle Rows in einer SAVEPOINT-Transaktion."""
        if dataset.engagement_id is None:
            raise ValueError("Dataset.engagement_id muss vor dem Persistieren gesetzt sein.")

        with savepoint(self.conn, "dataset_create"):
            cur = self.conn.execute(
                "INSERT INTO datasets "
                "(engagement_id, name, source_file, imported_at, row_count, columns_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    dataset.engagement_id,
                    dataset.name,
                    dataset.source_file,
                    dataset.imported_at,
                    len(dataset.rows),
                    json.dumps(list(dataset.columns)),
                ),
            )
            dataset_id = cur.lastrowid
            assert dataset_id is not None

            self.conn.executemany(
                "INSERT INTO dataset_rows (dataset_id, row_index, values_json) VALUES (?, ?, ?)",
                [(dataset_id, row.row_id, json.dumps(row.values)) for row in dataset.rows],
            )

        return replace(dataset, id=dataset_id)

    def get_by_id(self, dataset_id: int) -> Dataset | None:
        """Lädt Dataset inklusive aller Rows (sortiert nach `row_index`)."""
        ds_row = self.conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        if ds_row is None:
            return None

        row_cursor = self.conn.execute(
            "SELECT row_index, values_json FROM dataset_rows "
            "WHERE dataset_id = ? ORDER BY row_index",
            (dataset_id,),
        )
        rows = tuple(
            DatasetRow(row_id=r["row_index"], values=json.loads(r["values_json"]))
            for r in row_cursor
        )

        return Dataset(
            name=ds_row["name"],
            columns=tuple(json.loads(ds_row["columns_json"])),
            rows=rows,
            source_file=ds_row["source_file"],
            imported_at=ds_row["imported_at"],
            engagement_id=ds_row["engagement_id"],
            id=ds_row["id"],
        )

    def list_for_engagement(self, engagement_id: int) -> list[Dataset]:
        """Übersicht aller Datasets eines Engagements – OHNE Rows (Performance)."""
        cursor = self.conn.execute(
            "SELECT * FROM datasets WHERE engagement_id = ? ORDER BY imported_at DESC",
            (engagement_id,),
        )
        return [
            Dataset(
                name=r["name"],
                columns=tuple(json.loads(r["columns_json"])),
                rows=(),
                source_file=r["source_file"],
                imported_at=r["imported_at"],
                engagement_id=r["engagement_id"],
                id=r["id"],
            )
            for r in cursor
        ]

    def delete(self, dataset_id: int) -> None:
        """Löscht Dataset (Rows + Samples kaskadieren via FK ON DELETE CASCADE)."""
        with savepoint(self.conn, "dataset_delete"):
            self.conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))


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
                json.dumps(event.details) if event.details else None,
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
        details: dict[str, Any] = json.loads(details_raw) if details_raw else {}
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
# JSON-Helfer (modul-privat)
# ===========================================================================


def _json_or_none(value: Any) -> str | None:
    """Serialisiert primitive Werte zu JSON, gibt None bei None zurück."""
    return None if value is None else json.dumps(value)


def _json_or_none_load(text: str | None) -> Any:
    """Deserialisiert JSON oder gibt None zurück; tolerant gegenüber Plain-Strings."""
    if text is None:
        return None
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return text
