"""`busy_indicator` – Widget-Disable statt Pixmap-Cursor (Sprint 91 / A)."""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot

from sampling_tool.ui._busy_indicator import busy_indicator

pytestmark = pytest.mark.ui


class TestBusyIndicator:
    def test_disables_widget_during_block_and_restores_after(self, qtbot: QtBot) -> None:
        button = QPushButton()
        qtbot.addWidget(button)

        with busy_indicator(button):
            assert button.isEnabled() is False

        assert button.isEnabled() is True

    def test_restores_enabled_state_even_if_block_raises(self, qtbot: QtBot) -> None:
        button = QPushButton()
        qtbot.addWidget(button)

        with pytest.raises(ValueError, match="boom"), busy_indicator(button):
            raise ValueError("boom")

        assert button.isEnabled() is True

    def test_keeps_already_disabled_widget_disabled_after(self, qtbot: QtBot) -> None:
        button = QPushButton()
        qtbot.addWidget(button)
        button.setEnabled(False)

        with busy_indicator(button):
            assert button.isEnabled() is False

        assert button.isEnabled() is False

    def test_none_widget_is_a_noop(self) -> None:
        with busy_indicator(None):
            pass
