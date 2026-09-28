"""Handbuch-Fenster: `docs/USER_GUIDE.md` als gerendertes Markdown mit Suche (Sprint 89 / F)."""

from __future__ import annotations

from PyQt6.QtGui import QKeySequence, QShortcut, QTextCursor
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

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setMarkdown(markdown)

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
