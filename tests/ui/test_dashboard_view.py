"""Tests für `DashboardView` – Kachel-Rendering, Click-Signals, Empty-State."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import (
    AuditEvent,
    Dataset,
    Engagement,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
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
