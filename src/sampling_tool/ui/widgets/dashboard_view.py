"""Dashboard – Statistik-Kacheln und Mini-Charts für ein Engagement.

Layout: drei Spalten, beliebig viele Reihen aus `QFrame`-Kacheln. Jede
Kachel besteht aus Title-Label + Body-Widget (Zahl, Mini-Chart, Liste).
Die Charts werden über `chart_renderer` als `QPixmap` in `QLabel`s
gerendert – matplotlib läuft im `Agg`-Backend.

Klicks auf einzelne Samples in der "Letzte Stichproben"-Kachel feuern
`sample_clicked(int)` – der Controller kann damit Tabelle + Sidebar
synchronisieren.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Final

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from sampling_tool.core.models import AuditEvent, Dataset, Engagement, SampleResult
from sampling_tool.ui.widgets.chart_renderer import (
    render_bar_chart,
    render_line_chart,
)

_TILE_COLUMNS: Final[int] = 3
_CHART_WIDTH: Final[int] = 360
_CHART_HEIGHT: Final[int] = 160
_RECENT_SAMPLE_LIMIT: Final[int] = 5
_HISTORY_DAYS: Final[int] = 30


class DashboardTile(QFrame):
    """Generische Kachel – Title + Body."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DashboardTile")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setStyleSheet(
            "QFrame#DashboardTile { background-color: white; border: 1px solid #D9D9D9; "
            "border-radius: 6px; padding: 8px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._title_label = QLabel(title)
        self._title_label.setStyleSheet(
            "font-weight: 700; color: #333333; font-size: 12px; text-transform: uppercase;"
        )
        layout.addWidget(self._title_label)

        self._body_layout = QVBoxLayout()
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(4)
        layout.addLayout(self._body_layout, stretch=1)

    def set_body_widget(self, widget: QWidget) -> None:
        """Tauscht das Body-Widget der Kachel aus."""
        self._clear_body()
        self._body_layout.addWidget(widget)

    def _clear_body(self) -> None:
        while self._body_layout.count() > 0:
            item = self._body_layout.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()


class _ClickableSampleLabel(QLabel):
    """Label, das beim Klick die Sample-ID emittiert."""

    clicked = pyqtSignal(int)

    def __init__(self, text: str, sample_id: int, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._sample_id = sample_id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "QLabel { color: #333333; padding: 4px; }"
            "QLabel:hover { background-color: #F5F5F5; color: #E81A3B; }"
        )

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._sample_id)
        super().mousePressEvent(event)


class DashboardView(QWidget):
    """Übersichts-Dashboard mit Kacheln und Charts."""

    sample_clicked = pyqtSignal(int)
    dataset_clicked = pyqtSignal(int)
    refresh_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DashboardView")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # Refresh-Zeile oben.
        head_row = QHBoxLayout()
        head_row.addStretch(1)
        self._refresh_button = QPushButton("Aktualisieren")
        self._refresh_button.clicked.connect(self.refresh_requested.emit)
        head_row.addWidget(self._refresh_button)
        outer.addLayout(head_row)

        self._stack = QStackedWidget()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._content = QWidget()
        scroll.setWidget(self._content)

        self._grid = QGridLayout(self._content)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(10)

        # Kacheln (initial leer, set_data füllt sie).
        self._tile_datasets = DashboardTile("Datasets")
        self._tile_samples = DashboardTile("Samples")
        self._tile_events = DashboardTile("Audit-Events")
        self._tile_last_activity = DashboardTile("Letzte Aktivität")
        self._tile_recent_samples = DashboardTile("Letzte Stichproben")
        self._tile_history = DashboardTile("Sampling-Historie (30 Tage)")

        for index, tile in enumerate(
            (
                self._tile_datasets,
                self._tile_samples,
                self._tile_events,
                self._tile_last_activity,
                self._tile_recent_samples,
                self._tile_history,
            )
        ):
            row, col = divmod(index, _TILE_COLUMNS)
            self._grid.addWidget(tile, row, col)
        self._grid.setRowStretch(2, 1)

        self._stack.addWidget(scroll)

        self._empty_label = QLabel(
            "Engagement leer – starte mit einem Datei-Import, um Statistiken zu sehen."
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #7F7F7F; font-style: italic; padding: 24px;")
        self._stack.addWidget(self._empty_label)

        outer.addWidget(self._stack, stretch=1)

        self._stack.setCurrentWidget(self._empty_label)
        self._render_default_body()

    # ---- Public API -----------------------------------------------------

    def set_data(
        self,
        engagement: Engagement | None,
        datasets: list[Dataset],
        samples: list[SampleResult],
        audit_events: list[AuditEvent],
    ) -> None:
        """Aktualisiert alle Kacheln basierend auf den übergebenen Daten."""
        if engagement is None or (not datasets and not samples and not audit_events):
            self._stack.setCurrentWidget(self._empty_label)
            self._render_default_body()
            return

        self._stack.setCurrentWidget(self._stack.widget(0))
        self._render_datasets_tile(datasets)
        self._render_samples_tile(samples)
        self._render_events_tile(audit_events)
        self._render_last_activity_tile(audit_events)
        self._render_recent_samples_tile(samples)
        self._render_history_tile(samples)

    # ---- Renderer pro Kachel --------------------------------------------

    def _render_datasets_tile(self, datasets: list[Dataset]) -> None:
        label = _big_number_label(len(datasets), "Datensätze")
        self._tile_datasets.set_body_widget(label)

    def _render_samples_tile(self, samples: list[SampleResult]) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(_big_number_label(len(samples), "Stichproben"))

        method_counts: Counter[str] = Counter()
        for s in samples:
            method_counts[s.config.method.value] += 1
        if method_counts:
            labels = list(method_counts.keys())
            values = [float(method_counts[k]) for k in labels]
            pixmap = render_bar_chart(
                labels, values, title="Methoden", width=_CHART_WIDTH, height=_CHART_HEIGHT
            )
            chart_label = QLabel()
            chart_label.setPixmap(pixmap)
            chart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(chart_label)
        self._tile_samples.set_body_widget(container)

    def _render_events_tile(self, events: list[AuditEvent]) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(_big_number_label(len(events), "Events"))

        type_counts: Counter[str] = Counter()
        for e in events:
            type_counts[e.event_type] += 1
        if type_counts:
            top = type_counts.most_common(5)
            labels = [k for k, _ in top]
            values = [float(v) for _, v in top]
            pixmap = render_bar_chart(
                labels, values, title="Top-Eventtypen", width=_CHART_WIDTH, height=_CHART_HEIGHT
            )
            chart_label = QLabel()
            chart_label.setPixmap(pixmap)
            chart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(chart_label)
        self._tile_events.set_body_widget(container)

    def _render_last_activity_tile(self, events: list[AuditEvent]) -> None:
        if not events:
            self._tile_last_activity.set_body_widget(QLabel("—"))
            return
        latest = max(events, key=lambda e: e.timestamp)
        ts = _ensure_utc(latest.timestamp)
        absolute = ts.astimezone().strftime("%Y-%m-%d %H:%M")
        relative = _humanize_delta(datetime.now(UTC) - ts)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        absolute_label = QLabel(absolute)
        absolute_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #333333;")
        relative_label = QLabel(relative)
        relative_label.setStyleSheet("color: #7F7F7F;")
        layout.addWidget(absolute_label)
        layout.addWidget(relative_label)
        self._tile_last_activity.set_body_widget(container)

    def _render_recent_samples_tile(self, samples: list[SampleResult]) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        if not samples:
            layout.addWidget(_muted_label("Noch keine Stichproben gezogen."))
            self._tile_recent_samples.set_body_widget(container)
            return
        ordered = sorted(samples, key=lambda s: s.drawn_at, reverse=True)
        for sample in ordered[:_RECENT_SAMPLE_LIMIT]:
            if sample.id is None:
                continue
            drawn = _ensure_utc(sample.drawn_at).astimezone().strftime("%Y-%m-%d")
            text = f"#{sample.id} · {sample.config.method.value} · n={sample.actual_size} · {drawn}"
            row = _ClickableSampleLabel(text, sample.id)
            row.clicked.connect(self.sample_clicked.emit)
            layout.addWidget(row)
        self._tile_recent_samples.set_body_widget(container)

    def _render_history_tile(self, samples: list[SampleResult]) -> None:
        if not samples:
            self._tile_history.set_body_widget(_muted_label("Noch keine Sampling-Historie."))
            return
        labels, values = _samples_per_day(samples, _HISTORY_DAYS)
        pixmap = render_line_chart(
            labels, values, title="Stichproben pro Tag", width=_CHART_WIDTH, height=_CHART_HEIGHT
        )
        chart = QLabel()
        chart.setPixmap(pixmap)
        chart.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tile_history.set_body_widget(chart)

    def _render_default_body(self) -> None:
        """Leerer Zustand der Kacheln (vor dem ersten `set_data`)."""
        for tile in (
            self._tile_datasets,
            self._tile_samples,
            self._tile_events,
            self._tile_last_activity,
            self._tile_recent_samples,
            self._tile_history,
        ):
            tile.set_body_widget(_muted_label("—"))

    # ---- Accessors (Tests) ----------------------------------------------

    def datasets_tile(self) -> DashboardTile:
        return self._tile_datasets

    def samples_tile(self) -> DashboardTile:
        return self._tile_samples

    def events_tile(self) -> DashboardTile:
        return self._tile_events

    def recent_samples_tile(self) -> DashboardTile:
        return self._tile_recent_samples

    def history_tile(self) -> DashboardTile:
        return self._tile_history


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _big_number_label(value: int, label: str) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    number = QLabel(str(value))
    number.setStyleSheet("font-size: 28px; font-weight: 800; color: #E81A3B;")
    sub = QLabel(label)
    sub.setStyleSheet("color: #7F7F7F;")
    layout.addWidget(number)
    layout.addWidget(sub)
    return box


def _muted_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("color: #B0B0B0; font-style: italic;")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def _ensure_utc(ts: datetime) -> datetime:
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def _humanize_delta(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "vor wenigen Sekunden"
    if seconds < 3600:
        minutes = seconds // 60
        return f"vor {minutes} Minute{'n' if minutes != 1 else ''}"
    if seconds < 86400:
        hours = seconds // 3600
        return f"vor {hours} Stunde{'n' if hours != 1 else ''}"
    days = seconds // 86400
    return f"vor {days} Tag{'en' if days != 1 else ''}"


def _samples_per_day(
    samples: Iterable[SampleResult],
    days: int,
) -> tuple[list[str], list[float]]:
    """Aggregiert Sample-Counts pro Tag in den letzten `days` Tagen."""
    today = datetime.now(UTC).date()
    bins: defaultdict[str, int] = defaultdict(int)
    for sample in samples:
        d = _ensure_utc(sample.drawn_at).date()
        if (today - d).days < days:
            bins[d.isoformat()] += 1

    labels: list[str] = []
    values: list[float] = []
    for offset in range(days - 1, -1, -1):
        date_key = (today - timedelta(days=offset)).isoformat()
        labels.append(date_key[5:])  # MM-DD
        values.append(float(bins.get(date_key, 0)))
    return labels, values
