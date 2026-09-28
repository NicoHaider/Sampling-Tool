"""Sprint 89 / G: Erkennung synchronisierter Ordner (reine Pfad-Logik + iCloud-Marker)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sampling_tool.io.sync_folders import sync_folder_hint, sync_service

pytestmark = pytest.mark.unit


def _icloud_documents_marker(home: Path) -> None:
    (home / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Documents").mkdir(
        parents=True
    )


@pytest.mark.parametrize(
    "parts",
    [
        ("Library", "Mobile Documents", "com~apple~CloudDocs", "Projekte"),
        ("Library", "CloudStorage", "OneDrive-BDO", "Projekte"),
        ("OneDrive - BDO Austria", "Projekte"),
        ("OneDrive", "Projekte"),
        ("Dropbox", "Projekte"),
        ("iCloud Drive", "Projekte"),
    ],
)
def test_sync_markers_are_detected(tmp_path: Path, parts: tuple[str, ...]) -> None:
    project = tmp_path.joinpath(*parts, "ACME.db")
    assert sync_service(project, home=tmp_path / "home") is not None


def test_local_folder_is_fine(tmp_path: Path) -> None:
    home = tmp_path / "home"
    assert sync_service(home / "BDO Audit Sampling" / "ACME" / "ACME.db", home=home) is None


def test_documents_only_count_when_icloud_desktop_and_documents_is_on(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = home / "Documents" / "BDO Audit Sampling" / "SMOKE" / "SMOKE.db"
    assert sync_service(project, home=home) is None
    _icloud_documents_marker(home)
    assert sync_service(project, home=home) is not None


def test_hint_text(tmp_path: Path) -> None:
    hint = sync_folder_hint(tmp_path / "Dropbox" / "p.db", home=tmp_path / "home")
    assert hint is not None
    assert "synchronisierten Ordner" in hint
    assert "lokalen Ordner" in hint
    assert sync_folder_hint(tmp_path / "lokal" / "p.db", home=tmp_path / "home") is None
