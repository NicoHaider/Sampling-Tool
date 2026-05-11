"""Gemeinsame Basis-Komponente für alle Export-Dialoge.

`ExportTargetWidget` bündelt die rechte Spalte aller Export-Dialoge:
Dateiname, ID, Zielordner, Vorschau-Label. Damit haben Sample-Export,
AuditTrail-PDF, Excel-Report und HTML-Report ein einheitliches UI.

Der Widget feuert `changed`, sobald irgendetwas sich ändert – Dialoge nutzen
das, um den OK-Button live zu (de-)aktivieren und ggf. weitere Vorschauen
zu aktualisieren.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

DEFAULT_FILENAME_PATTERN: str = "{name}_ID{id}_BDO_{type}_{date}"


class ExportTargetWidget(QWidget):
    """Wiederverwendbare rechte Spalte: Dateiname, ID, Zielordner, Vorschau."""

    changed = pyqtSignal()

    def __init__(
        self,
        default_name: str = "",
        default_id: str = "",
        file_extension: str = "",
        filename_pattern: str = DEFAULT_FILENAME_PATTERN,
        type_token: str = "export",
        default_output_dir: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._file_extension = file_extension
        self._filename_pattern = filename_pattern
        self._type_token = type_token
        self._output_dir: Path | None = default_output_dir

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(_caption("Dateiname *"))
        self._name_field = QLineEdit(default_name)
        layout.addWidget(self._name_field)

        layout.addWidget(_caption("ID *"))
        self._id_field = QLineEdit(default_id)
        layout.addWidget(self._id_field)

        layout.addWidget(_caption("Zielordner *"))
        dir_row = QHBoxLayout()
        self._dir_label = QLabel(
            str(self._output_dir) if self._output_dir is not None else "(noch nicht gewählt)"
        )
        self._dir_label.setStyleSheet("color: #555555;")
        self._dir_label.setWordWrap(True)
        self._dir_button = QPushButton("Ordner wählen…")
        self._dir_button.setProperty("secondary", True)
        dir_row.addWidget(self._dir_label, stretch=1)
        dir_row.addWidget(self._dir_button)
        layout.addLayout(dir_row)

        layout.addSpacing(8)
        layout.addWidget(_caption("Vorschau Dateiname"))
        self._preview_label = QLabel("")
        self._preview_label.setStyleSheet("color: #7F7F7F; font-family: monospace;")
        self._preview_label.setWordWrap(True)
        layout.addWidget(self._preview_label)
        layout.addStretch(1)

        # ---- Signals ----
        self._name_field.textChanged.connect(self._on_field_changed)
        self._id_field.textChanged.connect(self._on_field_changed)
        self._dir_button.clicked.connect(self._choose_dir)

        self.update_preview()

    # ---- Public API ----------------------------------------------------

    def get_name(self) -> str:
        """Liefert den getrimmten Dateinamen."""
        return self._name_field.text().strip()

    def get_id(self) -> str:
        """Liefert die getrimmte ID."""
        return self._id_field.text().strip()

    def get_output_dir(self) -> Path | None:
        """Liefert den gewählten Zielordner (oder `None`)."""
        return self._output_dir

    def get_path(self) -> Path | None:
        """Liefert den vollständigen Ziel-Pfad (Ordner + finaler Dateiname)."""
        if self._output_dir is None:
            return None
        return self._output_dir / self.preview_filename()

    def preview_filename(self) -> str:
        """Aktueller Dateiname laut Pattern + Extension."""
        name = _sanitize(self.get_name() or "export")
        sid = _sanitize(self.get_id() or "0")
        body = self._filename_pattern.format(
            name=name,
            id=sid,
            type=self._type_token,
            date=datetime.now().strftime("%Y%m%d"),
        )
        return f"{body}{self._file_extension}"

    def is_valid(self) -> bool:
        """`True`, wenn Name, ID und Zielordner gesetzt sind."""
        if not self.get_name() or not self.get_id():
            return False
        if self._output_dir is None:
            return False
        return self._output_dir.is_dir()

    def update_preview(self) -> None:
        """Aktualisiert das Vorschau-Label – wird intern nach Änderungen aufgerufen."""
        self._preview_label.setText(self.preview_filename())

    def set_output_dir(self, path: Path) -> None:
        """Setzt den Zielordner programmatisch (z. B. für Tests)."""
        self._output_dir = path
        self._dir_label.setText(str(path))
        self.update_preview()
        self.changed.emit()

    # ---- Slots ---------------------------------------------------------

    def _on_field_changed(self) -> None:
        self.update_preview()
        self.changed.emit()

    def _choose_dir(self) -> None:
        start = str(self._output_dir) if self._output_dir is not None else ""
        chosen = QFileDialog.getExistingDirectory(self, "Zielordner wählen", start)
        if chosen:
            self.set_output_dir(Path(chosen))


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("color: #555555; font-weight: 600;")
    return label


def _sanitize(token: str) -> str:
    """Filesystem-untaugliche Zeichen durch Underscore ersetzen."""
    forbidden = '<>:"/\\|?*\0'
    cleaned = "".join("_" if c in forbidden else c for c in token).strip() or "x"
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned
