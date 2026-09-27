"""Sampling-Dialog – Konfiguration einer neuen Stichprobenziehung.

Entspricht der alten VBA-`SamplingUserForm`. Liefert nach `accept()` ein
`SamplingDialogResult` mit dem fertigen `SampleConfig` und einem Flag, ob
nur aus der aktuell hervorgehobenen Sample-Selektion gezogen werden soll
(Resampling).

Die Persistenz-Schicht kennt das Resampling-Flag nicht – es ist eine reine
UI-Anweisung an den Controller, das Dataset vor der Ziehung zu filtern.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.config import (
    BDO_GREY,
    DEFAULT_SAMPLE_SIZE,
    METHOD_LABELS,
    MIN_SAMPLE_SIZE,
    SEED_MAX,
    SEED_MIN,
    WARNING_COLOR,
)
from sampling_tool.core.models import (
    Dataset,
    FilterOperator,
    SampleConfig,
    SampleResult,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.core.presets import SamplingPreset
from sampling_tool.ui._dialog_buttons import mark_secondary_buttons
from sampling_tool.ui._dialog_sizing import (
    clamp_dialog_height_to_screen,
    clamp_dialog_width_to_screen,
    content_min_width,
)
from sampling_tool.ui._scaling import scaled_px
from sampling_tool.ui.preset_store import PresetStore
from sampling_tool.ui.settings_store import SamplingFeatures

logger = logging.getLogger(__name__)

NO_FILTER_LABEL: str = "(kein Filter)"

# Sprint 85 / B: Cluster- und Schicht-Feld starten ohne Auswahl. Vorher stand
# dort die erste Spalte (oft eine ID) – damit war jede Zeile ein eigener Cluster.
COLUMN_PLACEHOLDER: Final[str] = "Spalte wählen …"

# Erster, neutraler Dropdown-Eintrag (keine Vorlage). Steht auch dann zur
# Verfügung, wenn keine Vorlagen gespeichert sind.
PRESET_PLACEHOLDER: str = "(Vorlage wählen…)"

# QSpinBox-Maximum: int32-signed-Limit. Die Größe wird dadurch faktisch
# nicht mehr durch das Widget gecappt – stattdessen schlägt Validierung
# beim Accept zu (siehe `accept()`).
_SPINBOX_MAX: int = 2_147_483_647

# Sprint 69 / Bug 3: Rand des äußeren Layouts – eigene Konstante statt
# zweimal hartcodierter `20`, weil die Mindestbreiten-Berechnung
# (`content_min_width`) denselben Wert braucht.
_OUTER_MARGIN: Final[int] = 20
# Sprint 69 / Bug 3: kleiner Sicherheitspuffer (Details im Docstring von
# `content_min_width` in `_dialog_sizing.py` – Wechselwirkung zwischen
# horizontalem und vertikalem Scrollbalken).
_WIDTH_SAFETY_BUFFER: Final[int] = 8
#: LOGISCHE Kantenlänge des Mode-Hint-Icons. Bleibt logisch: die Device-Pixel
#: kommen über das Ratio dazu, nicht über diese Zahl (Sprint 78 / §2.5).
_HINT_ICON_PX: Final[int] = 14

# Sprint 82 / C: Hinweis neben dem Seed. Höchstens ~50 Zeichen – ein längerer
# Text vergrößert die Mindestbreite des Dialogs. Die Langform steht im Tooltip.
_SEED_HINT: Final[str] = "je Datensatz fest · in den Einstellungen änderbar"
_SEED_TOOLTIP: Final[str] = (
    "Schreibgeschützt. Der Seed wird je Datensatz bei der ersten Ziehung gewürfelt "
    "und danach beibehalten, damit Ergebnisse reproduzierbar bleiben.\n"
    "Für eine unabhängige neue Stichprobe in den Einstellungen (Erweitert → "
    "Sampling-Seed) einen festen Seed würfeln – er gilt dann für alle Datensätze.\n"
    "Gleicher Seed + gleiche Daten → bit-genau gleiche Stichprobe."
)

# Sprint 36: Vergleichsoperatoren des Spaltenfilters. Der sichtbare Label-Text
# steht im Combo, das `FilterOperator`-Member als `userData`.
_FILTER_OPERATOR_ITEMS: tuple[tuple[str, FilterOperator], ...] = (
    ("= (gleich)", FilterOperator.EQ),
    ("≠ (ungleich)", FilterOperator.NE),
    ("> (größer als)", FilterOperator.GT),
    ("≥ (größer/gleich)", FilterOperator.GTE),
    ("< (kleiner als)", FilterOperator.LT),
    ("≤ (kleiner/gleich)", FilterOperator.LTE),
)

# Ordering-Operatoren nutzen ein freies Schwellenwert-Textfeld statt des
# distinct-Werte-Dropdowns (EQ/NE).
_ORDERING_OPERATORS: frozenset[FilterOperator] = frozenset(
    {FilterOperator.GT, FilterOperator.GTE, FilterOperator.LT, FilterOperator.LTE}
)


@dataclass(frozen=True, slots=True)
class SamplingDialogResult:
    """Ergebnis des Sampling-Dialogs."""

    config: SampleConfig
    from_sample_only: bool = False
    # Sprint 36 / WP-B: reine UI-Anweisung wie `from_sample_only` (nicht in
    # SampleConfig/Persistenz). True → Nachstichprobe: aus der Basispopulation
    # ziehen, aber bereits gezogene Datensätze garantiert ausschließen. Der
    # Controller setzt den Ausschluss um.
    exclude_sample_ids: bool = False


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
        filter_match_count_provider: Callable[[str, FilterOperator, Any, bool], int] | None = None,
        ui_scale_factor: float = 1.0,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Neue Stichprobe")
        self.setModal(True)

        self._dataset = dataset
        self._factor = ui_scale_factor
        # Sprint 19 / P-005: kein Row-Materialize mehr – der Controller
        # injiziert einen distinct-Werte-Provider (SQL-basiert). None, wenn das
        # Filter-Feld nicht freigeschaltet ist.
        self._distinct_values_provider = distinct_values_provider
        # Sprint 34 / WP5: der Provider ist ein Full-Table-Scan pro Aufruf und
        # `currentTextChanged` feuert auch bei Pfeiltasten-Navigation pro
        # Tastendruck. Der Dialog ist modal – das Dataset ist während seiner
        # Lebensdauer unveränderlich, also wird jede Spalte genau einmal
        # geladen (Memo pro Dialog-Instanz, keine Invalidierung nötig).
        self._distinct_cache: dict[str, tuple[Any, ...]] = {}
        # Sprint 36: liefert die Trefferzahl eines aktiven Filters (Feld,
        # Operator, Wert, restrict-auf-aktuelle-Auswahl) für den Size-Hint.
        # Ein Aufruf ist ein Full-Table-Scan; deshalb wird das Ergebnis pro
        # (Feld, Operator, repr(Wert), restrict) memoisiert (Dataset ist modal
        # unveränderlich, keine Invalidierung nötig – wie `_distinct_cache`).
        self._filter_match_count_provider = filter_match_count_provider
        self._match_count_cache: dict[tuple[str, FilterOperator, str, bool], int] = {}
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
        # Sprint 32: Vorlagen erscheinen als Dropdown (ein Eintrag je Vorlage,
        # plus ein neutraler Platzhalter). Die zuletzt angewandte Vorlage bleibt
        # im Dropdown ausgewählt; eine manuelle Änderung setzt das Dropdown
        # wieder auf den Platzhalter. `_applying_preset` schützt die Auswahl
        # während des Anwendens (die Widget-Updates dürfen sie nicht löschen).
        self._applying_preset = False
        # Sprint 85 / B: vom Controller nachgereicht (`set_validators`). Der
        # Gruppen-Zähler liefert die Anzahl Cluster/Schichten einer Spalte mit
        # derselben Schlüssel-Semantik wie der Sampler; die Probeziehung prüft
        # beim OK exakt auf dem Zieh-Pfad und hält den Dialog bei einem Fehler
        # offen. Beide optional – ohne sie prüft der Dialog nur, was er selbst weiß.
        self._group_count_provider: Callable[[str], int] | None = None
        self._group_count_cache: dict[str, int] = {}
        self._draw_check: Callable[[SamplingDialogResult], str | None] | None = None

        self._build_ui()
        self._wire_signals()
        self._reload_preset_combo()
        if self._show_filter:
            self._refresh_filter_values()
        if self._show_methods:
            self._on_method_changed()
        self._validate()
        clamp_dialog_width_to_screen(
            self,
            content_min_width(self._content, self.style(), _OUTER_MARGIN, _WIDTH_SAFETY_BUFFER),
        )
        clamp_dialog_height_to_screen(self)

    # ---- Public API -----------------------------------------------------

    def get_result(self) -> SamplingDialogResult | None:
        """Liefert das Ergebnis – `None`, wenn der Dialog abgebrochen wurde."""
        return self._result

    def set_initial_seed(self, seed: int) -> None:
        """Übernimmt einen vorgemerkten Seed in das (schreibgeschützte) Seed-Feld.

        Beim Öffnen würfelt der Dialog standardmäßig einen frischen
        Zufalls-Seed. Der Controller reicht hier den aufgelösten Seed durch
        (fester Seed aus den Einstellungen, sonst – Sprint 82 / C – der Seed
        der jüngsten Stichprobe dieses Datensatzes aus der Projektdatei), damit
        eine erneute Ziehung (auch nach „Sampling zurücksetzen" oder erneutem
        Öffnen des Projekts) denselben Seed verwendet und die Stichprobe
        bit-genau reproduziert (ISAE-3402). Das Feld bleibt schreibgeschützt;
        geändert wird der Seed nur in den Einstellungen.
        """
        self._seed_spin.setValue(seed)

    def set_validators(
        self,
        *,
        group_count_provider: Callable[[str], int] | None = None,
        draw_check: Callable[[SamplingDialogResult], str | None] | None = None,
    ) -> None:
        """Hängt die Prüfungen an, die Daten brauchen (Sprint 85 / B).

        `group_count_provider(spalte)` → Anzahl verschiedener Werte, gezählt wie
        der Sampler Cluster und Schichten bildet (leere Zellen bilden eine
        eigene Gruppe). `draw_check(ergebnis)` zieht probeweise und liefert eine
        Fehlermeldung oder `None`; der Controller verwendet eine gelungene
        Probeziehung weiter, gezogen wird also nicht doppelt.
        """
        self._group_count_provider = group_count_provider
        self._group_count_cache.clear()
        self._draw_check = draw_check
        self._update_size_hint()

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
        if self._show_cluster and preset.cluster_field:
            _select_column(self._cluster_field, preset.cluster_field)
        if self._show_stratified:
            if preset.stratum_field:
                _select_column(self._stratum_field, preset.stratum_field)
            if preset.stratify_mode == StratifyMode.EQUAL:
                self._radio_equal.setChecked(True)
            else:
                self._radio_proportional.setChecked(True)
        if self._show_filter:
            self._apply_preset_filter(preset, skipped_filters)
        if self._show_methods:
            self._on_method_changed()
        self._validate()
        # Nach einem gefilterten Preset muss der „max. N verfügbar"-Hinweis den
        # neuen Filter widerspiegeln (idempotent + memoisiert).
        self._update_size_hint()
        return AppliedPresetResult(skipped_filters=tuple(skipped_filters))

    # ---- UI-Aufbau -----------------------------------------------------

    def _build_ui(self) -> None:
        content = QWidget()
        self._content = content
        outer = QVBoxLayout(content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        intro = QLabel(
            "Konfiguriere die Stichprobenziehung. Bei gleichem Seed und gleichen "
            "Daten ist das Ergebnis bit-genau reproduzierbar (ISAE-3402)."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {BDO_GREY};")
        outer.addWidget(intro)

        # ---- Vorlagen (Sprint 32) ----
        # Gespeicherte Vorlagen erscheinen als kompaktes Dropdown – die Auswahl
        # wendet die Vorlage an (`apply_preset`: setzt nur Parameter, zieht
        # NICHT). Bei vielen Vorlagen scrollt das Dropdown nativ. Anlegen/
        # Speichern/Bearbeiten/Umbenennen/Löschen leben ausschließlich im eigenen
        # Verwaltungsfenster (Menü „Stichprobe → Vorlagen verwalten…"). Die
        # Sprint-23-Mechanik (PresetStore/apply_preset) wird unverändert
        # wiederverwendet – keine neue Persistenz.
        preset_box = QGroupBox("Vorlagen")
        preset_layout = QHBoxLayout(preset_box)
        preset_layout.setSpacing(8)

        self._preset_combo = QComboBox()
        self._preset_combo.setToolTip(
            "Gespeicherte Vorlage anwenden (setzt nur Parameter, zieht nicht).\n"
            "Vorlagen anlegen/bearbeiten: Menü „Stichprobe → Vorlagen verwalten…“."
        )
        preset_layout.addWidget(self._preset_combo, stretch=1)
        outer.addWidget(preset_box)

        # ---- Methode (nur wenn Cluster ODER Geschichtet freigeschaltet) ----
        # Sprint 22: Die Gruppe zeigt „Einfach" plus genau die freigeschalteten
        # erweiterten Methoden. Ist keine erweiterte Methode aktiv, fehlt der
        # Block ganz und die Methode ist fix SIMPLE.
        if self._show_methods:
            method_box = QGroupBox("Methode")
            method_layout = QHBoxLayout(method_box)
            self._method_group = QButtonGroup(self)
            self._radio_simple = QRadioButton(METHOD_LABELS[SamplingMethod.SIMPLE.value])
            self._radio_simple.setChecked(True)
            self._method_group.addButton(self._radio_simple)
            method_layout.addWidget(self._radio_simple)
            if self._show_cluster:
                self._radio_cluster = QRadioButton(METHOD_LABELS[SamplingMethod.CLUSTER.value])
                self._method_group.addButton(self._radio_cluster)
                method_layout.addWidget(self._radio_cluster)
            if self._show_stratified:
                self._radio_stratified = QRadioButton(
                    METHOD_LABELS[SamplingMethod.STRATIFIED.value]
                )
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
        self._lbl_size_hint.setStyleSheet(
            f"color: {BDO_GREY}; font-size: {scaled_px(11, self._factor)}px;"
        )
        size_layout.addWidget(self._lbl_size_hint)
        self._inline_errors: dict[str, QLabel] = {}
        size_layout.addWidget(self._new_inline_error("size"))
        form.addRow("Stichprobengröße *", size_box)

        # Sprint 22: Filter, Cluster und Geschichtet werden je eigenem Toggle
        # einzeln gerendert – nicht mehr gebündelt unter einem Advanced-Flag.
        if self._show_filter:
            self._filter_field = QComboBox()
            self._filter_field.addItem(NO_FILTER_LABEL)
            self._filter_field.addItems(self._columns)
            self._filter_operator = QComboBox()
            for label, operator in _FILTER_OPERATOR_ITEMS:
                self._filter_operator.addItem(label, userData=operator)
            # Sprint 36: der Wert-Eingabe-Bereich schaltet je Operator um –
            # distinct-Dropdown (EQ/NE) vs. freies Schwellenwert-Feld
            # (>, ≥, <, ≤). Ein QStackedWidget hält beide Seiten; Seite 0 ist
            # das Dropdown (Default EQ), Seite 1 das Textfeld.
            self._filter_value = QComboBox()
            self._filter_value.setEnabled(False)
            self._filter_value_text = QLineEdit()
            self._filter_value_text.setPlaceholderText("Schwellenwert…")
            self._filter_value_stack = QStackedWidget()
            self._filter_value_stack.addWidget(self._filter_value)
            self._filter_value_stack.addWidget(self._filter_value_text)
            filter_row = QHBoxLayout()
            filter_row.setSpacing(8)
            filter_row.addWidget(self._filter_field, stretch=2)
            filter_row.addWidget(self._filter_operator, stretch=0)
            filter_row.addWidget(self._filter_value_stack, stretch=3)
            filter_widget = QWidget()
            filter_column = QVBoxLayout(filter_widget)
            filter_column.setContentsMargins(0, 0, 0, 0)
            filter_column.setSpacing(2)
            filter_column.addLayout(filter_row)
            filter_column.addWidget(self._new_inline_error("filter"))
            form.addRow("Filter (optional)", filter_widget)

        # Sprint 85 / B: Methodenfelder erscheinen nur bei ihrer Methode
        # (`_on_method_changed` schaltet die Formularzeilen um).
        if self._show_cluster:
            self._cluster_field = self._column_combo()
            self._cluster_row = self._field_with_inline_error(self._cluster_field, "cluster")
            form.addRow("Cluster-Feld", self._cluster_row)

        if self._show_stratified:
            self._stratum_field = self._column_combo()
            self._stratum_row = self._field_with_inline_error(self._stratum_field, "stratum")
            form.addRow("Schicht-Feld", self._stratum_row)

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
            self._stratify_row = stratify_box
            form.addRow("Schicht-Verteilung", stratify_box)

        self._form = form
        outer.addLayout(form)

        # ---- Resample-Filter (in beiden Modi sichtbar) ----
        # Der Filter "Nur aus aktueller Auswahl ziehen" entspricht semantisch
        # dem from_sample_only-Flag – er bleibt auch im Simple-Mode erreichbar,
        # damit Resampling jederzeit möglich ist.
        self._resample_checkbox = QCheckBox("Nur aus aktueller Auswahl ziehen (einschränken)")
        if self._current_sample is None or not self._current_sample.selected_row_ids:
            self._resample_checkbox.setEnabled(False)
            self._resample_checkbox.setToolTip(
                "Es ist kein Sample aktiv – Einschränken auf die Auswahl nicht möglich."
            )
        outer.addWidget(self._resample_checkbox)

        # ---- Nachstichprobe / Ergänzen (Sprint 36 / WP-B) ----
        # Gegenstück zum Resample-Filter: zieht aus der Basispopulation, schließt
        # aber garantiert die bereits gezogenen Datensätze aus (keine Duplikate).
        # Reine UI-Anweisung; der Controller setzt den Ausschluss um.
        self._supplement_checkbox = QCheckBox(
            "Ergänzen – bereits gezogene Datensätze ausschließen (Nachstichprobe)"
        )
        self._configure_supplement_enablement()
        outer.addWidget(self._supplement_checkbox)

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
        self._seed_spin.setToolTip(_SEED_TOOLTIP)
        self._seed_hint = QLabel(_SEED_HINT)
        self._seed_hint.setStyleSheet(
            f"color: {BDO_GREY}; font-size: {scaled_px(11, self._factor)}px;"
        )
        seed_row.addWidget(self._seed_spin, stretch=1)
        seed_row.addWidget(self._seed_hint)
        seed_widget = QWidget()
        seed_widget.setLayout(seed_row)
        seed_form.addRow("Seed", seed_widget)
        outer.addLayout(seed_form)

        # Initiale Hint-Befüllung (Resample ist hier garantiert noch unchecked).
        self._update_size_hint()

        # ---- Validierungs-Label ----
        self._error_label = QLabel("")
        self._error_label.setStyleSheet(f"color: {WARNING_COLOR};")
        self._error_label.setWordWrap(True)
        outer.addWidget(self._error_label)

        # ---- Footer: Mode-Hint (links, nur Simple) + Buttons (rechts) ----
        # Sprint 67 / Teil A: Buttons liegen BEWUSST außerhalb der
        # ScrollArea (siehe unten) – OK/Abbrechen müssen immer erreichbar
        # bleiben, auch wenn der Inhalt auf kleinen Screens scrollt.
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        mark_secondary_buttons(self._buttons)
        footer = QHBoxLayout()
        if not self._features.any_advanced:
            self._mode_hint = self._build_mode_hint()
            footer.addWidget(self._mode_hint)
        footer.addStretch(1)
        footer.addWidget(self._buttons)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)

        dialog_layout = QVBoxLayout(self)
        dialog_layout.setContentsMargins(_OUTER_MARGIN, _OUTER_MARGIN, _OUTER_MARGIN, _OUTER_MARGIN)
        dialog_layout.setSpacing(12)
        dialog_layout.addWidget(scroll, stretch=1)
        dialog_layout.addLayout(footer)

    def _column_combo(self) -> QComboBox:
        """Spaltenauswahl mit neutralem Platzhalter; die Spalte steht als `userData`."""
        combo = QComboBox()
        combo.addItem(COLUMN_PLACEHOLDER)
        for column in self._columns:
            combo.addItem(column, userData=column)
        return combo

    def _new_inline_error(self, field: str) -> QLabel:
        """Rote Meldungszeile unter einem Feld; unsichtbar, solange sie leer ist."""
        label = QLabel("")
        label.setStyleSheet(f"color: {WARNING_COLOR}; font-size: {scaled_px(11, self._factor)}px;")
        label.setWordWrap(True)
        label.setVisible(False)
        self._inline_errors[field] = label
        return label

    def _field_with_inline_error(self, field_widget: QWidget, field: str) -> QWidget:
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(field_widget)
        layout.addWidget(self._new_inline_error(field))
        return row

    def _icon_ratio(self) -> float:
        """Device-Pixel-Ratio des Bildschirms, auf dem dieser Dialog liegt.

        Die einzige Stelle im Mode-Hint-Pfad, die einen echten Bildschirmwert
        liest – analog zu `DashboardView._chart_ratio` (Sprint 78 / §2.1). Unter
        `QT_QPA_PLATFORM=offscreen` ist der Wert immer 1.0, deshalb ist er ein
        Parameter und keine Abfrage im Rechenweg.
        """
        return float(self.devicePixelRatioF())

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
            # Sprint 78 / §2.5, hier über die Qt-6-Überladung: die LOGISCHE Größe
            # bleibt `_HINT_ICON_PX`, das Ratio sagt Qt, dass die zusätzlichen
            # Pixel Auflösung sind und keine Größe. Ohne das skaliert Qt ein
            # 14-px-Raster hoch, obwohl das Icon eine 32-px-Quelle mitbringt.
            icon_lbl.setPixmap(icon.pixmap(QSize(_HINT_ICON_PX, _HINT_ICON_PX), self._icon_ratio()))
        text_lbl = QLabel("Einfach-Modus")
        text_lbl.setStyleSheet(f"color: {BDO_GREY}; font-size: {scaled_px(11, self._factor)}px;")

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

    def _configure_supplement_enablement(self) -> None:
        """Sperrt die Nachstichprobe-Checkbox ohne Sample bzw. wenn alles gezogen ist."""
        if self._current_sample is None or not self._current_sample.selected_row_ids:
            self._supplement_checkbox.setEnabled(False)
            self._supplement_checkbox.setToolTip(
                "Es ist kein Sample aktiv – Nachstichprobe nicht möglich."
            )
        elif self._dataset.row_count <= len(self._current_sample.selected_row_ids):
            # Ganze Population ist bereits gezogen → nichts mehr zu ergänzen.
            self._supplement_checkbox.setEnabled(False)
            self._supplement_checkbox.setToolTip("Es sind keine ungezogenen Datensätze mehr übrig.")

    def _wire_signals(self) -> None:
        self._size_spin.valueChanged.connect(self._validate)
        self._size_spin.valueChanged.connect(self._reset_combo_selection)
        self._resample_checkbox.toggled.connect(self._on_resample_toggled)
        self._supplement_checkbox.toggled.connect(self._on_supplement_toggled)
        # `activated` feuert nur bei echter Nutzer-Auswahl (nicht beim
        # programmatischen Zurücksetzen auf den Platzhalter) – so wendet ein
        # `setCurrentIndex(0)` keine Vorlage versehentlich an.
        self._preset_combo.activated.connect(self._on_preset_selected)
        if self._show_methods:
            for rb in self._method_radios():
                rb.toggled.connect(self._on_method_changed)
                rb.toggled.connect(self._reset_combo_selection)
        if self._show_filter:
            self._filter_field.currentTextChanged.connect(self._refresh_filter_values)
            self._filter_field.currentTextChanged.connect(self._reset_combo_selection)
            self._filter_field.currentTextChanged.connect(self._update_size_hint)
            self._filter_value.currentTextChanged.connect(self._validate)
            self._filter_value.currentIndexChanged.connect(self._update_size_hint)
            self._filter_operator.currentIndexChanged.connect(self._on_filter_operator_changed)
            self._filter_operator.activated.connect(self._reset_combo_selection)
            # Preview/Size-Hint darf NICHT pro Tastendruck den Provider (Full-
            # Table-Scan) triggern → nur `editingFinished` (Enter/Fokusverlust),
            # nicht `textChanged`. Die reine Leer-Validierung ist billig und
            # läuft pro Tastendruck weiter (kein Provider-Aufruf).
            self._filter_value_text.editingFinished.connect(self._update_size_hint)
            self._filter_value_text.editingFinished.connect(self._reset_combo_selection)
            self._filter_value_text.textChanged.connect(self._validate)
        if self._show_cluster:
            self._cluster_field.currentIndexChanged.connect(self._validate)
            self._cluster_field.currentIndexChanged.connect(self._update_size_hint)
        if self._show_stratified:
            self._stratum_field.currentIndexChanged.connect(self._validate)
            self._stratify_group.buttonToggled.connect(self._validate)
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
            self._form.setRowVisible(self._cluster_row, is_cluster)
        if self._show_stratified:
            self._form.setRowVisible(self._stratum_row, is_stratified)
            self._form.setRowVisible(self._stratify_row, is_stratified)
        self._update_size_hint()
        self._validate()

    def _refresh_filter_values(self) -> None:
        field = self._filter_field.currentText()
        self._filter_value.blockSignals(True)
        self._filter_value.clear()
        if field == NO_FILTER_LABEL or not field or self._distinct_values_provider is None:
            self._filter_value.setEnabled(False)
        else:
            self._filter_value.setEnabled(True)
            values = self._distinct_cache.get(field)
            if values is None:
                try:
                    values = tuple(self._distinct_values_provider(field))
                except Exception:
                    # Nicht cachen: ein transienter Fehler (z. B. "database is
                    # locked" durch eine parallele Snapshot-Erstellung) soll
                    # beim nächsten Wechsel auf dieses Feld erneut versucht
                    # werden, statt das Dropdown dauerhaft leer einzufrieren.
                    logger.warning(
                        "distinct-values provider failed for filter field %r", field, exc_info=True
                    )
                    values = ()
                else:
                    self._distinct_cache[field] = values
            for value in values:
                self._filter_value.addItem(_display(value), userData=value)
        self._filter_value.blockSignals(False)
        self._validate()

    def _on_filter_operator_changed(self) -> None:
        """Schaltet die Wert-Eingabe zwischen distinct-Dropdown (EQ/NE) und Textfeld.

        Ordering-Operatoren (>, ≥, <, ≤) brauchen einen freien Schwellenwert;
        EQ/NE bleiben beim distinct-Werte-Dropdown. Danach Validierung + Size-
        Hint (bei aktivem Filter ein Provider-Scan, hier zulässig).
        """
        is_ordering = self._filter_operator.currentData() in _ORDERING_OPERATORS
        self._filter_value_stack.setCurrentWidget(
            self._filter_value_text if is_ordering else self._filter_value
        )
        self._validate()
        self._update_size_hint()

    def _on_resample_toggled(self, checked: bool) -> None:
        # Kein hartes Cap mehr – Hint-Label informiert, Accept-Validierung
        # fängt Überschreitung ab.
        # Mutual Exclusion mit der Nachstichprobe (Sprint 36 / WP-B): rekursions-
        # sicher, weil setChecked(False) auf eine bereits ungecheckte Box nichts
        # emittiert und der Gegen-Slot mit checked=False keinen Rück-Uncheck macht.
        if checked and self._supplement_checkbox.isChecked():
            self._supplement_checkbox.setChecked(False)
        self._update_size_hint()
        self._validate()

    def _on_supplement_toggled(self, checked: bool) -> None:
        # Mutual Exclusion mit dem Resample-Filter (siehe `_on_resample_toggled`).
        if checked and self._resample_checkbox.isChecked():
            self._resample_checkbox.setChecked(False)
        # Sprint 85 / B: der Hinweis zieht die aktive Stichprobe ab (vorher
        # zeigte er die ganze Population, im Smoke-Test 500 statt 490).
        self._update_size_hint()
        self._validate()

    def _filter_is_active(self) -> bool:
        """Ist ein Spaltenfilter mit brauchbarem Wert gesetzt?

        Brauchbar heißt: Feld ≠ `NO_FILTER_LABEL` UND (für EQ/NE ein
        auswählbarer distinct-Wert, für Ordering-Ops ein nicht-leerer
        Schwellenwert-Text). Der Provider-`None`-Fall wird vom Aufrufer
        (`_effective_max_sample_size`) abgefangen.
        """
        if not self._show_filter:
            return False
        field = self._filter_field.currentText()
        if field == NO_FILTER_LABEL or not field:
            return False
        if self._filter_operator.currentData() in _ORDERING_OPERATORS:
            return bool(self._filter_value_text.text().strip())
        return self._filter_value.count() > 0

    def _current_filter_value(self, operator: FilterOperator) -> Any:
        """Leitet den Filter-Wert je Modus ab (Ordering-Text vs. EQ/NE-Dropdown).

        Single Source of Truth für Preview (`_active_filter_query`) UND Ziehung
        (`_build_config`): so zählt der Preview strukturell garantiert dieselbe
        Population, die auch gezogen wird – kein Auseinanderlaufen bei künftigen
        Edits (genau das, was dieses Feature verhindern soll).
        """
        if operator in _ORDERING_OPERATORS:
            return _parse_filter_threshold(self._filter_value_text.text())
        value = self._filter_value.currentData(int(Qt.ItemDataRole.UserRole))
        if value is None:
            value = self._filter_value.currentText()
        return value

    def _active_filter_query(self) -> tuple[str, FilterOperator, Any]:
        """(Feld, Operator, Wert) des aktiven Filters – Wert je Modus aufgelöst."""
        field = self._filter_field.currentText()
        operator: FilterOperator = self._filter_operator.currentData()
        return field, operator, self._current_filter_value(operator)

    def _match_count(
        self,
        provider: Callable[[str, FilterOperator, Any, bool], int],
        field: str,
        operator: FilterOperator,
        value: Any,
        restrict: bool,
    ) -> int:
        """Trefferzahl des Filters via Provider, memoisiert pro (Feld, Op, Wert, restrict)."""
        # `repr`, nicht `str`: der Key MUSS Typen unterscheiden – `matches_filter`
        # vergleicht per `==`, und int 5 ≠ str "5". `str(5) == str("5")` würde
        # kollidieren und einen veralteten Count für gemischt-typige Spalten zeigen.
        key = (field, operator, repr(value), restrict)
        cached = self._match_count_cache.get(key)
        if cached is not None:
            return cached
        count = provider(field, operator, value, restrict)
        self._match_count_cache[key] = count
        return count

    def _available_rows(self) -> int:
        """Datensätze, aus denen die Ziehung tatsächlich wählen kann (kann 0 sein).

        F = aktiver Filter mit Provider, R = Einschränken, E = Ergänzen:
        ohne F → Datasetgröße, Größe der aktiven Stichprobe (R) bzw. Datasetgröße
        minus aktive Stichprobe (E); mit F → Treffer gesamt, Treffer in der
        Stichprobe (R) bzw. Differenz der beiden (E). Der Provider (Full-Table-
        Scan) wird nie ohne brauchbaren Wert aufgerufen und ist memoisiert.
        """
        restrict = self._resample_checkbox.isChecked()
        supplement = self._supplement_checkbox.isChecked()
        drawn = len(self._current_sample.selected_row_ids) if self._current_sample else 0
        provider = self._filter_match_count_provider
        if provider is not None and self._filter_is_active():
            field, operator, value = self._active_filter_query()
            hits = self._match_count(provider, field, operator, value, False)
            if not (restrict or supplement) or self._current_sample is None:
                return hits
            hits_in_sample = self._match_count(provider, field, operator, value, True)
            return hits_in_sample if restrict else hits - hits_in_sample
        if restrict and self._current_sample is not None:
            return drawn
        if supplement:
            return self._dataset.row_count - drawn
        return self._dataset.row_count

    def _effective_max_sample_size(self) -> int:
        """Aktuell zulässige Maximalgröße der Stichprobe (mindestens 1, für den Hinweis)."""
        return max(self._available_rows(), 1)

    def _narrowing_note(self) -> str:
        """Zusatz, wenn eine Gruppenzahl nur die ganze Population beschreibt."""
        if self._filter_is_active():
            return " (vor Filter)"
        if self._resample_checkbox.isChecked() or self._supplement_checkbox.isChecked():
            return " (vor Auswahl)"
        return ""

    def _group_count(self, column: str) -> int | None:
        """Anzahl Gruppen einer Spalte über den Controller-Zähler (memoisiert)."""
        if self._group_count_provider is None:
            return None
        cached = self._group_count_cache.get(column)
        if cached is None:
            # Ein Full-Table-Scan (~0,5 s bei 500.000 Zeilen, Sprint 85 gemessen),
            # einmal je Spalte und Dialog.
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                cached = self._group_count_provider(column)
            finally:
                QApplication.restoreOverrideCursor()
            self._group_count_cache[column] = cached
        return cached

    def _update_size_hint(self) -> None:
        """Aktualisiert den Hint-Text unter dem Size-SpinBox."""
        if self._selected_method() == SamplingMethod.CLUSTER:
            column = _selected_column(self._cluster_field)
            clusters = self._group_count(column) if column is not None else None
            if clusters is not None:
                self._lbl_size_hint.setText(
                    f"max. {_format_int(clusters)} Cluster verfügbar{self._narrowing_note()}"
                )
                return
        max_n = self._effective_max_sample_size()
        self._lbl_size_hint.setText(f"max. {_format_int(max_n)} verfügbar")

    def accept(self) -> None:
        """Prüft alles vor dem Schließen; bei einem Fehler bleibt der Dialog offen.

        Sprint 85 / B: Meldungen stehen unter dem betroffenen Feld, alle
        Eingaben bleiben stehen. Was nur die Daten wissen, prüft zuletzt die
        Probeziehung des Controllers (`set_validators`).
        """
        self._clear_messages()
        errors = self._field_errors()
        if errors:
            for field, message in errors.items():
                self._show_message(field, message)
            return
        result = SamplingDialogResult(
            config=self._build_config(),
            from_sample_only=self._resample_checkbox.isChecked(),
            exclude_sample_ids=self._supplement_checkbox.isChecked(),
        )
        if self._draw_check is not None:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                problem = self._draw_check(result)
            finally:
                QApplication.restoreOverrideCursor()
            if problem is not None:
                self._show_message("size", problem)
                return
        self._result = result
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
        filter_operator: FilterOperator = FilterOperator.EQ
        if self._show_filter:
            filter_operator = self._filter_operator.currentData()
            if self._filter_field.currentText() != NO_FILTER_LABEL:
                filter_field = self._filter_field.currentText()
                filter_value = self._current_filter_value(filter_operator)
        stratify_mode = StratifyMode.PROPORTIONAL
        if self._show_stratified and self._radio_equal.isChecked():
            stratify_mode = StratifyMode.EQUAL
        return SampleConfig(
            method=method,
            size=self._size_spin.value(),
            seed=self._seed_spin.value(),
            cluster_field=_selected_column(self._cluster_field)
            if method == SamplingMethod.CLUSTER
            else None,
            stratum_field=_selected_column(self._stratum_field)
            if method == SamplingMethod.STRATIFIED
            else None,
            stratify_mode=stratify_mode,
            filter_field=filter_field,
            filter_value=filter_value,
            filter_operator=filter_operator,
        )

    def _field_errors(self) -> dict[str, str]:
        """Alle Fehler, die der Dialog selbst erkennen kann – je Feld eine Meldung.

        Schlüssel: `general`, `size`, `filter`, `cluster`, `stratum`. Die
        Reihenfolge der Prüfungen folgt dem Formular von oben nach unten.
        """
        if not self._columns:
            return {"general": "Das Dataset hat keine Spalten – Sampling nicht möglich."}
        errors: dict[str, str] = {}
        method = self._selected_method()
        cluster_column = (
            _selected_column(self._cluster_field) if method == SamplingMethod.CLUSTER else None
        )
        stratum_column = (
            _selected_column(self._stratum_field) if method == SamplingMethod.STRATIFIED else None
        )
        if method == SamplingMethod.CLUSTER and cluster_column is None:
            errors["cluster"] = "Bitte ein Cluster-Feld wählen."
        if method == SamplingMethod.STRATIFIED and stratum_column is None:
            errors["stratum"] = "Bitte ein Schicht-Feld wählen."
        filter_error = self._filter_error()
        if filter_error is not None:
            errors["filter"] = filter_error
            return errors
        size_error = self._size_error(cluster_column, stratum_column)
        if size_error is not None:
            errors["size"] = size_error
        return errors

    def _filter_error(self) -> str | None:
        if not self._show_filter or self._filter_field.currentText() == NO_FILTER_LABEL:
            return None
        if self._filter_operator.currentData() in _ORDERING_OPERATORS:
            if not self._filter_value_text.text().strip():
                return "Bitte einen Schwellenwert für den Vergleich eingeben."
        elif self._filter_value.count() == 0:
            return "Das Filterfeld enthält keine Werte – Filter entfernen."
        provider = self._filter_match_count_provider
        if provider is not None and self._filter_is_active():
            field, operator, value = self._active_filter_query()
            if self._match_count(provider, field, operator, value, False) == 0:
                return "Der Filter trifft keinen Datensatz – bitte Wert oder Feld ändern."
        return None

    def _size_error(self, cluster_column: str | None, stratum_column: str | None) -> str | None:
        size = self._size_spin.value()
        if size < MIN_SAMPLE_SIZE:
            return f"Die Stichprobengröße muss mindestens {MIN_SAMPLE_SIZE} betragen."
        available = self._available_rows()
        if available <= 0:
            return "Es sind keine ungezogenen Datensätze mehr übrig."
        if size > available:
            return (
                f"Die Größe ({_format_int(size)}) übersteigt die verfügbaren Datensätze "
                f"({_format_int(available)})."
            )
        # Gruppenzahlen gelten für die ganze Population; mit Filter oder Auswahl
        # entscheidet erst die Probeziehung (exakt auf dem Zieh-Pfad).
        if self._narrowing_note():
            return None
        clusters = self._group_count(cluster_column) if cluster_column is not None else None
        if clusters is not None and size > clusters:
            return (
                f"Es gibt nur {_format_int(clusters)} Cluster in „{cluster_column}“ – "
                f"bitte höchstens {_format_int(clusters)} wählen."
            )
        strata = self._group_count(stratum_column) if stratum_column is not None else None
        if strata is not None and size < strata:
            return (
                f"„{stratum_column}“ hat {_format_int(strata)} Schichten; aus jeder wird "
                f"mindestens ein Datensatz gezogen – bitte mindestens {_format_int(strata)} "
                "wählen."
            )
        return None

    def _show_message(self, field: str, message: str) -> None:
        label = self._inline_errors.get(field)
        if label is None:
            self._error_label.setText(message)
            return
        label.setText(message)
        label.setVisible(True)

    def _clear_messages(self) -> None:
        self._error_label.setText("")
        for label in self._inline_errors.values():
            label.setText("")
            label.setVisible(False)

    def _validate(self) -> None:
        """Jede Eingabeänderung räumt alte Meldungen weg; geprüft wird beim OK.

        Sprint 85 / B: OK bleibt immer aktiv – ein gesperrter Knopf ohne
        Erklärung ließ Anwender raten, was fehlt.
        """
        self._clear_messages()

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
        **Wert** (nur EQ/NE-Dropdown) dort nicht (mehr) vorkommt. So fällt der
        Dialog nie still auf einen anderen Wert zurück – „kein stiller
        Fehlschlag" (ISAE-3402). Der Operator wird immer gespiegelt.
        """
        self._apply_preset_operator(preset.filter_operator)
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
        if preset.filter_operator in _ORDERING_OPERATORS:
            # Ordering-Ops: Wert ins Schwellenwert-Textfeld (kein distinct-Match
            # gegen die Population – ein Vergleichswert muss dort nicht vorkommen).
            self._filter_value_text.setText(_display(preset.filter_value))
        elif not self._select_filter_value(preset.filter_value):
            # Spalte ja, aber der Wert kommt in dieser Population nicht vor.
            self._filter_field.setCurrentText(NO_FILTER_LABEL)
            skipped.append(preset.filter_field)

    def _apply_preset_operator(self, operator: FilterOperator) -> None:
        """Wählt den Operator im Combo (schaltet über den Slot die Wert-Eingabe um)."""
        for i in range(self._filter_operator.count()):
            if self._filter_operator.itemData(i) == operator:
                self._filter_operator.setCurrentIndex(i)
                return

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

    # ---- Vorlagen-Dropdown (Sprint 32) ---------------------------------

    def _reload_preset_combo(self) -> None:
        """Füllt das Dropdown neu aus dem Store (Platzhalter + je Vorlage ein Eintrag).

        Wird beim Öffnen aufgerufen; so spiegelt das Dropdown auch Änderungen
        aus dem Verwaltungsfenster beim nächsten Öffnen wider. Leere Liste: nur
        der Platzhalter, das Dropdown bleibt benutzbar. Der Vorlagen-Name wandert
        als `userData` mit (der Platzhalter trägt keinen) – so unterscheidet
        `_on_preset_selected` ihn typ-sicher von einer echten Vorlage.
        """
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        self._preset_combo.addItem(PRESET_PLACEHOLDER)
        for preset in self._preset_store.list():
            self._preset_combo.addItem(preset.name, userData=preset.name)
        self._preset_combo.setCurrentIndex(0)
        self._preset_combo.blockSignals(False)

    def _on_preset_selected(self, index: int) -> None:
        """Wendet die im Dropdown gewählte Vorlage an und meldet übersprungene Filter.

        `apply_preset` setzt nur Parameter (zieht NICHT, lässt den Seed in Ruhe).
        Der Platzhalter (kein `userData`) ist ein No-Op.
        """
        name = self._preset_combo.itemData(index)
        if name is None:
            return
        preset = self._preset_store.get(name)
        if preset is None:
            # Vorlage wurde zwischenzeitlich entfernt (Verwaltungsfenster).
            self._reload_preset_combo()
            return
        self._applying_preset = True
        try:
            result = self.apply_preset(preset)
        finally:
            self._applying_preset = False
        if result.skipped_filters:
            cols = ", ".join(f"„{c}“" for c in result.skipped_filters)
            QMessageBox.information(
                self,
                "Vorlage angewendet",
                f"Die Vorlage „{name}“ wurde angewendet.\n\n"
                f"Übersprungen, weil Spalte oder Wert in den aktuellen Daten "
                f"nicht vorhanden ist: {cols}.",
            )

    def _reset_combo_selection(self) -> None:
        """Setzt das Dropdown auf den Platzhalter zurück, sobald der Nutzer manuell ändert.

        Während `apply_preset` selbst die Widgets setzt, bleibt die Auswahl
        erhalten (`_applying_preset`-Guard) – sie spiegelt dann die unverändert
        angewandte Vorlage.
        """
        if self._applying_preset:
            return
        self._preset_combo.setCurrentIndex(0)


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _selected_column(combo: QComboBox) -> str | None:
    """Gewählte Spalte einer `_column_combo` – `None` beim Platzhalter."""
    column = combo.currentData()
    return column if isinstance(column, str) else None


def _select_column(combo: QComboBox, column: str) -> None:
    """Wählt `column`, falls die Population sie hat; sonst bleibt die Auswahl."""
    index = combo.findData(column)
    if index >= 0:
        combo.setCurrentIndex(index)


def _display(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _parse_filter_threshold(text: str) -> Any:
    """Parst einen Schwellenwert-Text für Ordering-Filter (>, ≥, <, ≤).

    Reihenfolge: int → float → datetime → Rohstring (Fallback). Ein reines Datum
    („2024-06-30") wird bewusst als `datetime` (Mitternacht) geparst, NICHT als
    `date`: Datums-Spalten liegen nach dem Import als `datetime` vor (der Importer
    coerct `date` → `datetime.combine(…, 00:00)`), und `datetime > date` wirft
    `TypeError` – ein reiner `date`-Schwellenwert würde gegen eine datetime-Spalte
    also nichts matchen. `datetime.fromisoformat` akzeptiert beide Formen
    („2024-06-30" und „2024-06-30T10:00"). Bewusst NICHT `_coerce_value`/
    `_coerce_string` (Import-Coercion) – ein eigener, kleiner Parser nur für
    dieses Textfeld.
    """
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    return text


def _generate_random_seed() -> int:
    """Zufalls-Seed im erlaubten QSpinBox-Bereich (immer > 0)."""
    return secrets.randbelow(_safe_int_max()) + 1


def _safe_int_max() -> int:
    # QSpinBox unterstützt nur 32-Bit-signed → wir kappen SEED_MAX entsprechend.
    return min(SEED_MAX, _SPINBOX_MAX)


def _format_int(value: int) -> str:
    """Tausenderpunkte für deutsche Locale (12345 → '12.345')."""
    return f"{value:,}".replace(",", ".")
