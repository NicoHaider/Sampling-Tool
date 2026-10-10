"""SampleRepo – SampleResults + selektierte row_ids (Sprint 19 / F-007-Split)."""

from __future__ import annotations

import sqlite3
from typing import Any

from sampling_tool.core.models import (
    FilterCondition,
    FilterOperator,
    ParentRelation,
    SampleConfig,
    SampleResult,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.persistence._json import (
    _json_dumps,
    _json_loads,
    _json_or_none,
)
from sampling_tool.persistence.database import savepoint


class SampleRepo:
    """Persistiert SampleResults + die ausgewählten row_ids in `sample_rows`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create_from_result(self, result: SampleResult, dataset_id: int) -> int:
        """Speichert die Ziehung; gibt die DB-id der `samples`-Zeile zurück.

        `created_by` kommt aus `result` (Sprint 83 / C) – bis dahin war es ein
        eigener Parameter, und das In-Memory-Objekt, aus dem Audit-Event und
        Export gebaut werden, trug weiter den Dataclass-Default.
        """
        cfg = result.config
        # Sprint 92: Altspalten nur bei genau einem Filter wie früher befüllen –
        # bei mehreren sähe ein Leser der Altspalten sonst nur einen Teil.
        only = cfg.filters[0] if len(cfg.filters) == 1 else None
        with savepoint(self.conn, "sample_create"):
            cur = self.conn.execute(
                "INSERT INTO samples "
                "(dataset_id, method, sample_size, population_size, seed, "
                " filter_field, filter_value, cluster_field, stratum_field, "
                " stratify_mode, filter_operator, parent_sample_id, created_at, created_by, "
                " algorithm_version, parent_relation, filters) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    dataset_id,
                    cfg.method.value,
                    cfg.size,
                    result.population_size,
                    cfg.seed,
                    only.field if only else None,
                    _json_or_none(only.value) if only else None,
                    cfg.cluster_field,
                    cfg.stratum_field,
                    cfg.stratify_mode.value,
                    only.operator.value if only else FilterOperator.EQ.value,
                    result.parent_sample_id,
                    result.drawn_at,
                    result.created_by,
                    result.algorithm_version,
                    result.parent_relation.value if result.parent_relation else None,
                    _filters_to_json(cfg.filters),
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

    def dataset_id_of(self, sample_id: int) -> int | None:
        """Datensatz, auf dem die Stichprobe gezogen wurde (`None`: unbekannt).

        `sample_rows.row_id` ist datensatzbezogen: dieselben IDs treffen in
        jedem anderen Datensatz andere Zeilen (Sprint 86).
        """
        row = self.conn.execute(
            "SELECT dataset_id FROM samples WHERE id = ?", (sample_id,)
        ).fetchone()
        return None if row is None else int(row["dataset_id"])

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
            filters=_filters_from_json(row["filters"]),
        )
        return SampleResult(
            config=config,
            selected_row_ids=selected_row_ids,
            population_size=row["population_size"],
            algorithm_version=row["algorithm_version"],
            drawn_at=row["created_at"],
            parent_sample_id=row["parent_sample_id"],
            parent_relation=(
                ParentRelation(row["parent_relation"]) if row["parent_relation"] else None
            ),
            created_by=row["created_by"],
            id=row["id"],
        )


def _filters_to_json(filters: tuple[FilterCondition, ...]) -> str:
    """`samples.filters`: JSON-Liste; der Wert wie die Altspalte `filter_value`."""
    return _json_dumps(
        [{"field": c.field, "operator": c.operator.value, "value": c.value} for c in filters]
    )


def _filters_from_json(text: str | None) -> tuple[FilterCondition, ...]:
    items: Any = _json_loads(text) if text else []
    return tuple(
        FilterCondition(
            field=item["field"],
            operator=FilterOperator(item["operator"]),
            value=item.get("value"),
        )
        for item in items
    )
