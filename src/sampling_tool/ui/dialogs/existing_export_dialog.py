"""Rückfrage, wenn eine Export-Zieldatei schon existiert (Sprint 84 / C).

Vorher überschrieben alle vier Exporte still: Die Default-ID ist das Datum,
also heißt ein zweiter Export am selben Tag gleich wie der erste – und eine
schon abgegebene Fassung konnte unbemerkt verschwinden. Drei Wege:

- **Neuen Namen verwenden** (Default) – erste freie Nummer vor der Endung.
- **Überschreiben (alte Fassung sichern)** – die vorhandene Datei wandert
  zuerst nach `archiv/`; gelingt das nicht, wird nichts überschrieben.
- **Abbrechen**.

Vorbild: `DuplicateEngagementDialog`.
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

from sampling_tool.config import ARCHIVE_DIR_NAME
from sampling_tool.ui._dialog_buttons import mark_secondary
from sampling_tool.ui._scaling import scaled_px


class ExistingExportChoice(IntEnum):
    """Ergebnis des `ExistingExportDialog`."""

    CANCEL = 0
    NEW_NAME = 1
    OVERWRITE = 2


class ExistingExportDialog(QDialog):
    """Wird gezeigt, bevor ein Export eine vorhandene Datei ersetzen würde."""

    def __init__(
        self,
        existing: Path,
        new_name: Path,
        parent: QWidget | None = None,
        *,
        ui_scale_factor: float = 1.0,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Datei existiert bereits")
        self.setModal(True)
        self.setMinimumWidth(scaled_px(480, ui_scale_factor))

        self._choice = ExistingExportChoice.CANCEL

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(14)

        self._message = QLabel(
            f"Im Ordner „{existing.parent}“ gibt es die Datei „{existing.name}“ schon.\n\n"
            f"Neuer Name: „{new_name.name}“\n\n"
            "Beim Überschreiben wird die vorhandene Fassung zuerst in den Unterordner "
            f"„{ARCHIVE_DIR_NAME}“ verschoben."
        )
        self._message.setWordWrap(True)
        outer.addWidget(self._message)

        self._new_name_btn = QPushButton("Neuen Namen verwenden")
        self._new_name_btn.setDefault(True)
        self._new_name_btn.setAutoDefault(True)
        self._new_name_btn.clicked.connect(self._on_new_name)

        self._overwrite_btn = QPushButton("Überschreiben (alte Fassung sichern)")
        mark_secondary(self._overwrite_btn)
        self._overwrite_btn.clicked.connect(self._on_overwrite)

        self._cancel_btn = QPushButton("Abbrechen")
        mark_secondary(self._cancel_btn)
        self._cancel_btn.clicked.connect(self._on_cancel)

        # Reihenfolge wie im Duplikat-Dialog: Rückweg links, Default rechts.
        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch(1)
        button_row.addWidget(self._cancel_btn)
        button_row.addWidget(self._overwrite_btn)
        button_row.addWidget(self._new_name_btn)
        outer.addLayout(button_row)

    def choice(self) -> ExistingExportChoice:
        """Die Wahl des Anwenders – auch nach `reject()` gültig (dann CANCEL)."""
        return self._choice

    def _on_new_name(self) -> None:
        self._choice = ExistingExportChoice.NEW_NAME
        self.accept()

    def _on_overwrite(self) -> None:
        self._choice = ExistingExportChoice.OVERWRITE
        self.accept()

    def _on_cancel(self) -> None:
        self._choice = ExistingExportChoice.CANCEL
        self.reject()
