"""Tests für `WelcomeScreen`/`_RecentCard` – UI-Skalierung (Sprint 68 / Teil B1)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QLabel, QScrollArea
from pytestqt.qtbot import QtBot

from sampling_tool.ui.recent import RecentEntry
from sampling_tool.ui.widgets.welcome import _OUTER_MARGIN, WelcomeScreen, _RecentCard

pytestmark = pytest.mark.ui


def _entry(tmp_path: Path, index: int = 0) -> RecentEntry:
    return RecentEntry(
        path=tmp_path / f"acme{index}.db",
        client_name=f"ACME {index}",
        audit_type="ISAE 3402",
        last_opened=datetime.now(UTC),
    )


class TestUiScale:
    def test_default_factor_matches_base_size(self, qtbot: QtBot, tmp_path: Path) -> None:
        screen = WelcomeScreen()
        qtbot.addWidget(screen)
        screen.set_recent_entries([_entry(tmp_path)])
        cards = screen.findChildren(_RecentCard)
        assert cards
        title_labels = [c for c in cards[0].children() if hasattr(c, "styleSheet")]
        assert any("font-size: 14px" in lbl.styleSheet() for lbl in title_labels)

    def test_set_ui_scale_rerenders_cards_at_new_size(self, qtbot: QtBot, tmp_path: Path) -> None:
        screen = WelcomeScreen()
        qtbot.addWidget(screen)
        screen.set_recent_entries([_entry(tmp_path)])
        screen.set_ui_scale(1.15)
        cards = screen.findChildren(_RecentCard)
        assert cards
        title_labels = [c for c in cards[0].children() if hasattr(c, "styleSheet")]
        assert any("font-size: 16px" in lbl.styleSheet() for lbl in title_labels)

    def test_set_ui_scale_without_entries_does_not_crash(self, qtbot: QtBot) -> None:
        screen = WelcomeScreen()
        qtbot.addWidget(screen)
        screen.set_ui_scale(0.9)  # kein set_recent_entries() zuvor.
        assert screen.recent_card_count() == 0


class TestWelcomeLayout:
    """Sprint 70 / Befund A: Inhalt war vertikal zentriert statt oben bündig."""

    def test_outer_layout_has_no_stretch_spacers(self, qtbot: QtBot) -> None:
        screen = WelcomeScreen()
        qtbot.addWidget(screen)
        layout = screen.layout()
        assert layout is not None
        for i in range(layout.count()):
            item = layout.itemAt(i)
            assert item is not None
            assert item.spacerItem() is None

    def test_content_starts_at_top_margin(self, qtbot: QtBot) -> None:
        screen = WelcomeScreen()
        qtbot.addWidget(screen)
        screen.resize(900, 1200)
        layout = screen.layout()
        assert layout is not None
        layout.activate()
        logo = screen.findChild(QLabel, "LogoPlaceholder")
        assert logo is not None
        assert logo.y() <= _OUTER_MARGIN + 2

    def test_recent_scroll_area_fills_remaining_height(self, qtbot: QtBot) -> None:
        screen = WelcomeScreen()
        qtbot.addWidget(screen)
        screen.resize(900, 1200)
        layout = screen.layout()
        assert layout is not None
        layout.activate()
        scroll = screen.findChild(QScrollArea)
        assert scroll is not None
        assert scroll.geometry().bottom() >= screen.height() - _OUTER_MARGIN - 2

    def test_recent_list_still_scrolls_when_small(self, qtbot: QtBot, tmp_path: Path) -> None:
        screen = WelcomeScreen()
        qtbot.addWidget(screen)
        screen.resize(600, 400)
        screen.set_recent_entries([_entry(tmp_path, i) for i in range(8)])
        layout = screen.layout()
        assert layout is not None
        layout.activate()
        assert screen.recent_card_count() == 8
        scroll = screen.findChild(QScrollArea)
        assert scroll is not None
        content = scroll.widget()
        assert content is not None
        viewport = scroll.viewport()
        assert viewport is not None
        assert content.sizeHint().height() > viewport.height()


class TestOpenDialogStartDir:
    """Sprint 90 / B: gemeinsame Startordner-Logik für „Projekt öffnen"."""

    def test_configured_folder_wins(self, tmp_path: Path) -> None:
        from dataclasses import replace

        from sampling_tool.ui.settings_store import (
            load_settings,
            open_dialog_start_dir,
            save_settings,
        )

        folder = tmp_path / "meine-projekte"
        folder.mkdir()
        save_settings(replace(load_settings(), engagements_dir=folder))
        assert open_dialog_start_dir() == str(folder)

    def test_missing_configured_folder_falls_back_to_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dataclasses import replace

        from sampling_tool.ui import settings_store

        default = tmp_path / "default"
        default.mkdir()
        monkeypatch.setattr(settings_store, "ENGAGEMENTS_DIR", default)
        settings_store.save_settings(
            replace(settings_store.load_settings(), engagements_dir=tmp_path / "weg")
        )
        assert settings_store.open_dialog_start_dir() == str(default)

    def test_nothing_exists_gives_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dataclasses import replace

        from sampling_tool.ui import settings_store

        monkeypatch.setattr(settings_store, "ENGAGEMENTS_DIR", tmp_path / "fehlt")
        settings_store.save_settings(
            replace(settings_store.load_settings(), engagements_dir=tmp_path / "weg")
        )
        assert settings_store.open_dialog_start_dir() == ""

    def test_welcome_open_dialog_uses_configured_folder(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dataclasses import replace

        from sampling_tool.ui.settings_store import load_settings, save_settings

        folder = tmp_path / "meine-projekte"
        folder.mkdir()
        save_settings(replace(load_settings(), engagements_dir=folder))
        captured: list[str] = []

        def _fake_open(_parent: object, _caption: str, directory: str, _f: str) -> tuple[str, str]:
            captured.append(directory)
            return ("", "")

        monkeypatch.setattr(
            "sampling_tool.ui.widgets.welcome.QFileDialog.getOpenFileName", _fake_open
        )
        screen = WelcomeScreen()
        qtbot.addWidget(screen)
        screen._on_open_clicked()

        assert captured == [str(folder)]
