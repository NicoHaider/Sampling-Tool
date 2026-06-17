"""Sheet-/Header-Auswahl-Dialog beim Import (Excel + CSV).

Wird vom `WorkspaceController.handle_import_excel` aufgerufen, wenn die
Datei mehr als ein Sheet hat ODER die Header-Detection unsicher ist
(``confidence != "high"``). Der User wählt das Sheet (nur Excel, bei >1
Blatt) und markiert die Kopfzeile – oder aktiviert **„keine Kopfzeile"**,
dann werden generische Spaltennamen vergeben. Das Ergebnis
(``ImportOptionsResult``) bekommt der Importer via `import_file_configured`.

Sprint 16 – aus dem VBA-Backlog portiert (Excel-Multi-Sheet + Header).
Sprint 29 – additiv erweitert um „keine Kopfzeile" und CSV-Unterstützung.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QCheckBox,
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

from sampling_tool.config import SUPPORTED_CSV_SUFFIXES
from sampling_tool.io.importer import ExcelImporter, SheetInfo, SheetPreview

# Erkannte Header-Zeile bekommt einen dezenten Grau-Hintergrund.
_HEADER_HINT_BG = QColor("#EEEEEE")
# BDO-Rot für die "ambiguous"-Warnung. Bewusst keine Style-Import-
# Abhängigkeit – Konstante reicht.
_AMBIGUOUS_RED = "#D6001C"
# Anzahl Vorschauzeilen – muss zur Importer-Default-`max_rows` passen.
_PREVIEW_MAX_ROWS = 20


@dataclass(frozen=True, slots=True)
class ImportOptionsResult:
    """Ergebnis des `ImportOptionsDialog`.

    ``header_row`` ist 0-basiert, oder ``None`` für **„keine Kopfzeile"**
    (generische Spaltennamen). ``sheet_name`` ist der gewählte Blattname
    bei Excel, oder ``None`` bei CSV (CSV hat keine Tabellenblätter). Passt
    direkt in `ExcelImporter.import_file_configured`.
    """

    sheet_name: str | None
    header_row: int | None


class ImportOptionsDialog(QDialog):
    """Kombinierter Dialog für Sheet-Auswahl + Header-Detection (Excel + CSV)."""

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
        self._is_csv = path.suffix.lower() in SUPPORTED_CSV_SUFFIXES
        # CSV hat keine Tabellenblätter; Excel listet die echten Sheets.
        self._sheets: list[SheetInfo] = [] if self._is_csv else importer.list_sheets(path)
        self._sheet_combo: QComboBox | None = None
        self._current_preview: SheetPreview | None = None
        # Sperrt das Preview-Reload, wenn wir programmatisch den Sheet/Spin setzen.
        self._loading = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        # ---- Sheet-Auswahl (nur Excel) ---------------------------------
        if not self._is_csv:
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
        outer.addWidget(_caption(f"Vorschau (erste {_PREVIEW_MAX_ROWS} Zeilen)"))
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
        self._no_header_check = QCheckBox("Keine Kopfzeile – Spaltennamen automatisch vergeben")
        header_row_layout.addWidget(self._no_header_check)
        header_row_layout.addStretch(1)
        outer.addLayout(header_row_layout)

        # Sprint 31: dezenter Hinweis, dass ein Klick auf eine Zeile sie als
        # Kopfzeile wählt (additiv – ändert die Header-Spin-Logik nicht).
        click_hint = QLabel(
            "Tipp: Zeile in der Vorschau anklicken, um sie als Kopfzeile zu wählen."
        )
        click_hint.setStyleSheet("color: #999999; font-style: italic;")
        outer.addWidget(click_hint)

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
        if self._sheet_combo is not None:
            self._sheet_combo.currentIndexChanged.connect(self._on_sheet_changed)
        self._header_spin.valueChanged.connect(self._on_header_changed)
        self._no_header_check.toggled.connect(self._on_no_header_toggled)
        # Sprint 31: Klick auf eine Zelle ODER den vertikalen Zeilenkopf wählt
        # die Zeile als Kopfzeile. Single Source of Truth bleibt der Spin – der
        # Klick setzt nur ihn, der bestehende Highlight-Pfad erledigt den Rest.
        self._preview_table.cellClicked.connect(self._on_preview_cell_clicked)
        v_header = self._preview_table.verticalHeader()
        if v_header is not None:
            v_header.sectionClicked.connect(self._on_preview_header_clicked)
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)

        # Initiale Vorschau laden. Excel: über das (bereits auf Index 0
        # stehende) Sheet-Dropdown. CSV: einmalig direkt.
        if self._is_csv:
            self._load_preview(self._csv_preview())
        else:
            self._on_sheet_changed(0)

    # ---- Public API ----------------------------------------------------

    def get_result(self) -> ImportOptionsResult | None:
        """Liefert das Ergebnis oder ``None`` bei Cancel."""
        return self._result

    def get_result_header_row(self) -> int:
        """0-basierter Header-Index (nur sinnvoll, wenn eine Kopfzeile gewählt ist)."""
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
        self._load_preview(preview)

    def _csv_preview(self) -> SheetPreview:
        try:
            return self._importer.preview_csv(self._path)
        except Exception:  # pragma: no cover – defensiv
            return SheetPreview(
                sheet_name=self._path.name,
                rows=(),
                detected_header_row=None,
                confidence="ambiguous",
            )

    def _load_preview(self, preview: SheetPreview) -> None:
        """Rendert eine Vorschau + setzt den Header-Spin (gemeinsam Excel/CSV)."""
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

    def _on_preview_cell_clicked(self, row: int, _column: int) -> None:
        self._select_header_row(row)

    def _on_preview_header_clicked(self, logical_index: int) -> None:
        self._select_header_row(logical_index)

    def _select_header_row(self, row: int) -> None:
        """Setzt die geklickte Vorschau-Zeile (0-basiert) als Kopfzeile.

        Wirkt nur, wenn keine „keine Kopfzeile" aktiv ist – dann ist der Spin
        gesperrt und der Klick bleibt bewusst wirkungslos (er deaktiviert die
        Checkbox NICHT). Setzt ausschließlich den Spin (1-basiert); der
        bestehende `_on_header_changed`-/Highlight-Pfad übernimmt den Rest.
        """
        if self._loading or self._no_header_check.isChecked():
            return
        if 0 <= row < self._header_spin.maximum():
            self._header_spin.setValue(row + 1)

    def _on_no_header_toggled(self, checked: bool) -> None:
        # „keine Kopfzeile": Header-Spin sperren, Hervorhebung/Validierung anpassen.
        self._header_spin.setEnabled(not checked)
        self._refresh_visual_state()
        self._update_ok_enabled()

    def _on_accept(self) -> None:
        if not self._is_valid():
            return
        sheet_name: str | None
        if self._is_csv:
            sheet_name = None
        else:
            assert self._sheet_combo is not None
            data = self._sheet_combo.currentData()
            if not isinstance(data, str):
                return
            sheet_name = data
        header_row = None if self._no_header_check.isChecked() else self._header_spin.value() - 1
        self._result = ImportOptionsResult(sheet_name=sheet_name, header_row=header_row)
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
        no_header = self._no_header_check.isChecked()
        # Bei „keine Kopfzeile" wird keine Zeile hervorgehoben.
        header_index = -1 if no_header else self._header_spin.value() - 1
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
        # Hinweis-Text.
        if no_header:
            self._confidence_label.setText(
                "Keine Kopfzeile – alle Zeilen werden als Daten importiert "
                "(Spaltennamen: Spalte 1, Spalte 2, …)."
            )
            self._confidence_label.setStyleSheet("color: #777777;")
            return
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
        # „keine Kopfzeile": gültig, sobald überhaupt Zeilen vorhanden sind.
        if self._no_header_check.isChecked():
            return len(self._current_preview.rows) >= 1

        header_index = self._header_spin.value() - 1
        if self._is_csv:
            # Mindestens eine Datenzeile nach dem Header – es sei denn, die
            # Vorschau war abgeschnitten (dann liegen evtl. weitere Zeilen vor).
            n = len(self._current_preview.rows)
            return header_index < n - 1 or n >= _PREVIEW_MAX_ROWS

        # Excel: echte Zeilenzahl aus den Sheet-Metadaten nutzen.
        assert self._sheet_combo is not None
        sheet_name = self._sheet_combo.currentData()
        if not isinstance(sheet_name, str):
            return False
        info = next((s for s in self._sheets if s.name == sheet_name), None)
        if info is None:
            return False
        # Mindestens eine Datenzeile NACH dem Header.
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
