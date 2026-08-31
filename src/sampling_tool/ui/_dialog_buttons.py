"""Button-Hierarchie in Dialogen: genau ein roter Button je Dialog (Sprint 81).

`QPushButton` ist in `bdo_light.qss` global rot – das Marken-Rot ist die
Default-Anmutung jedes Buttons. Damit sieht „Abbrechen" genauso dringlich aus
wie „OK", und im Einstellungen-Dialog war die destruktivste Aktion
(„Auf Default zurücksetzen") die auffälligste auf dem Bildschirm.

Die Gegenregel existiert seit Sprint 4 als `QPushButton[secondary="true"]`. Sie
wurde nur nicht überall gesetzt, und zwar aus einem strukturellen Grund:
`QDialogButtonBox` erzeugt ihre Standard-Buttons SELBST. Es gibt keine Stelle im
Dialog-Code, an der ein „Abbrechen"-Button konstruiert wird und an der man die
Property nebenbei mitsetzen könnte. Deshalb dieser Helfer – ein Ort statt elf.

**Regel:** rot ist der Button, der die Aktion AUSFÜHRT. Alles andere ist ein
Rückweg oder eine Nebenhandlung (Abbrechen, Zurücksetzen, Schließen,
Durchsuchen, Ordner wählen, Alle auswählen) und bleibt erreichbar, aber leise.

Warum `unpolish`/`polish` und nicht nur `setProperty`: Qt wertet Property-
Selektoren beim Polieren aus. Wer die Property auf einem Widget setzt, das schon
poliert ist – und die Buttons einer `QDialogButtonBox` sind das, sobald sie
existiert –, ändert am Aussehen nichts. Genau das ist der Grund, warum diese
Regel elf Dialoge lang wirkungslos gewesen wäre, wenn man sie nur gesetzt hätte.
"""

from __future__ import annotations

from typing import Final

from PyQt6.QtWidgets import QAbstractButton, QDialogButtonBox

#: Rollen, die per Definition kein primäres Ziel für das Auge sind.
#:
#: `RejectRole` deckt Abbrechen UND Schließen ab, `ResetRole` das Zurücksetzen,
#: `HelpRole` die Hilfe. `AcceptRole`/`ApplyRole` sind bewusst NICHT dabei: das
#: ist der eine Button, der etwas tut. `DestructiveRole` ebenfalls nicht – eine
#: löschende Aktion, die der Anwender bewusst wählt, ist ein Ziel und kein
#: Rückweg; sie kommt im Projekt derzeit nicht vor.
_SECONDARY_ROLES: Final[tuple[QDialogButtonBox.ButtonRole, ...]] = (
    QDialogButtonBox.ButtonRole.RejectRole,
    QDialogButtonBox.ButtonRole.ResetRole,
    QDialogButtonBox.ButtonRole.HelpRole,
)


def mark_secondary(button: QAbstractButton | None) -> None:
    """Setzt `secondary=True` auf EINEN Button und poliert ihn neu.

    Nimmt `None` entgegen, weil die Qt-Accessoren (`box.button(...)`,
    `wizard.button(...)`) optional sind – der Aufrufer soll für eine
    Selbstverständlichkeit keine Guard-Zeile schreiben müssen.
    """
    if button is None:
        return
    button.setProperty("secondary", True)
    style = button.style()
    if style is not None:
        style.unpolish(button)
        style.polish(button)


def mark_secondary_buttons(box: QDialogButtonBox) -> None:
    """Setzt `secondary=True` auf alle Rückweg-Buttons einer `QDialogButtonBox`.

    Nach dem Hinzufügen eigener Buttons aufrufen (`box.addButton(...)`), sonst
    sieht der Helfer sie nicht. Ein Dialog ohne Rückweg-Button (nur „OK") ist
    kein Sonderfall, sondern schlicht ein No-Op.
    """
    for button in box.buttons():
        if box.buttonRole(button) in _SECONDARY_ROLES:
            mark_secondary(button)


def set_accept_text(box: QDialogButtonBox, text: str) -> None:
    """Beschriftet den Accept-Button mit einem Verb statt mit „OK".

    „OK" beschreibt keine Handlung – „Importieren" und „Exportieren" schon. Der
    Import-Dialog macht das seit Sprint 16 von Hand; hier steht dasselbe
    Muster einmal, statt in jedem Export-Dialog neu.
    """
    button = box.button(QDialogButtonBox.StandardButton.Ok)
    if button is not None:
        button.setText(text)
