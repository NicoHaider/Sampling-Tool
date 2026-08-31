"""Zusagen der unteren Tab-Leiste (Sprint 81).

`QTabWidget#LowerTabs` hatte bis Sprint 80 keine einzige QSS-Regel und wurde
deshalb nativ gezeichnet – auf Windows anders als auf macOS und in beiden Fällen
anders als der Rest des Fensters. Es war das einzige Element im Hauptfenster,
dessen Aussehen nicht im Repository stand.

Die Prüfungen hier messen das GERENDERTE Bild, nicht den QSS-Text. Der Grund ist
dieselbe Klasse Falle wie beim weißen Toolbar-Separator (Sprint 71/2): ein
Selektor kann syntaktisch korrekt in der Datei stehen und trotzdem nichts
treffen – `QTabWidget#LowerTabs QTabBar` greift nur, solange der `objectName`
in `_window_layout.py` gesetzt bleibt. Ein Textvergleich wäre auch dann grün,
wenn der Name wegfällt und Qt wieder nativ zeichnet.
"""

from __future__ import annotations

import re

import pytest
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication, QTabBar
from pytestqt.qtbot import QtBot

from sampling_tool.config import BDO_RED, SURFACE_CHROME
from sampling_tool.ui._scaling import load_scaled_stylesheet
from sampling_tool.ui.main_window import MainWindow
from tests._styling_policy import strip_comments, stylesheet_text

pytestmark = pytest.mark.ui

_SELECTOR = "QTabWidget#LowerTabs"


def _rgb(image: QImage, x: int, y: int) -> tuple[int, int, int]:
    colour = image.pixelColor(x, y)
    return (colour.red(), colour.green(), colour.blue())


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    raw = value.lstrip("#")
    return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))


class TestLowerTabsStylesheetRules:
    """Der Vertrag über dem QSS-Text – flach, ohne font-size."""

    def test_selector_has_rules(self) -> None:
        qss = strip_comments(stylesheet_text())
        assert qss.count(_SELECTOR) >= 5, (
            "Erwartet Regeln für das Widget, pane, QTabBar, ::tab und ::tab:selected – "
            "sonst zeichnet Qt die Leiste wieder plattformabhängig nativ."
        )

    def test_rules_contain_no_font_size(self) -> None:
        """🔒 Styling-Vertrag: `font-weight` ist erlaubt, `font-size` nicht."""
        qss = strip_comments(stylesheet_text())
        blocks = re.findall(rf"{re.escape(_SELECTOR)}[^{{]*\{{([^}}]*)\}}", qss)
        assert blocks, "keine LowerTabs-Blöcke gefunden"
        offenders = [b.strip() for b in blocks if "font-size" in b]
        assert not offenders, (
            f"font-size in den LowerTabs-Regeln: {offenders} – `_scaling.py` "
            "skaliert die QSS per Regex, jede neue font-size muss ganzzahlig "
            "in px stehen. Hier ist gar keine nötig."
        )

    def test_selected_tab_declares_the_brand_underline(self) -> None:
        qss = strip_comments(stylesheet_text())
        block = re.search(rf"{re.escape(_SELECTOR)} QTabBar::tab:selected\s*\{{([^}}]*)\}}", qss)
        assert block is not None
        assert re.search(rf"border-bottom:\s*2px solid {BDO_RED}", block.group(1), re.IGNORECASE)


class TestLowerTabsRendering:
    """Gemessen am echten Fenster: die Regel greift auch wirklich."""

    def test_tab_bar_paints_the_chrome_surface(self, qtbot: QtBot) -> None:
        """Die Leiste trägt dieselbe Fläche wie Menü-, Toolbar- und Statusleiste.

        Nativ gezeichnet lieferte Qt hier plattformeigene Grautöne, die in der
        Palette nicht vorkommen. Gemessen werden drei Punkte: die Reiterleiste
        selbst, der Streifen rechts daneben (der zum QTabWidget gehört, nicht
        zur QTabBar) und – als Gegenprobe – die Inhaltsfläche darunter, die
        weiß bleiben muss.
        """
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        previous = app.styleSheet()
        app.setStyleSheet(load_scaled_stylesheet(1.0))
        try:
            win = MainWindow()
            qtbot.addWidget(win)
            # Ohne show_workspace() steht der QStackedWidget auf dem
            # Welcome-Screen und die Tab-Leiste existiert zwar, ist aber nie
            # sichtbar – die Messung würde still übersprungen statt zu prüfen.
            win.show_workspace()
            win.show()
            qtbot.waitExposed(win)
            win.resize(1200, 800)
            qtbot.wait(50)

            tab_bar = win._lower_tabs.findChild(QTabBar)
            assert tab_bar is not None, "keine QTabBar unter LowerTabs gefunden"
            if not tab_bar.isVisible() or tab_bar.count() == 0:
                pytest.skip("Untere Tab-Leiste in dieser Konfiguration nicht sichtbar.")

            chrome = _hex_to_rgb(SURFACE_CHROME)
            image = win._lower_tabs.grab().toImage()
            bar = tab_bar.geometry()
            y = bar.center().y()

            # 1) Die Reiterleiste selbst.
            assert _rgb(image, bar.left() + 2, bar.top() + 2) == chrome, (
                "Die QTabBar rendert nicht die Chrome-Fläche – die Regel greift "
                "nicht (objectName 'LowerTabs' verloren?)."
            )

            # 2) Der Streifen RECHTS neben den Reitern. Die QTabBar ist nur so
            #    breit wie ihre Reiter (gemessen 194 px); daneben liegt das
            #    QTabWidget selbst und fiel ohne eigene Regel auf die generische
            #    QWidget-Regel zurück – also auf Weiß mitten im Fenster.
            offsets = [dx for dx in (20, 200, 500) if bar.right() + dx < image.width()]
            assert offsets, "Fenster zu schmal – kein Streifen neben der Leiste messbar."
            offenders = [
                (dx, _rgb(image, bar.right() + dx, y))
                for dx in offsets
                if _rgb(image, bar.right() + dx, y) != chrome
            ]
            assert not offenders, (
                f"Der Streifen neben den Reitern rendert {offenders} statt "
                f"{chrome} – die Leiste bricht mitten im Fenster ab."
            )

            # 3) Gegenprobe: die Inhaltsfläche darunter bleibt weiß. Ohne sie
            #    wäre der Test auch dann grün, wenn das ganze Panel grau würde.
            content_y = bar.bottom() + 40
            if content_y < image.height():
                assert _rgb(image, image.width() // 2, content_y) == (255, 255, 255), (
                    "Die Inhaltsfläche unter den Reitern ist nicht mehr weiß – "
                    "die ::pane-Regel deckt den Widget-Hintergrund nicht mehr ab."
                )
            qtbot.wait(50)
        finally:
            app.setStyleSheet(previous)

    def test_selected_tab_shows_the_brand_underline(self, qtbot: QtBot) -> None:
        """Die 2-px-Akzentlinie ist die einzige Aktiv-Markierung – sie muss da sein."""
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        previous = app.styleSheet()
        app.setStyleSheet(load_scaled_stylesheet(1.0))
        try:
            win = MainWindow()
            qtbot.addWidget(win)
            # Ohne show_workspace() steht der QStackedWidget auf dem
            # Welcome-Screen und die Tab-Leiste existiert zwar, ist aber nie
            # sichtbar – die Messung würde still übersprungen statt zu prüfen.
            win.show_workspace()
            win.show()
            qtbot.waitExposed(win)
            win.resize(1200, 800)
            qtbot.wait(50)

            tab_bar = win._lower_tabs.findChild(QTabBar)
            assert tab_bar is not None
            if not tab_bar.isVisible() or tab_bar.count() == 0:
                pytest.skip("Untere Tab-Leiste in dieser Konfiguration nicht sichtbar.")

            image = tab_bar.grab().toImage()
            rect = tab_bar.tabRect(tab_bar.currentIndex())
            accent = _hex_to_rgb(BDO_RED)
            # Die unteren Zeilen des aktiven Reiters absuchen – die exakte
            # Position der 2-px-Linie hängt an Rahmen-/Margin-Details des Stils,
            # deshalb ein schmales Band statt einer gepinnten Zeile.
            found = any(
                _rgb(image, x, y) == accent
                for y in range(max(rect.bottom() - 3, 0), min(rect.bottom() + 1, image.height()))
                for x in range(rect.left(), min(rect.right() + 1, image.width()))
            )
            assert found, (
                "Kein einziges Marken-Rot unter dem aktiven Reiter – die "
                "Unterstreichung rendert nicht, der aktive Tab ist dann nur "
                "noch an der Schriftfarbe erkennbar."
            )
            qtbot.wait(50)
        finally:
            app.setStyleSheet(previous)
