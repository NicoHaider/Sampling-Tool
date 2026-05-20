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
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from typing import Any, ClassVar, Final

import orjson

from sampling_tool.core.cancellation import CancellationToken
from sampling_tool.core.models import (
    AuditEvent,
    Dataset,
    DatasetRow,
    Engagement,
    SampleConfig,
    SampleResult,
    SamplingMethod,
    Snapshot,
    StratifyMode,
    UndoStack,
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

    # Sprint 17: alle N persistierten Rows checken wir auf Cancellation und
    # feuern den Progress-Callback. Höher als _PROGRESS_INTERVAL im Importer,
    # weil der DB-Insert pro Row teurer ist und der UI eh nicht 1000-mal pro
    # Sekunde was zu sehen ist.
    _PERSIST_PROGRESS_INTERVAL: ClassVar[int] = 500

    def create(
        self,
        dataset: Dataset,
        rows: Iterable[DatasetRow],
        progress: Callable[[int, int], None] | None = None,
        cancellation: CancellationToken | None = None,
    ) -> Dataset:
        """Schreibt Dataset-Metadaten + alle Rows in einer SAVEPOINT-Transaktion.

        Sprint-11.1-API: rows kommen separat (Dataset hält keine rows mehr).
        Sprint-11.3-Streaming: `rows` darf jetzt ein **einmalig
        konsumierbarer Iterator** sein (z. B. von `ExcelImporter`).
        `dataset.row_count` wird nach echter Persistierung mit der
        tatsächlich geschriebenen Anzahl überschrieben – wichtig, weil
        ein Streaming-Importer Empty-Rows erst beim Lesen entdeckt und
        die Estimate aus `sheet.total_height` typischerweise zu hoch
        ist.

        Sprint-17 / P-008: Optionaler ``progress`` und ``cancellation``-
        Parameter für Worker-Thread-Persistenz. ``progress`` wird alle
        ``_PERSIST_PROGRESS_INTERVAL`` Rows aufgerufen (current, total).
        Bei gesetztem ``cancellation``-Token wird die Persistierung
        abgebrochen (SAVEPOINT rollt zurück → kein partielles Dataset
        in der DB).
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
                    # Vorläufig die Estimate – wird unten korrigiert.
                    dataset.row_count,
                    _json_dumps(list(dataset.columns)),
                ),
            )
            dataset_id = cur.lastrowid
            assert dataset_id is not None

            # Generator statt Listcomp → spart bei großen Datasets den
            # vollen Listen-Buffer im RAM. Akzeptiert auch einen
            # einmalig konsumierbaren Iterator (Streaming-Import 11.3).
            # `actual_count` zählt mit, weil wir am Ende den row_count
            # in der DB korrigieren müssen.
            actual_count = 0
            interval = self._PERSIST_PROGRESS_INTERVAL
            total_estimate = dataset.row_count

            def _row_params() -> Iterator[tuple[int, int, str]]:
                nonlocal actual_count
                for row in rows:
                    actual_count += 1
                    if actual_count % interval == 0:
                        if cancellation is not None:
                            cancellation.raise_if_cancelled()
                        if progress is not None:
                            progress(actual_count, max(total_estimate, actual_count))
                    yield (dataset_id, row.row_id, _values_to_json(row.values))

            # Frühabbruch: Token vor Persist-Start gesetzt → kein Insert,
            # SAVEPOINT rollt zurück, kein Partial-Dataset in der DB.
            if cancellation is not None:
                cancellation.raise_if_cancelled()

            self.conn.executemany(
                "INSERT INTO dataset_rows (dataset_id, row_index, values_json) VALUES (?, ?, ?)",
                _row_params(),
            )

            if actual_count != dataset.row_count:
                self.conn.execute(
                    "UPDATE datasets SET row_count = ? WHERE id = ?",
                    (actual_count, dataset_id),
                )

        # Final-Tick: bestätigt dem UI die echte Endgröße.
        if progress is not None:
            progress(actual_count, actual_count)
        return replace(dataset, id=dataset_id, row_count=actual_count)

    def get_by_id(self, dataset_id: int) -> Dataset | None:
        """Lädt Dataset-Metadaten (ohne Rows).

        Rows separat via `get_row`, `get_rows_in_range`, `iter_rows`,
        `iter_row_ids` oder `get_rows_by_ids` ziehen.
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

    def iter_row_ids(self, dataset_id: int) -> Iterator[int]:
        """Streaming-Iterator über alle row_ids eines Datasets (sortiert).

        Leichtgewichtige Variante von `iter_rows` – lädt nur die IDs, kein
        JSON-Parsing. Eintrittspunkt für SimpleSampler ohne Filter, der
        nur die Pool-Größe und shufflebare IDs braucht.
        """
        cur = self.conn.execute(
            "SELECT row_index FROM dataset_rows WHERE dataset_id = ? ORDER BY row_index",
            (dataset_id,),
        )
        for r in cur:
            yield int(r["row_index"])

    _SQLITE_VAR_LIMIT: ClassVar[int] = 900

    def get_rows_by_ids(
        self,
        dataset_id: int,
        row_ids: Sequence[int],
    ) -> list[DatasetRow]:
        """Holt die genannten Rows in einem (oder mehreren) Query(s).

        Behält die Eingabe-Reihenfolge bei. Stale row_ids (im Dataset nicht
        vorhanden) werden stillschweigend übersprungen – wichtig für
        EngagementState-Restore mit zwischenzeitlich gelöschten Rows.

        Bei sehr großen Listen wird gechunkt (SQLite-Default-Limit für
        Bind-Parameter = 999, konservativ auf 900 gesetzt).
        """
        if not row_ids:
            return []

        by_id: dict[int, DatasetRow] = {}
        for chunk_start in range(0, len(row_ids), self._SQLITE_VAR_LIMIT):
            chunk = row_ids[chunk_start : chunk_start + self._SQLITE_VAR_LIMIT]
            placeholders = ",".join("?" * len(chunk))
            cur = self.conn.execute(
                f"SELECT row_index, values_json FROM dataset_rows "
                f"WHERE dataset_id = ? AND row_index IN ({placeholders})",
                [dataset_id, *chunk],
            )
            for r in cur:
                rid = int(r["row_index"])
                by_id[rid] = DatasetRow(row_id=rid, values=_values_from_json(r["values_json"]))

        return [by_id[rid] for rid in row_ids if rid in by_id]

    def get_all_rows(self, dataset_id: int) -> tuple[DatasetRow, ...]:
        """Lädt alle Rows als Tuple. **In Production grundsätzlich vermeiden.**

        Materialisiert das gesamte Dataset im RAM – bei 1M-Zeilen-Datasets
        sprengt das den Footprint (siehe PERFORMANCE.md). Production-Code
        nutzt stattdessen `iter_rows`, `get_rows_in_range` oder
        `get_rows_by_ids`.

        Legitime Use-Cases (Sprint 11.5 verifiziert):
        - Tests / Convenience-Asserts.

        Distinkte Spaltenwerte (vorher der einzige Production-Use-Case,
        SamplingDialog-Advanced-Mode) laufen seit Sprint 19 / P-005 über
        `DatasetRepo.distinct_values` – SQL-`json_extract` statt
        Row-Materialize.
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

    def distinct_values(self, dataset_id: int, column: str) -> list[Any]:
        """Distinkte Nicht-None-Werte einer Dataset-Spalte – via SQL, ohne Row-Materialize.

        Ersetzt den `get_all_rows()`-Pfad des Advanced-Sampling-Dialogs (P-005).
        Bit-identisch zum bisherigen `_distinct_values(get_all_rows(...), column)`:
        None überspringen, Dedup über `repr(value)`, Sortierung über `str(value)`.
        RAM ~ Anzahl distinkter Werte (nicht Zeilenzahl).

        Tie-Break: bei `str()`-Gleichstand zweier verschiedener Werte
        (z. B. int 5 und str "5") entscheidet das früheste `row_index` –
        repliziert die Stable-Sort-First-Occurrence-Ordnung des alten
        RAM-Pfads.

        Limitierung: Spaltennamen mit eingebettetem `"` sind nicht abgedeckt
        (pathologisch bei Excel-Headern) – ein solcher Filter liefert eine
        leere Liste statt eines Crashs. Der JSON-Pfad wird als gebundener
        Parameter übergeben; SQL-Injection ist ausgeschlossen.
        """
        json_path = '$."' + column.replace('"', '""') + '"'
        cur = self.conn.execute(
            "SELECT json_extract(values_json, ?) AS raw, "
            "       json_type(values_json, ?) AS jtype, "
            "       MIN(row_index) AS first_idx "
            "FROM dataset_rows WHERE dataset_id = ? "
            "GROUP BY raw, jtype",
            (json_path, json_path, dataset_id),
        )
        decoded: list[tuple[Any, int]] = []
        seen: set[str] = set()
        for row in cur:
            jtype = row["jtype"]
            if jtype is None or jtype == "null":
                continue
            value = _distinct_decode(row["raw"], jtype)
            key = repr(value)
            if key in seen:
                continue
            seen.add(key)
            decoded.append((value, int(row["first_idx"])))
        decoded.sort(key=lambda item: (str(item[0]), item[1]))
        return [value for value, _ in decoded]


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


def _distinct_decode(raw: Any, jtype: str) -> Any:
    """Rekonstruiert einen Python-Wert aus json_extract-Rohwert + json_type.

    Bool wird aus `jtype` rekonstruiert, NICHT aus `raw` – json_extract
    liefert für JSON-Booleans `1`/`0`, sonst ginge bool vs. int verloren.
    `object` ist ein tagged datetime/date/time (siehe `_encode_value`).
    """
    if jtype == "object":
        return _decode_value(_json_loads(raw))
    if jtype == "true":
        return True
    if jtype == "false":
        return False
    if jtype == "integer":
        return int(raw)
    if jtype == "real":
        return float(raw)
    if jtype == "text":
        return str(raw)
    return raw
