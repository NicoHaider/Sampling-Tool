"""Reine Geometrie-Berechnungen für Fenstergröße/-position (Sprint 67 / Teil A).

Bewusst Qt-Screen-frei: `conftest.py` erzwingt `QT_QPA_PLATFORM=offscreen`
(fixe virtuelle Screen-Größe, `devicePixelRatio` immer 1.0) – echtes
Screen-Verhalten ist damit nicht testbar. Diese Funktionen arbeiten nur mit
Rechtecken/Größen und sind darum mit synthetischen `QRect`/`QSize` voll
unit-testbar; die dünne Qt-Anbindung (echte `QScreen`-Abfrage,
`windowState()`, `QSettings`-I/O) sitzt in `_window_state.py`.
"""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import QRect, QSize

# Rand beim Einpassen (px, pro Seite): das Fenster berührt beim Verkleinern
# nicht direkt die Bildschirmkante. Windows-Taskleiste/macOS-Menüleiste sind
# bereits in `available` (QScreen.availableGeometry()) herausgerechnet –
# dieser Rand ist zusätzliche Luft obendrauf.
DEFAULT_FIT_MARGIN: int = 24

# Ab welchem Flächenanteil eine gespeicherte Geometrie noch als "sichtbar"
# gilt, wenn sie nur TEILWEISE auf einem aktuellen Screen liegt (Monitor
# abgesteckt / Auflösung geändert). Bewusst kein 100%-Match – ein Fenster,
# das noch zu einem guten Teil sichtbar ist, muss nicht verworfen werden.
MIN_VISIBLE_AREA_FRACTION: float = 0.25


def fit_to_available(desired: QSize, available: QRect, margin: int = DEFAULT_FIT_MARGIN) -> QRect:
    """Begrenzt `desired` auf `available` (mit `margin` Luft) und zentriert.

    Passt `desired` unverändert in `available` minus `margin`, wird die
    Größe unverändert übernommen (nur die Position ändert sich – zentriert).
    Ist `desired` größer, wird sie auf `available` minus `margin` auf jeder
    Seite reduziert (nie kleiner als 1px). Ergebnis liegt immer vollständig
    innerhalb von `available`.
    """
    max_width = max(available.width() - 2 * margin, 1)
    max_height = max(available.height() - 2 * margin, 1)
    width = min(desired.width(), max_width)
    height = min(desired.height(), max_height)
    x = available.x() + (available.width() - width) // 2
    y = available.y() + (available.height() - height) // 2
    return QRect(x, y, width, height)


def is_geometry_visible(
    saved: QRect,
    screens: Sequence[QRect],
    min_visible_fraction: float = MIN_VISIBLE_AREA_FRACTION,
) -> bool:
    """`True`, wenn `saved` zu mindestens `min_visible_fraction` auf einem
    der `screens` liegt.

    Deckt Monitor-Wechsel/Auflösungsänderung ab: eine Geometrie komplett
    außerhalb aller Screens ist `False`; eine nur teilweise überlappende
    bleibt `True`, solange der sichtbare Anteil über der Schwelle liegt –
    reines Verwerfen bei jeder Teil-Überlappung wäre zu aggressiv (z. B.
    nach einem kleinen Auflösungs-Downgrade).
    """
    saved_area = saved.width() * saved.height()
    if saved_area <= 0:
        return False
    for screen in screens:
        overlap = saved.intersected(screen)
        if overlap.isEmpty():
            continue
        overlap_area = overlap.width() * overlap.height()
        if overlap_area >= min_visible_fraction * saved_area:
            return True
    return False
