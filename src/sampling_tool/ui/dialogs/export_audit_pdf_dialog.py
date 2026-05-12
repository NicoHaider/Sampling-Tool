"""Export-Dialog für den AuditTrail-PDF-Report.

Konfiguriert Inhalts-Filter (Zeitraum, Aktionstypen), Optionen
(Briefpapier-Layer, Statistik-Seite) und das Ziel-File. Das Ergebnis
wandert als `ExportAuditPdfDialogResult` an den `MainController`, der
daraus die `AuditTrailPDF.render(...)`-Argumente baut.

Die rechte Spalte (Dateiname/ID/Pfad/Vorschau) teilt sich den Code mit
allen anderen Export-Dialogen via `ExportTargetWidget`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDateEdit,
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

_DEFAULT_TYPES: tuple[str, ...] = (
    "sampling",
    "reset",
    "import",
    "export",
    "undo",
    "redo",
    "correction",
)


@dataclass(frozen=True, slots=True)
class ExportAuditPdfDialogResult:
    """Ergebnis des AuditTrail-PDF-Export-Dialogs."""

    output_path: Path
    date_from: date | None
    date_to: date | None
    event_types: set[str]
    use_briefpapier: bool
    include_statistics: bool


class ExportAuditPdfDialog(QDialog):
    """Zwei-spaltiger Dialog: Filter/Optionen links, Ziel-File rechts."""

    def __init__(
        self,
        engagement: Engagement,
        event_types_available: list[str],
        briefpapier_available: bool,
        parent: QWidget | None = None,
        default_output_dir: Path | None = None,
        default_use_briefpapier: bool | None = None,
        default_include_statistics: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("AuditTrail-PDF exportieren")
        self.setModal(True)
        self.setMinimumWidth(720)

        self._result: ExportAuditPdfDialogResult | None = None
        self._briefpapier_available = briefpapier_available
        # Wenn das Setting nichts vorgibt, bleibt das alte Verhalten:
        # Briefpapier an, falls es überhaupt verfügbar ist.
        self._default_use_briefpapier = (
            briefpapier_available if default_use_briefpapier is None else default_use_briefpapier
        )
        self._default_include_statistics = default_include_statistics

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        body = QHBoxLayout()
        body.setSpacing(20)

        body.addLayout(self._build_left(event_types_available, briefpapier_available), stretch=2)
        body.addLayout(self._build_right(engagement, default_output_dir), stretch=3)
        outer.addLayout(body)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        outer.addWidget(self._buttons)

        # ---- Signals ----
        self._from_check.toggled.connect(self._from_date.setEnabled)
        self._from_check.toggled.connect(self._update_state)
        self._to_check.toggled.connect(self._to_date.setEnabled)
        self._to_check.toggled.connect(self._update_state)
        self._types_list.itemChanged.connect(lambda _i: self._update_state())
        self._select_all_btn.clicked.connect(lambda: self._set_all_types(True))
        self._select_none_btn.clicked.connect(lambda: self._set_all_types(False))
        self._target.changed.connect(self._update_state)
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)

        self._update_state()

    # ---- Public API ----------------------------------------------------

    def get_result(self) -> ExportAuditPdfDialogResult | None:
        """Liefert das Result oder `None` bei Abbruch."""
        return self._result

    # ---- Layout-Bausteine ----------------------------------------------

    def _build_left(
        self, event_types_available: list[str], briefpapier_available: bool
    ) -> QVBoxLayout:
        left = QVBoxLayout()
        left.setSpacing(10)

        # Zeitraum.
        gb_range = QGroupBox("Zeitraum")
        range_layout = QVBoxLayout(gb_range)
        today = QDate.currentDate()

        from_row = QHBoxLayout()
        self._from_check = QCheckBox("Von")
        self._from_date = QDateEdit()
        self._from_date.setDisplayFormat("yyyy-MM-dd")
        self._from_date.setCalendarPopup(True)
        self._from_date.setDate(today.addMonths(-3))
        self._from_date.setEnabled(False)
        from_row.addWidget(self._from_check)
        from_row.addWidget(self._from_date, stretch=1)
        range_layout.addLayout(from_row)

        to_row = QHBoxLayout()
        self._to_check = QCheckBox("Bis")
        self._to_date = QDateEdit()
        self._to_date.setDisplayFormat("yyyy-MM-dd")
        self._to_date.setCalendarPopup(True)
        self._to_date.setDate(today)
        self._to_date.setEnabled(False)
        to_row.addWidget(self._to_check)
        to_row.addWidget(self._to_date, stretch=1)
        range_layout.addLayout(to_row)
        left.addWidget(gb_range)

        # Aktionstypen.
        gb_types = QGroupBox("Aktionstypen")
        types_layout = QVBoxLayout(gb_types)
        self._types_list = QListWidget()
        self._types_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        types_to_show = (
            list(event_types_available) if event_types_available else list(_DEFAULT_TYPES)
        )
        for type_name in types_to_show:
            item = QListWidgetItem(type_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self._types_list.addItem(item)
        types_layout.addWidget(self._types_list)

        types_btn_row = QHBoxLayout()
        self._select_all_btn = QPushButton("Alle auswählen")
        self._select_all_btn.setProperty("secondary", True)
        self._select_none_btn = QPushButton("Alle abwählen")
        self._select_none_btn.setProperty("secondary", True)
        types_btn_row.addWidget(self._select_all_btn)
        types_btn_row.addWidget(self._select_none_btn)
        types_btn_row.addStretch(1)
        types_layout.addLayout(types_btn_row)
        left.addWidget(gb_types, stretch=1)

        # Optionen.
        gb_options = QGroupBox("Optionen")
        opt_layout = QVBoxLayout(gb_options)
        self._cb_briefpapier = QCheckBox("Briefpapier verwenden")
        self._cb_briefpapier.setChecked(briefpapier_available and self._default_use_briefpapier)
        if not briefpapier_available:
            self._cb_briefpapier.setEnabled(False)
            self._cb_briefpapier.setToolTip("Briefpapier nicht konfiguriert")
        self._cb_statistics = QCheckBox("Statistik-Seite anhängen")
        self._cb_statistics.setChecked(self._default_include_statistics)
        opt_layout.addWidget(self._cb_briefpapier)
        opt_layout.addWidget(self._cb_statistics)
        left.addWidget(gb_options)

        return left

    def _build_right(self, engagement: Engagement, default_output_dir: Path | None) -> QVBoxLayout:
        self._target = ExportTargetWidget(
            default_name=engagement.client_name,
            default_id=datetime.now().strftime("%Y%m%d"),
            file_extension=".pdf",
            type_token="audit_trail",
            default_output_dir=default_output_dir,
        )
        right = QVBoxLayout()
        right.addWidget(self._target)
        return right

    # ---- Slots ---------------------------------------------------------

    def _set_all_types(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self._types_list.count()):
            item = self._types_list.item(i)
            if item is not None:
                item.setCheckState(state)

    def _selected_types(self) -> set[str]:
        result: set[str] = set()
        for i in range(self._types_list.count()):
            item = self._types_list.item(i)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                result.add(item.text())
        return result

    def _update_state(self) -> None:
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is None:
            return
        valid = self._target.is_valid() and bool(self._selected_types())
        ok_btn.setEnabled(valid)

    def _on_accept(self) -> None:
        path = self._target.get_path()
        if path is None:
            return
        date_from: date | None = (
            self._from_date.date().toPyDate() if self._from_check.isChecked() else None
        )
        date_to: date | None = (
            self._to_date.date().toPyDate() if self._to_check.isChecked() else None
        )
        self._result = ExportAuditPdfDialogResult(
            output_path=path,
            date_from=date_from,
            date_to=date_to,
            event_types=self._selected_types(),
            use_briefpapier=self._cb_briefpapier.isChecked(),
            include_statistics=self._cb_statistics.isChecked(),
        )
        self.accept()
