"""Export-Dialog – Spaltenauswahl + Dateiname + ID + Zielordner.

Entspricht der alten VBA-`frmSpaltenAuswahl1`. Liefert ein
`ExportSampleDialogResult` mit allem, was `ExcelExporter.export_sample`
braucht. Atomare Schreib-Logik passiert nicht hier, sondern im
`ExcelExporter` selbst.

Die rechte Spalte (Dateiname/ID/Pfad/Vorschau) teilt sich den Code mit
allen anderen Export-Dialogen via `ExportTargetWidget`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.config import (
    BDO_DARK_GREY,
    EXPORT_SUFFIX_SAMPLING,
    EXPORT_TYPE_SAMPLING,
    local_export_now,
)
from sampling_tool.core.models import Dataset
from sampling_tool.ui.dialogs._export_base import (
    HINT_NO_COLUMNS,
    ExportTargetWidget,
    apply_validation,
)


@dataclass(frozen=True, slots=True)
class ExportSampleDialogResult:
    """Ergebnis des Export-Dialogs."""

    columns: list[str]
    custom_name: str
    custom_id: str
    output_dir: Path
    # Sprint 74 / §2.2: der Zeitpunkt, aus dem die Vorschau gebaut wurde.
    # Der Controller reicht ihn an den Export-Task durch, damit die
    # geschriebene Datei denselben `{date}`-Token trägt. `None` = der Writer
    # liest selbst (Bestands-Aufrufer ohne Dialog).
    now: datetime | None = None


class ExportSampleDialog(QDialog):
    """Dialog zur Auswahl der Export-Spalten + Zieldatei."""

    def __init__(
        self,
        dataset: Dataset,
        default_name: str = "",
        default_id: str = "",
        default_output_dir: Path | None = None,
        parent: QWidget | None = None,
        *,
        now_provider: Callable[[], datetime] = local_export_now,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sample exportieren")
        self.setModal(True)
        self.setMinimumWidth(640)

        self._dataset = dataset
        self._result: ExportSampleDialogResult | None = None
        # Sprint 34 / WP5: unterdrückt die per-Item-itemChanged-Updates
        # während „Alle auswählen/abwählen" (sonst O(N²) pro Klick).
        self._bulk_updating = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        body = QHBoxLayout()
        body.setSpacing(20)

        # ---- linke Spalte: Multi-Select ----
        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(_caption("Zu exportierende Spalten *"))

        self._column_list = QListWidget()
        self._column_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        for column in dataset.columns:
            item = QListWidgetItem(column)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self._column_list.addItem(item)
        left.addWidget(self._column_list, stretch=1)

        button_row = QHBoxLayout()
        self._select_all_btn = QPushButton("Alle auswählen")
        self._select_all_btn.setProperty("secondary", True)
        self._select_none_btn = QPushButton("Alle abwählen")
        self._select_none_btn.setProperty("secondary", True)
        button_row.addWidget(self._select_all_btn)
        button_row.addWidget(self._select_none_btn)
        button_row.addStretch(1)
        left.addLayout(button_row)

        body.addLayout(left, stretch=2)

        # ---- rechte Spalte: gemeinsames ExportTargetWidget ----
        # `type_token`/`file_extension` kommen aus `config.py`: genau dieses
        # Paar muss mit dem Writer (`io/exporter.py`) übereinstimmen, damit
        # die Vorschau dem geschriebenen Dateinamen entspricht (Sprint 74).
        self._target = ExportTargetWidget(
            default_name=default_name or dataset.name,
            default_id=default_id,
            file_extension=EXPORT_SUFFIX_SAMPLING,
            type_token=EXPORT_TYPE_SAMPLING,
            default_output_dir=default_output_dir,
            now_provider=now_provider,
        )
        right = QVBoxLayout()
        right.addWidget(self._target)
        body.addLayout(right, stretch=3)

        outer.addLayout(body)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        outer.addWidget(self._buttons)

        # ---- Signals ----
        self._select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        self._select_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        self._column_list.itemChanged.connect(self._update_state)
        self._target.changed.connect(self._update_state)
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)

        self._update_state()

    # ---- Public API -----------------------------------------------------

    def get_result(self) -> ExportSampleDialogResult | None:
        """Liefert das Result oder `None` bei Abbruch."""
        return self._result

    # ---- intern --------------------------------------------------------

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        # Sprint 34 / WP5: jedes setCheckState emittiert itemChanged →
        # _update_state (O(N)-Scan). Während des Bulk-Setzens unterdrücken
        # und danach genau EINMAL aktualisieren – Endzustand (Auswahl,
        # OK-Button) identisch. Bewusst Guard-Flag statt blockSignals, damit
        # die Item-Repaints der Views nicht unterdrückt werden.
        self._bulk_updating = True
        try:
            for i in range(self._column_list.count()):
                item = self._column_list.item(i)
                if item is not None:
                    item.setCheckState(state)
        finally:
            self._bulk_updating = False
            self._update_state()

    def _selected_columns(self) -> list[str]:
        result: list[str] = []
        for i in range(self._column_list.count()):
            item = self._column_list.item(i)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                result.append(item.text())
        return result

    def _selection_hint(self) -> str:
        """Dialogspezifischer Grund: mindestens eine Spalte muss angehakt sein."""
        return "" if self._selected_columns() else HINT_NO_COLUMNS

    def _update_state(self) -> None:
        # Sprint 34 / WP5: während „Alle auswählen/abwählen" bewusst nichts tun –
        # der Endzustand wird danach genau einmal gesetzt (spart den O(N)-Scan
        # pro Häkchen).
        if self._bulk_updating:
            return
        apply_validation(
            self._buttons.button(QDialogButtonBox.StandardButton.Ok),
            self._target,
            self._selection_hint(),
        )

    def _on_accept(self) -> None:
        output_dir = self._target.get_output_dir()
        if output_dir is None:
            return
        self._result = ExportSampleDialogResult(
            columns=self._selected_columns(),
            custom_name=self._target.get_name(),
            custom_id=self._target.get_id(),
            output_dir=output_dir,
            # Derselbe Zeitpunkt, aus dem die Vorschau gebaut wurde.
            now=self._target.now(),
        )
        self.accept()


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color: {BDO_DARK_GREY}; font-weight: 600;")
    return label
