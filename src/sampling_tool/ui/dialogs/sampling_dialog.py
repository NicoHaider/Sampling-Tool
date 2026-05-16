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
from collections.abc import Sequence
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
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.config import (
    DEFAULT_SAMPLE_SIZE,
    MIN_SAMPLE_SIZE,
    SEED_MAX,
    SEED_MIN,
)
from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    SampleConfig,
    SampleResult,
    SamplingMethod,
    StratifyMode,
)

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


class SamplingDialog(QDialog):
    """Dialog für die Konfiguration einer Stichprobenziehung."""

    def __init__(
        self,
        dataset: Dataset,
        rows: Sequence[DatasetRow],
        current_sample: SampleResult | None = None,
        parent: QWidget | None = None,
        *,
        advanced_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Neue Stichprobe")
        self.setModal(True)
        self.setMinimumWidth(520)

        self._dataset = dataset
        self._rows: tuple[DatasetRow, ...] = tuple(rows)
        self._current_sample = current_sample
        self._result: SamplingDialogResult | None = None
        self._columns = list(dataset.columns)
        self._max_population = max(len(self._rows), 1)
        self._advanced_mode = advanced_mode

        self._build_ui()
        self._wire_signals()
        if self._advanced_mode:
            self._refresh_filter_values()
            self._on_method_changed()
        self._validate()

    # ---- Public API -----------------------------------------------------

    def get_result(self) -> SamplingDialogResult | None:
        """Liefert das Ergebnis – `None`, wenn der Dialog abgebrochen wurde."""
        return self._result

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

        # ---- Methode (nur Advanced) ----
        if self._advanced_mode:
            method_box = QGroupBox("Methode")
            method_layout = QHBoxLayout(method_box)
            self._radio_simple = QRadioButton("Einfach")
            self._radio_cluster = QRadioButton("Cluster")
            self._radio_stratified = QRadioButton("Geschichtet")
            self._radio_simple.setChecked(True)
            self._method_group = QButtonGroup(self)
            for rb in (self._radio_simple, self._radio_cluster, self._radio_stratified):
                self._method_group.addButton(rb)
                method_layout.addWidget(rb)
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

        if self._advanced_mode:
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

            self._cluster_field = QComboBox()
            self._cluster_field.addItems(self._columns)
            self._cluster_field.setEnabled(False)
            form.addRow("Cluster-Feld", self._cluster_field)

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
        # Auch im Simple-Mode soll der User den Seed sehen und ändern können
        # (Reproduzierbarkeits-Transparenz; ISAE-3402).
        seed_form = QFormLayout()
        seed_form.setSpacing(8)
        seed_row = QHBoxLayout()
        seed_row.setSpacing(8)
        self._seed_spin = QSpinBox()
        self._seed_spin.setRange(SEED_MIN, _safe_int_max())
        self._seed_spin.setValue(_generate_random_seed())
        self._seed_spin.setToolTip("Gleicher Seed + gleiche Daten → bit-genau gleiche Stichprobe.")
        self._seed_dice = QPushButton("🎲 Neuer Seed")
        self._seed_dice.setProperty("secondary", True)
        self._seed_dice.setToolTip("Neuen zufälligen Seed generieren")
        seed_row.addWidget(self._seed_spin, stretch=1)
        seed_row.addWidget(self._seed_dice)
        seed_widget = QWidget()
        seed_widget.setLayout(seed_row)
        seed_form.addRow("Seed *", seed_widget)
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
        if not self._advanced_mode:
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
            "Stratifiziert) und Detail-Optionen (Resample, manueller Seed) "
            "ausgeblendet.\n\nZum Aktivieren: Einstellungen → Erweitert → "
            '„Erweiterten Modus aktivieren".'
        )
        icon_lbl.setToolTip(tooltip)
        text_lbl.setToolTip(tooltip)

        layout.addWidget(icon_lbl)
        layout.addWidget(text_lbl)
        return hint

    def _wire_signals(self) -> None:
        self._size_spin.valueChanged.connect(self._validate)
        self._resample_checkbox.toggled.connect(self._on_resample_toggled)
        self._seed_dice.clicked.connect(self._reroll_seed)
        if self._advanced_mode:
            for rb in (self._radio_simple, self._radio_cluster, self._radio_stratified):
                rb.toggled.connect(self._on_method_changed)
            self._filter_field.currentTextChanged.connect(self._refresh_filter_values)
            self._filter_value.currentTextChanged.connect(self._validate)
            self._cluster_field.currentTextChanged.connect(self._validate)
            self._stratum_field.currentTextChanged.connect(self._validate)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

    # ---- Slots ---------------------------------------------------------

    def _on_method_changed(self) -> None:
        if not self._advanced_mode:
            return
        is_cluster = self._radio_cluster.isChecked()
        is_stratified = self._radio_stratified.isChecked()
        self._cluster_field.setEnabled(is_cluster)
        self._stratum_field.setEnabled(is_stratified)
        self._radio_proportional.setEnabled(is_stratified)
        self._radio_equal.setEnabled(is_stratified)
        self._validate()

    def _refresh_filter_values(self) -> None:
        field = self._filter_field.currentText()
        self._filter_value.blockSignals(True)
        self._filter_value.clear()
        if field == NO_FILTER_LABEL or not field:
            self._filter_value.setEnabled(False)
        else:
            self._filter_value.setEnabled(True)
            for value in _distinct_values(self._rows, field):
                self._filter_value.addItem(_display(value), userData=value)
        self._filter_value.blockSignals(False)
        self._validate()

    def _on_resample_toggled(self, _checked: bool) -> None:
        # Kein hartes Cap mehr – Hint-Label informiert, Accept-Validierung
        # fängt Überschreitung ab.
        self._update_size_hint()
        self._validate()

    def _reroll_seed(self) -> None:
        self._seed_spin.setValue(_generate_random_seed())

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
        if not self._advanced_mode:
            return SamplingMethod.SIMPLE
        if self._radio_cluster.isChecked():
            return SamplingMethod.CLUSTER
        if self._radio_stratified.isChecked():
            return SamplingMethod.STRATIFIED
        return SamplingMethod.SIMPLE

    def _build_config(self) -> SampleConfig:
        method = self._selected_method()
        if not self._advanced_mode:
            # Simple-Mode: Methode fix SIMPLE; Seed kommt aus dem
            # (vorbefüllten oder vom User editierten) SpinBox – ISAE-3402
            # bleibt reproduzierbar, weil der Seed im SampleConfig persistiert.
            return SampleConfig(
                method=SamplingMethod.SIMPLE,
                size=self._size_spin.value(),
                seed=self._seed_spin.value(),
            )

        filter_field = (
            None
            if self._filter_field.currentText() == NO_FILTER_LABEL
            else self._filter_field.currentText()
        )
        filter_value: Any = None
        if filter_field is not None:
            filter_value = self._filter_value.currentData(int(Qt.ItemDataRole.UserRole))
            if filter_value is None:
                filter_value = self._filter_value.currentText()
        stratify_mode = (
            StratifyMode.PROPORTIONAL
            if self._radio_proportional.isChecked()
            else StratifyMode.EQUAL
        )
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
        if not self._advanced_mode:
            return None
        method = self._selected_method()
        if method == SamplingMethod.CLUSTER and not self._cluster_field.currentText():
            return "Cluster-Sampling benötigt ein Cluster-Feld."
        if method == SamplingMethod.STRATIFIED and not self._stratum_field.currentText():
            return "Geschichtete Stichprobe benötigt ein Schicht-Feld."
        if self._filter_field.currentText() != NO_FILTER_LABEL and self._filter_value.count() == 0:
            return "Das Filterfeld enthält keine Werte – Filter entfernen."
        return None

    def _validate(self) -> None:
        message = self._validation_error()
        self._error_label.setText(message or "")
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setEnabled(message is None)


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _distinct_values(rows: Sequence[DatasetRow], field: str) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for row in rows:
        value = row.values.get(field)
        if value is None:
            continue
        key = repr(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    result.sort(key=lambda v: str(v))
    return result


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
