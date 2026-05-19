"""Sheet-/Header-Auswahl-Dialog beim Excel-Import.

Wird vom `WorkspaceController.handle_import_excel` aufgerufen, wenn die
Datei mehr als ein Sheet hat ODER die Header-Detection unsicher ist
(``confidence != "high"``). Der User wählt das Sheet und markiert die
Header-Zeile; das Ergebnis (``ImportOptionsResult``) bekommt der
Importer via `import_file_configured`.

Sprint 16 – nachträglich aus dem VBA-Backlog portiert.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.io.importer import ExcelImporter, SheetInfo, SheetPreview

# Erkannte Header-Zeile bekommt einen dezenten Grau-Hintergrund.
_HEADER_HINT_BG = QColor("#EEEEEE")
# BDO-Rot für die "ambiguous"-Warnung. Bewusst keine Style-Import-
# Abhängigkeit – Konstante reicht.
_AMBIGUOUS_RED = "#D6001C"


@dataclass(frozen=True, slots=True)
class ImportOptionsResult:
    """Ergebnis des `ImportOptionsDialog`.

    `header_row` ist 0-basiert, passt direkt für
    `ExcelImporter.import_file_configured`.
    """

    sheet_name: str
    header_row: int


class ImportOptionsDialog(QDialog):
    """Kombinierter Dialog für Sheet-Auswahl + Header-Detection."""

    def __init__(
        self,
        path: Path,
        importer: ExcelImporter,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Datei importieren: {path.name}")
        self.setModal(True)
        self.setMinimumSize(720, 520)

        self._path = path
        self._importer = importer
        self._result: ImportOptionsResult | None = None
        self._sheets: list[SheetInfo] = importer.list_sheets(path)
        self._current_preview: SheetPreview | None = None
        # Sperrt das Preview-Reload, wenn wir programmatisch den Sheet/Spin setzen.
        self._loading = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        # ---- Sheet-Auswahl ---------------------------------------------
        sheet_row = QHBoxLayout()
        sheet_row.addWidget(_caption("Sheet auswählen"))
        self._sheet_combo = QComboBox()
        for info in self._sheets:
            self._sheet_combo.addItem(
                f"{info.name}  ({info.row_count} Zeilen × {info.column_count} Spalten)",
                info.name,
            )
        sheet_row.addWidget(self._sheet_combo, stretch=1)
        outer.addLayout(sheet_row)

        # ---- Vorschau-Tabelle ------------------------------------------
        outer.addWidget(_caption("Vorschau (erste 20 Zeilen)"))
        self._preview_table = QTableWidget(0, 0, self)
        self._preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._preview_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        h_header = self._preview_table.horizontalHeader()
        if h_header is not None:
            h_header.setStretchLastSection(True)
        outer.addWidget(self._preview_table, stretch=1)

        # ---- Header-Zeile-Auswahl --------------------------------------
        header_row_layout = QHBoxLayout()
        header_row_layout.addWidget(_caption("Header-Zeile"))
        self._header_spin = QSpinBox()
        self._header_spin.setMinimum(1)
        self._header_spin.setMaximum(1)
        header_row_layout.addWidget(self._header_spin)
        header_row_layout.addStretch(1)
        outer.addLayout(header_row_layout)

        self._confidence_label = QLabel("")
        self._confidence_label.setWordWrap(True)
        outer.addWidget(self._confidence_label)

        # ---- Buttons ---------------------------------------------------
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText("Importieren")
        outer.addWidget(self._buttons)

        # ---- Signals ---------------------------------------------------
        self._sheet_combo.currentIndexChanged.connect(self._on_sheet_changed)
        self._header_spin.valueChanged.connect(self._on_header_changed)
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)

        # Initiales Sheet laden – emittiert kein change-Signal weil Index
        # bereits 0 ist, daher explizit aufrufen.
        self._on_sheet_changed(0)

    # ---- Public API ----------------------------------------------------

    def get_result(self) -> ImportOptionsResult | None:
        """Liefert das Ergebnis oder ``None`` bei Cancel."""
        return self._result

    def get_result_header_row(self) -> int:
        """0-basierter Header-Index, wie er in `import_file_configured` geht."""
        return self._header_spin.value() - 1

    # ---- Slots ---------------------------------------------------------

    def _on_sheet_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._sheets):
            return
        sheet_name = self._sheets[index].name
        try:
            preview = self._importer.preview_sheet(self._path, sheet_name)
        except Exception:  # pragma: no cover – defensiv
            preview = SheetPreview(
                sheet_name=sheet_name,
                rows=(),
                detected_header_row=None,
                confidence="ambiguous",
            )
        self._current_preview = preview
        self._loading = True
        try:
            self._render_preview(preview)
            self._update_header_spin(preview)
        finally:
            self._loading = False
        self._refresh_visual_state()
        self._update_ok_enabled()

    def _on_header_changed(self, _value: int) -> None:
        if self._loading:
            return
        self._refresh_visual_state()
        self._update_ok_enabled()

    def _on_accept(self) -> None:
        if not self._is_valid():
            return
        sheet_name = self._sheet_combo.currentData()
        if not isinstance(sheet_name, str):
            return
        self._result = ImportOptionsResult(
            sheet_name=sheet_name,
            header_row=self._header_spin.value() - 1,
        )
        self.accept()

    # ---- Rendering -----------------------------------------------------

    def _render_preview(self, preview: SheetPreview) -> None:
        """Füllt die `QTableWidget` mit den Roh-Zellen."""
        rows = preview.rows
        col_count = max((len(r) for r in rows), default=0)
        self._preview_table.clear()
        self._preview_table.setRowCount(len(rows))
        self._preview_table.setColumnCount(col_count)
        # Spalten-Header als Excel-artige Buchstaben (A, B, C, …).
        self._preview_table.setHorizontalHeaderLabels([_column_letter(i) for i in range(col_count)])
        # Zeilen-Header sind 1-basierte Zeilennummern – matchen den Spin.
        self._preview_table.setVerticalHeaderLabels([str(i + 1) for i in range(len(rows))])
        for r, row in enumerate(rows):
            for c in range(col_count):
                value = row[c] if c < len(row) else None
                item = QTableWidgetItem("" if value is None else str(value))
                self._preview_table.setItem(r, c, item)
        self._preview_table.resizeColumnsToContents()

    def _update_header_spin(self, preview: SheetPreview) -> None:
        # SpinBox-Range: 1 bis Anzahl Preview-Zeilen (min. 1).
        n_rows = len(preview.rows)
        self._header_spin.setMinimum(1)
        self._header_spin.setMaximum(max(1, n_rows))
        # Default: erkannte Header-Zeile (1-basiert) – ansonsten Zeile 1.
        default_1based = (
            (preview.detected_header_row + 1) if preview.detected_header_row is not None else 1
        )
        self._header_spin.setValue(default_1based)

    def _refresh_visual_state(self) -> None:
        """Header-Zeile in der Preview-Tabelle hervorheben + Confidence-Hinweis."""
        if self._current_preview is None:
            return
        header_index = self._header_spin.value() - 1
        # Reset background + bold auf allen Cells.
        default_brush = QBrush()
        normal_font = QFont()
        for r in range(self._preview_table.rowCount()):
            is_header = r == header_index
            for c in range(self._preview_table.columnCount()):
                item = self._preview_table.item(r, c)
                if item is None:
                    continue
                if is_header:
                    item.setBackground(QBrush(_HEADER_HINT_BG))
                    bold = QFont()
                    bold.setBold(True)
                    item.setFont(bold)
                else:
                    item.setBackground(default_brush)
                    item.setFont(normal_font)
        # Confidence-Text.
        confidence = self._current_preview.confidence
        if confidence == "high":
            self._confidence_label.setText("Header automatisch erkannt.")
            self._confidence_label.setStyleSheet("color: #777777;")
        elif confidence == "low":
            detected = self._current_preview.detected_header_row
            self._confidence_label.setText(
                f"Header in Zeile {detected + 1 if detected is not None else 1} erkannt."
            )
            self._confidence_label.setStyleSheet("color: #777777;")
        else:
            self._confidence_label.setText(
                "Header-Zeile konnte nicht eindeutig erkannt werden. Bitte manuell prüfen."
            )
            self._confidence_label.setStyleSheet(f"color: {_AMBIGUOUS_RED}; font-weight: 600;")

    # ---- Validierung ---------------------------------------------------

    def _is_valid(self) -> bool:
        if self._current_preview is None:
            return False
        sheet_name = self._sheet_combo.currentData()
        if not isinstance(sheet_name, str):
            return False
        info = next((s for s in self._sheets if s.name == sheet_name), None)
        if info is None:
            return False
        # Mindestens eine Datenzeile NACH dem Header.
        header_index = self._header_spin.value() - 1
        return header_index < info.row_count - 1

    def _update_ok_enabled(self) -> None:
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setEnabled(self._is_valid())


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("color: #555555; font-weight: 600;")
    label.setAlignment(Qt.AlignmentFlag.AlignLeft)
    return label


def _column_letter(index: int) -> str:
    """0-basiertes Index → Excel-Spaltenbuchstabe (A, B, …, AA, AB, …)."""
    result = ""
    n = index
    while True:
        result = chr(ord("A") + (n % 26)) + result
        n = n // 26 - 1
        if n < 0:
            break
    return result
