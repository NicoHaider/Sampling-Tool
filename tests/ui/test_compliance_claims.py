"""ISAE-Claim (D.6a, Variante B): About-Dialog und Welcome-Screen tragen die
präzise Formulierung – keine pauschale Konformitätszusage mehr.

Freigegebene Formulierung: „Unterstützt reproduzierbare, dokumentierte
Audit-Stichproben für ISAE-3402-Prüfungen." Das frühere „konform mit
ISAE 3402" darf an keiner der beiden Stellen mehr auftauchen.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from sampling_tool.ui.dialogs.about_dialog import AboutDialog
from sampling_tool.ui.widgets.welcome import WelcomeScreen

pytestmark = pytest.mark.ui

_PRECISE_CLAIM = (
    "Unterstützt reproduzierbare, dokumentierte Audit-Stichproben für ISAE-3402-Prüfungen."
)
_OLD_CLAIM = "konform mit ISAE 3402"


def _label_texts(widget: object) -> str:
    labels = widget.findChildren(QLabel)  # type: ignore[attr-defined]
    return "\n".join(label.text() for label in labels)


class TestIsaeClaimPrecise:
    def test_about_dialog_uses_precise_claim(self, qtbot: QtBot) -> None:
        dialog = AboutDialog()
        qtbot.addWidget(dialog)
        text = _label_texts(dialog)
        assert _PRECISE_CLAIM in text
        assert _OLD_CLAIM not in text

    def test_welcome_screen_uses_precise_claim(self, qtbot: QtBot) -> None:
        welcome = WelcomeScreen()
        qtbot.addWidget(welcome)
        text = _label_texts(welcome)
        assert _PRECISE_CLAIM in text
        assert _OLD_CLAIM not in text
