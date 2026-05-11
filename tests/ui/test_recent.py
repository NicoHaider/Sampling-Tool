"""RecentEngagementsStore – Add/List/Remove + Pruning + JSON-Roundtrip."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sampling_tool.ui.recent import RecentEngagementsStore

pytestmark = pytest.mark.unit


@pytest.fixture
def store(tmp_path: Path) -> RecentEngagementsStore:
    return RecentEngagementsStore(path=tmp_path / "recent.json")


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    path = tmp_path / "engagement.db"
    path.write_text("")
    return path


class TestRecentEngagementsStore:
    def test_empty_list_when_no_file(self, store: RecentEngagementsStore) -> None:
        assert store.list() == []

    def test_add_persists_entry_to_disk(self, store: RecentEngagementsStore, db_file: Path) -> None:
        store.add(db_file, "ACME GmbH", "ISAE 3402")
        assert store.path.exists()
        payload = json.loads(store.path.read_text(encoding="utf-8"))
        assert payload["entries"][0]["client_name"] == "ACME GmbH"
        assert payload["entries"][0]["opened_count"] == 1

    def test_add_existing_increments_opened_count(
        self, store: RecentEngagementsStore, db_file: Path
    ) -> None:
        store.add(db_file, "ACME GmbH", "ISAE 3402")
        store.add(db_file, "ACME GmbH", "ISAE 3402")
        entries = store.list()
        assert len(entries) == 1
        assert entries[0].opened_count == 2

    def test_list_filters_missing_paths(
        self, store: RecentEngagementsStore, tmp_path: Path
    ) -> None:
        missing = tmp_path / "ghost.db"
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text(
            json.dumps(
                {
                    "entries": [
                        {
                            "path": str(missing),
                            "client_name": "Ghost",
                            "audit_type": "—",
                            "last_opened": datetime.now(UTC).isoformat(),
                            "opened_count": 1,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        assert store.list() == []

    def test_remove_drops_entry(self, store: RecentEngagementsStore, db_file: Path) -> None:
        store.add(db_file, "A", "X")
        store.remove(db_file)
        assert store.list() == []

    def test_prune_missing_removes_dead_paths(
        self, store: RecentEngagementsStore, db_file: Path, tmp_path: Path
    ) -> None:
        store.add(db_file, "A", "X")
        ghost = tmp_path / "ghost.db"
        ghost.write_text("")
        store.add(ghost, "B", "Y")
        ghost.unlink()
        removed = store.prune_missing()
        assert removed == 1
        assert len(store.list()) == 1

    def test_corrupt_json_returns_empty_list(self, store: RecentEngagementsStore) -> None:
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text("not json at all", encoding="utf-8")
        assert store.list() == []

    def test_recent_entries_sorted_by_last_opened_first(
        self, store: RecentEngagementsStore, tmp_path: Path
    ) -> None:
        older = tmp_path / "older.db"
        newer = tmp_path / "newer.db"
        older.write_text("")
        newer.write_text("")
        store.add(older, "A", "X")
        # Eine Sekunde Versatz simulieren, indem wir last_opened in JSON manuell setzen.
        store.add(newer, "B", "Y")
        raw = json.loads(store.path.read_text(encoding="utf-8"))
        raw["entries"][1]["last_opened"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        store.path.write_text(json.dumps(raw), encoding="utf-8")
        first = store.list()[0]
        assert first.path.name == "newer.db"
