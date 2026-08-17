"""Tests für `DashboardView` – Kachel-Rendering, Click-Signals, Empty-State."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import (
    AuditEvent,
    Dataset,
    Engagement,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.ui._tile_layout import tile_rows
from sampling_tool.ui.widgets.dashboard_view import DashboardView, _ClickableSampleLabel

pytestmark = pytest.mark.ui


def _engagement() -> Engagement:
    return Engagement(auditor_name="anna", client_name="ACME", id=1)


def _dataset(ds_id: int = 1) -> Dataset:
    return Dataset(
        name=f"DS{ds_id}",
        columns=("a",),
        engagement_id=1,
        id=ds_id,
    )


def _sample(
    sample_id: int,
    method: SamplingMethod = SamplingMethod.SIMPLE,
    when: datetime | None = None,
) -> SampleResult:
    cfg = SampleConfig(method=method, size=5, seed=1)
    return SampleResult(
        config=cfg,
        selected_row_ids=(1, 2, 3),
        population_size=10,
        drawn_at=when if when is not None else datetime.now(UTC),
        id=sample_id,
    )


def _event(event_id: int, event_type: str = "sampling", when: datetime | None = None) -> AuditEvent:
    return AuditEvent(
        event_type=event_type,
        engagement_id=1,
        timestamp=when if when is not None else datetime.now(UTC),
        id=event_id,
    )


@pytest.fixture
def view(qtbot: QtBot) -> DashboardView:
    v = DashboardView()
    qtbot.addWidget(v)
    return v


def _settle(view: DashboardView, width: int, qtbot: QtBot) -> None:
    """Fenster auf `width` bringen und die Layout-Runde abwarten.

    Das Widget MUSS sichtbar sein: Qt legt versteckte Widgets nicht aus, der
    Scroll-Viewport hinkt dann der Fensterbreite hinterher (gemessen: Fenster
    1600 px, Viewport noch 638 px) und der Umbruch rechnete mit einer Zahl, die
    nichts mit dem Bildschirm zu tun hat.
    """
    view.resize(width, 800)
    qtbot.waitUntil(lambda: view.isVisible(), timeout=2000)
    QApplication.processEvents()


def _occupied_rows(view: DashboardView) -> set[int]:
    grid = view._grid
    rows = set()
    for index in range(grid.count()):
        item = grid.itemAt(index)
        if item is not None and item.widget() is not None:
            rows.add(grid.getItemPosition(index)[0])
    return rows


def _stretched_rows(view: DashboardView) -> list[int]:
    grid = view._grid
    return [row for row in range(grid.rowCount()) if grid.rowStretch(row) != 0]


@pytest.fixture
def wide_view(qtbot: QtBot) -> DashboardView:
    """Sichtbares Dashboard mit Daten – Ausgangslage für die Umbruch-Tests."""
    v = DashboardView()
    qtbot.addWidget(v)
    v.resize(1600, 800)
    v.show()
    qtbot.waitExposed(v)
    v.set_data(_engagement(), [_dataset()], [_sample(1)], [_event(1)])
    QApplication.processEvents()
    return v


class TestTileWrapping:
    """Kachel-Umbruch statt horizontalem Scrollen (Sprint 78 / B2)."""

    def _width_for(self, view: DashboardView, columns: int) -> int:
        """Fensterbreite, bei der `columns` Spalten sicher passen.

        Aus der GEMESSENEN Kachel-Mindestbreite abgeleitet statt als
        Pixel-Konstante hingeschrieben – die hängt an Fontmetriken und wäre auf
        einer anderen Plattform aus dem falschen Grund rot.
        """
        tile = view._tile_min_width()
        spacing = view._grid.spacing()
        chrome = 80  # Fensterrand + Scrollbar-Reserve, großzügig
        return columns * tile + (columns - 1) * spacing + chrome

    def test_wide_window_shows_exactly_three_columns(
        self, wide_view: DashboardView, qtbot: QtBot
    ) -> None:
        """🔒 Sicherheitslinie §2.2: wo drei Spalten passen, sind es genau drei."""
        _settle(wide_view, self._width_for(wide_view, 3), qtbot)
        assert wide_view.tile_columns_count() == 3

    def test_narrow_window_wraps_instead_of_overflowing(
        self, wide_view: DashboardView, qtbot: QtBot
    ) -> None:
        _settle(wide_view, self._width_for(wide_view, 2), qtbot)
        assert wide_view.tile_columns_count() == 2

    def test_very_narrow_window_falls_back_to_one_column(
        self, wide_view: DashboardView, qtbot: QtBot
    ) -> None:
        _settle(wide_view, self._width_for(wide_view, 1), qtbot)
        assert wide_view.tile_columns_count() == 1

    def test_content_never_needs_more_width_than_the_viewport(
        self, wide_view: DashboardView, qtbot: QtBot
    ) -> None:
        """Der eigentliche Zweck: kein horizontales Scrollen mehr.

        Vor Sprint 78 verlangte das Gitter bei drei festen Spalten mehr Breite,
        als der Viewport hatte – genau das war der Befund.
        """
        _settle(wide_view, self._width_for(wide_view, 1), qtbot)
        viewport = wide_view._scroll.viewport()
        assert viewport is not None
        assert wide_view._content.minimumSizeHint().width() <= viewport.width()

    def test_all_six_tiles_survive_every_wrap(self, wide_view: DashboardView, qtbot: QtBot) -> None:
        """Keine Kachel darf beim Neu-Einhängen ihren Platz verlieren."""
        for columns in (3, 2, 1, 2, 3):
            _settle(wide_view, self._width_for(wide_view, columns), qtbot)
            in_grid = {
                wide_view._grid.itemAt(i).widget()  # type: ignore[union-attr]
                for i in range(wide_view._grid.count())
            }
            for tile in wide_view._tiles:
                assert tile in in_grid, f"Kachel fehlt bei {columns} Spalten"
            assert wide_view._grid.count() == len(wide_view._tiles)


class TestRowStretch:
    """§2.7: der Stretch muss der berechneten Zeilenzahl folgen."""

    def _width_for(self, view: DashboardView, columns: int) -> int:
        return TestTileWrapping()._width_for(view, columns)

    def test_stretch_sits_on_the_last_occupied_row(
        self, wide_view: DashboardView, qtbot: QtBot
    ) -> None:
        for columns in (3, 2, 1):
            _settle(wide_view, self._width_for(wide_view, columns), qtbot)
            stretched = _stretched_rows(wide_view)
            assert stretched == [max(_occupied_rows(wide_view))], (
                f"{columns} Spalten: Stretch auf {stretched}"
            )

    def test_no_stretch_accumulates_across_two_wraps(
        self, wide_view: DashboardView, qtbot: QtBot
    ) -> None:
        """Zwei Umbrüche hintereinander dürfen keine Stretch-Werte auf alten
        Zeilen zurücklassen – sonst dehnt das Gitter an mehreren Stellen."""
        _settle(wide_view, self._width_for(wide_view, 3), qtbot)
        _settle(wide_view, self._width_for(wide_view, 1), qtbot)
        _settle(wide_view, self._width_for(wide_view, 2), qtbot)
        assert len(_stretched_rows(wide_view)) == 1

    def test_stretch_row_matches_the_pure_function(
        self, wide_view: DashboardView, qtbot: QtBot
    ) -> None:
        for columns in (3, 2, 1):
            _settle(wide_view, self._width_for(wide_view, columns), qtbot)
            expected = tile_rows(len(wide_view._tiles), wide_view.tile_columns_count()) - 1
            assert _stretched_rows(wide_view) == [expected]


class TestRelayoutIsAvoidedWhenNothingChanges:
    """§2.8: kein Neu-Einhängen, solange die Spaltenzahl gleich bleibt."""

    def test_small_resize_within_a_column_step_does_not_relayout(
        self, wide_view: DashboardView, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base = TestTileWrapping()._width_for(wide_view, 3)
        _settle(wide_view, base, qtbot)

        calls: list[int] = []
        original = wide_view._place_tiles

        def _spy(columns: int) -> None:
            calls.append(columns)
            original(columns)

        monkeypatch.setattr(wide_view, "_place_tiles", _spy)
        for delta in range(0, 40, 4):
            _settle(wide_view, base + delta, qtbot)
        assert calls == [], f"Unnötiges Neu-Legen: {calls}"


class TestDashboardView:
    def test_empty_state_shown_when_no_data(self, view: DashboardView) -> None:
        view.set_data(None, [], [], [])
        assert view._stack.currentWidget() is view._empty_label

    def test_set_data_switches_off_empty_state(self, view: DashboardView) -> None:
        view.set_data(_engagement(), [_dataset()], [_sample(1)], [_event(1)])
        assert view._stack.currentWidget() is not view._empty_label

    def test_datasets_count_rendered(self, view: DashboardView) -> None:
        view.set_data(_engagement(), [_dataset(1), _dataset(2)], [], [_event(1)])
        # Tile-Body enthält Big-Number-Label mit "2"
        tile = view.datasets_tile()
        children = [c.text() for c in tile.findChildren(type(tile._title_label))]
        assert "2" in children

    def test_recent_samples_emits_sample_clicked(self, view: DashboardView, qtbot: QtBot) -> None:
        view.set_data(_engagement(), [_dataset()], [_sample(7)], [_event(1)])
        # Sichtbares ClickableLabel finden und programmatisch emittieren.
        labels = view.recent_samples_tile().findChildren(_ClickableSampleLabel)
        assert labels, "Sample-Klick-Label sollte angelegt sein"
        with qtbot.waitSignal(view.sample_clicked, timeout=500) as blocker:
            labels[0].clicked.emit(labels[0]._sample_id)
        assert blocker.args == [7]

    def test_refresh_button_emits_signal(self, view: DashboardView, qtbot: QtBot) -> None:
        with qtbot.waitSignal(view.refresh_requested, timeout=500):
            view._refresh_button.click()

    def test_history_handles_old_samples(self, view: DashboardView) -> None:
        old = _sample(1, when=datetime.now(UTC) - timedelta(days=60))
        recent = _sample(2, when=datetime.now(UTC))
        # Darf nicht crashen, auch wenn alte Samples > Fenster sind.
        view.set_data(_engagement(), [_dataset()], [old, recent], [_event(1)])
        # History-Kachel enthält ein QLabel mit Pixmap.
        history = view.history_tile()
        from PyQt6.QtWidgets import QLabel

        chart_labels = history.findChildren(QLabel)
        has_chart = any(
            lbl.pixmap() is not None and not lbl.pixmap().isNull() for lbl in chart_labels
        )
        assert has_chart


class TestUiScale:
    """Sprint 68 / Teil B1: Kachel-Titel + Big-Number-Labels folgen dem Faktor."""

    def test_default_factor_matches_base_size(self, view: DashboardView) -> None:
        assert "font-size: 12px" in view.datasets_tile()._title_label.styleSheet()

    def test_set_ui_scale_updates_tile_titles(self, view: DashboardView) -> None:
        view.set_ui_scale(1.15)
        assert "font-size: 14px" in view.datasets_tile()._title_label.styleSheet()

    def test_set_ui_scale_rerenders_cached_body(self, view: DashboardView) -> None:
        view.set_data(_engagement(), [_dataset(1), _dataset(2)], [], [_event(1)])
        view.set_ui_scale(1.15)
        tile = view.datasets_tile()
        # Big-Number-Label (28px-Basis) muss nach Re-Render die 2 weiterhin zeigen,
        # jetzt mit skalierter font-size.
        labels = [c for c in tile.findChildren(type(tile._title_label)) if c.text() == "2"]
        assert labels
        assert "font-size: 32px" in labels[0].styleSheet()

    def test_set_ui_scale_without_data_does_not_crash(self, view: DashboardView) -> None:
        view.set_ui_scale(0.9)  # kein set_data() zuvor – darf nicht crashen.
        assert "font-size: 11px" in view.datasets_tile()._title_label.styleSheet()
