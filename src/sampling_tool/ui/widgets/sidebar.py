"""Navigations-Sidebar: Engagement-Block + Dataset- und Sample-Listen.

Drei Sektionen, jeweils ein `QListWidget`:
- **ENGAGEMENT** – Header-Block mit Mandant/Prüfungstyp/Auditor.
- **DATASETS** – Liste der Datensätze, Klick wechselt aktiven Datensatz.
- **SAMPLES** – Liste der Stichproben des aktiven Datasets; Klick highlightet,
  Doppelklick toggled den Filter.

Die Sidebar selbst kennt nur Domain-Modelle und feuert Signals mit IDs – die
Glue-Logik zum Repo läuft im `MainController`.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.core.models import Dataset, Engagement, SampleResult

_DATASET_ID_ROLE = int(Qt.ItemDataRole.UserRole)
_SAMPLE_ID_ROLE = int(Qt.ItemDataRole.UserRole)
_SAMPLE_LABEL_ROLE = int(Qt.ItemDataRole.UserRole) + 1
_ACTIVE_PREFIX: str = "● "
_SIDEBAR_WIDTH: int = 250


class NavigationSidebar(QFrame):
    """Sidebar-Widget – Höhe 100 %, fixe Breite ~250 px."""

    dataset_selected = pyqtSignal(int)
    sample_selected = pyqtSignal(int)
    sample_double_clicked = pyqtSignal(int)
    filter_only_sample_toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(_SIDEBAR_WIDTH)
        self.setFrameShape(QFrame.Shape.NoFrame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Engagement-Block
        self._engagement_title = QLabel("Kein Engagement geladen")
        self._engagement_title.setProperty("engagementTitle", True)
        self._engagement_title.setWordWrap(True)

        self._engagement_subtitle = QLabel("")
        self._engagement_subtitle.setProperty("engagementSubtitle", True)
        self._engagement_subtitle.setWordWrap(True)

        layout.addWidget(self._engagement_title)
        layout.addWidget(self._engagement_subtitle)

        # Datasets
        layout.addWidget(_section_label("Datensätze"))
        self._datasets_empty = _empty_hint("Noch keine Datensätze")
        layout.addWidget(self._datasets_empty)
        self._datasets_list = QListWidget()
        self._datasets_list.itemClicked.connect(self._on_dataset_clicked)
        layout.addWidget(self._datasets_list, stretch=1)

        # Samples
        layout.addWidget(_section_label("Stichproben"))
        self._samples_empty = _empty_hint("Noch keine Stichproben")
        layout.addWidget(self._samples_empty)
        self._samples_list = QListWidget()
        self._samples_list.itemClicked.connect(self._on_sample_clicked)
        self._samples_list.itemDoubleClicked.connect(self._on_sample_double_clicked)
        layout.addWidget(self._samples_list, stretch=1)

        # Filter-Checkbox – grenzt die Tabelle auf das aktive Sample ein.
        # Default deaktiviert, bis ein Sample aktiv ist (Controller schaltet frei).
        self._filter_only_sample = QCheckBox("Nur markierte Zeilen anzeigen")
        self._filter_only_sample.setObjectName("FilterOnlySampleCheckbox")
        self._filter_only_sample.setEnabled(False)
        self._filter_only_sample.toggled.connect(self.filter_only_sample_toggled.emit)
        layout.addWidget(self._filter_only_sample)

    # ---- Public API -----------------------------------------------------

    def set_engagement(self, engagement: Engagement | None) -> None:
        """Aktualisiert den Engagement-Header-Block."""
        if engagement is None:
            self._engagement_title.setText("Kein Engagement geladen")
            self._engagement_subtitle.setText("")
            return
        self._engagement_title.setText(engagement.client_name)
        parts = [p for p in (engagement.audit_type, engagement.auditor_name) if p]
        self._engagement_subtitle.setText(" · ".join(parts))

    def set_datasets(self, datasets: list[Dataset]) -> None:
        """Befüllt die Dataset-Liste – Auswahl wird zurückgesetzt."""
        self._datasets_list.clear()
        for ds in datasets:
            item = QListWidgetItem(ds.name)
            ds_id = ds.id if ds.id is not None else -1
            item.setData(_DATASET_ID_ROLE, ds_id)
            self._datasets_list.addItem(item)
        self._datasets_empty.setVisible(not datasets)

    def set_samples(self, samples: list[SampleResult]) -> None:
        """Befüllt die Sample-Liste – mit Methode + Größe als Label."""
        self._samples_list.clear()
        for idx, sample in enumerate(samples, start=1):
            label = (
                f"#{idx} · {sample.config.method.value} · n={sample.actual_size} "
                f"(seed {sample.config.seed})"
            )
            item = QListWidgetItem(label)
            sample_id = sample.id if sample.id is not None else -1
            item.setData(_SAMPLE_ID_ROLE, sample_id)
            item.setData(_SAMPLE_LABEL_ROLE, label)
            self._samples_list.addItem(item)
        self._samples_empty.setVisible(not samples)

    def clear_samples(self) -> None:
        """Leert die Sample-Liste (z. B. wenn kein Dataset aktiv)."""
        self._samples_list.clear()

    def set_active_sample(self, sample_id: int | None) -> None:
        """Markiert das Sample mit der gegebenen ID als „aktiv" (Bullet + Bold).

        Mit `sample_id=None` wird die Markierung von allen Items entfernt.
        """
        for row in range(self._samples_list.count()):
            item = self._samples_list.item(row)
            if item is None:
                continue
            base_label = item.data(_SAMPLE_LABEL_ROLE) or item.text()
            is_active = sample_id is not None and item.data(_SAMPLE_ID_ROLE) == sample_id
            item.setText(f"{_ACTIVE_PREFIX}{base_label}" if is_active else base_label)
            font = QFont(item.font())
            font.setBold(is_active)
            item.setFont(font)

    def select_dataset(self, dataset_id: int) -> None:
        """Wählt das Dataset mit der gegebenen ID programmatisch aus."""
        for row in range(self._datasets_list.count()):
            item = self._datasets_list.item(row)
            if item is not None and item.data(_DATASET_ID_ROLE) == dataset_id:
                self._datasets_list.setCurrentRow(row)
                return

    def datasets_widget(self) -> QListWidget:
        """Zugriff auf die innere Dataset-Liste (Tests)."""
        return self._datasets_list

    def samples_widget(self) -> QListWidget:
        """Zugriff auf die innere Sample-Liste (Tests)."""
        return self._samples_list

    def filter_checkbox(self) -> QCheckBox:
        """Zugriff auf die Filter-Checkbox (Tests)."""
        return self._filter_only_sample

    def set_filter_enabled(self, enabled: bool) -> None:
        """Schaltet die Filter-Checkbox (Controller schaltet frei wenn Sample aktiv)."""
        self._filter_only_sample.setEnabled(enabled)
        if not enabled and self._filter_only_sample.isChecked():
            # Wenn die Checkbox deaktiviert wird, soll sie auch entcheckt sein –
            # sonst entsteht ein verwirrender Zwischenstand (gecheckt, aber wirkungslos).
            self.set_filter_only_sample(False)

    def is_filter_only_sample(self) -> bool:
        """Aktueller Zustand der Filter-Checkbox."""
        return self._filter_only_sample.isChecked()

    def set_filter_only_sample(self, active: bool) -> None:
        """Setzt die Checkbox programmatisch ohne Signal-Loop auszulösen."""
        if self._filter_only_sample.isChecked() == active:
            return
        # Ohne Block würde `setChecked` das `toggled`-Signal feuern und damit
        # den Controller erneut anstoßen, der uns gerade aufruft – Endlos-Loop.
        self._filter_only_sample.blockSignals(True)
        try:
            self._filter_only_sample.setChecked(active)
        finally:
            self._filter_only_sample.blockSignals(False)

    # ---- Slots ---------------------------------------------------------

    def _on_dataset_clicked(self, item: QListWidgetItem) -> None:
        ds_id = item.data(_DATASET_ID_ROLE)
        if isinstance(ds_id, int) and ds_id >= 0:
            self.dataset_selected.emit(ds_id)

    def _on_sample_clicked(self, item: QListWidgetItem) -> None:
        sample_id = item.data(_SAMPLE_ID_ROLE)
        if isinstance(sample_id, int) and sample_id >= 0:
            self.sample_selected.emit(sample_id)

    def _on_sample_double_clicked(self, item: QListWidgetItem) -> None:
        sample_id = item.data(_SAMPLE_ID_ROLE)
        if isinstance(sample_id, int) and sample_id >= 0:
            self.sample_double_clicked.emit(sample_id)


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("sectionHeader", True)
    return label


def _empty_hint(text: str) -> QLabel:
    """Graues Sub-Label – wird unter den Sektions-Headern angezeigt, wenn leer."""
    label = QLabel(text)
    label.setStyleSheet("color: #B0B0B0; font-style: italic; padding: 4px 8px;")
    label.setProperty("emptyHint", True)
    return label
