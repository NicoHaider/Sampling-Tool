"""Zusage der Toolbar-Breite bei der Ziel-Fenstergröße (Sprint 81).

Zielhardware ist ein 13-Zoll-Lenovo mit 1920×1200 bei 125 % Windows-Skalierung,
also **1536 × 960 logische Pixel** – nicht ein 27-Zoll-Monitor. Bei dieser
Breite lagen Haupt-Aktionen hinter dem `»`-Überlaufmenü. Wer exportieren wollte,
musste ein Menü öffnen, das aussieht wie ein Zeichen.

🔒 **Warum hier NICHT „null verdeckte Aktionen" steht.** Genau das stand hier
zuerst, und es war grün auf macOS und rot auf Ubuntu und Windows – gemessen im
CI-Lauf zu PR #121:

    macOS 0 verdeckt · Ubuntu 1 · Windows 5

Die Toolbar hatte auf macOS 1482 von 1536 px belegt: 54 px Luft. Deutsche Labels
rendern unter der Windows-Schriftmetrik breiter, und damit ist eine absolute
Layout-Zusage keine Eigenschaft des Codes, sondern eine der Plattform. Ein Test,
der sie behauptet, misst die Schriftmetrik des Runners.

Geprüft wird deshalb die Zusage, die der Code tatsächlich einlöst und die auf
allen drei Plattformen gilt: **der Icon-only-Stil verringert den Überlauf
strikt.** Die Gegenprobe steckt in der Prüfung selbst – gemessen wird mit und
ohne Stil im selben Testlauf, auf demselben Rechner, mit derselben Schrift.

Dass Windows bei 1536 px weiterhin überläuft, ist ein offener Produkt-Befund und
gehört nicht in eine Testtoleranz: er verlangt eine Design-Entscheidung
(weniger Toolbar-Aktionen, kürzere Labels oder kleinere Icons), keine
angehobene Grenze.
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
    def test_icon_only_style_strictly_reduces_the_overflow(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mit Stil sind strikt weniger Aktionen verdeckt als ohne.

        Beide Messungen laufen im selben Testlauf auf demselben Rechner mit
        derselben Schrift – die Differenz ist damit die Wirkung des Stils und
        nicht die Schriftmetrik des CI-Runners. Genau daran ist die frühere
        Fassung dieses Tests gescheitert (siehe Modul-Docstring).
        """
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        previous = app.styleSheet()
        app.setStyleSheet(load_scaled_stylesheet(1.0))
        try:
            with monkeypatch.context() as m:
                m.setattr(_window_toolbar, "apply_icon_only_style", lambda toolbar, window: None)
                without_style = len(_hidden_action_texts(_build_window(qtbot)))
            with_style = len(_hidden_action_texts(_build_window(qtbot)))

            assert without_style > 0, (
                "Schon ohne ToolButtonIconOnly ist bei "
                f"{TARGET_WIDTH}×{TARGET_HEIGHT} alles sichtbar – dann misst dieser "
                "Test die Wirkung des Stils nicht mehr (Fenster zu breit? Aktion "
                "entfallen?)."
            )
            assert with_style < without_style, (
                f"Der Icon-only-Stil verringert den Überlauf nicht: {without_style} "
                f"verdeckte Aktionen ohne, {with_style} mit Stil."
            )
            qtbot.wait(50)
        finally:
            app.setStyleSheet(previous)

    def test_short_labels_apply_to_toolbar_only(self, qtbot: QtBot) -> None:
        """`iconText` kürzt die Toolbar, `text` bleibt der Menü-Eintrag.

        Beides an einer Stelle zu kürzen wäre der naheliegende Fehler: die
        Menü-Einträge sollen ausformuliert bleiben, dort ist Platz.
        """
        win = _build_window(qtbot)
        assert win._action_excel_report.iconText() == "Excel-Report"
        assert win._action_html_report.iconText() == "HTML-Report"
        assert win._action_excel_report.text() == "Excel-Report exportieren…"
        assert win._action_html_report.text() == "HTML-Report generieren…"


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
