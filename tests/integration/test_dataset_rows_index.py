"""Sprint 94: Index `(dataset_id, row_index)` auf `dataset_rows` (Migration 008).

Der Index ändert nur, WIE SQLite sucht, nicht WAS es liefert. Geprüft wird
deshalb dreierlei: das Schema nach der Migration, dass die echten Lesepfade
von `DatasetRepo` den Index nutzen (Plan der mitgeschnittenen Statements,
nicht abgeschriebenes SQL), und dass alle Ergebnisse vor und nach dem Index
identisch sind.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    Engagement,
    FilterCondition,
    FilterOperator,
    SampleConfig,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.core.sampling import (
    ClusterSampler,
    SimpleSampler,
    StratifiedSampler,
    create_sampler,
)
from sampling_tool.persistence.database import CURRENT_SCHEMA_VERSION, Database
from sampling_tool.persistence.db_preflight import PreflightAccepted, preflight_check
from sampling_tool.persistence.repositories import DatasetRepo, EngagementRepo, SampleRepo
from sampling_tool.resources import package_resource

pytestmark = pytest.mark.integration

NEW_INDEX = "idx_dataset_rows_dataset_row"
OLD_INDEX = "idx_dataset_rows_dataset"
_COLUMNS = ("Konto", "Betrag", "Kostenstelle", "Datum", "Text")


def _migrations_up_to(tmp_path: Path, version: int) -> Path:
    """Kopie des Migrationsordners bis einschließlich `version`."""
    target = tmp_path / f"migrations_v{version}"
    target.mkdir()
    for script in package_resource("persistence/migrations").glob("*.sql"):
        if int(script.name.split("_", 1)[0]) <= version:
            (target / script.name).write_bytes(script.read_bytes())
    return target


def _rows(n: int, *, seed: int, shuffled: bool) -> list[DatasetRow]:
    """Gemischte Werte; `shuffled` legt die Zeilen außer row_index-Reihenfolge ab."""
    rng = np.random.default_rng(seed)
    rows = [
        DatasetRow(
            row_id=i,
            values={
                "Konto": int(rng.integers(4000, 4010)),
                "Betrag": round(float(rng.uniform(-500, 5000)), 2),
                "Kostenstelle": f"KS{int(rng.integers(1, 6)):02d}",
                "Datum": datetime(2025, 1, 1) + timedelta(days=int(rng.integers(0, 365))),
                "Text": None if i % 7 == 0 else f"Buchung {i} – Zürich",
            },
        )
        for i in range(1, n + 1)
    ]
    if shuffled:
        order = rng.permutation(n)
        rows = [rows[int(k)] for k in order]
    return rows


def _engagement(db: Database) -> int:
    eng = EngagementRepo(db.connect()).get_or_create(
        Engagement(auditor_name="A", client_name="C", auditor_position="S", audit_type="ISAE 3402")
    )
    assert eng.id is not None
    return eng.id


def _add_dataset(db: Database, engagement_id: int, rows: list[DatasetRow], name: str) -> Dataset:
    return DatasetRepo(db.connect()).create(
        Dataset(name=name, columns=_COLUMNS, row_count=len(rows), engagement_id=engagement_id),
        iter(rows),
    )


def _db(tmp_path: Path, *, version: int | None = None, n: int = 400) -> tuple[Database, Dataset]:
    """Projektdatei mit zwei verzahnt geschriebenen Datensätzen; `version=None` = aktuell."""
    db = Database(tmp_path / f"v{version or 'cur'}.db")
    if version is None:
        db.migrate()
    else:
        db.migrate(migrations_root=_migrations_up_to(tmp_path, version))
    eng_id = _engagement(db)
    other = _add_dataset(db, eng_id, _rows(n // 2, seed=2, shuffled=True), "andere")
    main = _add_dataset(db, eng_id, _rows(n, seed=1, shuffled=True), "haupt")
    assert other.id is not None
    assert main.id is not None
    return db, main


def _index_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(r[0])
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'dataset_rows'"
        )
    }


def _read_paths(repo: DatasetRepo, dataset_id: int) -> dict[str, Callable[[], Any]]:
    """Alle Lesepfade von `DatasetRepo`, die über `dataset_rows` gehen."""
    unsorted_with_stale = [17, 3, 999_999, 250, 3, 1, -5, 400, 0, 401, 42]
    return {
        "get_row": lambda: [repo.get_row(dataset_id, rid) for rid in (1, 200, 400, 401, 0)],
        "get_rows_in_range": lambda: [
            repo.get_rows_in_range(dataset_id, s, e)
            for s, e in ((1, 252), (150, 401), (390, 600), (0, 1), (500, 600))
        ],
        "get_rows_by_ids": lambda: repo.get_rows_by_ids(dataset_id, unsorted_with_stale),
        "get_rows_by_ids_chunked": lambda: repo.get_rows_by_ids(
            dataset_id, [*range(400, 0, -1), *range(1, 1200, 2)]
        ),
        "iter_rows": lambda: list(repo.iter_rows(dataset_id)),
        "iter_row_ids": lambda: list(repo.iter_row_ids(dataset_id)),
        "iter_row_field_pairs": lambda: [
            list(repo.iter_row_field_pairs(dataset_id, column)) for column in _COLUMNS
        ],
        "distinct_values": lambda: [repo.distinct_values(dataset_id, c) for c in _COLUMNS],
    }


class TestMigration008:
    def test_index_exists_after_migrate(self, tmp_path: Path) -> None:
        db = Database(tmp_path / "neu.db")
        try:
            db.migrate()
            conn = db.connect()
            columns = [r["name"] for r in conn.execute(f"PRAGMA index_info('{NEW_INDEX}')")]
            names = _index_names(conn)
        finally:
            db.close()
        assert columns == ["dataset_id", "row_index"]
        assert NEW_INDEX in names
        assert OLD_INDEX not in names

    def test_upgrade_from_v7_keeps_data(self, tmp_path: Path) -> None:
        db, dataset = _db(tmp_path, version=7)
        try:
            assert db.schema_version() == 7
            assert dataset.id is not None
            repo = DatasetRepo(db.connect())
            result = create_sampler(
                SampleConfig(method=SamplingMethod.SIMPLE, size=25, seed=4711)
            ).sample(repo.iter_rows(dataset.id), population_size=dataset.row_count)
            SampleRepo(db.connect()).create_from_result(result, dataset.id)
            conn = db.connect()
            rows_before = conn.execute(
                "SELECT id, dataset_id, row_index, values_json FROM dataset_rows ORDER BY id"
            ).fetchall()
            samples_before = conn.execute("SELECT * FROM samples ORDER BY id").fetchall()
            items_before = conn.execute(
                "SELECT * FROM sample_rows ORDER BY sample_id, row_id"
            ).fetchall()

            db.migrate()

            assert db.schema_version() == CURRENT_SCHEMA_VERSION
            versions = {int(r[0]) for r in conn.execute("SELECT version FROM schema_version")}
            rows_after = conn.execute(
                "SELECT id, dataset_id, row_index, values_json FROM dataset_rows ORDER BY id"
            ).fetchall()
            samples_after = conn.execute("SELECT * FROM samples ORDER BY id").fetchall()
            items_after = conn.execute(
                "SELECT * FROM sample_rows ORDER BY sample_id, row_id"
            ).fetchall()
        finally:
            db.close()
        assert CURRENT_SCHEMA_VERSION in versions
        assert [tuple(r) for r in rows_after] == [tuple(r) for r in rows_before]
        assert len(rows_after) == 600
        assert [tuple(r) for r in samples_after] == [tuple(r) for r in samples_before]
        assert [tuple(r) for r in items_after] == [tuple(r) for r in items_before]
        assert len(items_after) == 25

    def test_v7_without_old_index_migrates_and_opens(self, tmp_path: Path) -> None:
        """Ein externer Editor hat den alten Index entfernt – die Migration scheitert nicht."""
        db, dataset = _db(tmp_path, version=7)
        db_path = db.db_path
        try:
            db.connect().execute(f"DROP INDEX {OLD_INDEX}")
            assert _index_names(db.connect()) == set()
        finally:
            db.checkpoint_and_close()

        upgraded = Database(db_path)
        try:
            upgraded.migrate()
            assert upgraded.schema_version() == CURRENT_SCHEMA_VERSION
            names = _index_names(upgraded.connect())
            assert dataset.id is not None
            row_ids = list(DatasetRepo(upgraded.connect()).iter_row_ids(dataset.id))
        finally:
            upgraded.close()
        assert names == {NEW_INDEX}
        assert row_ids == list(range(1, 401))
        assert preflight_check(db_path) == PreflightAccepted(schema_version=CURRENT_SCHEMA_VERSION)

    def test_cascade_delete_still_works(self, tmp_path: Path) -> None:
        # Es gibt keinen Produktpfad zum Löschen eines Datensatzes – direkt per SQL.
        db, dataset = _db(tmp_path)
        try:
            conn = db.connect()
            conn.execute("DELETE FROM datasets WHERE id = ?", (dataset.id,))
            remaining = conn.execute(
                "SELECT dataset_id, COUNT(*) FROM dataset_rows GROUP BY dataset_id"
            ).fetchall()
        finally:
            db.close()
        assert dataset.id not in {r[0] for r in remaining}
        assert [r[1] for r in remaining] == [200]


def _plan_violations(db: Database, dataset_id: int) -> list[str]:
    """Schneidet die SQL der echten Lesepfade mit und prüft deren Plan."""
    conn = db.connect()
    repo = DatasetRepo(conn)
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        for name in (
            "get_row",
            "get_rows_in_range",
            "get_rows_by_ids",
            "iter_rows",
            "iter_row_ids",
            "iter_row_field_pairs",
        ):
            _read_paths(repo, dataset_id)[name]()
    finally:
        conn.set_trace_callback(None)
    traced = [s for s in dict.fromkeys(statements) if "FROM dataset_rows" in s]
    assert traced, "Kein SQL mitgeschnitten – das Gate wäre leer."
    violations: list[str] = []
    for sql in traced:
        plan = " | ".join(str(r["detail"]) for r in conn.execute(f"EXPLAIN QUERY PLAN {sql}"))
        if NEW_INDEX not in plan or "USE TEMP B-TREE" in plan:
            violations.append(f"{sql[:90]} → {plan}")
    return violations


class TestQueryPlansUseIndex:
    def test_all_read_paths_use_index_without_temp_btree(self, tmp_path: Path) -> None:
        db, dataset = _db(tmp_path)
        try:
            assert dataset.id is not None
            violations = _plan_violations(db, dataset.id)
        finally:
            db.close()
        assert violations == []

    def test_positive_control_v7_fails_the_gate(self, tmp_path: Path) -> None:
        """Ohne Migration 008 schlägt dasselbe Gate an – sonst prüfte es nichts."""
        db, dataset = _db(tmp_path, version=7)
        try:
            assert dataset.id is not None
            violations = _plan_violations(db, dataset.id)
        finally:
            db.close()
        assert len(violations) >= 6
        assert any("USE TEMP B-TREE" in v for v in violations)


_UNFILTERED_CONFIGS: tuple[SampleConfig, ...] = (
    SampleConfig(method=SamplingMethod.SIMPLE, size=30, seed=1),
    SampleConfig(method=SamplingMethod.CLUSTER, size=2, seed=2, cluster_field="Kostenstelle"),
    SampleConfig(
        method=SamplingMethod.STRATIFIED,
        size=40,
        seed=3,
        stratum_field="Kostenstelle",
        stratify_mode=StratifyMode.PROPORTIONAL,
    ),
    SampleConfig(
        method=SamplingMethod.STRATIFIED,
        size=20,
        seed=2147483647,
        stratum_field="Konto",
        stratify_mode=StratifyMode.EQUAL,
    ),
)
_SAMPLING_CONFIGS: tuple[SampleConfig, ...] = (
    *_UNFILTERED_CONFIGS,
    *(
        replace(config, filters=(FilterCondition("Betrag", FilterOperator.GTE, 1000.0),))
        for config in _UNFILTERED_CONFIGS
    ),
)


def _draw_all(repo: DatasetRepo, dataset: Dataset) -> list[tuple[int, ...]]:
    """Alle Konfigurationen über die Pfade, die der WorkspaceController nimmt."""
    assert dataset.id is not None
    results: list[tuple[int, ...]] = []
    for config in _SAMPLING_CONFIGS:
        sampler = create_sampler(config)
        if config.filters:
            result = sampler.sample(repo.iter_rows(dataset.id), population_size=dataset.row_count)
        elif isinstance(sampler, SimpleSampler):
            result = sampler.sample_ids(repo.iter_row_ids(dataset.id), dataset.row_count)
        elif isinstance(sampler, ClusterSampler | StratifiedSampler):
            field = config.cluster_field or config.stratum_field
            assert field is not None
            result = sampler.sample_pairs(
                repo.iter_row_field_pairs(dataset.id, field), dataset.row_count
            )
        else:
            raise AssertionError(config)
        # Kontrolle: der klassische Pfad über iter_rows liefert dasselbe.
        classic = sampler.sample(repo.iter_rows(dataset.id), population_size=dataset.row_count)
        assert result.selected_row_ids == classic.selected_row_ids
        results.append(result.selected_row_ids)
    return results


class TestResultsUnchanged:
    def test_reads_identical_before_and_after_index(self, tmp_path: Path) -> None:
        db, dataset = _db(tmp_path)
        try:
            assert dataset.id is not None
            conn = db.connect()
            repo = DatasetRepo(conn)
            with_index = {name: fn() for name, fn in _read_paths(repo, dataset.id).items()}

            conn.execute(f"DROP INDEX {NEW_INDEX}")
            conn.execute(f"CREATE INDEX {OLD_INDEX} ON dataset_rows(dataset_id)")
            assert _index_names(conn) == {OLD_INDEX}
            without_index = {name: fn() for name, fn in _read_paths(repo, dataset.id).items()}
        finally:
            db.close()
        assert with_index == without_index
        # Der Vergleich ist nicht leer: Inhalt, Reihenfolge und stale IDs greifen.
        assert [r.row_id for r in with_index["get_rows_by_ids"]] == [17, 3, 250, 3, 1, 400, 42]
        assert with_index["iter_row_ids"] == list(range(1, 401))
        assert len(with_index["iter_rows"]) == 400

    def test_sampling_identical_after_migration(self, tmp_path: Path) -> None:
        db, dataset = _db(tmp_path, version=7)
        try:
            before = _draw_all(DatasetRepo(db.connect()), dataset)
            db.migrate()
            assert NEW_INDEX in _index_names(db.connect())
            after = _draw_all(DatasetRepo(db.connect()), dataset)
        finally:
            db.close()
        assert after == before
        assert all(before)
