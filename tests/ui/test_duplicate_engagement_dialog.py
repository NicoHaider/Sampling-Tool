"""DuplicateEngagementDialog – Result-Enum & Button-Verhalten."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from sampling_tool.ui.dialogs.duplicate_engagement_dialog import (
    DuplicateEngagementChoice,
    DuplicateEngagementDialog,
)

pytestmark = pytest.mark.ui


class TestDuplicateEngagementDialog:
    def test_default_choice_is_cancel_before_user_interaction(self, qtbot: QtBot) -> None:
        dialog = DuplicateEngagementDialog(Path("/tmp/x.db"))
        qtbot.addWidget(dialog)
        assert dialog.choice() is DuplicateEngagementChoice.CANCEL

    def test_open_existing_button_sets_choice_and_accepts(self, qtbot: QtBot) -> None:
        dialog = DuplicateEngagementDialog(Path("/tmp/foo.db"))
        qtbot.addWidget(dialog)
        dialog._open_btn.click()
        assert dialog.choice() is DuplicateEngagementChoice.OPEN_EXISTING
        assert dialog.result() == int(dialog.DialogCode.Accepted)

    def test_rename_button_sets_choice_and_accepts(self, qtbot: QtBot) -> None:
        dialog = DuplicateEngagementDialog(Path("/tmp/foo.db"))
        qtbot.addWidget(dialog)
        dialog._rename_btn.click()
        assert dialog.choice() is DuplicateEngagementChoice.RENAME
        assert dialog.result() == int(dialog.DialogCode.Accepted)

    def test_cancel_button_sets_choice_and_rejects(self, qtbot: QtBot) -> None:
        dialog = DuplicateEngagementDialog(Path("/tmp/foo.db"))
        qtbot.addWidget(dialog)
        dialog._cancel_btn.click()
        assert dialog.choice() is DuplicateEngagementChoice.CANCEL
        assert dialog.result() == int(dialog.DialogCode.Rejected)

    def test_message_mentions_filename_and_parent(self, qtbot: QtBot) -> None:
        db_path = Path("/tmp/some_mandant/some_mandant.db")
        dialog = DuplicateEngagementDialog(db_path)
        qtbot.addWidget(dialog)
        full_text = " ".join(label.text() for label in dialog.findChildren(QLabel))
        assert "some_mandant.db" in full_text
        # Der Dialog interpoliert `db_path.parent` – auf Windows also mit
        # Backslashes. Erwartungswert daher aus demselben Path ableiten.
        assert str(db_path.parent) in full_text


class TestOverwriteChoice:
    """Sprint 30: vierte Option „Überschreiben (mit Backup)"."""

    def test_overwrite_button_sets_choice_overwrite(self, qtbot: QtBot) -> None:
        dialog = DuplicateEngagementDialog(Path("/tmp/foo.db"))
        qtbot.addWidget(dialog)
        dialog._overwrite_btn.click()
        assert dialog.choice() is DuplicateEngagementChoice.OVERWRITE
        assert dialog.result() == int(dialog.DialogCode.Accepted)

    def test_default_button_is_open_existing(self, qtbot: QtBot) -> None:
        dialog = DuplicateEngagementDialog(Path("/tmp/foo.db"))
        qtbot.addWidget(dialog)
        # „Bestehendes öffnen" bleibt der sicherste Default-Button.
        assert dialog._open_btn.isDefault() is True
        assert dialog._overwrite_btn.isDefault() is False
