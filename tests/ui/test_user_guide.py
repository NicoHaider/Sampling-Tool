"""Sprint 89 / F: „Hilfe → Handbuch" zeigt docs/USER_GUIDE.md in einem Fenster."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from PyQt6.QtGui import QKeySequence
from pytestqt.qtbot import QtBot

from sampling_tool import resources
from sampling_tool.ui.controllers.main_controller import MainController
from sampling_tool.ui.dialogs.user_guide_dialog import UserGuideDialog
from sampling_tool.ui.main_window import MainWindow
from sampling_tool.ui.recent import RecentEngagementsStore

pytestmark = pytest.mark.ui

_GUIDE = "# Handbuch\n\n## Stichprobe ziehen\n\nText über **Seed** und Population.\n"


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    return win


class TestResourcePath:
    def test_dev_path_is_the_committed_guide(self) -> None:
        path = resources.doc_resource("USER_GUIDE.md")
        assert path.parts[-2:] == ("docs", "USER_GUIDE.md")
        assert path.exists()

    def test_frozen_path_lives_in_the_bundle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert resources.doc_resource("USER_GUIDE.md") == tmp_path / "docs" / "USER_GUIDE.md"

    def test_spec_bundles_the_guide(self) -> None:
        spec = (Path(resources.__file__).resolve().parents[2] / "sampling_tool.spec").read_text(
            encoding="utf-8"
        )
        assert '(str(ROOT / "docs" / "USER_GUIDE.md"), "docs")' in spec


class TestMenuEntry:
    def test_help_menu_has_the_guide(self, window: MainWindow, qtbot: QtBot) -> None:
        assert window._action_user_guide in window._help_menu.actions()
        assert window._action_user_guide.text() == "Handbuch"
        assert window._action_user_guide.shortcut() == QKeySequence(
            QKeySequence.StandardKey.HelpContents
        )
        with qtbot.waitSignal(window.user_guide_requested, timeout=1000):
            window._action_user_guide.trigger()


class TestOpenGuide:
    def test_guide_opens_with_the_markdown(
        self,
        window: MainWindow,
        qtbot: QtBot,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        guide = tmp_path / "USER_GUIDE.md"
        guide.write_text(_GUIDE, encoding="utf-8")
        monkeypatch.setattr(
            "sampling_tool.ui.controllers.help_controller.doc_resource", lambda _name: guide
        )
        controller = MainController(window, recent_store=RecentEngagementsStore(tmp_path / "r"))
        window._action_user_guide.trigger()
        dialog = controller.help._user_guide
        assert isinstance(dialog, UserGuideDialog)
        qtbot.addWidget(dialog)
        assert dialog.isVisible()
        text = dialog.browser().toPlainText()
        assert "Stichprobe ziehen" in text
        assert "**" not in text  # als Markdown gerendert, nicht roh

    def test_second_call_reuses_the_window(
        self,
        window: MainWindow,
        qtbot: QtBot,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        guide = tmp_path / "USER_GUIDE.md"
        guide.write_text(_GUIDE, encoding="utf-8")
        monkeypatch.setattr(
            "sampling_tool.ui.controllers.help_controller.doc_resource", lambda _name: guide
        )
        controller = MainController(window, recent_store=RecentEngagementsStore(tmp_path / "r"))
        controller.help.handle_user_guide()
        first = controller.help._user_guide
        assert first is not None
        qtbot.addWidget(first)
        controller.help.handle_user_guide()
        assert controller.help._user_guide is first

    def test_missing_guide_gives_a_friendly_message(
        self,
        window: MainWindow,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "sampling_tool.ui.controllers.help_controller.doc_resource",
            lambda _name: tmp_path / "fehlt.md",
        )
        controller = MainController(window, recent_store=RecentEngagementsStore(tmp_path / "r"))
        with patch("sampling_tool.ui.controllers.help_controller.QMessageBox.information") as info:
            controller.help.handle_user_guide()
        info.assert_called_once()
        assert "Handbuch" in info.call_args.args[1]
        assert controller.help._user_guide is None


class TestSearch:
    def test_find_moves_to_the_hit_and_wraps(self, qtbot: QtBot) -> None:
        dialog = UserGuideDialog(_GUIDE + "\nNoch einmal Seed.\n")
        qtbot.addWidget(dialog)
        dialog.search_field().setText("seed")
        assert dialog.find_next() is True
        first = dialog.browser().textCursor().position()
        assert dialog.find_next() is True
        assert dialog.browser().textCursor().position() > first
        assert dialog.find_next() is True  # wieder von vorn
        assert dialog.browser().textCursor().position() == first

    def test_no_hit_is_reported(self, qtbot: QtBot) -> None:
        dialog = UserGuideDialog(_GUIDE)
        qtbot.addWidget(dialog)
        dialog.search_field().setText("gibtsnicht")
        assert dialog.find_next() is False
        assert "Keine Treffer" in dialog.status_text()

    def test_find_shortcut_focuses_the_search(self, qtbot: QtBot) -> None:
        dialog = UserGuideDialog(_GUIDE)
        qtbot.addWidget(dialog)
        assert dialog.find_shortcut().key() == QKeySequence(QKeySequence.StandardKey.Find)


class TestLinks:
    """Review-Befund: ein relativer Link leerte das Handbuch bis zum Neustart."""

    _LINKED = (
        "# Handbuch\n\n[Installation](INSTALL_USER.md) · [Kapitel 2](#2-zweites-kapitel)"
        " · [Web](https://example.org)\n\n"
        + "Absatz.\n\n" * 200
        + "## 2. Zweites Kapitel\n\nZiel.\n"
    )

    def test_relative_document_link_keeps_the_guide(self, qtbot: QtBot) -> None:
        from PyQt6.QtCore import QUrl

        dialog = UserGuideDialog(self._LINKED)
        qtbot.addWidget(dialog)
        dialog.browser().anchorClicked.emit(QUrl("INSTALL_USER.md"))
        assert "Zweites Kapitel" in dialog.browser().toPlainText()
        assert "nicht in der App" in dialog.status_text()

    def test_toc_anchor_jumps_to_the_heading(self, qtbot: QtBot) -> None:
        from PyQt6.QtCore import QUrl

        dialog = UserGuideDialog(self._LINKED)
        qtbot.addWidget(dialog)
        dialog.browser().anchorClicked.emit(QUrl("#2-zweites-kapitel"))
        block = dialog.browser().textCursor().block()
        assert block.text() == "2. Zweites Kapitel"

    def test_web_link_opens_outside(self, qtbot: QtBot) -> None:
        from PyQt6.QtCore import QUrl

        dialog = UserGuideDialog(self._LINKED)
        qtbot.addWidget(dialog)
        with patch(
            "sampling_tool.ui.dialogs.user_guide_dialog.QDesktopServices.openUrl"
        ) as open_url:
            dialog.browser().anchorClicked.emit(QUrl("https://example.org"))
        open_url.assert_called_once()
        assert "Zweites Kapitel" in dialog.browser().toPlainText()
