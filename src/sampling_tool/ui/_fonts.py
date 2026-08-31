"""Schrift-Ableitung RELATIV zur vorhandenen Widget-/Painter-Schrift (Sprint 80).

Qt speichert eine Schriftgröße **entweder** in Punkt **oder** in Pixel – die
jeweils andere Abfrage liefert dann `-1`. `bdo_light.qss` deklariert alle
Schriftgrößen in Pixel, also ist auf jeder gestylten Widget-Schrift
`pointSize() == -1`.

Damit wird `font.setPointSize(font.pointSize() + 2)` – die naheliegendste Art,
„eine Stufe größer" zu schreiben – zu `setPointSize(1)`: eine 1-Punkt-Schrift.
Der Text verschwindet, ohne Fehlermeldung, bei **jedem** Skalierungsfaktor, auch
beim Default 1,0. Genau das ist zwischen Sprint 1 und 79 unbemerkt geblieben
(Empty-State-Hinweis der Datentabelle, gemessen 21 Tintenpixel statt lesbarem
Text, unverändert bei „klein"/„normal"/„groß").

`relative_font` ist deshalb die **einzige** Stelle im Paket, die eine
Schriftgröße setzen darf – gespiegelt zu `_scaling.py`, das als einzige Stelle
die Pixel-Angaben eines Stylesheets skaliert. Der Styling-Vertrag
(`tests/_styling_policy.py`) hält beides fest.
"""

from __future__ import annotations

from PyQt6.QtGui import QFont


def relative_font(
    base: QFont,
    *,
    scale: float = 1.0,
    bold: bool | None = None,
    italic: bool | None = None,
) -> QFont:
    """Leitet eine Schrift relativ zu `base` ab – einheiten-agnostisch.

    Skaliert die Größe in der Einheit, in der `base` sie tatsächlich trägt, und
    lässt sie unangetastet, wenn `base` gar keine gesetzte Größe hat (dann erbt
    das Ziel weiter aus der QSS-Kaskade – das ist gewollt und kein Fehlerfall).

    `bold`/`italic` bleiben `None`, wenn sie nicht gesetzt werden sollen: ein
    explizites `False` würde die Kaskade überschreiben und z. B. ein
    `font-weight: 600` aus dem Stylesheet unterdrücken.
    """
    font = QFont(base)
    if font.pixelSize() > 0:
        font.setPixelSize(max(1, round(font.pixelSize() * scale)))
    elif font.pointSizeF() > 0:
        font.setPointSizeF(max(1.0, font.pointSizeF() * scale))
    if bold is not None:
        font.setBold(bold)
    if italic is not None:
        font.setItalic(italic)
    return font
