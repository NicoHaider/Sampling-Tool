"""Export-Dialog für den HTML-Report (E-Mail-Versand).

Erlaubt das Ein-/Ausschalten einzelner Report-Blöcke (Charts, AuditTrail,
Samples-Übersicht). Der HtmlReportGenerator nimmt das `Result` als Flags
entgegen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.core.models import Engagement
from sampling_tool.ui.dialogs._export_base import ExportTargetWidget


@dataclass(frozen=True, slots=True)
class ExportHtmlReportDialogResult:
    """Ergebnis des HTML-Report-Export-Dialogs."""

    output_path: Path
    include_charts: bool
    include_audit_trail: bool
    include_samples_table: bool


class ExportHtmlReportDialog(QDialog):
    """HTML-Report-Inhalts-Optionen + Datei-Ziel."""

    def __init__(
        self,
        engagement: Engagement,
        parent: QWidget | None = None,
        default_output_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("HTML-Report exportieren")
        self.setModal(True)
        self.setMinimumWidth(640)

        self._result: ExportHtmlReportDialogResult | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        body = QHBoxLayout()
        body.setSpacing(20)

        # Links: Inhalts-Optionen.
        left = QVBoxLayout()
        left.setSpacing(10)
        gb = QGroupBox("Inhalte")
        gb_layout = QVBoxLayout(gb)
        self._cb_charts = QCheckBox("Charts einbetten (Base64)")
        self._cb_charts.setChecked(True)
        self._cb_charts.setToolTip("Macht die Datei größer, aber selbstständig")
        self._cb_audit_trail = QCheckBox("AuditTrail-Tabelle anhängen")
        self._cb_audit_trail.setChecked(True)
        self._cb_samples = QCheckBox("Samples-Übersicht anhängen")
        self._cb_samples.setChecked(True)
        gb_layout.addWidget(self._cb_charts)
        gb_layout.addWidget(self._cb_audit_trail)
        gb_layout.addWidget(self._cb_samples)
        left.addWidget(gb)
        left.addStretch(1)
        body.addLayout(left, stretch=2)

        # Rechts: Datei-Ziel.
        self._target = ExportTargetWidget(
            default_name=engagement.client_name,
            default_id=datetime.now().strftime("%Y%m%d"),
            file_extension=".html",
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
        self._target.changed.connect(self._update_state)
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)

        self._update_state()

    # ---- Public API ----------------------------------------------------

    def get_result(self) -> ExportHtmlReportDialogResult | None:
        """Liefert das Result oder `None` bei Abbruch."""
        return self._result

    # ---- intern --------------------------------------------------------

    def _update_state(self) -> None:
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is None:
            return
        ok_btn.setEnabled(self._target.is_valid())

    def _on_accept(self) -> None:
        path = self._target.get_path()
        if path is None:
            return
        self._result = ExportHtmlReportDialogResult(
            output_path=path,
            include_charts=self._cb_charts.isChecked(),
            include_audit_trail=self._cb_audit_trail.isChecked(),
            include_samples_table=self._cb_samples.isChecked(),
        )
        self.accept()
