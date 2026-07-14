"""EngagementVersionManager – Snapshot anlegen, listen, Sanity-Checks."""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime, tzinfo
from pathlib import Path

import pytest

import sampling_tool.persistence.version_manager as version_manager
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.version_manager import (
    EngagementVersionManager,
    _parse_snapshot_name,
)

pytestmark = pytest.mark.integration


def _create_probe_database(path: Path, *values: str) -> None:
    database = Database(path)
    try:
        with database.session() as conn:
            conn.execute("CREATE TABLE snapshot_probe (value TEXT NOT NULL)")
            conn.executemany(
                "INSERT INTO snapshot_probe (value) VALUES (?)",
                ((value,) for value in values),
            )
    finally:
        database.close()


def _insert_probe_value(path: Path, value: str) -> None:
    database = Database(path)
    try:
        with database.session() as conn:
            conn.execute("INSERT INTO snapshot_probe (value) VALUES (?)", (value,))
    finally:
        database.close()


def _read_probe_values(path: Path) -> list[str]:
    uri = f"{path.absolute().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute("SELECT value FROM snapshot_probe ORDER BY rowid").fetchall()
    finally:
        conn.close()
    return [str(row[0]) for row in rows]


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz: tzinfo | None = None) -> _FixedDatetime:
        return cls(2026, 5, 11, 10, 30, 15, 123456, tzinfo=tz)


@pytest.fixture
def engagement_db(tmp_path: Path) -> Path:
    """Lege eine minimale echte SQLite-DB für Snapshot-Vergleiche an."""
    folder = tmp_path / "ACME"
    folder.mkdir()
    db = folder / "ACME.db"
    _create_probe_database(db, "engagement-payload-v1")
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
        # Pattern: ACME_YYYY-MM-DD_HH-MM-SS-microseconds_Anna_Auditorin.db
        assert snapshot.name.startswith("ACME_")
        assert snapshot.name.endswith("_Anna_Auditorin.db")
        assert _read_probe_values(snapshot) == ["engagement-payload-v1"]

    def test_create_snapshot_does_not_require_sqlite_file_uris(
        self,
        engagement_db: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mgr = EngagementVersionManager(engagement_db)

        def reject_file_uri(_path: Path) -> str:
            raise AssertionError("Snapshot creation must use ordinary filesystem paths")

        with monkeypatch.context() as scoped:
            scoped.setattr(Path, "as_uri", reject_file_uri)
            snapshot = mgr.create_snapshot("Anna")

        assert _read_probe_values(snapshot) == ["engagement-payload-v1"]

    def test_snapshot_contains_uncheckpointed_wal_transaction(self, engagement_db: Path) -> None:
        database = Database(engagement_db)
        try:
            conn = database.connect()
            conn.execute("PRAGMA wal_autocheckpoint = 0")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
            with database.session() as session:
                session.execute(
                    "INSERT INTO snapshot_probe (value) VALUES (?)",
                    ("committed-in-wal",),
                )

            wal_path = engagement_db.with_name(f"{engagement_db.name}-wal")
            assert wal_path.exists()
            assert wal_path.stat().st_size > 0

            snapshot = EngagementVersionManager(engagement_db).create_snapshot("Anna")
            assert _read_probe_values(snapshot) == [
                "engagement-payload-v1",
                "committed-in-wal",
            ]
        finally:
            database.close()

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
        _create_probe_database(early, "old")
        _create_probe_database(late, "new")

        snapshots = mgr.list_snapshots()
        assert [s.path.name for s in snapshots] == [late.name, early.name]

    def test_list_snapshots_skips_unparseable_files(self, engagement_db: Path) -> None:
        mgr = EngagementVersionManager(engagement_db)
        archive = mgr.archive_dir
        (archive / "garbage.db").write_bytes(b"")
        _create_probe_database(archive / "ACME_2026-05-11_10-30-00_Anna.db", "valid")
        names = [s.path.name for s in mgr.list_snapshots()]
        assert names == ["ACME_2026-05-11_10-30-00_Anna.db"]

    def test_list_snapshots_only_matches_exact_managed_stem(self, engagement_db: Path) -> None:
        mgr = EngagementVersionManager(engagement_db)
        archive = mgr.archive_dir
        managed = archive / "ACME_2026-05-11_10-30-00_Anna.db"
        other_database = archive / "OTHER_2026-05-12_10-30-00_Bob.db"
        longer_stem = archive / "ACME_extra_2026-05-13_10-30-00_Carla.db"
        for path in (managed, other_database, longer_stem):
            _create_probe_database(path, path.stem)

        assert [info.path for info in mgr.list_snapshots()] == [managed]

    def test_list_snapshots_handles_date_time_tokens_in_managed_stem(
        self,
        tmp_path: Path,
    ) -> None:
        database_path = tmp_path / "Project_2020-01-02_03-04-05.db"
        _create_probe_database(database_path, "current")
        mgr = EngagementVersionManager(database_path)
        first = mgr.archive_dir / "Project_2020-01-02_03-04-05_2026-05-11_10-30-15-123456_Anna.db"
        second = mgr.archive_dir / "Project_2020-01-02_03-04-05_2026-05-11_10-30-15-123456_Bob~2.db"
        _create_probe_database(first, "first")
        _create_probe_database(second, "second")

        snapshots = mgr.list_snapshots()

        assert [info.path for info in snapshots] == [second, first]
        assert [info.timestamp for info in snapshots] == [
            datetime(2026, 5, 11, 10, 30, 15, 123456),
            datetime(2026, 5, 11, 10, 30, 15, 123456),
        ]
        assert [info.auditor_name for info in snapshots] == ["Bob", "Anna"]

    def test_snapshot_info_metadata(self, engagement_db: Path) -> None:
        mgr = EngagementVersionManager(engagement_db)
        snapshot = mgr.create_snapshot("Bob")
        info = mgr.list_snapshots()[0]
        assert info.auditor_name == "Bob"
        assert info.size_bytes == snapshot.stat().st_size
        assert info.size_bytes > 0
        assert info.path.exists()

    def test_wal_and_shm_files_are_not_copied(self, engagement_db: Path) -> None:
        database = Database(engagement_db)
        try:
            conn = database.connect()
            conn.execute("PRAGMA wal_autocheckpoint = 0")
            with database.session() as session:
                session.execute(
                    "INSERT INTO snapshot_probe (value) VALUES (?)",
                    ("sidecar-marker",),
                )
            wal = engagement_db.with_name(f"{engagement_db.name}-wal")
            shm = engagement_db.with_name(f"{engagement_db.name}-shm")
            assert wal.exists()
            assert shm.exists()

            snapshot = EngagementVersionManager(engagement_db).create_snapshot("Anna")
            assert list(snapshot.parent.iterdir()) == [snapshot]
            assert not snapshot.with_name(f"{snapshot.name}-wal").exists()
            assert not snapshot.with_name(f"{snapshot.name}-shm").exists()
            assert not snapshot.with_name(f"{snapshot.name}-journal").exists()
        finally:
            database.close()

    def test_two_snapshots_same_second_are_distinct(
        self,
        engagement_db: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(version_manager, "datetime", _FixedDatetime)
        mgr = EngagementVersionManager(engagement_db)

        first = mgr.create_snapshot("Anna")
        _insert_probe_value(engagement_db, "second-snapshot-only")
        second = mgr.create_snapshot("Anna")

        assert first.name == "ACME_2026-05-11_10-30-15-123456_Anna.db"
        assert second.name == "ACME_2026-05-11_10-30-15-123456_Anna~2.db"
        assert first != second
        assert _read_probe_values(first) == ["engagement-payload-v1"]
        assert _read_probe_values(second) == [
            "engagement-payload-v1",
            "second-snapshot-only",
        ]
        infos = mgr.list_snapshots()
        assert [info.path for info in infos] == [second, first]
        assert {info.auditor_name for info in infos} == {"Anna"}

    @pytest.mark.parametrize(
        ("auditor_name", "auditor_token"),
        [
            ("Team 2", "Team_2"),
            ("2 Team", "2_Team"),
            ("Team__2_", "Team__2_"),
        ],
    )
    def test_numeric_auditor_name_roundtrips(
        self,
        engagement_db: Path,
        monkeypatch: pytest.MonkeyPatch,
        auditor_name: str,
        auditor_token: str,
    ) -> None:
        monkeypatch.setattr(version_manager, "datetime", _FixedDatetime)
        mgr = EngagementVersionManager(engagement_db)

        first = mgr.create_snapshot(auditor_name)
        second = mgr.create_snapshot(auditor_name)

        assert first.name == f"ACME_2026-05-11_10-30-15-123456_{auditor_token}.db"
        assert second.name == f"ACME_2026-05-11_10-30-15-123456_{auditor_token}~2.db"
        assert [info.auditor_name for info in mgr.list_snapshots()] == [
            auditor_token,
            auditor_token,
        ]

    def test_stem_with_numeric_suffix_does_not_claim_other_database_snapshots(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(version_manager, "datetime", _FixedDatetime)
        first_database = tmp_path / "ACME.db"
        second_database = tmp_path / "ACME_2.db"
        _create_probe_database(first_database, "ACME")
        _create_probe_database(second_database, "ACME_2")
        first_manager = EngagementVersionManager(first_database)
        second_manager = EngagementVersionManager(second_database)

        acme_first = first_manager.create_snapshot("Team__2_")
        acme_second = first_manager.create_snapshot("Team__2_")
        acme_2_first = second_manager.create_snapshot("Team__2_")
        acme_2_second = second_manager.create_snapshot("Team__2_")

        assert acme_first.name == "ACME_2026-05-11_10-30-15-123456_Team__2_.db"
        assert acme_second.name == "ACME_2026-05-11_10-30-15-123456_Team__2_~2.db"
        assert acme_2_first.name == "ACME_2_2026-05-11_10-30-15-123456_Team__2_.db"
        assert acme_2_second.name == "ACME_2_2026-05-11_10-30-15-123456_Team__2_~2.db"
        assert [info.path for info in first_manager.list_snapshots()] == [
            acme_second,
            acme_first,
        ]
        assert [info.path for info in second_manager.list_snapshots()] == [
            acme_2_second,
            acme_2_first,
        ]
        assert {info.auditor_name for info in first_manager.list_snapshots()} == {"Team__2_"}
        assert {info.auditor_name for info in second_manager.list_snapshots()} == {"Team__2_"}

    def test_existing_symlink_is_collision_and_is_not_listed(
        self,
        engagement_db: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(version_manager, "datetime", _FixedDatetime)
        mgr = EngagementVersionManager(engagement_db)
        candidate = mgr.archive_dir / "ACME_2026-05-11_10-30-15-123456_Anna.db"
        symlink_target = tmp_path / "must-not-be-created.db"
        try:
            candidate.symlink_to(symlink_target)
        except (NotImplementedError, OSError) as exc:
            pytest.skip(f"Symlinks sind auf diesem System nicht verfügbar: {exc}")

        real_open = os.open

        def reject_opening_existing_symlink(path: Path, flags: int, mode: int) -> int:
            if path == candidate:
                raise AssertionError("Existing symlink candidates must be skipped before os.open")
            return real_open(path, flags, mode)

        monkeypatch.setattr(os, "open", reject_opening_existing_symlink)

        snapshot = mgr.create_snapshot("Anna")

        assert candidate.is_symlink()
        assert not symlink_target.exists()
        assert snapshot.name == "ACME_2026-05-11_10-30-15-123456_Anna~2.db"
        infos = mgr.list_snapshots()
        assert [info.path for info in infos] == [snapshot]
        assert infos[0].auditor_name == "Anna"

    def test_list_snapshots_uses_one_no_follow_metadata_read(
        self,
        engagement_db: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mgr = EngagementVersionManager(engagement_db)
        snapshot = mgr.archive_dir / "ACME_2026-05-11_10-30-00_Anna.db"
        _create_probe_database(snapshot, "listed")
        expected_size = snapshot.lstat().st_size
        real_is_file = Path.is_file
        real_stat = Path.stat

        def reject_following_is_file(
            path: Path,
            *,
            follow_symlinks: bool = True,
        ) -> bool:
            if path == snapshot:
                raise AssertionError("list_snapshots must not call Path.is_file")
            return real_is_file(path, follow_symlinks=follow_symlinks)

        def reject_following_stat(
            path: Path,
            *,
            follow_symlinks: bool = True,
        ) -> os.stat_result:
            if path == snapshot and follow_symlinks:
                raise AssertionError("list_snapshots must not follow Path.stat")
            return real_stat(path, follow_symlinks=follow_symlinks)

        monkeypatch.setattr(Path, "is_file", reject_following_is_file)
        monkeypatch.setattr(Path, "stat", reject_following_stat)

        infos = mgr.list_snapshots()

        assert [info.path for info in infos] == [snapshot]
        assert infos[0].size_bytes == expected_size

    def test_source_removed_before_open_is_not_recreated(
        self,
        engagement_db: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        real_connect = sqlite3.connect
        real_samestat = os.path.samestat
        source_uri = engagement_db.absolute().as_uri()
        removed = False
        simulated_inode_reuse = False

        def remove_source_then_connect(
            database: str,
            *,
            uri: bool = False,
        ) -> sqlite3.Connection:
            nonlocal removed
            is_source = database == str(engagement_db) or database == f"{source_uri}?mode=ro"
            if is_source and not removed:
                engagement_db.unlink()
                removed = True
            return real_connect(database, uri=uri)

        def simulate_source_inode_reuse(
            first: os.stat_result,
            second: os.stat_result,
        ) -> bool:
            nonlocal simulated_inode_reuse
            if first.st_size > 0 and second.st_size == 0:
                simulated_inode_reuse = True
                return True
            return real_samestat(first, second)

        monkeypatch.setattr(sqlite3, "connect", remove_source_then_connect)
        monkeypatch.setattr(os.path, "samestat", simulate_source_inode_reuse)
        mgr = EngagementVersionManager(engagement_db)

        with pytest.raises(sqlite3.OperationalError):
            mgr.create_snapshot("Anna")

        assert removed
        assert simulated_inode_reuse
        assert not engagement_db.exists()
        assert list(mgr.archive_dir.iterdir()) == []

    def test_snapshot_rechecks_reserved_target_after_backup(
        self,
        engagement_db: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(version_manager, "datetime", _FixedDatetime)
        mgr = EngagementVersionManager(engagement_db)
        target = mgr.archive_dir / "ACME_2026-05-11_10-30-15-123456_Anna.db"
        replacement = tmp_path / "replacement.db"
        replacement.write_bytes(b"must-not-be-chmodded-or-removed")
        probe = tmp_path / "symlink-probe"
        try:
            probe.symlink_to(replacement)
            probe.unlink()
        except (NotImplementedError, OSError) as exc:
            pytest.skip(f"Symlinks sind auf diesem System nicht verfügbar: {exc}")

        real_verify = version_manager._verify_reserved_target
        verification_calls = 0

        def replace_before_final_verify(path: Path, descriptor: int) -> None:
            nonlocal verification_calls
            verification_calls += 1
            if verification_calls == 4:
                try:
                    path.unlink()
                    path.symlink_to(replacement)
                except OSError as exc:
                    pytest.skip(f"Offene Datei kann hier nicht ersetzt werden: {exc}")
            real_verify(path, descriptor)

        monkeypatch.setattr(
            version_manager,
            "_verify_reserved_target",
            replace_before_final_verify,
        )

        with pytest.raises(OSError, match="während der Reservierung ersetzt"):
            mgr.create_snapshot("Anna")

        assert verification_calls >= 4
        assert target.is_symlink()
        assert replacement.read_bytes() == b"must-not-be-chmodded-or-removed"

    def test_failed_backup_removes_reserved_target(self, tmp_path: Path) -> None:
        source = tmp_path / "broken.db"
        source.write_bytes(b"not a sqlite database")
        mgr = EngagementVersionManager(source)

        with pytest.raises(sqlite3.DatabaseError):
            mgr.create_snapshot("Anna")

        assert list(mgr.archive_dir.iterdir()) == []

    def test_reserved_identity_failure_closes_and_removes_target(
        self,
        engagement_db: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        real_open = os.open
        real_close = os.close
        real_fstat = os.fstat
        opened_descriptors: list[int] = []
        closed_descriptors: list[int] = []
        fstat_calls = 0

        def record_open(path: Path, flags: int, mode: int) -> int:
            descriptor = real_open(path, flags, mode)
            opened_descriptors.append(descriptor)
            return descriptor

        def record_close(descriptor: int) -> None:
            real_close(descriptor)
            closed_descriptors.append(descriptor)

        def fail_reserved_identity_once(descriptor: int) -> os.stat_result:
            nonlocal fstat_calls
            fstat_calls += 1
            if fstat_calls == 2:
                raise OSError("injected reserved identity failure")
            return real_fstat(descriptor)

        monkeypatch.setattr(os, "open", record_open)
        monkeypatch.setattr(os, "close", record_close)
        monkeypatch.setattr(os, "fstat", fail_reserved_identity_once)

        try:
            with pytest.raises(OSError, match="injected reserved identity failure"):
                EngagementVersionManager(engagement_db).create_snapshot("Anna")

            assert fstat_calls >= 2
            assert opened_descriptors == closed_descriptors
            assert list((engagement_db.parent / "archiv").iterdir()) == []
        finally:
            for descriptor in set(opened_descriptors) - set(closed_descriptors):
                real_close(descriptor)
            for entry in (engagement_db.parent / "archiv").iterdir():
                entry.unlink()

    def test_restore_removes_stale_sidecars(
        self,
        engagement_db: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        snapshot = tmp_path / "snapshot.db"
        _create_probe_database(snapshot, "restored")
        wal = engagement_db.with_name(f"{engagement_db.name}-wal")
        shm = engagement_db.with_name(f"{engagement_db.name}-shm")
        wal.write_bytes(b"stale-wal")
        shm.write_bytes(b"stale-shm")

        real_copy2 = shutil.copy2

        def assert_sidecars_removed_before_copy(
            source: Path,
            destination: Path,
        ) -> Path | str:
            assert not wal.exists()
            assert not shm.exists()
            return real_copy2(source, destination)

        monkeypatch.setattr(shutil, "copy2", assert_sidecars_removed_before_copy)

        restored = EngagementVersionManager(engagement_db).restore_from_snapshot(snapshot)

        assert restored == engagement_db
        assert not wal.exists()
        assert not shm.exists()
        assert _read_probe_values(engagement_db) == ["restored"]

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

    def test_parse_snapshot_name_with_microseconds_and_counter(self) -> None:
        parsed = _parse_snapshot_name("ACME_2026-05-11_10-30-15-123456_Anna_Auditorin~2.db")
        assert parsed is not None
        timestamp, auditor = parsed
        assert timestamp == datetime(2026, 5, 11, 10, 30, 15, 123456)
        assert auditor == "Anna_Auditorin"
