"""Handbuch-Fenster: `docs/USER_GUIDE.md` als gerendertes Markdown mit Suche (Sprint 89 / F)."""

from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QKeySequence, QShortcut, QTextCursor, QTextDocument
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.config import BDO_GREY
from sampling_tool.ui._dialog_buttons import mark_secondary, mark_secondary_buttons
from sampling_tool.ui._dialog_sizing import clamp_dialog_height_to_screen


class UserGuideDialog(QDialog):
    """Nicht-modales Lesefenster für das Handbuch.

    Suche mit Strg/Cmd+F; Enter springt zum nächsten Treffer und beginnt nach
    dem letzten wieder oben.
    """

    def __init__(self, markdown: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Handbuch")
        self.setModal(False)
        self.resize(820, 760)

        # Links selbst behandeln: `QTextBrowser` versuchte relative Links
        # (`INSTALL_USER.md`) als Dokument zu laden und stand danach leer da,
        # und Qts Markdown-Überschriften haben keine Anker für `#…`-Links.
        self._browser = QTextBrowser()
        self._browser.setOpenLinks(False)
        self._browser.anchorClicked.connect(self._on_link)
        self._browser.setMarkdown(markdown)
        self._heading_positions = _heading_positions(self._browser.document())

        self._search = QLineEdit()
        self._search.setPlaceholderText("Im Handbuch suchen…")
        self._search.setClearButtonEnabled(True)
        self._search.returnPressed.connect(self.find_next)
        self._search.textChanged.connect(lambda _text: self._status.clear())
        find_button = QPushButton("Weitersuchen")
        find_button.clicked.connect(self.find_next)
        mark_secondary(find_button)
        self._status = QLabel()
        self._status.setStyleSheet(f"color: {BDO_GREY};")

        self._find_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self)
        self._find_shortcut.activated.connect(self._focus_search)

        search_row = QHBoxLayout()
        search_row.addWidget(self._search, 1)
        search_row.addWidget(find_button)
        search_row.addWidget(self._status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        mark_secondary_buttons(buttons)

        layout = QVBoxLayout(self)
        layout.addLayout(search_row)
        layout.addWidget(self._browser, 1)
        layout.addWidget(buttons)
        clamp_dialog_height_to_screen(self)

    # ---- Suche ------------------------------------------------------------

    def find_next(self) -> bool:
        """Nächster Treffer (ohne Groß-/Kleinschreibung); nach dem letzten wieder von oben."""
        needle = self._search.text()
        if not needle:
            self._status.clear()
            return False
        if self._browser.find(needle):
            self._status.clear()
            return True
        self._browser.moveCursor(QTextCursor.MoveOperation.Start)
        if self._browser.find(needle):
            self._status.setText("Wieder von oben")
            return True
        self._status.setText("Keine Treffer")
        return False

    def _on_link(self, url: QUrl) -> None:
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
            return
        if not url.path() and url.fragment():
            position = self._heading_positions.get(url.fragment().casefold())
            if position is not None:
                cursor = self._browser.textCursor()
                cursor.setPosition(position)
                self._browser.setTextCursor(cursor)
                # Überschrift nach oben: erst ans Ende, dann zurück zur Stelle.
                self._browser.moveCursor(QTextCursor.MoveOperation.End)
                self._browser.setTextCursor(cursor)
                return
        self._status.setText("Dieses Dokument ist nicht in der App enthalten.")

    def _focus_search(self) -> None:
        self._search.setFocus()
        self._search.selectAll()

    # ---- Zugriff (Tests) -------------------------------------------------

    def browser(self) -> QTextBrowser:
        return self._browser

    def search_field(self) -> QLineEdit:
        return self._search

    def status_text(self) -> str:
        return self._status.text()

    def find_shortcut(self) -> QShortcut:
        return self._find_shortcut


def _heading_positions(document: QTextDocument | None) -> dict[str, int]:
    """Anker-Name (wie GitHub ihn aus der Überschrift bildet) → Textposition."""
    positions: dict[str, int] = {}
    if document is None:
        return positions
    block = document.begin()
    while block.isValid():
        if block.blockFormat().headingLevel() > 0:
            positions.setdefault(_github_anchor(block.text()), block.position())
        block = block.next()
    return positions


def _github_anchor(heading: str) -> str:
    """„6. Ergebnisse prüfen, auswählen" → „6-ergebnisse-prüfen-auswählen"."""
    kept = "".join(ch for ch in heading.casefold() if ch.isalnum() or ch in " -_")
    return kept.replace(" ", "-")
