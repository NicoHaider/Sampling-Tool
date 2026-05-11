"""Modal-Fortschrittsdialog für langlaufende Aufgaben (Import, Export).

Wickelt `QProgressDialog` so, dass die Callback-Signatur `(current, total)`
aus `ExcelImporter`/`ExcelExporter` ohne Adapter direkt angeschlossen werden
kann.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QProgressDialog, QWidget

ProgressCallback = Callable[[int, int], None]


class TaskProgressDialog(QProgressDialog):
    """Dünner Wrapper um `QProgressDialog` mit Callback-Adapter."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(label, "Abbrechen", 0, 0, parent)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumDuration(300)
        self.setAutoClose(True)
        self.setAutoReset(True)
        self.setValue(0)

    def progress_callback(self) -> ProgressCallback:
        """Liefert einen Callback im `ExcelImporter`-Signatur-Format."""

        def _cb(current: int, total: int) -> None:
            if total != self.maximum():
                self.setMaximum(total)
            self.setValue(current)

        return _cb
