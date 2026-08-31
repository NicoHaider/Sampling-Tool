"""Optionaler Post-Import-Schritt: eine Spalte als ID-Spalte markieren (Sprint 31).

Erscheint nach jedem erfolgreichen Import (sofern der Import Spalten hat) –
unabhängig davon, ob der Header-/Sheet-Dialog erschien. Die Wahl ist eine reine
Anzeige-Hilfe für die Sidebar-Stichprobenliste (ISAE-Zuordnung der gezogenen
Datensätze) und landet in `QSettings` (siehe `ui/dataset_id_store.py`), **nicht**
in der Projekt-DB – kein Schema-Eingriff, der Import-Output bleibt unberührt.
"""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.ui._dialog_buttons import mark_secondary_buttons

_NONE_LABEL = "Keine"


class IdColumnDialog(QDialog):
    """Lässt den User optional eine ID-Spalte für die Sidebar-Übersicht wählen."""

    def __init__(
        self,
        columns: Sequence[str],
        current: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ID-Spalte wählen (optional)")
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        info = QLabel(
            "Welche Spalte enthält die ID/Belegnummer? Sie wird in der "
            "Stichprobenliste je gezogener Stichprobe angezeigt. Optional – "
            "„Keine“ lässt die Liste unverändert."
        )
        info.setWordWrap(True)
        outer.addWidget(info)

        self._combo = QComboBox()
        # „Keine" ist Default (UserData None) – der User wählt aktiv eine Spalte.
        self._combo.addItem(_NONE_LABEL, None)
        for column in columns:
            self._combo.addItem(column, column)
        if current is not None:
            idx = self._combo.findData(current)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
        outer.addWidget(self._combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        mark_secondary_buttons(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def selected_column(self) -> str | None:
        """Gewählte Spalte oder ``None`` für „Keine"."""
        data = self._combo.currentData()
        return data if isinstance(data, str) else None
