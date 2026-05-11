"""EngagementVersionManager – Snapshot anlegen, listen, Sanity-Checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from sampling_tool.persistence.version_manager import (
    EngagementVersionManager,
    _parse_snapshot_name,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def engagement_db(tmp_path: Path) -> Path:
    """Lege eine Mini-„DB"-Datei an, deren Inhalt für Snapshot-Vergleiche reicht."""
    folder = tmp_path / "ACME"
    folder.mkdir()
    db = folder / "ACME.db"
    db.write_bytes(b"engagement-payload-v1")
    return db


class TestEngagementVersionManager:
    def test_archive_dir_is_created_on_demand(self, engagement_db: Path) -> None:
        mgr = EngagementVersionManager(engagement_db)
        archive = mgr.archive_dir
        assert archive.exists()
        assert archive.name == "archiv"
        assert archive.parent == engagement_db.parent

    def test_create_snapshot_writes_file_with_pattern(self, engagement_db: Path) -> None:
        mgr = EngagementVersionManager(engagement_db)
        snapshot = mgr.create_snapshot("Anna Auditorin")
        assert snapshot.exists()
        assert snapshot.parent.name == "archiv"
        # Pattern: ACME_YYYY-MM-DD_HH-MM-SS_Anna_Auditorin.db
        assert snapshot.name.startswith("ACME_")
        assert snapshot.name.endswith("_Anna_Auditorin.db")
        # Inhalt wurde 1:1 kopiert
        assert snapshot.read_bytes() == b"engagement-payload-v1"

    def test_missing_source_raises(self, tmp_path: Path) -> None:
        mgr = EngagementVersionManager(tmp_path / "ghost.db")
        with pytest.raises(FileNotFoundError):
            mgr.create_snapshot("Anna")

    def test_list_snapshots_returns_newest_first(self, engagement_db: Path) -> None:
        mgr = EngagementVersionManager(engagement_db)
        # Zwei Snapshots mit unterschiedlichen Dateinamen anlegen,
        # ohne uns auf realtime sleep zu verlassen: Dateinamen direkt setzen.
        archive = mgr.archive_dir
        early = archive / "ACME_2026-05-10_09-00-00_Anna.db"
        late = archive / "ACME_2026-05-11_10-30-00_Anna.db"
        early.write_bytes(b"old")
        late.write_bytes(b"new")

        snapshots = mgr.list_snapshots()
        assert [s.path.name for s in snapshots] == [late.name, early.name]

    def test_list_snapshots_skips_unparseable_files(self, engagement_db: Path) -> None:
        mgr = EngagementVersionManager(engagement_db)
        archive = mgr.archive_dir
        (archive / "garbage.db").write_bytes(b"")
        (archive / "ACME_2026-05-11_10-30-00_Anna.db").write_bytes(b"")
        names = [s.path.name for s in mgr.list_snapshots()]
        assert names == ["ACME_2026-05-11_10-30-00_Anna.db"]

    def test_snapshot_info_metadata(self, engagement_db: Path) -> None:
        mgr = EngagementVersionManager(engagement_db)
        mgr.create_snapshot("Bob")
        info = mgr.list_snapshots()[0]
        assert info.auditor_name == "Bob"
        assert info.size_bytes == len(b"engagement-payload-v1")
        assert info.path.exists()

    def test_wal_and_shm_files_are_not_copied(self, engagement_db: Path) -> None:
        # WAL/SHM neben der .db simulieren – sie dürfen NICHT mitkopiert werden.
        wal = engagement_db.with_suffix(".db-wal")
        shm = engagement_db.with_suffix(".db-shm")
        wal.write_bytes(b"wal")
        shm.write_bytes(b"shm")
        mgr = EngagementVersionManager(engagement_db)
        snapshot = mgr.create_snapshot("Anna")
        siblings = list(snapshot.parent.iterdir())
        assert wal.name not in {p.name for p in siblings}
        assert shm.name not in {p.name for p in siblings}

    def test_parse_snapshot_name_roundtrip(self) -> None:
        parsed = _parse_snapshot_name("ACME_2026-05-11_10-30-15_Anna_Auditorin.db")
        assert parsed is not None
        timestamp, auditor = parsed
        assert timestamp.year == 2026
        assert timestamp.day == 11
        assert timestamp.hour == 10
        assert timestamp.minute == 30
        assert timestamp.second == 15
        assert auditor == "Anna_Auditorin"
