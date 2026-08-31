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

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
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

from sampling_tool.config import (
    BDO_DARK_GREY,
    BDO_GREY,
    BDO_LIGHT_GREY,
    BDO_RED,
    BDO_RED_INK,
    SURFACE_HOVER,
)
from sampling_tool.core.formatting import ensure_utc
from sampling_tool.core.models import AuditEvent, Dataset, Engagement, SampleResult
from sampling_tool.ui._dialog_buttons import mark_secondary
from sampling_tool.ui._scaling import scaled_px
from sampling_tool.ui._tile_layout import tile_columns, tile_rows
from sampling_tool.ui.widgets.chart_renderer import (
    render_bar_chart,
    render_line_chart,
)

# Obergrenze, nicht mehr die feste Spaltenzahl (Sprint 78 / B2): bis Sprint 77
# stand hier `_TILE_COLUMNS = 3` starr, und sechs Kacheln in drei Spalten
# brauchen mehr logische Breite, als ein 13-Zoll-Gerät bei 125 % Windows-
# Skalierung hat – der Nutzer bekam horizontales Scrollen statt Umbruch.
_MAX_TILE_COLUMNS: Final[int] = 3
_CHART_WIDTH: Final[int] = 360
_CHART_HEIGHT: Final[int] = 160
_RECENT_SAMPLE_LIMIT: Final[int] = 5
_HISTORY_DAYS: Final[int] = 30


class DashboardTile(QFrame):
    """Generische Kachel – Title + Body."""

    def __init__(
        self, title: str, parent: QWidget | None = None, *, ui_scale_factor: float = 1.0
    ) -> None:
        super().__init__(parent)
        self.setObjectName("DashboardTile")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setStyleSheet(
            f"QFrame#DashboardTile {{ background-color: white; border: 1px solid {BDO_LIGHT_GREY}; "
            "border-radius: 6px; padding: 8px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._title_label = QLabel(title)
        self._title_label.setStyleSheet(
            f"font-weight: 700; color: {BDO_DARK_GREY}; font-size: {scaled_px(12, ui_scale_factor)}px; "
            "text-transform: uppercase;"
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

    def set_ui_scale(self, factor: float) -> None:
        """Skaliert den Kachel-Titel neu (Sprint 68 / Teil B1)."""
        self._title_label.setStyleSheet(
            f"font-weight: 700; color: {BDO_DARK_GREY}; font-size: {scaled_px(12, factor)}px; "
            "text-transform: uppercase;"
        )


class _ClickableSampleLabel(QLabel):
    """Label, das beim Klick die Sample-ID emittiert."""

    clicked = pyqtSignal(int)

    def __init__(self, text: str, sample_id: int, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._sample_id = sample_id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QLabel {{ color: {BDO_DARK_GREY}; padding: 4px; }}"
            f"QLabel:hover {{ background-color: {SURFACE_HOVER}; color: {BDO_RED_INK}; }}"
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

    def __init__(self, parent: QWidget | None = None, *, ui_scale_factor: float = 1.0) -> None:
        super().__init__(parent)
        self._factor = ui_scale_factor
        self._last_data: (
            tuple[Engagement | None, list[Dataset], list[SampleResult], list[AuditEvent]] | None
        ) = None
        self.setObjectName("DashboardView")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # Refresh-Zeile oben.
        head_row = QHBoxLayout()
        head_row.addStretch(1)
        self._refresh_button = QPushButton("Aktualisieren")
        # Sprint 81: „Aktualisieren" zeichnet nur neu, was schon da ist – es
        # erzeugt nichts. Rot bleibt den Aktionen vorbehalten, die etwas
        # erzeugen; im Hauptfenster konkurrierte dieser Button sonst mit den
        # roten Tabellenköpfen direkt darüber.
        mark_secondary(self._refresh_button)
        self._refresh_button.clicked.connect(self.refresh_requested.emit)
        head_row.addWidget(self._refresh_button)
        outer.addLayout(head_row)

        self._stack = QStackedWidget()

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._content = QWidget()
        self._scroll.setWidget(self._content)

        self._grid = QGridLayout(self._content)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(10)

        # Kacheln (initial leer, set_data füllt sie).
        self._tile_datasets = DashboardTile("Datasets", ui_scale_factor=self._factor)
        self._tile_samples = DashboardTile("Samples", ui_scale_factor=self._factor)
        self._tile_events = DashboardTile("Audit-Events", ui_scale_factor=self._factor)
        self._tile_last_activity = DashboardTile("Letzte Aktivität", ui_scale_factor=self._factor)
        self._tile_recent_samples = DashboardTile(
            "Letzte Stichproben", ui_scale_factor=self._factor
        )
        self._tile_history = DashboardTile(
            "Sampling-Historie (30 Tage)", ui_scale_factor=self._factor
        )

        self._tiles: tuple[DashboardTile, ...] = (
            self._tile_datasets,
            self._tile_samples,
            self._tile_events,
            self._tile_last_activity,
            self._tile_recent_samples,
            self._tile_history,
        )
        # `_columns = 0` heißt "noch nie gelegt" – `_place_tiles` unten legt zum
        # ersten Mal, danach wird nur noch bei echter Änderung neu gelegt (§2.8).
        self._columns = 0
        self._stretch_row: int | None = None
        self._place_tiles(_MAX_TILE_COLUMNS)

        # Der Viewport meldet seine Größenänderungen selbst – siehe eventFilter.
        viewport = self._scroll.viewport()
        if viewport is not None:
            viewport.installEventFilter(self)

        self._stack.addWidget(self._scroll)

        self._empty_label = QLabel(
            "Projekt leer – starte mit einem Datei-Import, um Statistiken zu sehen."
        )
        # Ohne Wortumbruch ist die Mindestbreite eines QLabel die VOLLE
        # Textbreite. Dieses Label liegt im selben QStackedWidget wie das
        # Kachelgitter, und ein QStackedWidget nimmt das Maximum über alle
        # Seiten – die Textbreite wurde damit zur Mindestbreite des ganzen
        # Dashboards und verhinderte genau das Schmalerwerden, um das es in
        # diesem Sprint geht. Der Wert ist schrift- und plattformabhängig
        # (offscreen/macOS 405 px, Windows deutlich mehr), weshalb der
        # Kachel-Umbruch auf Windows in eine andere Spaltenzahl lief als auf
        # macOS. Mit Wortumbruch sinkt die Mindestbreite auf das längste Wort
        # (62 px gemessen); bei normaler Fensterbreite bleibt der Text
        # einzeilig und das Erscheinungsbild unverändert.
        self._empty_label.setWordWrap(True)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(f"color: {BDO_GREY}; font-style: italic; padding: 24px;")
        self._stack.addWidget(self._empty_label)

        outer.addWidget(self._stack, stretch=1)

        self._stack.setCurrentWidget(self._empty_label)
        self._render_default_body()

    # ---- Kachel-Umbruch (Sprint 78 / B2) --------------------------------

    def eventFilter(self, obj: QObject | None, event: QEvent | None) -> bool:  # noqa: N802
        """Reagiert auf die Größenänderung des Scroll-Viewports.

        Bewusst NICHT auf `resizeEvent` dieses Widgets: Qt legt versteckte
        Widgets nicht aus, der Viewport hinkt der View-Breite dann hinterher
        (gemessen: View 1600 px, Viewport noch 638 px). Ein Umbruch auf Basis
        dieser veralteten Zahl legt die Kacheln zweimal – erst falsch, dann
        korrigiert – und das ist genau das Flackern, das §2.8 verbietet.
        Der Viewport ist die Größe, um die es geht; er meldet sich selbst, auch
        wenn die Änderung von `show()` oder vom Splitter kommt.
        """
        if (
            event is not None
            and event.type() == QEvent.Type.Resize
            and obj is self._scroll.viewport()
        ):
            self._apply_responsive_columns()
        return super().eventFilter(obj, event)

    def _apply_responsive_columns(self) -> None:
        """Legt die Kacheln neu – aber nur, wenn sich die Spaltenzahl ändert.

        §2.8: ein `resizeEvent`, das bei jedem Pixel alle Kacheln aus dem Grid
        nimmt und neu einhängt, flackert sichtbar und kostet unnötig Zeit.
        """
        columns = self._responsive_columns()
        if columns == self._columns:
            return
        self._place_tiles(columns)

    def _responsive_columns(self) -> int:
        viewport = self._scroll.viewport()
        available = viewport.width() if viewport is not None else self.width()
        left, _, right, _ = self._grid.getContentsMargins()
        return tile_columns(
            available_width=available,
            tile_min_width=self._tile_min_width(),
            spacing=self._grid.spacing(),
            margins=left + right,
            max_columns=_MAX_TILE_COLUMNS,
        )

    def _tile_min_width(self) -> int:
        """Breite, die die breiteste Kachel wirklich braucht – gemessen, nicht geschätzt.

        §2.10 verlangt, dass mit derselben Breite gerechnet wird, mit der die
        Kachel tatsächlich gebaut wird. Der Wert wird deshalb bei den Kacheln
        selbst erfragt statt aus `_CHART_WIDTH` abgeleitet: so stecken Rahmen,
        Padding und – über die skalierten QSS-Schriftgrößen – die UI-Größe
        automatisch mit drin, ohne einen zweiten Skalierungsweg einzuführen.

        Bewusst das MAXIMUM über alle Kacheln: welche Kachel in welcher Spalte
        landet, hängt von der Spaltenzahl ab, die hier gerade erst berechnet
        wird. Nur ein zuordnungsunabhängiger Wert kann garantieren, dass keine
        Kachel in ihrer Spalte überläuft.
        """
        widths = [tile.minimumSizeHint().width() for tile in self._tiles]
        return max([*widths, 1])

    def _place_tiles(self, columns: int) -> None:
        """Hängt alle Kacheln in `columns` Spalten neu ins Grid."""
        for tile in self._tiles:
            self._grid.removeWidget(tile)
        for index, tile in enumerate(self._tiles):
            row, col = divmod(index, columns)
            self._grid.addWidget(tile, row, col)

        # §2.7: der Stretch der VORHER gedehnten Zeile muss zurückgenommen
        # werden – sonst sammeln sich bei jedem Umbruch Stretch-Werte auf alten
        # Zeilen an und das Gitter dehnt an mehreren Stellen gleichzeitig.
        if self._stretch_row is not None:
            self._grid.setRowStretch(self._stretch_row, 0)
        last_row = tile_rows(len(self._tiles), columns) - 1
        self._grid.setRowStretch(last_row, 1)
        self._stretch_row = last_row

        # Spalten jenseits der aktuellen Zahl dürfen keinen Platz mehr
        # beanspruchen. 0 ist auch der Qt-Default – die Zeile ist damit für den
        # 3-Spalten-Fall wirkungslos und hält die Sicherheitslinie aus §2.2.
        for col in range(columns, _MAX_TILE_COLUMNS):
            self._grid.setColumnStretch(col, 0)

        self._columns = columns

    def _chart_ratio(self) -> float:
        """Device-Pixel-Ratio des Bildschirms, auf dem dieses Widget liegt.

        Die einzige Stelle im Chart-Pfad, die einen echten Bildschirmwert liest.
        Unter `QT_QPA_PLATFORM=offscreen` ist er immer 1.0 – genau deshalb ist
        die Rechenlogik darüber (`io/charts.py`) parametrisiert und fragt nicht
        selbst ab (§2.1).
        """
        return float(self.devicePixelRatioF())

    def tile_columns_count(self) -> int:
        """Aktuelle Spaltenzahl des Kachelgitters (Tests)."""
        return self._columns

    # ---- Public API -----------------------------------------------------

    def set_data(
        self,
        engagement: Engagement | None,
        datasets: list[Dataset],
        samples: list[SampleResult],
        audit_events: list[AuditEvent],
    ) -> None:
        """Aktualisiert alle Kacheln basierend auf den übergebenen Daten."""
        self._last_data = (engagement, datasets, samples, audit_events)
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
        # Der Kachel-Inhalt bestimmt die Mindestbreite – nach dem Füllen kann
        # eine andere Spaltenzahl richtig sein als davor.
        self._apply_responsive_columns()

    # ---- Renderer pro Kachel --------------------------------------------

    def _render_datasets_tile(self, datasets: list[Dataset]) -> None:
        label = _big_number_label(len(datasets), "Datensätze", self._factor)
        self._tile_datasets.set_body_widget(label)

    def _render_samples_tile(self, samples: list[SampleResult]) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(_big_number_label(len(samples), "Stichproben", self._factor))

        method_counts: Counter[str] = Counter()
        for s in samples:
            method_counts[s.config.method.value] += 1
        if method_counts:
            labels = list(method_counts.keys())
            values = [float(method_counts[k]) for k in labels]
            pixmap = render_bar_chart(
                labels,
                values,
                title="Methoden",
                width=_CHART_WIDTH,
                height=_CHART_HEIGHT,
                device_pixel_ratio=self._chart_ratio(),
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
        layout.addWidget(_big_number_label(len(events), "Events", self._factor))

        type_counts: Counter[str] = Counter()
        for e in events:
            type_counts[e.event_type] += 1
        if type_counts:
            top = type_counts.most_common(5)
            labels = [k for k, _ in top]
            values = [float(v) for _, v in top]
            pixmap = render_bar_chart(
                labels,
                values,
                title="Top-Eventtypen",
                width=_CHART_WIDTH,
                height=_CHART_HEIGHT,
                device_pixel_ratio=self._chart_ratio(),
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
        ts = ensure_utc(latest.timestamp)
        absolute = ts.astimezone().strftime("%Y-%m-%d %H:%M")
        relative = _humanize_delta(datetime.now(UTC) - ts)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        absolute_label = QLabel(absolute)
        absolute_label.setStyleSheet(
            f"font-size: {scaled_px(16, self._factor)}px; font-weight: 700; color: {BDO_DARK_GREY};"
        )
        relative_label = QLabel(relative)
        relative_label.setStyleSheet(f"color: {BDO_GREY};")
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
            drawn = ensure_utc(sample.drawn_at).astimezone().strftime("%Y-%m-%d")
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
            labels,
            values,
            title="Stichproben pro Tag",
            width=_CHART_WIDTH,
            height=_CHART_HEIGHT,
            device_pixel_ratio=self._chart_ratio(),
        )
        chart = QLabel()
        chart.setPixmap(pixmap)
        chart.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tile_history.set_body_widget(chart)

    def _render_default_body(self) -> None:
        """Leerer Zustand der Kacheln (vor dem ersten `set_data`)."""
        for tile in self._tiles:
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

    def set_ui_scale(self, factor: float) -> None:
        """Wendet einen neuen UI-Skalierungsfaktor sofort an (Sprint 68 / Teil B1)."""
        self._factor = factor
        for tile in self._tiles:
            tile.set_ui_scale(factor)
        if self._last_data is not None:
            self.set_data(*self._last_data)


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _big_number_label(value: int, label: str, factor: float = 1.0) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    number = QLabel(str(value))
    number.setStyleSheet(
        f"font-size: {scaled_px(28, factor)}px; font-weight: 800; color: {BDO_RED};"
    )
    sub = QLabel(label)
    sub.setStyleSheet(f"color: {BDO_GREY};")
    layout.addWidget(number)
    layout.addWidget(sub)
    return box


def _muted_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color: {BDO_GREY}; font-style: italic;")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


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
        d = ensure_utc(sample.drawn_at).date()
        if (today - d).days < days:
            bins[d.isoformat()] += 1

    labels: list[str] = []
    values: list[float] = []
    for offset in range(days - 1, -1, -1):
        date_key = (today - timedelta(days=offset)).isoformat()
        labels.append(date_key[5:])  # MM-DD
        values.append(float(bins.get(date_key, 0)))
    return labels, values
