"""Sampling-Dialog – Konfiguration einer neuen Stichprobenziehung.

Entspricht der alten VBA-`SamplingUserForm`. Liefert nach `accept()` ein
`SamplingDialogResult` mit dem fertigen `SampleConfig` und einem Flag, ob
nur aus der aktuell hervorgehobenen Sample-Selektion gezogen werden soll
(Resampling).

Die Persistenz-Schicht kennt das Resampling-Flag nicht – es ist eine reine
UI-Anweisung an den Controller, das Dataset vor der Ziehung zu filtern.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.config import (
    BDO_GREY,
    BDO_RED,
    DEFAULT_SAMPLE_SIZE,
    MIN_SAMPLE_SIZE,
    SEED_MAX,
    SEED_MIN,
)
from sampling_tool.core.models import (
    Dataset,
    SampleConfig,
    SampleResult,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.core.presets import SamplingPreset
from sampling_tool.ui.preset_store import PresetStore
from sampling_tool.ui.settings_store import SamplingFeatures

NO_FILTER_LABEL: str = "(kein Filter)"

# QSpinBox-Maximum: int32-signed-Limit. Die Größe wird dadurch faktisch
# nicht mehr durch das Widget gecappt – stattdessen schlägt Validierung
# beim Accept zu (siehe `accept()`).
_SPINBOX_MAX: int = 2_147_483_647


@dataclass(frozen=True, slots=True)
class SamplingDialogResult:
    """Ergebnis des Sampling-Dialogs."""

    config: SampleConfig
    from_sample_only: bool = False


@dataclass(frozen=True, slots=True)
class AppliedPresetResult:
    """Ergebnis von `SamplingDialog.apply_preset` (Sprint 23).

    `skipped_filters` listet die Filter-Spalten, die übersprungen wurden, weil
    sie in der aktuell geladenen Population nicht existieren – der Rest des
    Presets wird trotzdem angewendet (kein stiller Fehlschlag, kein Crash).
    """

    skipped_filters: tuple[str, ...] = ()


class SamplingDialog(QDialog):
    """Dialog für die Konfiguration einer Stichprobenziehung."""

    def __init__(
        self,
        dataset: Dataset,
        distinct_values_provider: Callable[[str], Sequence[Any]] | None = None,
        current_sample: SampleResult | None = None,
        parent: QWidget | None = None,
        *,
        features: SamplingFeatures | None = None,
        preset_store: PresetStore | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Neue Stichprobe")
        self.setModal(True)
        self.setMinimumWidth(520)

        self._dataset = dataset
        # Sprint 19 / P-005: kein Row-Materialize mehr – der Controller
        # injiziert einen distinct-Werte-Provider (SQL-basiert). None, wenn das
        # Filter-Feld nicht freigeschaltet ist.
        self._distinct_values_provider = distinct_values_provider
        self._current_sample = current_sample
        self._result: SamplingDialogResult | None = None
        self._columns = list(dataset.columns)
        self._max_population = max(dataset.row_count, 1)
        # Sprint 22: pro Funktion aufgelöste Sichtbarkeit (ODER aus Advanced-
        # Mode + Einzel-Toggle, vom Controller berechnet). Der Dialog kennt
        # weder advanced_mode noch die Einzel-Toggles.
        self._features = features if features is not None else SamplingFeatures()
        self._show_filter = self._features.show_filter
        self._show_cluster = self._features.show_cluster
        self._show_stratified = self._features.show_stratified
        self._show_methods = self._features.show_methods
        # Sprint 23: app-weiter Preset-Store (benannte Profile). Default: echter
        # QSettings-Store; Tests können einen isolierten Store injizieren.
        self._preset_store = preset_store if preset_store is not None else PresetStore()
        # Sprint 28: Vorlagen erscheinen als Chips (ein Chip je Vorlage). Der
        # zuletzt angewandte Chip wird markiert; eine manuelle Änderung hebt die
        # Markierung wieder auf. `_applying_preset` schützt die Markierung
        # während des Anwendens (die Widget-Updates dürfen sie nicht löschen).
        self._preset_chips: list[QPushButton] = []
        self._applying_preset = False

        self._build_ui()
        self._wire_signals()
        self._reload_preset_chips()
        if self._show_filter:
            self._refresh_filter_values()
        if self._show_methods:
            self._on_method_changed()
        self._validate()

    # ---- Public API -----------------------------------------------------

    def get_result(self) -> SamplingDialogResult | None:
        """Liefert das Ergebnis – `None`, wenn der Dialog abgebrochen wurde."""
        return self._result

    def set_initial_seed(self, seed: int) -> None:
        """Übernimmt einen vorgemerkten Seed in das (schreibgeschützte) Seed-Feld.

        Beim Öffnen würfelt der Dialog standardmäßig einen frischen
        Zufalls-Seed. Der Controller reicht hier den aufgelösten Seed durch
        (Sprint 27: fester Seed aus den Einstellungen, sonst der zuletzt
        genutzte Seed der Session), damit eine erneute Ziehung (auch nach
        „Sampling zurücksetzen") denselben Seed verwendet und die Stichprobe
        bit-genau reproduziert (ISAE-3402). Das Feld bleibt schreibgeschützt;
        geändert wird der Seed nur in den Einstellungen.
        """
        self._seed_spin.setValue(seed)

    # ---- Presets (Sprint 23) -------------------------------------------

    def current_settings_as_preset(self, name: str) -> SamplingPreset:
        """Friert die aktuellen Dialog-Einstellungen als benanntes Preset ein.

        Der Seed wandert NICHT ins Preset (`SamplingPreset.from_config` lässt
        ihn fallen) – ein Profil beschreibt nur, *wie* gesampelt wird.
        """
        return SamplingPreset.from_config(name, self._build_config())

    def apply_preset(self, preset: SamplingPreset) -> AppliedPresetResult:
        """Übernimmt ein Preset in die Dialog-Widgets.

        Setzt ausschließlich Parameter – es wird NICHT gezogen und der Seed
        bleibt unangetastet (ISAE-3402). Nur Funktionen, die aktuell sichtbar
        sind, werden gesetzt. Filter, deren Spalte in der geladenen Population
        fehlt, werden übersprungen und im Ergebnis gemeldet (kein Crash).
        """
        skipped_filters: list[str] = []
        self._size_spin.setValue(preset.size)
        self._apply_preset_method(preset.method)
        if self._show_cluster and preset.cluster_field and preset.cluster_field in self._columns:
            self._cluster_field.setCurrentText(preset.cluster_field)
        if self._show_stratified:
            if preset.stratum_field and preset.stratum_field in self._columns:
                self._stratum_field.setCurrentText(preset.stratum_field)
            if preset.stratify_mode == StratifyMode.EQUAL:
                self._radio_equal.setChecked(True)
            else:
                self._radio_proportional.setChecked(True)
        if self._show_filter:
            self._apply_preset_filter(preset, skipped_filters)
        if self._show_methods:
            self._on_method_changed()
        self._validate()
        return AppliedPresetResult(skipped_filters=tuple(skipped_filters))

    # ---- UI-Aufbau -----------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        intro = QLabel(
            "Konfiguriere die Stichprobenziehung. Bei gleichem Seed und gleichen "
            "Daten ist das Ergebnis bit-genau reproduzierbar (ISAE-3402)."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #7F7F7F;")
        outer.addWidget(intro)

        # ---- Vorlagen (Sprint 28) ----
        # Gespeicherte Vorlagen erscheinen als kompakte Chips – ein Klick wendet
        # die Vorlage an (`apply_preset`: setzt nur Parameter, zieht NICHT). Das
        # kleine „+" speichert die aktuellen Einstellungen als neue Vorlage.
        # Bearbeiten/Umbenennen/Löschen leben im eigenen Verwaltungsfenster
        # (Menü „Stichprobe → Vorlagen verwalten…"). Die Sprint-23-Mechanik
        # (PresetStore/apply_preset) wird unverändert wiederverwendet – keine
        # neue Persistenz. Bei vielen Vorlagen scrollt die Leiste horizontal,
        # statt das Layout zu sprengen.
        preset_box = QGroupBox("Vorlagen")
        preset_layout = QHBoxLayout(preset_box)
        preset_layout.setSpacing(8)

        self._chip_scroll = QScrollArea()
        self._chip_scroll.setWidgetResizable(True)
        self._chip_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._chip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._chip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._chip_scroll.setFixedHeight(44)
        chip_container = QWidget()
        self._chip_layout = QHBoxLayout(chip_container)
        self._chip_layout.setContentsMargins(0, 0, 0, 0)
        self._chip_layout.setSpacing(6)
        self._chip_scroll.setWidget(chip_container)

        self._btn_add_preset = QPushButton("+")
        self._btn_add_preset.setProperty("secondary", True)
        self._btn_add_preset.setFixedWidth(36)
        self._btn_add_preset.setToolTip("Aktuelle Einstellungen als neue Vorlage speichern")

        preset_layout.addWidget(self._chip_scroll, stretch=1)
        preset_layout.addWidget(self._btn_add_preset)
        outer.addWidget(preset_box)

        # ---- Methode (nur wenn Cluster ODER Geschichtet freigeschaltet) ----
        # Sprint 22: Die Gruppe zeigt „Einfach" plus genau die freigeschalteten
        # erweiterten Methoden. Ist keine erweiterte Methode aktiv, fehlt der
        # Block ganz und die Methode ist fix SIMPLE.
        if self._show_methods:
            method_box = QGroupBox("Methode")
            method_layout = QHBoxLayout(method_box)
            self._method_group = QButtonGroup(self)
            self._radio_simple = QRadioButton("Einfach")
            self._radio_simple.setChecked(True)
            self._method_group.addButton(self._radio_simple)
            method_layout.addWidget(self._radio_simple)
            if self._show_cluster:
                self._radio_cluster = QRadioButton("Cluster")
                self._method_group.addButton(self._radio_cluster)
                method_layout.addWidget(self._radio_cluster)
            if self._show_stratified:
                self._radio_stratified = QRadioButton("Geschichtet")
                self._method_group.addButton(self._radio_stratified)
                method_layout.addWidget(self._radio_stratified)
            method_layout.addStretch(1)
            outer.addWidget(method_box)

        # ---- Felder ----
        form = QFormLayout()
        form.setSpacing(8)

        self._size_spin = QSpinBox()
        # Kein hartes Cap mehr im Widget – Hint-Label + Accept-Validierung
        # sind transparenter als stilles QSpinBox-Capping.
        self._size_spin.setRange(MIN_SAMPLE_SIZE, _SPINBOX_MAX)
        self._size_spin.setValue(min(DEFAULT_SAMPLE_SIZE, self._max_population))
        size_box = QWidget()
        size_layout = QVBoxLayout(size_box)
        size_layout.setContentsMargins(0, 0, 0, 0)
        size_layout.setSpacing(2)
        size_layout.addWidget(self._size_spin)
        self._lbl_size_hint = QLabel()
        self._lbl_size_hint.setStyleSheet("color: #7F7F7F; font-size: 11px;")
        size_layout.addWidget(self._lbl_size_hint)
        form.addRow("Stichprobengröße *", size_box)

        # Sprint 22: Filter, Cluster und Geschichtet werden je eigenem Toggle
        # einzeln gerendert – nicht mehr gebündelt unter einem Advanced-Flag.
        if self._show_filter:
            self._filter_field = QComboBox()
            self._filter_field.addItem(NO_FILTER_LABEL)
            self._filter_field.addItems(self._columns)
            self._filter_value = QComboBox()
            self._filter_value.setEnabled(False)
            filter_row = QHBoxLayout()
            filter_row.setSpacing(8)
            filter_row.addWidget(self._filter_field, stretch=1)
            filter_row.addWidget(self._filter_value, stretch=2)
            filter_widget = QWidget()
            filter_widget.setLayout(filter_row)
            form.addRow("Filter (optional)", filter_widget)

        if self._show_cluster:
            self._cluster_field = QComboBox()
            self._cluster_field.addItems(self._columns)
            self._cluster_field.setEnabled(False)
            form.addRow("Cluster-Feld", self._cluster_field)

        if self._show_stratified:
            self._stratum_field = QComboBox()
            self._stratum_field.addItems(self._columns)
            self._stratum_field.setEnabled(False)
            form.addRow("Schicht-Feld", self._stratum_field)

            stratify_box = QWidget()
            stratify_layout = QHBoxLayout(stratify_box)
            stratify_layout.setContentsMargins(0, 0, 0, 0)
            self._radio_proportional = QRadioButton("Proportional")
            self._radio_equal = QRadioButton("Gleich")
            self._radio_proportional.setChecked(True)
            self._stratify_group = QButtonGroup(self)
            self._stratify_group.addButton(self._radio_proportional)
            self._stratify_group.addButton(self._radio_equal)
            stratify_layout.addWidget(self._radio_proportional)
            stratify_layout.addWidget(self._radio_equal)
            stratify_layout.addStretch(1)
            self._radio_proportional.setEnabled(False)
            self._radio_equal.setEnabled(False)
            form.addRow("Schicht-Verteilung", stratify_box)

        outer.addLayout(form)

        # ---- Resample-Filter (in beiden Modi sichtbar) ----
        # Der Filter "Nur aus aktueller Auswahl ziehen" entspricht semantisch
        # dem from_sample_only-Flag – er bleibt auch im Simple-Mode erreichbar,
        # damit Resampling jederzeit möglich ist.
        self._resample_checkbox = QCheckBox("Nur aus aktueller Auswahl ziehen (Resampling)")
        if self._current_sample is None or not self._current_sample.selected_row_ids:
            self._resample_checkbox.setEnabled(False)
            self._resample_checkbox.setToolTip(
                "Es ist kein Sample aktiv – Resampling nicht möglich."
            )
        outer.addWidget(self._resample_checkbox)

        # ---- Seed-Zeile (in beiden Modi sichtbar) ----
        # Sprint 27: Der Seed ist hier schreibgeschützt – der Wert bleibt
        # sichtbar (Reproduzierbarkeits-Transparenz; ISAE-3402), geändert wird
        # er ausschließlich in den Einstellungen (Erweitert → Sampling-Seed).
        # Der frühere „🎲 Neuer Seed"-Würfel ist dorthin verschoben.
        seed_form = QFormLayout()
        seed_form.setSpacing(8)
        seed_row = QHBoxLayout()
        seed_row.setSpacing(8)
        self._seed_spin = QSpinBox()
        self._seed_spin.setRange(SEED_MIN, _safe_int_max())
        self._seed_spin.setValue(_generate_random_seed())
        self._seed_spin.setReadOnly(True)
        self._seed_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._seed_spin.setToolTip(
            "Schreibgeschützt – der Seed wird in den Einstellungen geändert "
            "(Erweitert → Sampling-Seed).\nGleicher Seed + gleiche Daten → "
            "bit-genau gleiche Stichprobe."
        )
        seed_hint = QLabel("in den Einstellungen änderbar")
        seed_hint.setStyleSheet("color: #7F7F7F; font-size: 11px;")
        seed_row.addWidget(self._seed_spin, stretch=1)
        seed_row.addWidget(seed_hint)
        seed_widget = QWidget()
        seed_widget.setLayout(seed_row)
        seed_form.addRow("Seed", seed_widget)
        outer.addLayout(seed_form)

        # Initiale Hint-Befüllung (Resample ist hier garantiert noch unchecked).
        self._update_size_hint()

        # ---- Validierungs-Label ----
        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: #C62828;")
        self._error_label.setWordWrap(True)
        outer.addWidget(self._error_label)

        # ---- Footer: Mode-Hint (links, nur Simple) + Buttons (rechts) ----
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        footer = QHBoxLayout()
        if not self._features.any_advanced:
            self._mode_hint = self._build_mode_hint()
            footer.addWidget(self._mode_hint)
        footer.addStretch(1)
        footer.addWidget(self._buttons)
        outer.addLayout(footer)

    def _build_mode_hint(self) -> QWidget:
        """Diskreter Hinweis unten links: 'Einfach-Modus' mit Erklär-Tooltip."""
        hint = QWidget()
        layout = QHBoxLayout(hint)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        icon_lbl = QLabel()
        style = self.style()
        if style is not None:
            icon = style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
            icon_lbl.setPixmap(icon.pixmap(14, 14))
        text_lbl = QLabel("Einfach-Modus")
        text_lbl.setStyleSheet("color: #7F7F7F; font-size: 11px;")

        tooltip = (
            "Im Einfach-Modus sind erweiterte Sampling-Methoden (Cluster, "
            "Geschichtet) und der Spaltenfilter ausgeblendet.\n\nZum "
            'Aktivieren: Menü „Ansicht" (einzelne Funktionen) oder '
            'Einstellungen → Erweitert → „Erweiterten Modus aktivieren".'
        )
        icon_lbl.setToolTip(tooltip)
        text_lbl.setToolTip(tooltip)

        layout.addWidget(icon_lbl)
        layout.addWidget(text_lbl)
        return hint

    def _wire_signals(self) -> None:
        self._size_spin.valueChanged.connect(self._validate)
        self._size_spin.valueChanged.connect(self._clear_chip_marker)
        self._resample_checkbox.toggled.connect(self._on_resample_toggled)
        self._btn_add_preset.clicked.connect(self._on_save_preset)
        if self._show_methods:
            for rb in self._method_radios():
                rb.toggled.connect(self._on_method_changed)
                rb.toggled.connect(self._clear_chip_marker)
        if self._show_filter:
            self._filter_field.currentTextChanged.connect(self._refresh_filter_values)
            self._filter_field.currentTextChanged.connect(self._clear_chip_marker)
            self._filter_value.currentTextChanged.connect(self._validate)
        if self._show_cluster:
            self._cluster_field.currentTextChanged.connect(self._validate)
        if self._show_stratified:
            self._stratum_field.currentTextChanged.connect(self._validate)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

    def _method_radios(self) -> list[QRadioButton]:
        """Die tatsächlich gebauten Methoden-Radios (abhängig von den Toggles)."""
        radios = [self._radio_simple]
        if self._show_cluster:
            radios.append(self._radio_cluster)
        if self._show_stratified:
            radios.append(self._radio_stratified)
        return radios

    # ---- Slots ---------------------------------------------------------

    def _on_method_changed(self) -> None:
        if not self._show_methods:
            return
        is_cluster = self._show_cluster and self._radio_cluster.isChecked()
        is_stratified = self._show_stratified and self._radio_stratified.isChecked()
        if self._show_cluster:
            self._cluster_field.setEnabled(is_cluster)
        if self._show_stratified:
            self._stratum_field.setEnabled(is_stratified)
            self._radio_proportional.setEnabled(is_stratified)
            self._radio_equal.setEnabled(is_stratified)
        self._validate()

    def _refresh_filter_values(self) -> None:
        field = self._filter_field.currentText()
        self._filter_value.blockSignals(True)
        self._filter_value.clear()
        if field == NO_FILTER_LABEL or not field or self._distinct_values_provider is None:
            self._filter_value.setEnabled(False)
        else:
            self._filter_value.setEnabled(True)
            for value in self._distinct_values_provider(field):
                self._filter_value.addItem(_display(value), userData=value)
        self._filter_value.blockSignals(False)
        self._validate()

    def _on_resample_toggled(self, _checked: bool) -> None:
        # Kein hartes Cap mehr – Hint-Label informiert, Accept-Validierung
        # fängt Überschreitung ab.
        self._update_size_hint()
        self._validate()

    def _effective_max_sample_size(self) -> int:
        """Aktuell zulässige Maximalgröße der Stichprobe.

        Bei aktivem Resampling-Filter ist das die Größe des bestehenden
        Samples, sonst die Datasetgröße.
        """
        if self._resample_checkbox.isChecked() and self._current_sample is not None:
            return max(len(self._current_sample.selected_row_ids), 1)
        return self._max_population

    def _update_size_hint(self) -> None:
        """Aktualisiert den Hint-Text unter dem Size-SpinBox."""
        max_n = self._effective_max_sample_size()
        self._lbl_size_hint.setText(f"max. {_format_int(max_n)} verfügbar")

    def accept(self) -> None:
        """QDialog-Accept mit zusätzlicher Größen-Validierung."""
        size = self._size_spin.value()
        max_n = self._effective_max_sample_size()
        if size < MIN_SAMPLE_SIZE:
            QMessageBox.warning(
                self,
                "Ungültige Stichprobengröße",
                f"Die Stichprobengröße muss mindestens {MIN_SAMPLE_SIZE} betragen.",
            )
            return
        if size > max_n:
            QMessageBox.warning(
                self,
                "Stichprobengröße zu groß",
                f"Die gewählte Größe ({_format_int(size)}) übersteigt die "
                f"verfügbare Datenmenge ({_format_int(max_n)}).\n\n"
                f"Bitte wähle einen Wert zwischen 1 und {_format_int(max_n)}.",
            )
            return
        other = self._validation_error()
        if other is not None:
            self._error_label.setText(other)
            return
        self._result = SamplingDialogResult(
            config=self._build_config(),
            from_sample_only=self._resample_checkbox.isChecked(),
        )
        super().accept()

    # ---- Validierung ---------------------------------------------------

    def _selected_method(self) -> SamplingMethod:
        # Nur freigeschaltete Methoden können überhaupt ausgewählt sein – die
        # zugehörigen Radios existieren sonst nicht.
        if self._show_cluster and self._radio_cluster.isChecked():
            return SamplingMethod.CLUSTER
        if self._show_stratified and self._radio_stratified.isChecked():
            return SamplingMethod.STRATIFIED
        return SamplingMethod.SIMPLE

    def _build_config(self) -> SampleConfig:
        # Einheitlicher Pfad für alle Sichtbarkeits-Kombinationen. Nicht
        # freigeschaltete Funktionen tragen ihre SampleConfig-Defaults bei
        # (filter_field/value=None, cluster/stratum_field=None,
        # stratify_mode=PROPORTIONAL) – damit ist die pure Simple-Stichprobe
        # bit-identisch zum bisherigen Simple-Mode-Pfad (ISAE-3402).
        method = self._selected_method()
        filter_field: str | None = None
        filter_value: Any = None
        if self._show_filter and self._filter_field.currentText() != NO_FILTER_LABEL:
            filter_field = self._filter_field.currentText()
            filter_value = self._filter_value.currentData(int(Qt.ItemDataRole.UserRole))
            if filter_value is None:
                filter_value = self._filter_value.currentText()
        stratify_mode = StratifyMode.PROPORTIONAL
        if self._show_stratified and self._radio_equal.isChecked():
            stratify_mode = StratifyMode.EQUAL
        return SampleConfig(
            method=method,
            size=self._size_spin.value(),
            seed=self._seed_spin.value(),
            cluster_field=self._cluster_field.currentText()
            if method == SamplingMethod.CLUSTER
            else None,
            stratum_field=self._stratum_field.currentText()
            if method == SamplingMethod.STRATIFIED
            else None,
            stratify_mode=stratify_mode,
            filter_field=filter_field,
            filter_value=filter_value,
        )

    def _validation_error(self) -> str | None:
        if not self._columns:
            return "Das Dataset hat keine Spalten – Sampling nicht möglich."
        method = self._selected_method()
        if method == SamplingMethod.CLUSTER and not self._cluster_field.currentText():
            return "Cluster-Sampling benötigt ein Cluster-Feld."
        if method == SamplingMethod.STRATIFIED and not self._stratum_field.currentText():
            return "Geschichtete Stichprobe benötigt ein Schicht-Feld."
        if (
            self._show_filter
            and self._filter_field.currentText() != NO_FILTER_LABEL
            and self._filter_value.count() == 0
        ):
            return "Das Filterfeld enthält keine Werte – Filter entfernen."
        return None

    def _validate(self) -> None:
        message = self._validation_error()
        self._error_label.setText(message or "")
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setEnabled(message is None)

    # ---- Preset-Anwendung (intern) -------------------------------------

    def _apply_preset_method(self, method: SamplingMethod) -> None:
        """Setzt das Methoden-Radio, sofern Methodenwahl + Radio sichtbar sind.

        Ist die zum Preset gehörende Methode nicht freigeschaltet, fällt der
        Dialog auf „Einfach" zurück (der Auditor sieht das vor dem Ziehen).
        """
        if not self._show_methods:
            return
        if method == SamplingMethod.CLUSTER and self._show_cluster:
            self._radio_cluster.setChecked(True)
        elif method == SamplingMethod.STRATIFIED and self._show_stratified:
            self._radio_stratified.setChecked(True)
        else:
            self._radio_simple.setChecked(True)

    def _apply_preset_filter(self, preset: SamplingPreset, skipped: list[str]) -> None:
        """Spielt die Filter-Definition ein – validiert gegen die Population.

        Übersprungen (und in `skipped` gemeldet) wird der Filter, wenn seine
        **Spalte** in der aktuellen Population fehlt ODER wenn der gespeicherte
        **Wert** dort nicht (mehr) vorkommt. So fällt der Dialog nie still auf
        einen anderen Wert zurück – „kein stiller Fehlschlag" (ISAE-3402).
        """
        if preset.filter_field is None:
            self._filter_field.setCurrentText(NO_FILTER_LABEL)
            return
        if preset.filter_field not in self._columns:
            # Spalte existiert in dieser Population nicht → Filter überspringen.
            self._filter_field.setCurrentText(NO_FILTER_LABEL)
            skipped.append(preset.filter_field)
            return
        # blockSignals: der currentTextChanged-Slot würde sonst zusätzlich
        # `_refresh_filter_values` feuern – wir rufen es kontrolliert einmal.
        self._filter_field.blockSignals(True)
        self._filter_field.setCurrentText(preset.filter_field)
        self._filter_field.blockSignals(False)
        self._refresh_filter_values()
        if not self._select_filter_value(preset.filter_value):
            # Spalte ja, aber der Wert kommt in dieser Population nicht vor.
            self._filter_field.setCurrentText(NO_FILTER_LABEL)
            skipped.append(preset.filter_field)

    def _select_filter_value(self, value: Any) -> bool:
        """Wählt den Filter-Wert per typ-erhaltendem userData-Match (Fallback Text).

        Liefert True bei Treffer, sonst False (Wert nicht in der Population).
        """
        role = int(Qt.ItemDataRole.UserRole)
        for i in range(self._filter_value.count()):
            if self._filter_value.itemData(i, role) == value:
                self._filter_value.setCurrentIndex(i)
                return True
        text_idx = self._filter_value.findText(_display(value))
        if text_idx >= 0:
            self._filter_value.setCurrentIndex(text_idx)
            return True
        return False

    # ---- Vorlagen-Chips + „+" (Sprint 28) ------------------------------

    def _reload_preset_chips(self) -> None:
        """Baut die Chip-Leiste neu aus dem Store (ein Chip je Vorlage).

        Wird beim Öffnen und nach jedem „+"-Speichern aufgerufen; so spiegeln
        die Chips auch Änderungen aus dem Verwaltungsfenster beim nächsten
        Öffnen wider.
        """
        while self._chip_layout.count():
            item = self._chip_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._preset_chips = []
        presets = self._preset_store.list()
        if not presets:
            hint = QLabel("Noch keine Vorlagen – mit „+“ speichern.")
            hint.setStyleSheet(f"color: {BDO_GREY}; font-size: 11px;")
            self._chip_layout.addWidget(hint)
        else:
            for preset in presets:
                chip = self._make_chip(preset.name)
                self._preset_chips.append(chip)
                self._chip_layout.addWidget(chip)
        self._chip_layout.addStretch(1)

    def _make_chip(self, name: str) -> QPushButton:
        """Erzeugt einen Chip-Button für eine Vorlage (Klick = anwenden)."""
        chip = QPushButton(name)
        chip.setProperty("secondary", True)
        chip.setCheckable(True)
        chip.setToolTip(f"Vorlage „{name}“ anwenden (setzt nur Parameter, zieht nicht)")
        chip.setStyleSheet(
            f"QPushButton:checked {{ border: 2px solid {BDO_RED}; font-weight: bold; }}"
        )
        chip.clicked.connect(lambda _checked=False, n=name: self._on_chip_clicked(n))
        return chip

    def _on_chip_clicked(self, name: str) -> None:
        """Wendet die Vorlage an (`apply_preset`) und meldet übersprungene Filter."""
        preset = self._preset_store.get(name)
        if preset is None:
            # Vorlage wurde zwischenzeitlich entfernt (Verwaltungsfenster).
            self._reload_preset_chips()
            return
        self._applying_preset = True
        try:
            result = self.apply_preset(preset)
        finally:
            self._applying_preset = False
        self._mark_chip_applied(name)
        if result.skipped_filters:
            cols = ", ".join(f"„{c}“" for c in result.skipped_filters)
            QMessageBox.information(
                self,
                "Vorlage angewendet",
                f"Die Vorlage „{name}“ wurde angewendet.\n\n"
                f"Übersprungen, weil Spalte oder Wert in den aktuellen Daten "
                f"nicht vorhanden ist: {cols}.",
            )

    def _mark_chip_applied(self, name: str) -> None:
        """Markiert den zuletzt angewandten Chip (visuelle Rückmeldung)."""
        for chip in self._preset_chips:
            chip.setChecked(chip.text() == name)

    def _clear_chip_marker(self) -> None:
        """Hebt die Chip-Markierung auf, sobald der Nutzer manuell ändert.

        Während `apply_preset` selbst die Widgets setzt, bleibt die Markierung
        erhalten (`_applying_preset`-Guard) – sie spiegelt dann die unverändert
        angewandte Vorlage.
        """
        if self._applying_preset:
            return
        for chip in self._preset_chips:
            chip.setChecked(False)

    def _on_save_preset(self) -> None:
        """„+": Aktuelle Einstellungen als neue Vorlage speichern."""
        name, ok = QInputDialog.getText(self, "Vorlage speichern", "Name der Vorlage:")
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if self._preset_store.exists(name) and not self._confirm_overwrite(name):
            return
        self._preset_store.save(self.current_settings_as_preset(name))
        self._reload_preset_chips()
        self._mark_chip_applied(name)

    def _confirm_overwrite(self, name: str) -> bool:
        answer = QMessageBox.question(
            self,
            "Vorlage überschreiben",
            f"Eine Vorlage „{name}“ existiert bereits. Überschreiben?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _display(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _generate_random_seed() -> int:
    """Zufalls-Seed im erlaubten QSpinBox-Bereich (immer > 0)."""
    return secrets.randbelow(_safe_int_max()) + 1


def _safe_int_max() -> int:
    # QSpinBox unterstützt nur 32-Bit-signed → wir kappen SEED_MAX entsprechend.
    return min(SEED_MAX, _SPINBOX_MAX)


def _format_int(value: int) -> str:
    """Tausenderpunkte für deutsche Locale (12345 → '12.345')."""
    return f"{value:,}".replace(",", ".")
