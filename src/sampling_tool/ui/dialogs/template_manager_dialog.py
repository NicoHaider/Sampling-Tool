"""Verwaltungsfenster für Sampling-Vorlagen (Sprint 28).

Eigenes Fenster (Menü „Stichprobe → Vorlagen verwalten…") zum Auflisten,
Umbenennen, Löschen, Duplizieren und Bearbeiten der app-weit gespeicherten
Vorlagen. Alle Schreibvorgänge laufen über die unveränderte `PresetStore`-
Schicht (Sprint 23) – keine neue Persistenz, kein Schema-Change.

Das Fenster wird über **einen** klar definierten Einstiegspunkt geöffnet
(`HelpController.handle_manage_templates`), damit später ein Passwort-Gate
davor ergänzt werden kann (Sprint 28 implementiert noch keins).

**Bearbeiten ohne geladene Population.** Das Fenster ist app-weit erreichbar,
auch ohne offenes Projekt – es kennt also keine Population. Editierbar sind
daher die populations-unabhängigen Felder (Methode, Größe, Cluster-/Schicht-
Feldname als Text, Schicht-Verteilung). Der konkrete **Filter-Wert** lässt
sich ohne Population nicht typ-sicher wählen (er kann ein Datum sein); er wird
deshalb hier nur angezeigt und unverändert mitgespeichert. Gesetzt/geändert
werden Filter über das „+" im Stichproben-Dialog (mit geladener Population).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Final

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.config import BDO_GREY, MIN_SAMPLE_SIZE
from sampling_tool.core.models import SamplingMethod, StratifyMode
from sampling_tool.core.presets import SamplingPreset
from sampling_tool.ui.preset_store import PresetStore

_SPINBOX_MAX: Final[int] = 2_147_483_647

_METHOD_LABELS: Final[list[tuple[str, SamplingMethod]]] = [
    ("Einfach", SamplingMethod.SIMPLE),
    ("Cluster", SamplingMethod.CLUSTER),
    ("Geschichtet", SamplingMethod.STRATIFIED),
]

_STRATIFY_LABELS: Final[list[tuple[str, StratifyMode]]] = [
    ("Proportional", StratifyMode.PROPORTIONAL),
    ("Gleich", StratifyMode.EQUAL),
]


class TemplateManagerDialog(QDialog):
    """Listet alle Vorlagen und erlaubt Bearbeiten/Umbenennen/Löschen/Duplizieren."""

    def __init__(self, preset_store: PresetStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Vorlagen verwalten")
        self.setModal(True)
        self.setMinimumWidth(620)

        self._store = preset_store
        # Populations-abhängige Filter-Definition der gewählten Vorlage – wird
        # nur angezeigt und beim Speichern unverändert durchgereicht.
        self._current_filter_field: str | None = None
        self._current_filter_value: object = None

        self._build_ui()
        self._wire_signals()
        self._reload()

    # ---- UI-Aufbau -----------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        intro = QLabel(
            "Gespeicherte Vorlagen verwalten. Änderungen erscheinen beim nächsten "
            "Öffnen des Stichproben-Dialogs in der Chip-Leiste."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {BDO_GREY};")
        outer.addWidget(intro)

        body = QHBoxLayout()
        body.setSpacing(16)

        # ---- Liste (links) + Listen-Aktionen ----
        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(QLabel("Vorlagen"))
        self._list = QListWidget()
        self._list.setMinimumWidth(200)
        left.addWidget(self._list, stretch=1)
        list_buttons = QHBoxLayout()
        list_buttons.setSpacing(6)
        self._btn_rename = QPushButton("Umbenennen…")
        self._btn_duplicate = QPushButton("Duplizieren")
        self._btn_delete = QPushButton("Löschen")
        for btn in (self._btn_rename, self._btn_duplicate, self._btn_delete):
            btn.setProperty("secondary", True)
            list_buttons.addWidget(btn)
        left.addLayout(list_buttons)
        body.addLayout(left, stretch=1)

        # ---- Bearbeiten-Formular (rechts) ----
        edit_box = QGroupBox("Konfiguration bearbeiten")
        edit_outer = QVBoxLayout(edit_box)
        form = QFormLayout()
        form.setSpacing(8)

        self._edit_method = QComboBox()
        for label, method in _METHOD_LABELS:
            self._edit_method.addItem(label, userData=method)
        form.addRow("Methode", self._edit_method)

        self._edit_size = QSpinBox()
        self._edit_size.setRange(MIN_SAMPLE_SIZE, _SPINBOX_MAX)
        form.addRow("Stichprobengröße", self._edit_size)

        self._edit_cluster_field = QLineEdit()
        self._edit_cluster_field.setPlaceholderText("Spaltenname")
        form.addRow("Cluster-Feld", self._edit_cluster_field)

        self._edit_stratum_field = QLineEdit()
        self._edit_stratum_field.setPlaceholderText("Spaltenname")
        form.addRow("Schicht-Feld", self._edit_stratum_field)

        self._edit_stratify_mode = QComboBox()
        for label, mode in _STRATIFY_LABELS:
            self._edit_stratify_mode.addItem(label, userData=mode)
        form.addRow("Schicht-Verteilung", self._edit_stratify_mode)

        self._lbl_filter = QLabel("—")
        self._lbl_filter.setStyleSheet(f"color: {BDO_GREY};")
        form.addRow("Filter", self._lbl_filter)
        edit_outer.addLayout(form)

        filter_hint = QLabel(
            "Filter werden mit geladener Population über das „+“ im Stichproben-Dialog gesetzt."
        )
        filter_hint.setWordWrap(True)
        filter_hint.setStyleSheet(f"color: {BDO_GREY}; font-size: 11px;")
        edit_outer.addWidget(filter_hint)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self._btn_save = QPushButton("Speichern")
        save_row.addWidget(self._btn_save)
        edit_outer.addLayout(save_row)

        body.addWidget(edit_box, stretch=2)
        outer.addLayout(body)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        outer.addWidget(self._buttons)

    def _wire_signals(self) -> None:
        self._list.currentRowChanged.connect(self._on_selection_changed)
        self._edit_method.currentIndexChanged.connect(self._on_edit_method_changed)
        self._btn_rename.clicked.connect(self._on_rename)
        self._btn_duplicate.clicked.connect(self._on_duplicate)
        self._btn_delete.clicked.connect(self._on_delete)
        self._btn_save.clicked.connect(self._on_save_edit)
        self._buttons.rejected.connect(self.reject)

    # ---- Liste / Auswahl -----------------------------------------------

    def _reload(self, select: str | None = None) -> None:
        """Befüllt die Liste neu aus dem Store; selektiert `select`, sonst Zeile 0."""
        self._list.blockSignals(True)
        self._list.clear()
        for preset in self._store.list():
            self._list.addItem(preset.name)
        self._list.blockSignals(False)
        target = self._find_row(select) if select is not None else 0
        if self._list.count() == 0:
            self._on_selection_changed(-1)
        else:
            self._list.setCurrentRow(max(target, 0))

    def _find_row(self, name: str) -> int:
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item is not None and item.text() == name:
                return i
        return 0

    def _selected_name(self) -> str | None:
        item = self._list.currentItem()
        return item.text() if item is not None else None

    def _on_selection_changed(self, _row: int) -> None:
        name = self._selected_name()
        has = name is not None
        for widget in (
            self._edit_method,
            self._edit_size,
            self._edit_cluster_field,
            self._edit_stratum_field,
            self._edit_stratify_mode,
            self._btn_rename,
            self._btn_duplicate,
            self._btn_delete,
            self._btn_save,
        ):
            widget.setEnabled(has)
        if name is None:
            self._lbl_filter.setText("—")
            return
        preset = self._store.get(name)
        if preset is not None:
            self._load_into_form(preset)

    def _load_into_form(self, preset: SamplingPreset) -> None:
        self._set_edit_method(preset.method)
        self._edit_size.setValue(preset.size)
        self._edit_cluster_field.setText(preset.cluster_field or "")
        self._edit_stratum_field.setText(preset.stratum_field or "")
        self._set_edit_stratify_mode(preset.stratify_mode)
        self._current_filter_field = preset.filter_field
        self._current_filter_value = preset.filter_value
        if preset.filter_field:
            self._lbl_filter.setText(f"{preset.filter_field} = {preset.filter_value}")
        else:
            self._lbl_filter.setText("(kein Filter)")
        self._on_edit_method_changed()

    def _on_edit_method_changed(self) -> None:
        method = self._edit_method_value()
        self._edit_cluster_field.setEnabled(method == SamplingMethod.CLUSTER)
        is_stratified = method == SamplingMethod.STRATIFIED
        self._edit_stratum_field.setEnabled(is_stratified)
        self._edit_stratify_mode.setEnabled(is_stratified)

    # ---- Methoden-/Modus-Mapping (für Tests + interne Nutzung) ----------

    def _edit_method_value(self) -> SamplingMethod:
        data = self._edit_method.currentData()
        return data if isinstance(data, SamplingMethod) else SamplingMethod.SIMPLE

    def _set_edit_method(self, method: SamplingMethod) -> None:
        idx = self._edit_method.findData(method)
        if idx >= 0:
            self._edit_method.setCurrentIndex(idx)

    def _edit_stratify_mode_value(self) -> StratifyMode:
        data = self._edit_stratify_mode.currentData()
        return data if isinstance(data, StratifyMode) else StratifyMode.PROPORTIONAL

    def _set_edit_stratify_mode(self, mode: StratifyMode) -> None:
        idx = self._edit_stratify_mode.findData(mode)
        if idx >= 0:
            self._edit_stratify_mode.setCurrentIndex(idx)

    # ---- Aktionen (alle über PresetStore) ------------------------------

    def _on_save_edit(self) -> None:
        """Speichert die geänderte Konfiguration der gewählten Vorlage.

        Cluster-/Schicht-Feld werden nur für die passende Methode übernommen
        (analog `SampleConfig`); der Filter wird unverändert mitgespeichert.
        """
        name = self._selected_name()
        if name is None:
            return
        method = self._edit_method_value()
        cluster_field = self._edit_cluster_field.text().strip() or None
        stratum_field = self._edit_stratum_field.text().strip() or None
        preset = SamplingPreset(
            name=name,
            method=method,
            size=self._edit_size.value(),
            cluster_field=cluster_field if method == SamplingMethod.CLUSTER else None,
            stratum_field=stratum_field if method == SamplingMethod.STRATIFIED else None,
            stratify_mode=self._edit_stratify_mode_value(),
            filter_field=self._current_filter_field,
            filter_value=self._current_filter_value,
        )
        self._store.save(preset)
        self._reload(select=name)

    def _on_rename(self) -> None:
        old = self._selected_name()
        if old is None:
            return
        new, ok = QInputDialog.getText(self, "Vorlage umbenennen", "Neuer Name:", text=old)
        if not ok:
            return
        new = new.strip()
        if not new or new == old:
            return
        if self._store.exists(new) and not self._confirm_overwrite(new):
            return
        self._store.rename(old, new)
        self._reload(select=new)

    def _on_delete(self) -> None:
        name = self._selected_name()
        if name is None:
            return
        answer = QMessageBox.question(
            self,
            "Vorlage löschen",
            f"Soll die Vorlage „{name}“ wirklich gelöscht werden?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._store.delete(name)
        self._reload()

    def _on_duplicate(self) -> None:
        name = self._selected_name()
        if name is None:
            return
        source = self._store.get(name)
        if source is None:
            return
        copy_name = self._unique_copy_name(name)
        self._store.save(replace(source, name=copy_name))
        self._reload(select=copy_name)

    def _unique_copy_name(self, name: str) -> str:
        base = f"{name} (Kopie)"
        if not self._store.exists(base):
            return base
        i = 2
        while self._store.exists(f"{base} {i}"):
            i += 1
        return f"{base} {i}"

    def _confirm_overwrite(self, name: str) -> bool:
        answer = QMessageBox.question(
            self,
            "Vorlage überschreiben",
            f"Eine Vorlage „{name}“ existiert bereits. Überschreiben?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes
