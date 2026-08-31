"""Zusagen der Button-Hierarchie (Sprint 81).

Die Regel lautet: **ein roter Button pro Dialog** – der, der die Aktion
ausführt. Alles andere (Abbrechen, Zurücksetzen, Schließen) ist ein Rückweg und
trägt `secondary="true"`.

Diese Zusage bricht auf zwei Wegen, und beide sind still:

1. Ein neuer Dialog erzeugt seine `QDialogButtonBox` und ruft den Helfer nicht.
   Nichts wird rot markiert, was nicht rot sein sollte – es bleibt einfach alles
   rot, so wie es vor Sprint 81 überall war.
2. Der Helfer setzt die Property, aber Qt hat den Button längst poliert. Dann
   steht `secondary=True` auf dem Widget und ändert am Aussehen nichts. Genau
   deshalb prüft `test_property_is_visible_to_the_stylesheet` nicht die
   Property, sondern die tatsächlich aufgelöste Hintergrundfarbe.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QPushButton,
    QWidget,
)
from pytestqt.qtbot import QtBot

from sampling_tool.config import BDO_RED
from sampling_tool.ui._dialog_buttons import (
    mark_secondary,
    mark_secondary_buttons,
    set_accept_text,
)
from sampling_tool.ui._scaling import load_scaled_stylesheet

pytestmark = pytest.mark.ui


def _is_secondary(button: QAbstractButton) -> bool:
    return bool(button.property("secondary"))


def primary_buttons(widget: QWidget) -> list[str]:
    """Beschriftungen aller Buttons unter `widget`, die NICHT sekundär sind."""
    return [
        b.text()
        for b in widget.findChildren(QAbstractButton)
        if isinstance(b, QPushButton) and b.isVisible() and not _is_secondary(b)
    ]


class TestMarkSecondaryButtons:
    """Der Helfer trifft die Rückwege – und nur die."""

    def test_reject_and_reset_become_secondary_accept_stays_primary(self, qtbot: QtBot) -> None:
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Reset
            | QDialogButtonBox.StandardButton.Help
        )
        qtbot.addWidget(box)
        mark_secondary_buttons(box)

        by_role = {
            QDialogButtonBox.StandardButton.Ok: False,
            QDialogButtonBox.StandardButton.Cancel: True,
            QDialogButtonBox.StandardButton.Reset: True,
            QDialogButtonBox.StandardButton.Help: True,
        }
        for standard, expected in by_role.items():
            button = box.button(standard)
            assert button is not None
            assert _is_secondary(button) is expected, f"{standard!r}: erwartet secondary={expected}"

    def test_close_only_dialog_has_no_primary_button(self, qtbot: QtBot) -> None:
        """`Close` trägt RejectRole – ein reiner Schließen-Dialog hat kein rotes Ziel."""
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        qtbot.addWidget(box)
        mark_secondary_buttons(box)
        button = box.button(QDialogButtonBox.StandardButton.Close)
        assert button is not None
        assert _is_secondary(button)

    def test_ok_only_dialog_keeps_its_single_button_primary(self, qtbot: QtBot) -> None:
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        qtbot.addWidget(box)
        mark_secondary_buttons(box)
        button = box.button(QDialogButtonBox.StandardButton.Ok)
        assert button is not None
        assert not _is_secondary(button)

    def test_custom_accept_button_added_afterwards_stays_primary(self, qtbot: QtBot) -> None:
        """Das Muster aus `bug_report_dialog`: Cancel + eigener Accept-Button.

        Der Helfer muss NACH `addButton` laufen – der Test hält fest, dass er in
        dieser Reihenfolge das Richtige tut (und nicht etwa den eigenen Button
        mitfärbt, weil er keine Standard-Rolle hat).
        """
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        qtbot.addWidget(box)
        send = box.addButton("E-Mail vorbereiten", QDialogButtonBox.ButtonRole.AcceptRole)
        mark_secondary_buttons(box)

        cancel = box.button(QDialogButtonBox.StandardButton.Cancel)
        assert cancel is not None
        assert _is_secondary(cancel)
        assert send is not None
        assert not _is_secondary(send)

    def test_mark_secondary_tolerates_none(self) -> None:
        """Die Qt-Accessoren liefern `... | None`; der Helfer schluckt das."""
        mark_secondary(None)  # darf nicht werfen

    def test_set_accept_text_renames_only_the_accept_button(self, qtbot: QtBot) -> None:
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        qtbot.addWidget(box)
        set_accept_text(box, "Exportieren")

        ok = box.button(QDialogButtonBox.StandardButton.Ok)
        cancel = box.button(QDialogButtonBox.StandardButton.Cancel)
        assert ok is not None
        assert cancel is not None
        assert ok.text() == "Exportieren"
        assert cancel.text() != "Exportieren"


class TestPropertyReachesTheStylesheet:
    """Die Property ist kein Selbstzweck – sie muss das Aussehen ändern."""

    def test_property_is_visible_to_the_stylesheet(self, qtbot: QtBot) -> None:
        """Gemessen, nicht hergeleitet: der Rückweg-Button ist nicht mehr rot.

        `setProperty` allein genügt nicht – Qt wertet Property-Selektoren beim
        Polieren aus. Ein bereits polierter Button (und die Buttons einer
        `QDialogButtonBox` sind das, sobald die Box existiert) würde die
        Property tragen und trotzdem rot bleiben. Deshalb prüft dieser Test die
        aufgelöste Hintergrundfarbe gegen das echte Stylesheet, nicht die
        Property, die `TestMarkSecondaryButtons` schon abdeckt.
        """
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        previous = app.styleSheet()
        app.setStyleSheet(load_scaled_stylesheet(1.0))
        try:
            dialog = QDialog()
            qtbot.addWidget(dialog)
            box = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
                dialog,
            )
            dialog.show()
            qtbot.waitExposed(dialog)

            ok = box.button(QDialogButtonBox.StandardButton.Ok)
            cancel = box.button(QDialogButtonBox.StandardButton.Cancel)
            assert ok is not None
            assert cancel is not None

            # Vorher: beide tragen dasselbe Marken-Rot – das ist der Ist-Zustand,
            # den Sprint 81 auflöst. Ohne diese Zeile wäre der Test unten auch
            # dann grün, wenn die QSS gar kein Rot mehr setzte.
            assert ok.palette().button().color().name().upper() == BDO_RED

            mark_secondary(cancel)
            qtbot.wait(20)

            assert cancel.palette().button().color().name().upper() != BDO_RED, (
                "Der Rückweg-Button ist nach mark_secondary() immer noch im "
                "Marken-Rot – die Property erreicht das Stylesheet nicht "
                "(fehlendes unpolish/polish?)."
            )
            assert ok.palette().button().color().name().upper() == BDO_RED, (
                "Der Accept-Button hat sein Rot verloren – mark_secondary() "
                "trifft mehr als den einen Button."
            )
        finally:
            app.setStyleSheet(previous)


class TestOneRedButtonPerDialog:
    """Stichproben über echte Dialoge – die Regel gilt am Produkt, nicht am Helfer."""

    def test_settings_dialog_has_exactly_one_primary_button(self, qtbot: QtBot) -> None:
        from sampling_tool.ui.dialogs.settings_dialog import SettingsDialog
        from sampling_tool.ui.settings_store import AppSettings

        dialog = SettingsDialog(AppSettings.defaults())
        qtbot.addWidget(dialog)
        dialog.show()
        qtbot.waitExposed(dialog)

        primaries = primary_buttons(dialog)
        assert primaries == ["OK"], (
            f"Erwartet genau einen roten Button ('OK'), gefunden: {primaries}. "
            "'Auf Default zurücksetzen' ist die destruktivste Aktion des Dialogs "
            "und darf nicht die auffälligste sein."
        )

    def test_bug_report_dialog_has_exactly_one_primary_button(self, qtbot: QtBot) -> None:
        from sampling_tool.ui.dialogs.bug_report_dialog import BugReportDialog

        dialog = BugReportDialog()
        qtbot.addWidget(dialog)
        dialog.show()
        qtbot.waitExposed(dialog)

        assert primary_buttons(dialog) == ["E-Mail vorbereiten"]

    def test_duplicate_engagement_dialog_has_exactly_one_primary_button(self, qtbot: QtBot) -> None:
        from pathlib import Path

        from sampling_tool.ui.dialogs.duplicate_engagement_dialog import (
            DuplicateEngagementDialog,
        )

        dialog = DuplicateEngagementDialog(Path("/tmp/muster.db"))
        qtbot.addWidget(dialog)
        dialog.show()
        qtbot.waitExposed(dialog)

        assert primary_buttons(dialog) == ["Bestehendes öffnen"]
