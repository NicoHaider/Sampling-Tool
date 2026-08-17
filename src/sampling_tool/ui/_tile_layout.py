"""Reine Umbruch-Rechnung für das Dashboard-Kachelgitter (Sprint 78 / B2).

Bewusst Qt-frei – dasselbe Muster wie `_geometry.py` (Sprint 67) und
`_scaling.py` (Sprint 68): `conftest.py` erzwingt `QT_QPA_PLATFORM=offscreen`
(feste virtuelle Screen-Größe, `devicePixelRatio` immer 1.0), echtes
Screen-Verhalten ist damit nicht testbar. Jeder Wert, der vom Bildschirm oder
von einem Widget kommt, ist hier ein **Parameter** und keine Abfrage im
Rechenweg; die dünne Qt-Anbindung (Viewport-Breite, `minimumSizeHint`) sitzt in
`widgets/dashboard_view.py` und bleibt so klein, dass sie offensichtlich richtig
ist.
"""

from __future__ import annotations

import math


def tile_columns(
    available_width: int,
    tile_min_width: int,
    spacing: int,
    margins: int,
    max_columns: int,
) -> int:
    """Wie viele Kacheln nebeneinander passen – mindestens 1, höchstens `max_columns`.

    `n` Spalten brauchen `margins + n * tile_min_width + (n - 1) * spacing`.
    Nach `n` aufgelöst ergibt das `n <= (nutzbar + spacing) / (tile_min_width + spacing)`.

    Die Untergrenze 1 ist Absicht: ist die Kachel breiter als das Fenster, wird
    **eine** Spalte gezeigt (die dann horizontal scrollt) statt null Spalten –
    ein leeres Dashboard wäre die schlechtere Antwort auf ein schmales Fenster.
    """
    if max_columns < 1:
        return 1
    if tile_min_width <= 0:
        # Ohne sinnvolle Kachelbreite ist die Rechnung bedeutungslos; das
        # bisherige Verhalten (volle Spaltenzahl) ist die konservative Antwort.
        return max_columns

    usable = available_width - margins
    if usable <= 0:
        return 1

    fitting = (usable + spacing) // (tile_min_width + spacing)
    return max(1, min(int(fitting), max_columns))


def tile_rows(tile_count: int, columns: int) -> int:
    """Zeilenzahl für `tile_count` Kacheln in `columns` Spalten (mindestens 1).

    Getrennt von `tile_columns`, weil der Zeilen-Stretch daraus folgt: mit
    dynamischen Spalten ist ein fest verdrahtetes `setRowStretch(2, 1)` falsch,
    sobald nicht mehr 3 Spalten gezeigt werden (§2.7).
    """
    if tile_count <= 0 or columns <= 0:
        return 1
    return max(1, math.ceil(tile_count / columns))
