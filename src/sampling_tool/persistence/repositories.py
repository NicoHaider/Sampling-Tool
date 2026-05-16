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
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from typing import Any, Final

import orjson

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


def _json_dumps(value: Any) -> str:
    """orjson dump → str (SQLite-TEXT-Spalten brauchen str, nicht bytes)."""
    return orjson.dumps(value).decode("utf-8")


def _json_loads(text: str | bytes) -> Any:
    """orjson load – akzeptiert str und bytes."""
    return orjson.loads(text)


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

    def create(
        self,
        dataset: Dataset,
        rows: Sequence[DatasetRow],
    ) -> Dataset:
        """Schreibt Dataset-Metadaten + alle Rows in einer SAVEPOINT-Transaktion.

        Sprint-11.1-API: rows kommen jetzt separat (Dataset hält keine
        rows mehr). `dataset.row_count` wird vom Repo auf `len(rows)`
        gesetzt – der Wert im übergebenen Dataset wird überschrieben.
        """
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
                    len(rows),
                    _json_dumps(list(dataset.columns)),
                ),
            )
            dataset_id = cur.lastrowid
            assert dataset_id is not None

            # Generator statt Listcomp → spart bei großen Datasets den
            # vollen Listen-Buffer im RAM. Crash-Sicherheit bleibt durch
            # den umliegenden SAVEPOINT erhalten.
            def _row_params() -> Iterator[tuple[int, int, str]]:
                for row in rows:
                    yield (dataset_id, row.row_id, _values_to_json(row.values))

            self.conn.executemany(
                "INSERT INTO dataset_rows (dataset_id, row_index, values_json) VALUES (?, ?, ?)",
                _row_params(),
            )

        return replace(dataset, id=dataset_id, row_count=len(rows))

    def get_by_id(self, dataset_id: int) -> Dataset | None:
        """Lädt Dataset-Metadaten (ohne Rows).

        Rows separat via `get_row`, `get_rows_in_range`, `iter_rows` oder
        `get_all_rows` ziehen.
        """
        ds_row = self.conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        if ds_row is None:
            return None

        return Dataset(
            name=ds_row["name"],
            columns=tuple(_json_loads(ds_row["columns_json"])),
            row_count=int(ds_row["row_count"]),
            source_file=ds_row["source_file"],
            imported_at=ds_row["imported_at"],
            engagement_id=ds_row["engagement_id"],
            id=ds_row["id"],
        )

    # ---- Row-Zugriffe (Sprint 11.1) -------------------------------------

    def get_row(self, dataset_id: int, row_id: int) -> DatasetRow | None:
        """Holt eine einzelne Row aus dem Dataset."""
        cur = self.conn.execute(
            "SELECT row_index, values_json FROM dataset_rows "
            "WHERE dataset_id = ? AND row_index = ?",
            (dataset_id, row_id),
        )
        r = cur.fetchone()
        if r is None:
            return None
        return DatasetRow(row_id=r["row_index"], values=_values_from_json(r["values_json"]))

    def get_rows_in_range(
        self,
        dataset_id: int,
        start: int,
        end: int,
    ) -> list[DatasetRow]:
        """Holt Rows mit row_index ∈ [start, end) – sortiert nach row_index.

        Half-open Range (start inklusive, end exklusive) – konsistent mit
        Python-Slicing. Für UI-Pagination / Viewport-Loads in 11.2.
        """
        cur = self.conn.execute(
            "SELECT row_index, values_json FROM dataset_rows "
            "WHERE dataset_id = ? AND row_index >= ? AND row_index < ? "
            "ORDER BY row_index",
            (dataset_id, start, end),
        )
        return [
            DatasetRow(row_id=r["row_index"], values=_values_from_json(r["values_json"]))
            for r in cur
        ]

    def iter_rows(self, dataset_id: int) -> Iterator[DatasetRow]:
        """Streaming-Iterator über alle Rows eines Datasets (sortiert).

        Default-Eintrittspunkt für große Datasets – kein voller
        In-Memory-Materialize.
        """
        cur = self.conn.execute(
            "SELECT row_index, values_json FROM dataset_rows "
            "WHERE dataset_id = ? ORDER BY row_index",
            (dataset_id,),
        )
        for r in cur:
            yield DatasetRow(row_id=r["row_index"], values=_values_from_json(r["values_json"]))

    def get_all_rows(self, dataset_id: int) -> tuple[DatasetRow, ...]:
        """Lädt alle Rows als Tuple.

        **Übergangs-Helper** für Sprint-11.1-Migration: Stellen, die
        früher `dataset.rows` lasen, rufen das hier auf. Wird in
        Sprint 11.3/11.4 durch echtes Streaming (`iter_rows`) ersetzt,
        wo der Konsument das tatsächlich braucht. NICHT für 1M-Rows
        gedacht – nutzt linear RAM.
        """
        return tuple(self.iter_rows(dataset_id))

    def list_for_engagement(self, engagement_id: int) -> list[Dataset]:
        """Übersicht aller Datasets eines Engagements (Metadaten only)."""
        cursor = self.conn.execute(
            "SELECT * FROM datasets WHERE engagement_id = ? ORDER BY imported_at DESC",
            (engagement_id,),
        )
        return [
            Dataset(
                name=r["name"],
                columns=tuple(_json_loads(r["columns_json"])),
                row_count=int(r["row_count"]),
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
# JSON-Helfer (modul-privat)
# ===========================================================================


def _json_or_none(value: Any) -> str | None:
    """Serialisiert primitive Werte zu JSON, gibt None bei None zurück."""
    return None if value is None else _json_dumps(value)


def _json_or_none_load(text: str | None) -> Any:
    """Deserialisiert JSON oder gibt None zurück; tolerant gegenüber Plain-Strings."""
    if text is None:
        return None
    try:
        return _json_loads(text)
    except (TypeError, orjson.JSONDecodeError):
        return text


# ---------------------------------------------------------------------------
# Datetime-aware JSON für `dataset_rows.values_json`
#
# Die Importer-Schicht (Sprint 3) liefert echte datetime/date/time-Objekte in
# `DatasetRow.values`. Der eingebaute `json.dumps` kann das nicht, daher
# tagged-Encoding mit `__type__`-Marker und Round-Trip-sicherer Decode.
# ---------------------------------------------------------------------------

_TYPE_KEY: Final[str] = "__type__"
_VAL_KEY: Final[str] = "v"


def _encode_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return {_TYPE_KEY: "datetime", _VAL_KEY: value.isoformat()}
    if isinstance(value, date):
        return {_TYPE_KEY: "date", _VAL_KEY: value.isoformat()}
    if isinstance(value, time):
        return {_TYPE_KEY: "time", _VAL_KEY: value.isoformat()}
    return value


def _decode_value(value: Any) -> Any:
    if not (isinstance(value, dict) and _TYPE_KEY in value and _VAL_KEY in value):
        return value
    type_tag = value[_TYPE_KEY]
    raw = value[_VAL_KEY]
    if not isinstance(raw, str):
        return value
    if type_tag == "datetime":
        return datetime.fromisoformat(raw)
    if type_tag == "date":
        return date.fromisoformat(raw)
    if type_tag == "time":
        return time.fromisoformat(raw)
    return value


def _values_to_json(values: dict[str, Any]) -> str:
    return _json_dumps({k: _encode_value(v) for k, v in values.items()})


def _values_from_json(text: str) -> dict[str, Any]:
    raw = _json_loads(text)
    return {k: _decode_value(v) for k, v in raw.items()}
