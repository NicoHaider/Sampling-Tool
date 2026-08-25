"""Settings-Dialog: 3 Tabs (Allgemein / Reports / Erweitert).

Bewusst dumm gehalten: rendert das aktuelle `AppSettings`-Objekt,
liefert bei OK ein neues `AppSettings` zurück und überlässt die
Persistenz dem Controller (`settings_store.save_settings`).
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Final

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QResizeEvent
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.config import BDO_GREY, DEFAULT_BRIEFPAPIER, SEED_MAX
from sampling_tool.io.bdo_locations import (
    companies,
    default_company,
    default_location,
    locations,
)
from sampling_tool.io.briefpapier import validate_briefpapier
from sampling_tool.logging_setup import log_file_path
from sampling_tool.ui._dialog_sizing import (
    clamp_dialog_height_to_screen,
    clamp_dialog_width_to_screen,
)
from sampling_tool.ui._scaling import UI_SCALE_LEVELS
from sampling_tool.ui.settings_store import (
    LOG_LEVELS,
    AppSettings,
)

# QSpinBox unterstützt nur 32-Bit-signed → SEED_MAX wird gekappt (wie im
# Sampling-Dialog). 0 ist reserviert für „zufällig" (specialValueText).
_SEED_SPIN_MAX: int = min(SEED_MAX, 2_147_483_647)
# Label für den Seed-Wert 0 = kein fester Seed.
_SEED_RANDOM_LABEL: str = "Zufällig (bei jeder Ziehung neu)"
# Sprint 68 / Teil B1: Anzeige-Labels für die UI-Größe-Stufen (userData bleibt
# der interne Key aus `ui/_scaling.py`).
_UI_SCALE_DISPLAY: Final[dict[str, str]] = {"klein": "Klein", "normal": "Normal", "groß": "Groß"}

# Sprint 69 / Bug 3: Rand des äußeren Layouts – eigene Konstante statt zweimal
# hartcodierter `20`, weil `_content_min_width()` denselben Wert für die
# Mindestbreiten-Berechnung braucht (siehe dort).
_OUTER_MARGIN: Final[int] = 20
# Sprint 69 / Bug 3: kleiner Sicherheitspuffer für `_content_min_width()`
# (Details im Docstring dort).
_WIDTH_SAFETY_BUFFER: Final[int] = 8


def _select_combo_by_key(combo: QComboBox, key: str, fallback_key: str) -> None:
    """Wählt den Eintrag mit `key` vor; fehlt/unbekannt → `fallback_key`."""
    idx = combo.findData(key) if key else -1
    if idx < 0:
        idx = combo.findData(fallback_key)
    if idx >= 0:
        combo.setCurrentIndex(idx)


class _WrappingHintLabel(QLabel):
    """Word-wrap-`QLabel`, das seine Mindesthöhe selbst nachführt.

    Sprint 69 / Bug 2: Innerhalb der `QScrollArea` aus Sprint 67 propagiert
    `QFormLayout` `heightForWidth` nicht zuverlässig durch die Layout-Kette
    (QScrollArea → QTabWidget → Tab-Seite → QFormLayout). Ohne Gegenmaßnahme
    bekommt das Label nur eine einzeilige Höhe zugewiesen, obwohl der
    Wortumbruch bei der tatsächlichen Breite mehrzeilig ist – der Text wird
    abgeschnitten und überlappt die nächste Zeile. Der `resizeEvent`-Override
    erzwingt vor jedem Resize eine Mindesthöhe passend zur aktuellen Breite.
    """

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)

    def resizeEvent(self, event: QResizeEvent | None) -> None:  # noqa: N802
        self.setMinimumHeight(self.heightForWidth(self.width()))
        super().resizeEvent(event)


class SettingsDialog(QDialog):
    """Settings-Konfigurator. Öffnet sich mit den übergebenen Werten."""

    def __init__(self, current: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.setModal(True)

        self._initial = current
        self._result: AppSettings | None = None

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_general_tab(current), "Allgemein")
        self._tabs.addTab(self._build_reports_tab(current), "Reports")
        self._tabs.addTab(self._build_advanced_tab(current), "Erweitert")

        # Sprint 67 / Teil A: Tabs scrollen als Ganzes, wenn der Dialog auf
        # einem kleinen Screen niedriger als der Inhalt sein muss. Buttons
        # bleiben BEWUSST außerhalb der ScrollArea (immer erreichbar).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._tabs)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(_OUTER_MARGIN, _OUTER_MARGIN, _OUTER_MARGIN, _OUTER_MARGIN)
        outer.setSpacing(12)
        outer.addWidget(scroll, stretch=1)

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

        clamp_dialog_width_to_screen(self, self._content_min_width())
        clamp_dialog_height_to_screen(self)

    # ---- Public API -----------------------------------------------------

    def get_settings(self) -> AppSettings | None:
        """Liefert die neuen Settings oder `None`, wenn der Dialog abgebrochen wurde."""
        return self._result

    # ---- Größe -----------------------------------------------------------

    def _content_min_width(self) -> int:
        """Mindestbreite, die der Dialog braucht, damit KEINE Tab-Seite einen
        horizontalen Scrollbalken auslöst (Sprint 69 / Bug 3).

        Die `QScrollArea` aus Sprint 67 bricht die `minimumSizeHint`-
        Propagation vom Inhalt zum Dialog (siehe Modul-Docstring der
        `QScrollArea`-Einbindung oben) – ohne Gegenmaßnahme bleibt nur das
        hartcodierte `setMinimumWidth`, das schmaler sein kann als der
        tatsächliche Inhalt (z. B. die „Auswählen…“-Buttons).

        `QTabWidget.sizeHint()` bemisst je nach Qt-Version/-Plattform u. U. NUR
        die aktuell sichtbare Tab-Seite statt aller drei – deshalb wird hier
        explizit über `self._tabs.widget(i)` aller Indizes iteriert und das
        Maximum genommen, statt sich auf `self._tabs.sizeHint()` zu verlassen.

        Zum Inhalt kommt Chrome dazu: der schmale Rahmen des `QTabWidget`
        selbst (Differenz zwischen dessen eigenem `sizeHint()` und der
        breitesten Tab-Seite), die äußeren Dialog-Ränder auf beiden Seiten
        sowie die Breite eines vertikalen Scrollbalkens – der ist im
        Normalfall bereits sichtbar, weil die Dialoghöhe bewusst NICHT auf die
        volle Inhaltshöhe wächst (Sprint 67: Inhalt scrollt als Ganzes). Ein
        kleiner fixer Puffer obendrauf fängt eine empirisch beobachtete
        Wechselwirkung zwischen horizontalem und vertikalem Scrollbalken ab
        (das Erscheinen/Verschwinden des einen ändert kurzzeitig den
        verfügbaren Platz für den anderen) – kostet auf normalen Screens
        nichts, weil `clamp_dialog_width_to_screen` einen Überschuss ohnehin
        kappt.
        """
        widest_page = max(
            (
                page.sizeHint().width()
                for i in range(self._tabs.count())
                if (page := self._tabs.widget(i)) is not None
            ),
            default=0,
        )
        tabs_chrome = max(self._tabs.sizeHint().width() - widest_page, 0)
        style = self.style()
        scrollbar_extent = (
            style.pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent) if style is not None else 0
        )
        return (
            widest_page + tabs_chrome + 2 * _OUTER_MARGIN + scrollbar_extent + _WIDTH_SAFETY_BUFFER
        )

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
        form.addRow("Projekt-Ordner", wrapper)

        language = QLabel("Sprache: Deutsch (weitere folgen)")
        language.setStyleSheet(f"color: {BDO_GREY};")
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

        # Sprint 31: optionale ID-Spalte je Sample in der Sidebar-Stichprobenliste.
        self._chk_show_sample_id_column = QCheckBox("ID in Stichprobenliste anzeigen")
        self._chk_show_sample_id_column.setChecked(current.show_sample_id_column)
        self._chk_show_sample_id_column.setToolTip(
            "Zeigt in der Stichprobenliste die Werte der beim Import gewählten "
            "ID-Spalte je Stichprobe an (z. B. „IDs: 1001, 1002, …“). Reine "
            "Anzeige-Hilfe – ohne Einfluss auf die Ziehung."
        )
        panels_layout.addWidget(self._chk_show_sample_id_column)
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

        # Sprint 27: Audit-PDF-Export bietet den von/bis-Datumsfilter nur an,
        # wenn dieser Toggle aktiv ist. Default aus → der Export überspringt
        # den Datumsschritt und exportiert alle Events.
        self._audit_export_date_filter = QCheckBox(
            "Im Audit-PDF-Export einen Datumsfilter (von/bis) anbieten"
        )
        self._audit_export_date_filter.setChecked(current.audit_export_offer_date_filter)
        self._audit_export_date_filter.setToolTip(
            "Aus: der Export enthält alle Events ohne Datumsabfrage.\n"
            "An: im Export-Dialog erscheint ein von/bis-Filter."
        )
        outer.addWidget(self._audit_export_date_filter)

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

        # ---- Sprint 33: Standard-BDO-Gesellschaft + -Standort ----
        # Zwei unabhängige Dropdowns (analog dem Export-Dialog) – sie filtern
        # sich nicht gegenseitig. Speisen die Vorauswahl im Audit-PDF-Export.
        bdo_box = QGroupBox("BDO-Adressblock (Standard für Audit-PDF)")
        bdo_form = QFormLayout(bdo_box)
        self._bdo_company = QComboBox()
        for company in companies():
            self._bdo_company.addItem(company.name, company.key)
        self._bdo_location = QComboBox()
        for location in locations():
            self._bdo_location.addItem(
                f"{location.display_name} ({location.bundesland})", location.key
            )
        _select_combo_by_key(self._bdo_company, current.bdo_company_key, default_company().key)
        _select_combo_by_key(self._bdo_location, current.bdo_location_key, default_location().key)
        bdo_form.addRow("Standard-BDO-Gesellschaft", self._bdo_company)
        bdo_form.addRow("Standard-BDO-Standort", self._bdo_location)
        outer.addWidget(bdo_box)

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

        self._log_level = QComboBox()
        self._log_level.addItems(LOG_LEVELS)
        idx = self._log_level.findText(current.log_level)
        if idx >= 0:
            self._log_level.setCurrentIndex(idx)
        form.addRow("Log-Level", self._log_level)

        self._ui_scale = QComboBox()
        for level in UI_SCALE_LEVELS:
            self._ui_scale.addItem(_UI_SCALE_DISPLAY[level], userData=level)
        _select_combo_by_key(self._ui_scale, current.ui_scale, AppSettings.defaults().ui_scale)
        form.addRow("UI-Größe", self._ui_scale)

        self._ui_scale_hint = _WrappingHintLabel(
            "Skaliert Schrift, Symbole und Zeilenhöhe. Wirkt sofort; einzelne "
            "Dialoge übernehmen die neue Größe beim nächsten Öffnen."
        )
        self._ui_scale_hint.setStyleSheet(f"color: {BDO_GREY};")
        form.addRow(" ", self._ui_scale_hint)

        # Sprint 27: Der Sampling-Seed wird ausschließlich hier geändert – im
        # Haupt-Dialog ist das Feld schreibgeschützt. 0 (= specialValueText)
        # bedeutet „kein fester Seed": es wird wie bisher zufällig gewürfelt
        # und der zuletzt genutzte Seed gemerkt (ISAE-3402, Sprint 21).
        self._seed_spin = QSpinBox()
        self._seed_spin.setRange(0, _SEED_SPIN_MAX)
        self._seed_spin.setSpecialValueText(_SEED_RANDOM_LABEL)
        self._seed_spin.setValue(current.seed if current.seed is not None else 0)
        self._seed_spin.setToolTip(
            "Fester Seed für die nächste Ziehung. Gleicher Seed + gleiche Daten "
            "→ bit-genau gleiche Stichprobe.\n0 = zufällig (kein fester Seed)."
        )
        self._seed_dice = QPushButton("🎲 Würfeln")
        self._seed_dice.setProperty("secondary", True)
        self._seed_dice.setToolTip("Einen neuen zufälligen festen Seed setzen")
        self._seed_dice.clicked.connect(self._on_reroll_seed)
        seed_row = QHBoxLayout()
        seed_row.setSpacing(8)
        seed_row.addWidget(self._seed_spin, stretch=1)
        seed_row.addWidget(self._seed_dice)
        seed_widget = QWidget()
        seed_widget.setLayout(seed_row)
        form.addRow("Sampling-Seed", seed_widget)

        self._info_label = _WrappingHintLabel(
            f"Log-Datei: zentral unter {log_file_path()} (app-weit, nicht im "
            "Projekt-Ordner). Das Log-Level wirkt sofort, ohne Neustart."
        )
        self._info_label.setStyleSheet(f"color: {BDO_GREY};")
        form.addRow(" ", self._info_label)
        outer.addLayout(form)
        outer.addStretch(1)
        return page

    # ---- Slots ----------------------------------------------------------

    def _on_reroll_seed(self) -> None:
        """Setzt einen neuen zufälligen festen Seed (immer > 0)."""
        self._seed_spin.setValue(secrets.randbelow(_SEED_SPIN_MAX) + 1)

    def _on_browse_engagements_dir(self) -> None:
        start = self._engagements_dir.text() or str(self._initial.engagements_dir)
        directory = QFileDialog.getExistingDirectory(self, "Projekt-Ordner wählen", start)
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
        if not path_str:
            return
        # Sprint 47 / N-010: Fail-Fast – eine unlesbare/zu große Datei wird
        # gar nicht erst übernommen, statt erst beim Export aufzufallen.
        try:
            validate_briefpapier(Path(path_str))
        except (FileNotFoundError, ValueError) as exc:
            QMessageBox.warning(self, "Ungültiges Briefpapier", str(exc))
            return
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
        self._audit_export_date_filter.setChecked(defaults.audit_export_offer_date_filter)
        self._radio_placeholder.setChecked(True)
        self._custom_briefpapier.clear()
        _select_combo_by_key(self._bdo_company, defaults.bdo_company_key, default_company().key)
        _select_combo_by_key(self._bdo_location, defaults.bdo_location_key, default_location().key)
        self._chk_show_dashboard.setChecked(defaults.show_dashboard)
        self._chk_show_audit_trail.setChecked(defaults.show_audit_trail)
        self._chk_show_sample_id_column.setChecked(defaults.show_sample_id_column)
        self._chk_advanced_mode.setChecked(defaults.advanced_mode)
        self._undo_depth.setValue(defaults.undo_depth)
        self._seed_spin.setValue(defaults.seed if defaults.seed is not None else 0)
        idx = self._log_level.findText(defaults.log_level)
        if idx >= 0:
            self._log_level.setCurrentIndex(idx)
        _select_combo_by_key(self._ui_scale, defaults.ui_scale, defaults.ui_scale)

    def _on_accept(self) -> None:
        custom_path: Path | None = None
        if self._radio_custom.isChecked():
            text = self._custom_briefpapier.text().strip()
            if text:
                custom_path = Path(text)

        if custom_path is not None:
            # Sprint 47 / N-010: auch ein manuell ins Textfeld getippter/
            # editierter Pfad (statt über „Auswählen…") muss Fail-Fast
            # geprüft werden – eine unlesbare Datei darf nie gespeichert
            # werden.
            try:
                validate_briefpapier(custom_path)
            except (FileNotFoundError, ValueError) as exc:
                QMessageBox.warning(self, "Ungültiges Briefpapier", str(exc))
                return

        engagements_text = self._engagements_dir.text().strip()
        if not engagements_text:
            QMessageBox.warning(self, "Ungültiger Pfad", "Bitte einen Projekt-Ordner angeben.")
            return
        seed_value = self._seed_spin.value()
        self._result = AppSettings(
            default_auditor_name=self._auditor_name.text().strip(),
            engagements_dir=Path(engagements_text),
            reset_keeps_filter=self._reset_keeps_filter.isChecked(),
            default_include_briefpapier=self._default_briefpapier.isChecked(),
            default_include_statistics=self._default_statistics.isChecked(),
            custom_briefpapier_path=custom_path,
            audit_export_offer_date_filter=self._audit_export_date_filter.isChecked(),
            bdo_company_key=self._bdo_company.currentData() or "",
            bdo_location_key=self._bdo_location.currentData() or "",
            # 0 (specialValueText) bedeutet „kein fester Seed" → None.
            seed=seed_value if seed_value != 0 else None,
            show_dashboard=self._chk_show_dashboard.isChecked(),
            show_audit_trail=self._chk_show_audit_trail.isChecked(),
            show_sample_id_column=self._chk_show_sample_id_column.isChecked(),
            advanced_mode=self._chk_advanced_mode.isChecked(),
            undo_depth=self._undo_depth.value(),
            log_level=self._log_level.currentText(),
            ui_scale=self._ui_scale.currentData() or AppSettings.defaults().ui_scale,
            # Sprint 22: Die Einzel-Toggles für Advanced-Funktionen leben im
            # „Ansicht"-Menü, nicht in diesem Dialog. Werte unverändert
            # durchreichen, damit OK sie nicht versehentlich zurücksetzt.
            show_filter_feature=self._initial.show_filter_feature,
            show_cluster_feature=self._initial.show_cluster_feature,
            show_stratified_feature=self._initial.show_stratified_feature,
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
