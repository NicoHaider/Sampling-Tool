"""Dünne Qt-Anbindung: Dialoggröße auf den verfügbaren Screen begrenzen (Sprint 67 / Teil A, Sprint 69 / Bug 3)."""

from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QStyle, QWidget

from sampling_tool.ui._geometry import DEFAULT_FIT_MARGIN

# Sprint 69 / Bug 3: Für die Breite wird bewusst KEIN Rand reserviert (anders
# als beim Höhen-Pendant oben). Der Höhen-Rand ist eine reine Kosmetik-Zugabe
# (siehe `clamp_dialog_height_to_screen`-Docstring: "zusätzliche Luft OBENDRAUF"
# auf das von `availableGeometry()` bereits ausgeschlossene Taskleiste/Menüleiste-
# Are). Bei der Breite geht es dagegen genau darum, den ohnehin knappen
# Inhalts-Bedarf (breiteste Tab-Seite + Scrollbar-Chrome) möglichst ohne
# unnötigen horizontalen Scrollbalken unterzubringen – ein zusätzlicher
# kosmetischer Rand würde den in Bug 3 behobenen Effekt (Scrollbalken im
# Normalfall) auf kleineren Screens wieder herbeiführen, ohne einen echten
# Vorteil zu bieten (ein modaler Dialog, der links/rechts an den Bildschirmrand
# reicht, fällt visuell kaum auf).
WIDTH_CLAMP_MARGIN: int = 0


def clamp_dialog_height_to_screen(dialog: QDialog, margin: int = DEFAULT_FIT_MARGIN) -> None:
    """Begrenzt die max. Höhe von `dialog` auf den verfügbaren Screen-Bereich.

    Ohne das könnte ein hoher Dialog (z. B. `SamplingDialog` mit allen
    Advanced-Feldern) auf einem 720px-hohen Bildschirm über den sichtbaren
    Bereich hinausragen, bevor der `QScrollArea`-Fallback im Inhalt greifen
    kann (der greift erst, wenn der Dialog selbst eine endliche Höhe hat).
    """
    screen = dialog.screen()
    if screen is None:
        return
    available_height = screen.availableGeometry().height()
    dialog.setMaximumHeight(max(available_height - 2 * margin, 1))


def clamp_dialog_width_to_screen(
    dialog: QDialog, desired_min_width: int, margin: int = WIDTH_CLAMP_MARGIN
) -> None:
    """Setzt `desired_min_width` als Mindestbreite von `dialog`, gedeckelt auf
    den verfügbaren Screen (Sprint 69 / Bug 3).

    `desired_min_width` kommt vom Aufrufer aus dem tatsächlichen Inhalt (z. B.
    der breitesten Tab-Seite plus Scrollbar-/Rahmen-Chrome) – anders als bei
    `clamp_dialog_height_to_screen` gibt es hier keine natürlich durchgereichte
    Breite, weil die `QScrollArea` aus Sprint 67 die `minimumSizeHint`-
    Propagation genau für die Breite bricht (siehe Docstring der
    `QScrollArea`-Einbindung in `SettingsDialog`).

    Mindest- UND Maximalbreite werden HIER in einem Aufruf gesetzt (statt
    Mindestbreite beim Aufrufer + separates `setMaximumWidth` danach), damit
    nie ein Widerspruch entsteht: Wäre `desired_min_width` größer als die
    Maximalbreite, würde Qt laut `qBound`-Verhalten die (zu große)
    Minimalbreite gewinnen und der Dialog trotz Deckelung breiter als der
    Bildschirm werden. Auf einem sehr schmalen Screen bleibt in diesem Fall
    der bereits vorhandene `QScrollArea`-Fallback (horizontale Scrollleiste)
    aktiv – ein akzeptierter Edge-Case (Sprint-Vorgabe: kein Scrollbalken nur
    im *Normalfall*).
    """
    screen = dialog.screen()
    if screen is None:
        dialog.setMinimumWidth(desired_min_width)
        return
    available_width = screen.availableGeometry().width()
    max_width = max(available_width - 2 * margin, 1)
    dialog.setMinimumWidth(min(desired_min_width, max_width))
    dialog.setMaximumWidth(max_width)


def content_min_width(
    content: QWidget, style: QStyle | None, outer_margin: int, safety_buffer: int = 0
) -> int:
    """Mindestbreite für den `content`-Widget einer `QScrollArea` (Sprint 69 / Bug 3).

    Für einen einzelnen (nicht getabbten) `QScrollArea`-Inhalt reicht
    `content.sizeHint()` als Basis – der von Sprint 67 verursachte
    Propagations-Bruch sitzt zwischen `QScrollArea` und ihrem Parent, NICHT
    innerhalb des Inhalts selbst; `content.sizeHint()` bleibt also korrekt,
    auch für Widgets, die aktuell per `setEnabled(False)` (nicht
    `setVisible(False)`) deaktiviert sind – sie tragen weiterhin zur Breite
    bei (z. B. `SamplingDialog`s Cluster-/Schicht-Feld, je nach gewählter
    Methode). Ein `QTabWidget`-Inhalt (mehrere, teils inaktive Seiten) braucht
    dagegen die spezialisierte Logik in `SettingsDialog._content_min_width`.

    Dazu kommen die äußeren Dialog-Ränder auf beiden Seiten sowie die Breite
    eines vertikalen Scrollbalkens (der regelmäßig sichtbar ist, weil die
    Dialoghöhe bewusst NICHT auf die volle Inhaltshöhe wächst, siehe
    `clamp_dialog_height_to_screen`).
    """
    scrollbar_extent = (
        style.pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent) if style is not None else 0
    )
    return content.sizeHint().width() + 2 * outer_margin + scrollbar_extent + safety_buffer
