"""Persistenz der zuletzt geöffneten Engagements.

JSON-Datei unter dem plattformspezifischen User-Data-Dir
(`platformdirs.user_data_dir`) – auf macOS landet sie unter
`~/Library/Application Support/AuditSamplingTool/recent.json`, auf
Windows unter `%APPDATA%\\BDO\\AuditSamplingTool\\recent.json`.

Defekte / verschwundene `.db`-Dateien werden beim Listen herausgefiltert
(aber nicht persistent entfernt – das übernimmt erst `prune_missing`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from platformdirs import user_data_dir

# Alias auf den builtin `list`. Innerhalb der Klasse `RecentEngagementsStore`
# schattet die Methode `list` den builtin – mit `_List` bleiben die Annotations
# eindeutig (mypy würde sonst `list[RecentEntry]` auf die Methode beziehen).
_List = list

APP_NAME: str = "AuditSamplingTool"
APP_AUTHOR: str = "BDO"
RECENT_FILENAME: str = "recent.json"
DEFAULT_LIMIT: int = 5
MAX_ENTRIES: int = 50


@dataclass(frozen=True, slots=True)
class RecentEntry:
    """Ein Eintrag in der Recent-Liste."""

    path: Path
    client_name: str
    audit_type: str
    last_opened: datetime
    opened_count: int = 1


def default_recent_path() -> Path:
    """Plattformspezifischer Default-Pfad zur recent.json."""
    base = Path(user_data_dir(appname=APP_NAME, appauthor=APP_AUTHOR))
    return base / RECENT_FILENAME


class RecentEngagementsStore:
    """Liest/schreibt die `recent.json` mit den zuletzt geöffneten Engagements."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else default_recent_path()

    # ---- Public API -----------------------------------------------------

    def add(self, db_path: Path, client_name: str, audit_type: str) -> RecentEntry:
        """Fügt ein Engagement hinzu (oder aktualisiert den vorhandenen Eintrag)."""
        entries = self._load()
        absolute = db_path.resolve()
        now = datetime.now(UTC)

        existing_idx = next(
            (i for i, e in enumerate(entries) if e.path == absolute),
            None,
        )
        if existing_idx is not None:
            old = entries.pop(existing_idx)
            entry = replace(
                old,
                client_name=client_name,
                audit_type=audit_type,
                last_opened=now,
                opened_count=old.opened_count + 1,
            )
        else:
            entry = RecentEntry(
                path=absolute,
                client_name=client_name,
                audit_type=audit_type,
                last_opened=now,
                opened_count=1,
            )

        entries.insert(0, entry)
        self._save(entries[:MAX_ENTRIES])
        return entry

    def list(self, limit: int = DEFAULT_LIMIT) -> _List[RecentEntry]:
        """Letzte (existierende) Engagements – limitiert auf `limit`."""
        return [e for e in self._load() if e.path.exists()][:limit]

    def remove(self, db_path: Path) -> None:
        """Entfernt einen Eintrag (idempotent – kein Fehler bei unbekanntem Pfad)."""
        absolute = db_path.resolve()
        entries = [e for e in self._load() if e.path != absolute]
        self._save(entries)

    def prune_missing(self) -> int:
        """Entfernt Einträge, deren Datei nicht mehr existiert. Liefert Anzahl."""
        entries = self._load()
        remaining = [e for e in entries if e.path.exists()]
        removed = len(entries) - len(remaining)
        if removed > 0:
            self._save(remaining)
        return removed

    # ---- I/O -----------------------------------------------------------

    def _load(self) -> _List[RecentEntry]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        items = raw.get("entries", []) if isinstance(raw, dict) else []
        result: _List[RecentEntry] = []
        for item in items:
            entry = _entry_from_dict(item)
            if entry is not None:
                result.append(entry)
        return result

    def _save(self, entries: _List[RecentEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"entries": [_entry_to_dict(e) for e in entries]}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# JSON-(De-)Serialisierung
# ---------------------------------------------------------------------------


def _entry_to_dict(entry: RecentEntry) -> dict[str, object]:
    return {
        "path": str(entry.path),
        "client_name": entry.client_name,
        "audit_type": entry.audit_type,
        "last_opened": entry.last_opened.isoformat(),
        "opened_count": entry.opened_count,
    }


def _entry_from_dict(item: object) -> RecentEntry | None:
    if not isinstance(item, dict):
        return None
    try:
        path = Path(str(item["path"]))
        client = str(item["client_name"])
        audit_type = str(item["audit_type"])
        last_opened_raw = str(item["last_opened"])
        opened_count = int(item.get("opened_count", 1))
    except (KeyError, TypeError, ValueError):
        return None
    try:
        last_opened = datetime.fromisoformat(last_opened_raw)
    except ValueError:
        return None
    if last_opened.tzinfo is None:
        last_opened = last_opened.replace(tzinfo=UTC)
    return RecentEntry(
        path=path,
        client_name=client,
        audit_type=audit_type,
        last_opened=last_opened,
        opened_count=opened_count,
    )
