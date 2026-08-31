"""Export-Dialog für den HTML-Report (E-Mail-Versand).

Erlaubt das Ein-/Ausschalten einzelner Report-Blöcke (Charts, AuditTrail,
Samples-Übersicht). Der HtmlReportGenerator nimmt das `Result` als Flags
entgegen.
"""

from __future__ import annotations

from collections.abc import Callable
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

from sampling_tool.config import export_date_token, local_export_now
from sampling_tool.core.models import Engagement
from sampling_tool.ui._dialog_buttons import mark_secondary_buttons, set_accept_text
from sampling_tool.ui.dialogs._export_base import ExportTargetWidget, apply_validation


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
        *,
        now_provider: Callable[[], datetime] = local_export_now,
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
        # Sprint 74: EINE Uhr-Lesung für Dialog UND Widget. Vorher las
        # `default_id` hier eine eigene Uhr und das `{date}`-Token im Widget
        # eine zweite – im selben Dateinamen konnten zwei verschiedene Tage
        # stehen (…_ID20260812_BDO_report_20260813.html).
        now = now_provider()
        self._target = ExportTargetWidget(
            default_name=engagement.client_name,
            default_id=export_date_token(now),
            file_extension=".html",
            type_token="report",
            default_output_dir=default_output_dir,
            now_provider=lambda: now,
        )
        right = QVBoxLayout()
        right.addWidget(self._target)
        body.addLayout(right, stretch=3)

        outer.addLayout(body)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        # Sprint 81: ein Verb sagt, was passiert – so wie der Import-Dialog es
        # seit Sprint 16 macht. „OK" beschreibt keine Handlung.
        set_accept_text(self._buttons, "Exportieren")
        mark_secondary_buttons(self._buttons)
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

    def _selection_hint(self) -> str:
        """Dieser Dialog hat KEINE Auswahl-Bedingung – die drei Inhalts-Toggles
        dürfen alle aus sein (dann entsteht ein Report ohne Zusatzblöcke, das
        ist ein gültiges Ergebnis). Die Methode existiert trotzdem, damit alle
        vier Dialoge dieselbe Naht haben; ein fünfter Grund wäre hier ein
        Einzeiler. Festgenagelt in `test_html_dialog_has_no_selection_hint`."""
        return ""

    def _update_state(self) -> None:
        apply_validation(
            self._buttons.button(QDialogButtonBox.StandardButton.Ok),
            self._target,
            self._selection_hint(),
        )

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
