"""DatasetRepo – Datasets + DatasetRows, inkl. distinct_values (Sprint 19 / F-007-Split)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import replace
from typing import Any, ClassVar

from sampling_tool.core.cancellation import CancellationToken
from sampling_tool.core.models import Dataset, DatasetRow
from sampling_tool.persistence._json import (
    _decode_value,
    _json_dumps,
    _json_loads,
    _values_from_json,
    _values_to_json,
)
from sampling_tool.persistence.database import savepoint


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

    @staticmethod
    def supports_field_pairs(column: str) -> bool:
        """Ob ``iter_row_field_pairs`` diesen Spaltennamen sicher abbilden kann.

        Sprint 35 (Review-Finding): ``"`` und ``\\`` im Spaltennamen brechen
        das quoted JSON-Path-Label – ``json_extract`` liefert dann für JEDE
        Row NULL, was Cluster/Strata still in eine None-Gruppe kippen würde.
        Die Controller-Weiche (und perf_probe) prüfen hier und weichen für
        solche Spalten auf den klassischen ``sample(iter_rows)``-Pfad aus.
        """
        return '"' not in column and "\\" not in column

    def iter_row_field_pairs(self, dataset_id: int, column: str) -> Iterator[tuple[int, Any]]:
        """Streaming über ``(row_index, decodierter Spaltenwert)``, sortiert.

        Sprint 35 / P-003: Cluster-/Stratified-Sampler brauchen pro Row nur
        die row_id + den Wert EINES Feldes. ``json_extract`` zieht das Feld
        in C aus ``values_json``; decodiert wird mit exakt der
        ``_distinct_decode``-Mechanik aus P-005 – bit-identisch zu
        ``DatasetRow.get(column)`` (Oracle-Tests in
        ``tests/integration/test_iter_row_field_pairs.py``). Fehlender Key
        und JSON-``null`` liefern beide ``None`` (wie ``DatasetRow.get``).
        RAM ~ ein 2-Tupel pro Row statt des vollen Spalten-Dicts.

        u64-Grenzfall (Review-Finding Sprint 35): ``json_extract``
        approximiert JSON-Integer > 2^63 als REAL, während ``json_type``
        weiterhin ``'integer'`` meldet – solche Rows werden über den vollen
        JSON-Decode exakt nachgeladen (``exact_json``-Spalte, NULL für alle
        normalen Rows). Spaltennamen mit ``"``/``\\`` werden nicht
        unterstützt (``supports_field_pairs``) – laut Fehler statt still
        falsch.
        """
        if not self.supports_field_pairs(column):
            raise ValueError(
                "iter_row_field_pairs unterstützt keine Spaltennamen mit '\"' oder "
                f"'\\' (Spalte: {column!r}) – Caller weichen via supports_field_pairs "
                f"auf iter_rows aus."
            )
        json_path = '$."' + column + '"'
        cur = self.conn.execute(
            "SELECT row_index, json_extract(values_json, ?) AS raw, "
            "       json_type(values_json, ?) AS jtype, "
            "       CASE WHEN json_type(values_json, ?) = 'integer' "
            "                 AND typeof(json_extract(values_json, ?)) = 'real' "
            "            THEN values_json END AS exact_json "
            "FROM dataset_rows WHERE dataset_id = ? ORDER BY row_index",
            (json_path, json_path, json_path, json_path, dataset_id),
        )
        for r in cur:
            if r["exact_json"] is not None:
                yield int(r["row_index"]), _values_from_json(r["exact_json"]).get(column)
                continue
            jtype = r["jtype"]
            value = None if jtype is None or jtype == "null" else _distinct_decode(r["raw"], jtype)
            yield int(r["row_index"]), value

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
        Row-Materialize. Bewusst als Test-only-Helfer behalten
        (Sprint 58 / D.3-Entscheidung, kein Verhaltens-Change).
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

        Spaltennamen mit `"` oder `\\` (siehe `supports_field_pairs`) liefern
        eine leere Liste statt eines Crashs (Sprint 51 / N-008) – der JSON-Pfad
        kann für solche Namen nicht sicher gebaut werden, genau wie bei der
        Schwester `iter_row_field_pairs`. `sqlite3.OperationalError` wird
        zusätzlich als Belt-and-Suspenders abgefangen. Der JSON-Pfad wird als
        gebundener Parameter übergeben; SQL-Injection ist ausgeschlossen.
        """
        if not self.supports_field_pairs(column):
            return []
        json_path = '$."' + column + '"'
        decoded: list[tuple[Any, int]] = []
        seen: set[str] = set()
        try:
            cur = self.conn.execute(
                "SELECT json_extract(values_json, ?) AS raw, "
                "       json_type(values_json, ?) AS jtype, "
                "       MIN(row_index) AS first_idx "
                "FROM dataset_rows WHERE dataset_id = ? "
                "GROUP BY raw, jtype",
                (json_path, json_path, dataset_id),
            )
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
        except sqlite3.OperationalError:
            return []
        decoded.sort(key=lambda item: (str(item[0]), item[1]))
        return [value for value, _ in decoded]


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
