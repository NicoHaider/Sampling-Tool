"""Settings-Dialog: 3 Tabs (Allgemein / Reports / Erweitert).

Bewusst dumm gehalten: rendert das aktuelle `AppSettings`-Objekt,
liefert bei OK ein neues `AppSettings` zurück und überlässt die
Persistenz dem Controller (`settings_store.save_settings`).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStyle,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.config import DEFAULT_BRIEFPAPIER
from sampling_tool.ui.settings_store import (
    LOG_LEVELS,
    AppSettings,
)


class SettingsDialog(QDialog):
    """Settings-Konfigurator. Öffnet sich mit den übergebenen Werten."""

    def __init__(self, current: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.setModal(True)
        self.setMinimumWidth(560)

        self._initial = current
        self._result: AppSettings | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_general_tab(current), "Allgemein")
        self._tabs.addTab(self._build_reports_tab(current), "Reports")
        self._tabs.addTab(self._build_advanced_tab(current), "Erweitert")
        outer.addWidget(self._tabs)

        # Reset-Button (links) + OK/Cancel (rechts).
        button_row = QHBoxLayout()
        self._reset_button = QPushButton("Auf Default zurücksetzen")
        self._reset_button.clicked.connect(self._on_reset_defaults)
        button_row.addWidget(self._reset_button)
        button_row.addStretch(1)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)
        button_row.addWidget(self._buttons)
        outer.addLayout(button_row)

    # ---- Public API -----------------------------------------------------

    def get_settings(self) -> AppSettings | None:
        """Liefert die neuen Settings oder `None`, wenn der Dialog abgebrochen wurde."""
        return self._result

    # ---- Tabs -----------------------------------------------------------

    def _build_general_tab(self, current: AppSettings) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(10)

        self._auditor_name = QLineEdit(current.default_auditor_name)
        self._auditor_name.setPlaceholderText("z. B. Anna Auditorin")
        form.addRow("Standard-Auditor-Name", self._auditor_name)

        self._engagements_dir = QLineEdit(str(current.engagements_dir))
        browse = QPushButton("Auswählen…")
        browse.clicked.connect(self._on_browse_engagements_dir)
        row = QHBoxLayout()
        row.addWidget(self._engagements_dir)
        row.addWidget(browse)
        wrapper = QWidget()
        wrapper.setLayout(row)
        form.addRow("Engagement-Ordner", wrapper)

        language = QLabel("Sprache: Deutsch (weitere folgen)")
        language.setStyleSheet("color: #7F7F7F;")
        form.addRow(" ", language)
        outer.addLayout(form)

        # ---- Angezeigte Bereiche (Dashboard / AuditTrail togglen) ----
        panels_box = QGroupBox("Angezeigte Bereiche")
        panels_layout = QVBoxLayout(panels_box)
        panel_tooltip = (
            "Blendet den jeweiligen Tab im unteren Bereich des Hauptfensters "
            "ein oder aus. Wenn weder Dashboard noch Audit-Trail aktiv sind, "
            "wird der gesamte untere Bereich ausgeblendet und die Datentabelle "
            "nutzt die volle Höhe."
        )
        self._chk_show_dashboard = QCheckBox("Dashboard anzeigen")
        self._chk_show_dashboard.setChecked(current.show_dashboard)
        self._chk_show_dashboard.setToolTip(panel_tooltip)
        self._chk_show_audit_trail = QCheckBox("Audit-Trail anzeigen")
        self._chk_show_audit_trail.setChecked(current.show_audit_trail)
        self._chk_show_audit_trail.setToolTip(panel_tooltip)
        panels_layout.addWidget(self._chk_show_dashboard)
        panels_layout.addWidget(self._chk_show_audit_trail)
        outer.addWidget(panels_box)
        outer.addStretch(1)
        return page

    def _build_reports_tab(self, current: AppSettings) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setSpacing(10)

        self._reset_keeps_filter = QCheckBox("Reset behält Filter aktiv")
        self._reset_keeps_filter.setChecked(current.reset_keeps_filter)
        outer.addWidget(self._reset_keeps_filter)

        self._default_briefpapier = QCheckBox("Briefpapier standardmäßig im PDF einbetten")
        self._default_briefpapier.setChecked(current.default_include_briefpapier)
        outer.addWidget(self._default_briefpapier)

        self._default_statistics = QCheckBox("Statistik-Seite standardmäßig anhängen")
        self._default_statistics.setChecked(current.default_include_statistics)
        outer.addWidget(self._default_statistics)

        # ---- Briefpapier-GroupBox ----
        group = QGroupBox("Briefpapier")
        group_layout = QVBoxLayout(group)

        self._radio_placeholder = QRadioButton("Platzhalter-Briefpapier verwenden (Default)")
        self._radio_custom = QRadioButton("Eigenes Briefpapier verwenden:")
        button_group = QButtonGroup(group)
        button_group.addButton(self._radio_placeholder)
        button_group.addButton(self._radio_custom)
        if current.custom_briefpapier_path is None:
            self._radio_placeholder.setChecked(True)
        else:
            self._radio_custom.setChecked(True)
        group_layout.addWidget(self._radio_placeholder)
        group_layout.addWidget(self._radio_custom)

        path_row = QHBoxLayout()
        self._custom_briefpapier = QLineEdit(
            str(current.custom_briefpapier_path) if current.custom_briefpapier_path else ""
        )
        self._custom_briefpapier.setPlaceholderText("Pfad zu PNG/JPG/PDF…")
        browse_briefpapier = QPushButton("Auswählen…")
        browse_briefpapier.clicked.connect(self._on_browse_briefpapier)
        path_row.addWidget(self._custom_briefpapier)
        path_row.addWidget(browse_briefpapier)
        path_wrapper = QWidget()
        path_wrapper.setLayout(path_row)
        group_layout.addWidget(path_wrapper)

        preview_button = QPushButton("Vorschau anzeigen")
        preview_button.clicked.connect(self._on_preview_briefpapier)
        group_layout.addWidget(preview_button)
        self._preview_button = preview_button

        outer.addWidget(group)
        outer.addStretch(1)
        return page

    def _build_advanced_tab(self, current: AppSettings) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setSpacing(10)

        # ---- Erweiterter Modus (prominent oben) ----
        self._chk_advanced_mode = QCheckBox("Erweiterten Modus aktivieren")
        self._chk_advanced_mode.setChecked(current.advanced_mode)
        info_btn = QToolButton()
        style = self.style()
        if style is not None:
            info_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation))
        info_btn.setAutoRaise(True)
        info_btn.setToolTip(
            "Schaltet zusätzliche Sampling-Methoden (Cluster, Stratifiziert) "
            "und Detail-Optionen (Resample, manueller Seed) im Stichproben-"
            "Dialog frei. Standardmäßig ist nur die einfache Zufallsstichprobe "
            "sichtbar."
        )
        advanced_row = QHBoxLayout()
        advanced_row.addWidget(self._chk_advanced_mode)
        advanced_row.addWidget(info_btn)
        advanced_row.addStretch(1)
        outer.addLayout(advanced_row)

        # ---- Rest des Tabs ----
        form = QFormLayout()
        form.setSpacing(10)

        self._undo_depth = QSpinBox()
        self._undo_depth.setRange(1, 100)
        self._undo_depth.setValue(current.undo_depth)
        form.addRow("Undo-Tiefe (max. Aktionen)", self._undo_depth)

        self._snapshot_retention = QSpinBox()
        self._snapshot_retention.setRange(0, 3650)
        self._snapshot_retention.setValue(current.snapshot_retention_days)
        self._snapshot_retention.setToolTip("0 = unbegrenzt")
        form.addRow("Snapshots aufbewahren (Tage)", self._snapshot_retention)

        self._log_level = QComboBox()
        self._log_level.addItems(LOG_LEVELS)
        idx = self._log_level.findText(current.log_level)
        if idx >= 0:
            self._log_level.setCurrentIndex(idx)
        form.addRow("Log-Level", self._log_level)

        info = QLabel(
            "Log-Datei: standardmäßig im Engagement-Ordner unter `app.log`. "
            "Wird beim nächsten Start angewendet."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #7F7F7F;")
        form.addRow(" ", info)
        outer.addLayout(form)
        outer.addStretch(1)
        return page

    # ---- Slots ----------------------------------------------------------

    def _on_browse_engagements_dir(self) -> None:
        start = self._engagements_dir.text() or str(self._initial.engagements_dir)
        directory = QFileDialog.getExistingDirectory(self, "Engagement-Ordner wählen", start)
        if directory:
            self._engagements_dir.setText(directory)

    def _on_browse_briefpapier(self) -> None:
        start = self._custom_briefpapier.text()
        path_str, _filter = QFileDialog.getOpenFileName(
            self,
            "Briefpapier wählen",
            start,
            "Briefpapier (*.png *.jpg *.jpeg *.pdf);;Alle Dateien (*)",
        )
        if path_str:
            self._custom_briefpapier.setText(path_str)
            self._radio_custom.setChecked(True)

    def _on_preview_briefpapier(self) -> None:
        path = self._active_briefpapier_path()
        if path is None or not path.exists():
            QMessageBox.warning(
                self,
                "Vorschau nicht möglich",
                "Es ist kein gültiges Briefpapier hinterlegt.",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _on_reset_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            "Defaults wiederherstellen?",
            "Alle Einstellungen werden auf die Werks-Defaults zurückgesetzt. Fortfahren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        defaults = AppSettings.defaults()
        self._auditor_name.setText(defaults.default_auditor_name)
        self._engagements_dir.setText(str(defaults.engagements_dir))
        self._reset_keeps_filter.setChecked(defaults.reset_keeps_filter)
        self._default_briefpapier.setChecked(defaults.default_include_briefpapier)
        self._default_statistics.setChecked(defaults.default_include_statistics)
        self._radio_placeholder.setChecked(True)
        self._custom_briefpapier.clear()
        self._chk_show_dashboard.setChecked(defaults.show_dashboard)
        self._chk_show_audit_trail.setChecked(defaults.show_audit_trail)
        self._chk_advanced_mode.setChecked(defaults.advanced_mode)
        self._undo_depth.setValue(defaults.undo_depth)
        self._snapshot_retention.setValue(defaults.snapshot_retention_days)
        idx = self._log_level.findText(defaults.log_level)
        if idx >= 0:
            self._log_level.setCurrentIndex(idx)

    def _on_accept(self) -> None:
        custom_path: Path | None = None
        if self._radio_custom.isChecked():
            text = self._custom_briefpapier.text().strip()
            if text:
                custom_path = Path(text)

        engagements_text = self._engagements_dir.text().strip()
        if not engagements_text:
            QMessageBox.warning(self, "Ungültiger Pfad", "Bitte einen Engagement-Ordner angeben.")
            return
        self._result = AppSettings(
            default_auditor_name=self._auditor_name.text().strip(),
            engagements_dir=Path(engagements_text),
            reset_keeps_filter=self._reset_keeps_filter.isChecked(),
            default_include_briefpapier=self._default_briefpapier.isChecked(),
            default_include_statistics=self._default_statistics.isChecked(),
            custom_briefpapier_path=custom_path,
            show_dashboard=self._chk_show_dashboard.isChecked(),
            show_audit_trail=self._chk_show_audit_trail.isChecked(),
            advanced_mode=self._chk_advanced_mode.isChecked(),
            undo_depth=self._undo_depth.value(),
            snapshot_retention_days=self._snapshot_retention.value(),
            log_level=self._log_level.currentText(),
            # First-Run-Flag wird im Dialog NICHT verändert – einmal True,
            # bleibt True. Wir reichen den Initial-Wert einfach durch.
            first_run_completed=self._initial.first_run_completed,
        )
        self.accept()

    # ---- intern --------------------------------------------------------

    def _active_briefpapier_path(self) -> Path | None:
        """Pfad, den die Vorschau-Schaltfläche öffnen soll."""
        if self._radio_custom.isChecked():
            text = self._custom_briefpapier.text().strip()
            return Path(text) if text else None
        return DEFAULT_BRIEFPAPIER if DEFAULT_BRIEFPAPIER.exists() else None
