"""Welcome-Screen – Startansicht wenn kein Engagement geladen ist.

Zeigt einen BDO-Logo-Platzhalter, Titel/Subtitle, zwei große Buttons
(Neues / Öffnen) sowie eine Liste der zuletzt geöffneten Engagements
als klickbare Karten.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.config import ENGAGEMENTS_DIR
from sampling_tool.ui.recent import RecentEntry


class _RecentCard(QFrame):
    """Klickbare Karte für einen Recent-Engagement-Eintrag."""

    clicked = pyqtSignal(Path)

    def __init__(self, entry: RecentEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entry = entry
        self.setObjectName("WelcomeCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        title = QLabel(entry.client_name)
        title.setStyleSheet("font-weight: 700; font-size: 14px; color: #333333;")
        layout.addWidget(title)

        subtitle = QLabel(entry.audit_type or "—")
        subtitle.setStyleSheet("color: #7F7F7F; font-size: 11px;")
        layout.addWidget(subtitle)

        path_label = QLabel(str(entry.path))
        path_label.setStyleSheet("color: #B0B0B0; font-size: 10px;")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._entry.path)
        super().mousePressEvent(event)


class WelcomeScreen(QWidget):
    """Welcome-Screen mit Recent-Engagements und Aktions-Buttons."""

    new_engagement_requested = pyqtSignal()
    open_engagement_requested = pyqtSignal(Path)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.setSpacing(24)
        outer.addStretch(1)

        # Logo + Titel-Block
        head = QHBoxLayout()
        head.setSpacing(20)

        logo = QLabel("BDO")
        logo.setObjectName("LogoPlaceholder")
        head.addWidget(logo, alignment=Qt.AlignmentFlag.AlignTop)

        head_text = QVBoxLayout()
        title = QLabel("Audit Sampling Tool")
        title.setObjectName("WelcomeTitle")
        subtitle = QLabel(
            "Reproduzierbare Stichproben für Prüfungshandlungen – konform mit ISAE 3402."
        )
        subtitle.setObjectName("WelcomeSubtitle")
        subtitle.setWordWrap(True)
        head_text.addWidget(title)
        head_text.addWidget(subtitle)
        head_text.addStretch(1)
        head.addLayout(head_text, stretch=1)

        outer.addLayout(head)

        # Aktions-Buttons
        actions = QHBoxLayout()
        actions.setSpacing(12)

        self._new_button = QPushButton("Neues Engagement")
        self._new_button.setMinimumHeight(44)
        self._new_button.clicked.connect(self.new_engagement_requested.emit)

        self._open_button = QPushButton("Bestehende öffnen…")
        self._open_button.setMinimumHeight(44)
        self._open_button.setProperty("secondary", True)
        self._open_button.clicked.connect(self._on_open_clicked)

        actions.addWidget(self._new_button)
        actions.addWidget(self._open_button)
        actions.addStretch(1)
        outer.addLayout(actions)

        # Recent-Block
        recent_label = QLabel("Zuletzt geöffnet")
        recent_label.setStyleSheet("color: #7F7F7F; font-weight: 700;")
        outer.addWidget(recent_label)

        self._recent_container = QWidget()
        self._recent_layout = QVBoxLayout(self._recent_container)
        self._recent_layout.setContentsMargins(0, 0, 0, 0)
        self._recent_layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidget(self._recent_container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, stretch=2)

        self._empty_label = QLabel("Noch keine Engagements geöffnet.")
        self._empty_label.setStyleSheet("color: #B0B0B0; font-style: italic;")
        self._recent_layout.addWidget(self._empty_label)
        self._recent_layout.addStretch(1)

        outer.addStretch(1)

    # ---- Public API -----------------------------------------------------

    def set_recent_entries(self, entries: list[RecentEntry]) -> None:
        """Erneuert die Recent-Karten."""
        # Vorhandene Karten entsorgen (Stretch + Empty-Label bleiben dazwischen).
        while self._recent_layout.count() > 0:
            item = self._recent_layout.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        if not entries:
            self._recent_layout.addWidget(self._empty_label)
            self._recent_layout.addStretch(1)
            return

        for entry in entries:
            card = _RecentCard(entry, parent=self._recent_container)
            card.clicked.connect(self.open_engagement_requested.emit)
            self._recent_layout.addWidget(card)
        self._recent_layout.addStretch(1)

    def recent_card_count(self) -> int:
        """Anzahl der aktuell sichtbaren Recent-Karten (Tests)."""
        count = 0
        for i in range(self._recent_layout.count()):
            item = self._recent_layout.itemAt(i)
            if item is not None and isinstance(item.widget(), _RecentCard):
                count += 1
        return count

    # ---- Slots ---------------------------------------------------------

    def _on_open_clicked(self) -> None:
        start_dir = str(ENGAGEMENTS_DIR) if ENGAGEMENTS_DIR.exists() else ""
        path_str, _filter = QFileDialog.getOpenFileName(
            self,
            "Engagement öffnen",
            start_dir,
            "SQLite-Engagement (*.db);;Alle Dateien (*)",
        )
        if path_str:
            self.open_engagement_requested.emit(Path(path_str))
