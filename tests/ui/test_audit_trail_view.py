"""Tests für `AuditTrailView` – Model, Proxy-Filter, Sortierung, Doppelklick."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from PyQt6.QtCore import QModelIndex, Qt
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import AuditEvent
from sampling_tool.ui.widgets.audit_trail_view import (
    AuditTrailModel,
    AuditTrailView,
)

pytestmark = pytest.mark.ui


def _make_event(
    *,
    event_type: str = "sampling",
    user: str = "anna",
    sample_id: int | None = 1,
    sample_size: int | None = 10,
    sample_percent: float | None = 25.0,
    seed: int | None = 42,
    import_file: str | None = None,
    export_file: str | None = None,
    timestamp: datetime | None = None,
    event_id: int | None = 1,
    corrects: int | None = None,
) -> AuditEvent:
    return AuditEvent(
        event_type=event_type,
        engagement_id=1,
        user_name=user,
        timestamp=timestamp if timestamp is not None else datetime.now(UTC),
        sample_id=sample_id,
        sample_size=sample_size,
        sample_percent=sample_percent,
        seed=seed,
        import_file=import_file,
        export_file=export_file,
        corrects_event_id=corrects,
        id=event_id,
    )


@pytest.fixture
def view(qtbot: QtBot) -> AuditTrailView:
    v = AuditTrailView()
    qtbot.addWidget(v)
    return v


class TestAuditTrailModel:
    def test_set_events_populates_rows(self, qtbot: QtBot) -> None:
        model = AuditTrailModel()
        events = [_make_event(event_id=1), _make_event(event_id=2, user="bob")]
        model.set_events(events)
        assert model.rowCount() == 2
        assert model.columnCount() == 8

    def test_users_returns_unique_sorted(self, qtbot: QtBot) -> None:
        model = AuditTrailModel()
        model.set_events(
            [
                _make_event(user="bob"),
                _make_event(user="anna", event_id=2),
                _make_event(user="anna", event_id=3),
            ]
        )
        assert model.users() == ["anna", "bob"]

    def test_event_at_returns_none_for_invalid_row(self, qtbot: QtBot) -> None:
        model = AuditTrailModel()
        model.set_events([_make_event()])
        assert model.event_at(99) is None
        assert model.event_at(0) is not None


class TestAuditTrailView:
    def test_empty_state_shown_initially(self, view: AuditTrailView) -> None:
        view.set_events([])
        assert view.visible_row_count() == 0

    def test_set_events_fills_table(self, view: AuditTrailView) -> None:
        view.set_events([_make_event(event_id=1), _make_event(event_id=2)])
        assert view.visible_row_count() == 2

    def test_action_filter_reduces_rows(self, view: AuditTrailView) -> None:
        events = [
            _make_event(event_type="sampling", event_id=1),
            _make_event(event_type="export", event_id=2),
            _make_event(event_type="import", event_id=3),
        ]
        view.set_events(events)
        view._action_combo.setCurrentIndex(view._action_combo.findData("export"))
        assert view.visible_row_count() == 1

    def test_user_filter_reduces_rows(self, view: AuditTrailView) -> None:
        events = [
            _make_event(user="anna", event_id=1),
            _make_event(user="bob", event_id=2),
            _make_event(user="anna", event_id=3),
        ]
        view.set_events(events)
        idx = view._user_combo.findData("anna")
        assert idx >= 0
        view._user_combo.setCurrentIndex(idx)
        assert view.visible_row_count() == 2

    def test_range_filter_today(self, view: AuditTrailView) -> None:
        events = [
            _make_event(event_id=1, timestamp=datetime.now(UTC)),
            _make_event(event_id=2, timestamp=datetime.now(UTC) - timedelta(days=10)),
        ]
        view.set_events(events)
        idx = view._range_combo.findData("Heute")
        view._range_combo.setCurrentIndex(idx)
        assert view.visible_row_count() == 1

    def test_search_filter_by_user(self, view: AuditTrailView) -> None:
        events = [
            _make_event(user="anna", event_id=1),
            _make_event(user="bob", event_id=2),
        ]
        view.set_events(events)
        view._search.setText("bob")
        assert view.visible_row_count() == 1

    def test_double_click_emits_event_id(self, view: AuditTrailView, qtbot: QtBot) -> None:
        events = [_make_event(event_id=42, sample_id=7)]
        view.set_events(events)
        proxy = view.proxy()
        index = proxy.index(0, 0)
        with qtbot.waitSignal(view.event_double_clicked, timeout=500) as blocker:
            view._on_double_click(index)
        assert blocker.args == [42]

    def test_double_click_invalid_index_is_noop(self, view: AuditTrailView) -> None:
        view.set_events([])
        view._on_double_click(QModelIndex())  # darf nicht crashen

    def test_sort_by_timestamp_descending_default(self, view: AuditTrailView) -> None:
        old = _make_event(event_id=1, timestamp=datetime(2026, 1, 1, tzinfo=UTC))
        new = _make_event(event_id=2, timestamp=datetime(2026, 5, 1, tzinfo=UTC))
        view.set_events([old, new])
        proxy = view.proxy()
        # Erste Zeile (nach Default-Sort) muss das jüngere Event sein.
        first_display = proxy.data(proxy.index(0, 0), Qt.ItemDataRole.DisplayRole)
        assert "2026-05" in first_display

    def test_refresh_button_emits_signal(self, view: AuditTrailView, qtbot: QtBot) -> None:
        with qtbot.waitSignal(view.refresh_requested, timeout=500):
            view._refresh_button.click()
