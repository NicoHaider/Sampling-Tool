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
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.core.models import Engagement
from sampling_tool.io.bdo_locations import (
    companies,
    default_company,
    default_location,
    locations,
)
from sampling_tool.ui._dialog_sizing import clamp_dialog_height_to_screen
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
    # Sprint 33 – gewählte BDO-Gesellschaft + Standort (stabile Keys).
    # Defaults bewahren bestehende Konstruktions-Call-Sites (Tests) backward-compatible.
    company_key: str = ""
    location_key: str = ""


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
        offer_date_filter: bool = False,
        default_company_key: str | None = None,
        default_location_key: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("AuditTrail-PDF exportieren")
        self.setModal(True)
        self.setMinimumWidth(720)

        self._result: ExportAuditPdfDialogResult | None = None
        self._briefpapier_available = briefpapier_available
        # Sprint 33 – Vorauswahl der beiden unabhängigen BDO-Dropdowns.
        self._default_company_key = default_company_key
        self._default_location_key = default_location_key
        # Sprint 27: Der von/bis-Datumsfilter wird nur angeboten, wenn das
        # app-weite Setting es vorgibt (Default aus → kein Datumsschritt, alle
        # Events). Ist er aus, existieren die QDateEdit-Felder gar nicht und
        # das Ergebnis trägt date_from/date_to = None.
        self._offer_date_filter = offer_date_filter
        # Wenn das Setting nichts vorgibt, bleibt das alte Verhalten:
        # Briefpapier an, falls es überhaupt verfügbar ist.
        self._default_use_briefpapier = (
            briefpapier_available if default_use_briefpapier is None else default_use_briefpapier
        )
        self._default_include_statistics = default_include_statistics

        body_widget = QWidget()
        body = QHBoxLayout(body_widget)
        body.setSpacing(20)
        body.addLayout(self._build_left(event_types_available, briefpapier_available), stretch=2)
        body.addLayout(self._build_right(engagement, default_output_dir), stretch=3)

        # Sprint 67 / Teil A: Inhalt scrollt als Ganzes auf kleinen Screens –
        # Buttons bleiben BEWUSST außerhalb der ScrollArea (immer erreichbar).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body_widget)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)
        outer.addWidget(scroll, stretch=1)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        outer.addWidget(self._buttons)

        # ---- Signals ----
        self._types_list.itemChanged.connect(lambda _i: self._update_state())
        self._select_all_btn.clicked.connect(lambda: self._set_all_types(True))
        self._select_none_btn.clicked.connect(lambda: self._set_all_types(False))
        self._target.changed.connect(self._update_state)
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)

        self._update_state()
        clamp_dialog_height_to_screen(self)

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

        # Zeitraum (Sprint 27): nur wenn der app-weite Toggle aktiv ist. Die
        # QDateEdit-Felder sind dann DIREKT editierbar – früher waren sie per
        # `setEnabled(False)` deaktiviert und nur über separate Checkboxen
        # freischaltbar, was den Filter faktisch „nicht ausfüllbar" machte.
        if self._offer_date_filter:
            gb_range = QGroupBox("Zeitraum")
            range_layout = QVBoxLayout(gb_range)
            today = QDate.currentDate()

            from_row = QHBoxLayout()
            self._from_date = QDateEdit()
            self._from_date.setDisplayFormat("yyyy-MM-dd")
            self._from_date.setCalendarPopup(True)
            self._from_date.setDate(today.addMonths(-3))
            from_row.addWidget(QLabel("Von"))
            from_row.addWidget(self._from_date, stretch=1)
            range_layout.addLayout(from_row)

            to_row = QHBoxLayout()
            self._to_date = QDateEdit()
            self._to_date.setDisplayFormat("yyyy-MM-dd")
            self._to_date.setCalendarPopup(True)
            self._to_date.setDate(today)
            to_row.addWidget(QLabel("Bis"))
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

        # Sprint 33 – BDO-Gesellschaft & Standort (zwei UNABHÄNGIGE Dropdowns).
        left.addWidget(self._build_bdo_group())

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

    def _build_bdo_group(self) -> QGroupBox:
        """GroupBox mit zwei voneinander unabhängigen Dropdowns: Gesellschaft
        und Standort. Sie filtern sich NICHT gegenseitig – jede Gesellschaft ist
        mit jedem Standort kombinierbar (Kern der Sprint-33-Anforderung)."""
        gb = QGroupBox("BDO-Gesellschaft & Standort")
        form = QFormLayout(gb)

        self._company_combo = QComboBox()
        for company in companies():
            self._company_combo.addItem(company.name, company.key)

        self._location_combo = QComboBox()
        for location in locations():
            self._location_combo.addItem(
                f"{location.display_name} ({location.bundesland})", location.key
            )

        self._preselect_combo(self._company_combo, self._default_company_key, default_company().key)
        self._preselect_combo(
            self._location_combo, self._default_location_key, default_location().key
        )

        form.addRow("Gesellschaft", self._company_combo)
        form.addRow("Standort", self._location_combo)
        return gb

    @staticmethod
    def _preselect_combo(combo: QComboBox, key: str | None, fallback_key: str) -> None:
        """Wählt den Eintrag mit `key` vor; fehlt/unbekannt → `fallback_key`."""
        idx = combo.findData(key) if key else -1
        if idx < 0:
            idx = combo.findData(fallback_key)
        if idx >= 0:
            combo.setCurrentIndex(idx)

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
            self._from_date.date().toPyDate() if self._offer_date_filter else None
        )
        date_to: date | None = self._to_date.date().toPyDate() if self._offer_date_filter else None
        self._result = ExportAuditPdfDialogResult(
            output_path=path,
            date_from=date_from,
            date_to=date_to,
            event_types=self._selected_types(),
            use_briefpapier=self._cb_briefpapier.isChecked(),
            include_statistics=self._cb_statistics.isChecked(),
            company_key=self._company_combo.currentData() or "",
            location_key=self._location_combo.currentData() or "",
        )
        self.accept()
