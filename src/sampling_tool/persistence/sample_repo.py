"""SampleRepo – SampleResults + selektierte row_ids (Sprint 19 / F-007-Split)."""

from __future__ import annotations

import sqlite3

from sampling_tool.core.models import (
    SampleConfig,
    SampleResult,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.persistence._json import _json_or_none, _json_or_none_load
from sampling_tool.persistence.database import savepoint


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
