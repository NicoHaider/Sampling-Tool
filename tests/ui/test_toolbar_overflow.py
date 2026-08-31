"""Zusage der Toolbar-Breite bei der Ziel-Fenstergröße (Sprint 81).

Zielhardware ist ein 13-Zoll-Lenovo mit 1920×1200 bei 125 % Windows-Skalierung,
also **1536 × 960 logische Pixel** – nicht ein 27-Zoll-Monitor. Bei dieser
Breite lagen vier der Haupt-Aktionen hinter dem `»`-Überlaufmenü. Wer
exportieren wollte, musste ein Menü öffnen, das aussieht wie ein Zeichen.

Die Prüfung misst die tatsächliche Sichtbarkeit der Toolbar-Buttons. Sie hätte
auch als „`ToolButtonIconOnly` steht auf sechs Buttons" geschrieben werden
können – aber das ist die Mechanik, nicht die Wirkung: die Zusage ist „bei
1536 px ist alles erreichbar", und die kann auch durch ein längeres Label oder
ein größeres Icon brechen, ohne dass jemand den Stil anfasst.

`test_icon_only_style_is_what_makes_them_fit` belegt per Neutralisierung, dass
die Messung überhaupt etwas misst: ohne den Stil müssen wieder Aktionen
verschwinden. Ohne diese Gegenprobe wäre der Test auch dann grün, wenn die
Toolbar aus einem ganz anderen Grund passt.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from sampling_tool.ui import _window_toolbar
from sampling_tool.ui._scaling import load_scaled_stylesheet
from sampling_tool.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

#: Die Design-Ziel-Fenstergröße (13 Zoll, Windows 125 %).
TARGET_WIDTH = 1536
TARGET_HEIGHT = 960


def _hidden_action_texts(win: MainWindow) -> list[str]:
    """Beschriftungen der Aktionen, deren Button gerade NICHT sichtbar ist."""
    toolbar = win._toolbar
    hidden = []
    for action in toolbar.actions():
        if action.isSeparator() or not action.text():
            continue
        widget = toolbar.widgetForAction(action)
        if widget is not None and not widget.isVisible():
            hidden.append(action.text())
    return hidden


def _overflow_button_visible(win: MainWindow) -> bool:
    """Ist der `»`-Überlauf-Button sichtbar?

    In PyQt6 heißt die Klasse je nach Stil `QToolBarExtension` oder schlicht
    `QToolButton` – deshalb wird zusätzlich über den objectName gesucht, den Qt
    intern vergibt.
    """
    for child in win._toolbar.children():
        if not isinstance(child, QWidget):
            continue
        if (
            child.objectName() == "qt_toolbar_ext_button"
            or type(child).__name__ == "QToolBarExtension"
        ):
            return bool(child.isVisible())
    return False


def _build_window(qtbot: QtBot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show_workspace()
    win.show()
    qtbot.waitExposed(win)
    win.resize(TARGET_WIDTH, TARGET_HEIGHT)
    qtbot.wait(50)
    return win


class TestToolbarFitsTheTargetWindow:
    def test_no_action_is_hidden_at_the_design_size(self, qtbot: QtBot) -> None:
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        previous = app.styleSheet()
        app.setStyleSheet(load_scaled_stylesheet(1.0))
        try:
            win = _build_window(qtbot)
            hidden = _hidden_action_texts(win)
            assert not hidden, (
                f"Bei {TARGET_WIDTH}×{TARGET_HEIGHT} liegen {len(hidden)} Aktionen "
                f"hinter dem »-Überlaufmenü: {hidden}. Das ist die Ziel-Fenstergröße, "
                "nicht ein Sonderfall."
            )
            assert not _overflow_button_visible(win), (
                "Der »-Überlauf-Button ist bei der Ziel-Fenstergröße sichtbar."
            )
            qtbot.wait(50)
        finally:
            app.setStyleSheet(previous)

    def test_icon_only_style_is_what_makes_them_fit(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Gegenprobe per Neutralisierung: ohne den Stil passt es NICHT.

        Ohne sie wäre der Test oben auch dann grün, wenn die Toolbar aus einem
        ganz anderen Grund passt – und niemand merkte, dass die Zusage gar nicht
        mehr an dieser Stelle hängt.
        """
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        previous = app.styleSheet()
        app.setStyleSheet(load_scaled_stylesheet(1.0))
        try:
            monkeypatch.setattr(
                _window_toolbar, "apply_icon_only_style", lambda toolbar, window: None
            )
            win = _build_window(qtbot)
            assert _hidden_action_texts(win), (
                "Ohne ToolButtonIconOnly ist trotzdem alles sichtbar – dann misst "
                "der Test oben nicht mehr die Wirkung dieses Stils."
            )
            qtbot.wait(50)
        finally:
            app.setStyleSheet(previous)


class TestIconOnlyActionsAreUsable:
    """Ein Button ohne Text braucht Symbol UND Tooltip – sonst ist er ein Rätsel."""

    def test_every_icon_only_action_has_icon_and_tooltip(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        offenders = []
        for action in _window_toolbar.icon_only_actions(win):
            if action.icon().isNull():
                offenders.append(f"{action.text()!r}: kein Icon")
            if not action.toolTip():
                offenders.append(f"{action.text()!r}: kein Tooltip")
        assert not offenders, (
            f"Text-lose Toolbar-Buttons ohne Symbol oder Tooltip: {offenders}. "
            "Ein unbeschrifteter Knopf ohne beides ist schlechter als ein "
            "Überlaufmenü."
        )

    def test_labelled_actions_keep_their_text(self, qtbot: QtBot) -> None:
        """Der Stil wird pro Button gesetzt, nicht toolbar-weit.

        `toolbar.setToolButtonStyle(...)` wäre die naheliegende Ein-Zeilen-
        Variante und würde ALLEN Aktionen den Text nehmen – auch „Datei
        importieren…" und den Export-Aktionen, deren Standard-Pixmaps sich kaum
        unterscheiden.
        """
        from PyQt6.QtCore import Qt

        win = _build_window(qtbot)
        icon_only = set(_window_toolbar.icon_only_actions(win))
        toolbar = win._toolbar
        for action in toolbar.actions():
            if action.isSeparator() or not action.text() or action in icon_only:
                continue
            button = toolbar.widgetForAction(action)
            if button is None or not hasattr(button, "toolButtonStyle"):
                continue
            assert button.toolButtonStyle() != Qt.ToolButtonStyle.ToolButtonIconOnly, (
                f"{action.text()!r} hat seinen Text verloren – der Stil wurde "
                "toolbar-weit statt pro Button gesetzt."
            )
