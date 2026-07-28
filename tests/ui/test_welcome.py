"""Tests für `WelcomeScreen`/`_RecentCard` – UI-Skalierung (Sprint 68 / Teil B1)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from sampling_tool.ui.recent import RecentEntry
from sampling_tool.ui.widgets.welcome import WelcomeScreen, _RecentCard

pytestmark = pytest.mark.ui


def _entry(tmp_path: Path) -> RecentEntry:
    return RecentEntry(
        path=tmp_path / "acme.db",
        client_name="ACME",
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
