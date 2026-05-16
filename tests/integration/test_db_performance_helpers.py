"""Sprint 10.3: JSON-Roundtrip mit orjson + Bulk-Insert-Pragmas."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from datetime import date, datetime
from datetime import time as dt_time
from pathlib import Path

import pytest

from sampling_tool.core.models import Dataset, DatasetRow, Engagement
from sampling_tool.persistence.database import Database, bulk_insert_pragmas
from sampling_tool.persistence.repositories import (
    DatasetRepo,
    EngagementRepo,
    _values_from_json,
    _values_to_json,
)

# ---------------------------------------------------------------------------
# JSON-Roundtrip (orjson)
# ---------------------------------------------------------------------------


class TestValuesJsonRoundtrip:
    def test_roundtrip_basic_types(self) -> None:
        values = {"a": 1, "b": 2.5, "c": "hallo", "d": None, "e": True}
        s = _values_to_json(values)
        assert _values_from_json(s) == values

    def test_roundtrip_datetime_date_time(self) -> None:
        values = {
            "dt": datetime(2024, 1, 1, 12, 30),
            "d": date(2024, 1, 1),
            "t": dt_time(12, 30),
        }
        s = _values_to_json(values)
        result = _values_from_json(s)
        assert result["dt"] == datetime(2024, 1, 1, 12, 30)
        assert result["d"] == date(2024, 1, 1)
        assert result["t"] == dt_time(12, 30)

    def test_roundtrip_umlaute(self) -> None:
        # orjson hat strict-utf8 – deutsche Umlaute + Euro müssen ohne
        # Escape durchgehen.
        values = {"name": "Müller", "land": "Österreich", "preis": "€42,50"}
        s = _values_to_json(values)
        assert _values_from_json(s) == values

    def test_returns_str_not_bytes(self) -> None:
        # orjson liefert bytes – Helper muss zu str konvertieren, weil
        # SQLite-TEXT-Spalten str erwarten.
        s = _values_to_json({"a": 1})
        assert isinstance(s, str)


# ---------------------------------------------------------------------------
# bulk_insert_pragmas
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """Echte File-basierte Connection (WAL-fähig)."""
    db_path = tmp_path / "bulk_test.db"
    c = sqlite3.connect(str(db_path), isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL").fetchall()
    c.execute("PRAGMA synchronous=NORMAL").fetchall()
    try:
        yield c
    finally:
        c.close()


class TestBulkInsertPragmas:
    def test_setzt_synchronous_off_im_block_und_restored(self, conn: sqlite3.Connection) -> None:
        prev_sync = conn.execute("PRAGMA synchronous").fetchone()[0]

        with bulk_insert_pragmas(conn):
            sync_during = conn.execute("PRAGMA synchronous").fetchone()[0]
            assert sync_during == 0  # OFF

        # Vor-Zustand wiederhergestellt.
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == prev_sync

    def test_journal_mode_bleibt_unveraendert(self, conn: sqlite3.Connection) -> None:
        # Sprint-10.3-Erfahrung: journal_mode-Wechsel innerhalb der Bulk-
        # Pragmas hat in Multi-Connection-Tests gedeadlockt – der CM lässt
        # journal_mode bewusst unangetastet.
        prev_journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        with bulk_insert_pragmas(conn):
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == prev_journal
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == prev_journal

    def test_restored_auch_bei_exception(self, conn: sqlite3.Connection) -> None:
        prev_sync = conn.execute("PRAGMA synchronous").fetchone()[0]

        with pytest.raises(RuntimeError, match="boom"), bulk_insert_pragmas(conn):
            raise RuntimeError("boom")

        assert conn.execute("PRAGMA synchronous").fetchone()[0] == prev_sync


# ---------------------------------------------------------------------------
# Smoke-Performance: DatasetRepo.create für 10k Rows
# ---------------------------------------------------------------------------


class TestDatasetRepoPerformanceSmoke:
    def test_create_10k_rows_unter_2s(self, tmp_path: Path) -> None:
        """Regressions-Sanity: 10k Rows müssen weit unter 2s persistiert sein.

        Ohne orjson + Bulk-Pragmas lag der Wert auf der Probe-Maschine bei
        ~0.4s – die 2s-Schwelle ist großzügig dimensioniert, um auch in
        langsameren CI-Umgebungen nicht falsch zu schlagen.
        """
        db = Database(tmp_path / "perf_smoke.db")
        db.migrate()

        eng_repo = EngagementRepo(db.connect())
        engagement = eng_repo.get_or_create(
            Engagement(
                auditor_name="Perf",
                auditor_position="Senior",
                client_name="ACME",
                audit_type="ISAE 3402",
            )
        )
        assert engagement.id is not None

        rows = tuple(
            DatasetRow(
                row_id=i,
                values={"a": i, "b": i * 1.5, "c": f"row_{i}", "d": None},
            )
            for i in range(1, 10_001)
        )
        dataset = Dataset(
            name="perf",
            columns=("a", "b", "c", "d"),
            rows=rows,
            engagement_id=engagement.id,
        )

        repo = DatasetRepo(db.connect())
        t0 = time.perf_counter()
        repo.create(dataset)
        elapsed = time.perf_counter() - t0

        assert elapsed < 2.0, f"DatasetRepo.create(10k) brauchte {elapsed:.2f}s"

        db.close()
