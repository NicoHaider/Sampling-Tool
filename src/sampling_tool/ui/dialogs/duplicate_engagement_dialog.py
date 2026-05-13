"""Dialog, wenn beim Anlegen ein Engagement im Zielordner schon existiert.

Bietet drei Optionen statt eines stumpfen Überschreiben-Ja/Nein:
- **Bestehendes öffnen** – delegiert zurück an `handle_open_engagement`
  (inkl. Snapshot + State-Restore). Verhindert versehentliches
  Überschreiben mit leerer DB.
- **Anderen Namen wählen** – schickt den User zurück in den
  `NewEngagementDialog` mit den bisherigen Eingaben vorbefüllt.
- **Abbrechen** – Workflow ohne Engagement-Wechsel beenden.
"""

from __future__ import annotations

from enum import IntEnum
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class DuplicateEngagementChoice(IntEnum):
    """Ergebnis des `DuplicateEngagementDialog`."""

    CANCEL = 0
    OPEN_EXISTING = 1
    RENAME = 2


class DuplicateEngagementDialog(QDialog):
    """Wird gezeigt, wenn der Ziel-DB-Pfad bereits existiert."""

    def __init__(self, db_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Engagement existiert bereits")
        self.setModal(True)
        self.setMinimumWidth(480)

        self._choice: DuplicateEngagementChoice = DuplicateEngagementChoice.CANCEL

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(14)

        parent_dir = db_path.parent
        filename = db_path.name
        message = QLabel(
            f"Im Ordner '{parent_dir}' existiert bereits ein Engagement "
            f"'{filename}'.\n\n"
            "Möchtest du das bestehende Engagement öffnen oder einen "
            "anderen Namen wählen?"
        )
        message.setWordWrap(True)
        outer.addWidget(message)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        self._open_btn = QPushButton("Bestehendes öffnen")
        self._open_btn.setDefault(True)
        self._open_btn.setAutoDefault(True)
        self._open_btn.clicked.connect(self._on_open_existing)

        self._rename_btn = QPushButton("Anderen Namen wählen")
        self._rename_btn.clicked.connect(self._on_rename)

        self._cancel_btn = QPushButton("Abbrechen")
        self._cancel_btn.clicked.connect(self._on_cancel)

        button_row.addStretch(1)
        button_row.addWidget(self._cancel_btn)
        button_row.addWidget(self._rename_btn)
        button_row.addWidget(self._open_btn)
        outer.addLayout(button_row)

    # ---- Public API -----------------------------------------------------

    def choice(self) -> DuplicateEngagementChoice:
        """Liefert den vom User gewählten Pfad – auch nach `reject()` gültig."""
        return self._choice

    # ---- Slots ---------------------------------------------------------

    def _on_open_existing(self) -> None:
        self._choice = DuplicateEngagementChoice.OPEN_EXISTING
        self.accept()

    def _on_rename(self) -> None:
        self._choice = DuplicateEngagementChoice.RENAME
        self.accept()

    def _on_cancel(self) -> None:
        self._choice = DuplicateEngagementChoice.CANCEL
        self.reject()
