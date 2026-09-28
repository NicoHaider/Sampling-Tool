"""Erkennt Projektpfade in synchronisierten Cloud-Ordnern (Sprint 89 / G).

SQLite mit WAL in einem Sync-Ordner ist ein Korruptionsrisiko: der Sync-Dienst
kann `.db`, `-wal` und `-shm` einzeln und zeitversetzt hochladen oder die
Datei nur als Platzhalter vorhalten. Mehrere echte Projekt-DBs waren beim
Test nur iCloud-Platzhalter. Der Hinweis blockiert nichts.

Reine Pfad-Logik; einzige Dateisystem-Abfrage ist der iCloud-Marker für
„Schreibtisch & Dokumente". `home` ist injizierbar, damit Tests nie das echte
Home-Verzeichnis brauchen.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Final

SYNC_FOLDER_HINT: Final[str] = (
    "Dieses Projekt liegt in einem synchronisierten Ordner ({service}). "
    "Cloud-Synchronisation kann Projektdateien beschädigen oder nur als Platzhalter "
    "vorhalten. Empfohlen: Projekt in einen lokalen Ordner verschieben."
)
#: Wortlaut für den Projekt-Ordner in den Einstellungen (Sprint 89 / G3).
SYNC_FOLDER_SETTINGS_HINT: Final[str] = (
    "Dieser Ordner wird synchronisiert ({service}). Cloud-Synchronisation kann "
    "Projektdateien beschädigen oder nur als Platzhalter vorhalten. Empfohlen: "
    "einen lokalen Ordner wählen."
)

#: Aufeinanderfolgende Pfadteile, die macOS für Cloud-Ordner nutzt.
_MACOS_CLOUD_PARENTS: Final[dict[tuple[str, str], str]] = {
    ("Library", "Mobile Documents"): "iCloud Drive",
    ("Library", "CloudStorage"): "Cloud-Speicher",
}
#: Namensbestandteile einzelner Ordner (ohne Groß-/Kleinschreibung).
_FOLDER_MARKERS: Final[tuple[tuple[str, str], ...]] = (
    ("onedrive", "OneDrive"),
    ("dropbox", "Dropbox"),
    ("icloud drive", "iCloud Drive"),
    ("iclouddrive", "iCloud Drive"),
)
_ICLOUD_DOCUMENTS_MARKER: Final[tuple[str, ...]] = (
    "Library",
    "Mobile Documents",
    "com~apple~CloudDocs",
    "Documents",
)


def sync_service(path: Path, *, home: Path | None = None) -> str | None:
    """Name des Sync-Dienstes, in dessen Ordner `path` liegt, sonst `None`.

    `~/Documents` zählt nur, wenn iCloud „Schreibtisch & Dokumente" aktiv ist
    (der Ordner `…/com~apple~CloudDocs/Documents` existiert).
    """
    parts = path.parts
    for pair in pairwise(parts):
        if pair in _MACOS_CLOUD_PARENTS:
            return _MACOS_CLOUD_PARENTS[pair]
    for part in parts:
        folded = part.casefold()
        for marker, service in _FOLDER_MARKERS:
            if marker in folded:
                return service
    home = Path.home() if home is None else home
    if home.joinpath(*_ICLOUD_DOCUMENTS_MARKER).is_dir() and _is_under(path, home / "Documents"):
        return "iCloud Drive, Schreibtisch & Dokumente"
    return None


def sync_folder_hint(
    path: Path, *, home: Path | None = None, template: str = SYNC_FOLDER_HINT
) -> str | None:
    """Anzeigetext für `path` in einem Sync-Ordner, sonst `None`."""
    service = sync_service(path, home=home)
    return None if service is None else template.format(service=service)


def _is_under(path: Path, base: Path) -> bool:
    if path.is_relative_to(base):
        return True
    return path.resolve().is_relative_to(base.resolve())
