"""BugReportDialog – mailto-URL, URL-Encoding, App-Info-Inclusion."""

from __future__ import annotations

import urllib.parse
from unittest.mock import patch

import pytest
from pytestqt.qtbot import QtBot

from sampling_tool import __version__
from sampling_tool.config import BUG_REPORT_EMAIL
from sampling_tool.ui.dialogs.bug_report_dialog import (
    BugReportDialog,
    BugReportPayload,
)

pytestmark = pytest.mark.ui


class TestBugReportPayload:
    def test_subject_includes_version(self) -> None:
        payload = BugReportPayload(
            what_did_you_do="x",
            what_did_you_expect="y",
            what_happened_instead="z",
            include_system_info=False,
        )
        assert __version__ in payload.subject()

    def test_body_with_system_info_includes_platform(self) -> None:
        payload = BugReportPayload(
            what_did_you_do="x",
            what_did_you_expect="y",
            what_happened_instead="z",
            include_system_info=True,
        )
        body = payload.body()
        assert "App-Version" in body
        assert "OS:" in body

    def test_body_without_system_info_omits_platform(self) -> None:
        payload = BugReportPayload(
            what_did_you_do="x",
            what_did_you_expect="y",
            what_happened_instead="z",
            include_system_info=False,
        )
        assert "App-Version" not in payload.body()

    def test_mailto_encodes_special_chars(self) -> None:
        payload = BugReportPayload(
            what_did_you_do="A & B",
            what_did_you_expect="C => D",
            what_happened_instead="öäü %",
            include_system_info=False,
        )
        url = payload.mailto_url()
        assert url.startswith(f"mailto:{BUG_REPORT_EMAIL}?")
        # Sonderzeichen müssen URL-encoded sein:
        assert "%26" in url  # &
        assert "%C3%B6" in url or "%F6" in url  # ö
        # Decoded muss den Original-Text enthalten:
        decoded = urllib.parse.unquote(url)
        assert "A & B" in decoded
        assert "öäü" in decoded


class TestBugReportDialog:
    def test_accept_opens_mailto_url(self, qtbot: QtBot) -> None:
        dialog = BugReportDialog()
        qtbot.addWidget(dialog)
        dialog._did.setPlainText("klick auf import")
        dialog._expected.setPlainText("import läuft durch")
        dialog._actual.setPlainText("crash")
        with patch(
            "sampling_tool.ui.dialogs.bug_report_dialog.QDesktopServices.openUrl"
        ) as open_url:
            dialog._on_accept()
        open_url.assert_called_once()
        url_arg = open_url.call_args.args[0]
        assert url_arg.toString().startswith("mailto:")
