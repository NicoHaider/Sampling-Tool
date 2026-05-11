"""AboutDialog – Version, Repo-Link, Accept."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytestqt.qtbot import QtBot

from sampling_tool import __version__
from sampling_tool.ui.dialogs.about_dialog import REPO_URL, AboutDialog

pytestmark = pytest.mark.ui


class TestAboutDialog:
    def test_dialog_contains_version_string(self, qtbot: QtBot) -> None:
        dialog = AboutDialog()
        qtbot.addWidget(dialog)
        # findChildren-Texte sammeln
        all_text = " ".join(
            child.text()
            for child in dialog.findChildren(type(dialog._repo_label))
            if hasattr(child, "text")
        )
        assert __version__ in all_text

    def test_repo_link_opens_via_qdesktopservices(self, qtbot: QtBot) -> None:
        dialog = AboutDialog()
        qtbot.addWidget(dialog)
        with patch("sampling_tool.ui.dialogs.about_dialog.QDesktopServices.openUrl") as open_url:
            dialog._open_repo(REPO_URL)
        open_url.assert_called_once()
        assert open_url.call_args.args[0].toString() == REPO_URL

    def test_ok_accepts_dialog(self, qtbot: QtBot) -> None:
        dialog = AboutDialog()
        qtbot.addWidget(dialog)
        dialog.accept()
        # Dialog hatte keinen result-State, aber Accept-Code ist != Rejected:
        from PyQt6.QtWidgets import QDialog

        assert dialog.result() == int(QDialog.DialogCode.Accepted)
