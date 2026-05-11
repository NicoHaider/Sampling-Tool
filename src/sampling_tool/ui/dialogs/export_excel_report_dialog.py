"""Export-Dialog für den Multi-Sheet-Excel-Report.

Erlaubt dem Auditor, gezielt nur die Sheets zu exportieren, die für den
aktuellen Bericht relevant sind. Default: alle vier Sheets ausgewählt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.core.models import Engagement
from sampling_tool.ui.dialogs._export_base import ExportTargetWidget

AVAILABLE_SHEETS: tuple[str, ...] = ("Übersicht", "AuditTrail", "Samples", "Statistiken")


@dataclass(frozen=True, slots=True)
class ExportExcelReportDialogResult:
    """Ergebnis des Excel-Report-Export-Dialogs."""

    output_path: Path
    sheets: set[str]


class ExportExcelReportDialog(QDialog):
    """Sheet-Selektion + Ziel-Datei-Konfiguration."""

    def __init__(
        self,
        engagement: Engagement,
        parent: QWidget | None = None,
        default_output_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Excel-Report exportieren")
        self.setModal(True)
        self.setMinimumWidth(680)

        self._result: ExportExcelReportDialogResult | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        body = QHBoxLayout()
        body.setSpacing(20)

        # Links: Sheet-Auswahl.
        left = QVBoxLayout()
        left.setSpacing(10)
        gb_sheets = QGroupBox("Sheets")
        sheet_layout = QVBoxLayout(gb_sheets)
        self._sheet_list = QListWidget()
        self._sheet_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        for sheet in AVAILABLE_SHEETS:
            item = QListWidgetItem(sheet)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self._sheet_list.addItem(item)
        sheet_layout.addWidget(self._sheet_list)

        btn_row = QHBoxLayout()
        self._select_all_btn = QPushButton("Alle auswählen")
        self._select_all_btn.setProperty("secondary", True)
        self._only_overview_btn = QPushButton("Nur Übersicht")
        self._only_overview_btn.setProperty("secondary", True)
        btn_row.addWidget(self._select_all_btn)
        btn_row.addWidget(self._only_overview_btn)
        btn_row.addStretch(1)
        sheet_layout.addLayout(btn_row)

        left.addWidget(gb_sheets, stretch=1)
        body.addLayout(left, stretch=2)

        # Rechts: Datei-Ziel.
        self._target = ExportTargetWidget(
            default_name=engagement.client_name,
            default_id=datetime.now().strftime("%Y%m%d"),
            file_extension=".xlsx",
            type_token="report",
            default_output_dir=default_output_dir,
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
        self._sheet_list.itemChanged.connect(lambda _i: self._update_state())
        self._select_all_btn.clicked.connect(lambda: self._set_all_sheets(True))
        self._only_overview_btn.clicked.connect(self._select_only_overview)
        self._target.changed.connect(self._update_state)
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)

        self._update_state()

    # ---- Public API ----------------------------------------------------

    def get_result(self) -> ExportExcelReportDialogResult | None:
        """Liefert das Result oder `None` bei Abbruch."""
        return self._result

    # ---- intern --------------------------------------------------------

    def _set_all_sheets(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self._sheet_list.count()):
            item = self._sheet_list.item(i)
            if item is not None:
                item.setCheckState(state)

    def _select_only_overview(self) -> None:
        for i in range(self._sheet_list.count()):
            item = self._sheet_list.item(i)
            if item is None:
                continue
            checked = item.text() == "Übersicht"
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def _selected_sheets(self) -> set[str]:
        result: set[str] = set()
        for i in range(self._sheet_list.count()):
            item = self._sheet_list.item(i)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                result.add(item.text())
        return result

    def _update_state(self) -> None:
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is None:
            return
        valid = self._target.is_valid() and bool(self._selected_sheets())
        ok_btn.setEnabled(valid)

    def _on_accept(self) -> None:
        path = self._target.get_path()
        if path is None:
            return
        self._result = ExportExcelReportDialogResult(
            output_path=path,
            sheets=self._selected_sheets(),
        )
        self.accept()
