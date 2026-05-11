"""Export-Dialog – Spaltenauswahl + Dateiname + ID + Zielordner.

Entspricht der alten VBA-`frmSpaltenAuswahl1`. Liefert ein
`ExportSampleDialogResult` mit allem, was `ExcelExporter.export_sample`
braucht. Atomare Schreib-Logik passiert nicht hier, sondern im
`ExcelExporter` selbst.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.core.models import Dataset

_FILENAME_PREVIEW: str = "{name}_ID{id}_BDO_sampling_{date}.xlsx"


@dataclass(frozen=True, slots=True)
class ExportSampleDialogResult:
    """Ergebnis des Export-Dialogs."""

    columns: list[str]
    custom_name: str
    custom_id: str
    output_dir: Path


class ExportSampleDialog(QDialog):
    """Dialog zur Auswahl der Export-Spalten + Zieldatei."""

    def __init__(
        self,
        dataset: Dataset,
        default_name: str = "",
        default_id: str = "",
        default_output_dir: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sample exportieren")
        self.setModal(True)
        self.setMinimumWidth(640)

        self._dataset = dataset
        self._result: ExportSampleDialogResult | None = None
        self._output_dir: Path | None = default_output_dir

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

        # ---- rechte Spalte: Felder ----
        right = QVBoxLayout()
        right.setSpacing(8)

        right.addWidget(_caption("Dateiname *"))
        self._name_field = QLineEdit(default_name or dataset.name)
        right.addWidget(self._name_field)

        right.addWidget(_caption("Sample-ID *"))
        self._id_field = QLineEdit(default_id)
        right.addWidget(self._id_field)

        right.addWidget(_caption("Zielordner *"))
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
        right.addLayout(dir_row)

        right.addSpacing(8)
        right.addWidget(_caption("Vorschau Dateiname"))
        self._preview_label = QLabel("")
        self._preview_label.setStyleSheet("color: #7F7F7F; font-family: monospace;")
        self._preview_label.setWordWrap(True)
        right.addWidget(self._preview_label)
        right.addStretch(1)

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
        self._name_field.textChanged.connect(self._update_state)
        self._id_field.textChanged.connect(self._update_state)
        self._dir_button.clicked.connect(self._choose_dir)
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
        for i in range(self._column_list.count()):
            item = self._column_list.item(i)
            if item is not None:
                item.setCheckState(state)

    def _selected_columns(self) -> list[str]:
        result: list[str] = []
        for i in range(self._column_list.count()):
            item = self._column_list.item(i)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                result.append(item.text())
        return result

    def _choose_dir(self) -> None:
        start = str(self._output_dir) if self._output_dir is not None else ""
        chosen = QFileDialog.getExistingDirectory(self, "Zielordner wählen", start)
        if chosen:
            self._output_dir = Path(chosen)
            self._dir_label.setText(chosen)
            self._update_state()

    def _build_preview(self) -> str:
        name = _sanitize(self._name_field.text() or "sample")
        sid = _sanitize(self._id_field.text() or "0")
        return _FILENAME_PREVIEW.format(name=name, id=sid, date=datetime.now().strftime("%Y%m%d"))

    def _update_state(self) -> None:
        self._preview_label.setText(self._build_preview())
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        valid = (
            bool(self._selected_columns())
            and bool(self._name_field.text().strip())
            and bool(self._id_field.text().strip())
            and self._output_dir is not None
        )
        if ok_btn is not None:
            ok_btn.setEnabled(valid)

    def _on_accept(self) -> None:
        if self._output_dir is None:
            return
        self._result = ExportSampleDialogResult(
            columns=self._selected_columns(),
            custom_name=self._name_field.text().strip(),
            custom_id=self._id_field.text().strip(),
            output_dir=self._output_dir,
        )
        self.accept()


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("color: #555555; font-weight: 600;")
    return label


def _sanitize(token: str) -> str:
    forbidden = '<>:"/\\|?*\0'
    cleaned = "".join("_" if c in forbidden else c for c in token).strip() or "x"
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned
