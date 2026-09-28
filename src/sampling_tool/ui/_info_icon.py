"""Eindeutiges Info-Symbol für Erfolgs- und Hinweismeldungen (Sprint 89 / D4).

Die Meldungen „Bericht gespeichert unter …", „AuditTrail-PDF exportiert", die
Tastenkürzel-Liste usw. laufen längst über `QMessageBox.information`. Unter
macOS zeichnet Qt dafür aber eine graue Sprechblase mit Ausrufezeichen – für
Anwender ein Warn-Symbol. Dieser Proxy-Style ersetzt NUR das Information-Symbol
durch ein „i" im Kreis; Warnung, Fehler und Frage bleiben die des Systems.
Unter Windows ist das System-Symbol bereits ein „i" und bleibt unverändert.
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QProxyStyle, QStyle, QStyleOption, QWidget

from sampling_tool.config import BDO_GREY

_ICON_SIZE = 128


def info_icon() -> QIcon:
    """Weißes „i" im Kreis in `BDO_GREY` – die Farbe für Sekundärinformation."""
    pixmap = QPixmap(_ICON_SIZE, _ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(BDO_GREY))
        margin = _ICON_SIZE * 0.06
        painter.drawEllipse(
            QRectF(margin, margin, _ICON_SIZE - 2 * margin, _ICON_SIZE - 2 * margin)
        )
        # Das „i" als Punkt + Balken gezeichnet, nicht als Schrift: keine
        # Abhängigkeit von vorhandenen Fonts, keine Schriftgröße außerhalb von
        # `_fonts.py` (Styling-Vertrag).
        painter.setBrush(QColor(Qt.GlobalColor.white))
        unit = _ICON_SIZE / 16
        painter.drawEllipse(QRectF(7 * unit, 3 * unit, 2 * unit, 2 * unit))
        painter.drawRoundedRect(QRectF(7 * unit, 6.5 * unit, 2 * unit, 7 * unit), unit, unit)
    finally:
        painter.end()
    return QIcon(pixmap)


class InfoIconStyle(QProxyStyle):
    """Wie der Basis-Style, nur mit `info_icon()` für `SP_MessageBoxInformation`."""

    def standardIcon(  # noqa: N802 – Qt-Override
        self,
        standardIcon: QStyle.StandardPixmap,  # noqa: N803 – Qt-Signatur
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
    ) -> QIcon:
        if standardIcon == QStyle.StandardPixmap.SP_MessageBoxInformation:
            return info_icon()
        return super().standardIcon(standardIcon, option, widget)


def install_info_icon(app: QApplication, platform: str = sys.platform) -> bool:
    """Setzt `InfoIconStyle` als App-Style – nur unter macOS. Vor `setStyleSheet` rufen.

    Der Basis-Style wird über seinen Namen neu erzeugt, statt den laufenden zu
    übernehmen: `QApplication.setStyle` löscht den alten Style, den der Proxy
    sonst noch als Basis hielte.
    """
    if platform != "darwin":
        return False
    style = app.style()
    if style is None:
        return False
    app.setStyle(InfoIconStyle(style.name()))
    return True
