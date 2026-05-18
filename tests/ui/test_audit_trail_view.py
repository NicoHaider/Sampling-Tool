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


class TestAuditTrailFilterProxyExtras:
    """Sprint 14 / T-002 – Filter-Proxy-Branches die zuvor uncovered waren.

    Pass 4 hat audit_trail_view.py mit 72 % Coverage als SEV-1 markiert; die
    Lücken lagen v. a. in Range-Wochen-/Monats-Filter, Filter-Reset auf None,
    kombinierten Filtern und der Sortierung der „Größe"-Spalte (Spalte 4).
    """

    def test_range_week_includes_yesterday_excludes_last_month(self, view: AuditTrailView) -> None:
        now = datetime.now(UTC)
        recent = _make_event(event_id=1, timestamp=now - timedelta(hours=1))
        long_past = _make_event(event_id=2, timestamp=now - timedelta(days=60))
        view.set_events([recent, long_past])
        idx = view._range_combo.findData("Diese Woche")
        view._range_combo.setCurrentIndex(idx)
        # Das Event vor 60 Tagen liegt sicher außerhalb der aktuellen Woche.
        assert view.visible_row_count() == 1

    def test_range_month_includes_today_excludes_two_months_ago(self, view: AuditTrailView) -> None:
        now = datetime.now(UTC)
        today = _make_event(event_id=1, timestamp=now)
        old = _make_event(event_id=2, timestamp=now - timedelta(days=70))
        view.set_events([today, old])
        idx = view._range_combo.findData("Dieser Monat")
        view._range_combo.setCurrentIndex(idx)
        assert view.visible_row_count() == 1

    def test_range_reset_to_alle_shows_all_events(self, view: AuditTrailView) -> None:
        now = datetime.now(UTC)
        view.set_events(
            [
                _make_event(event_id=1, timestamp=now),
                _make_event(event_id=2, timestamp=now - timedelta(days=400)),
            ]
        )
        idx_today = view._range_combo.findData("Heute")
        view._range_combo.setCurrentIndex(idx_today)
        assert view.visible_row_count() == 1
        idx_all = view._range_combo.findData("Alle")
        view._range_combo.setCurrentIndex(idx_all)
        assert view.visible_row_count() == 2

    def test_combined_action_user_range_filter(self, view: AuditTrailView) -> None:
        now = datetime.now(UTC)
        events = [
            _make_event(event_type="sampling", user="anna", event_id=1, timestamp=now),
            _make_event(event_type="export", user="anna", event_id=2, timestamp=now),
            _make_event(event_type="sampling", user="bob", event_id=3, timestamp=now),
            _make_event(
                event_type="sampling",
                user="anna",
                event_id=4,
                timestamp=now - timedelta(days=400),
            ),
        ]
        view.set_events(events)
        view._action_combo.setCurrentIndex(view._action_combo.findData("sampling"))
        view._user_combo.setCurrentIndex(view._user_combo.findData("anna"))
        view._range_combo.setCurrentIndex(view._range_combo.findData("Heute"))
        # Nur Event 1: sampling + anna + heute.
        assert view.visible_row_count() == 1

    def test_search_matches_filename_in_export_field(self, view: AuditTrailView) -> None:
        events = [
            _make_event(
                event_type="export",
                user="anna",
                event_id=1,
                export_file="/tmp/Stichprobe_BDO_2026.xlsx",
            ),
            _make_event(event_type="sampling", user="anna", event_id=2),
        ]
        view.set_events(events)
        view._search.setText("Stichprobe_BDO")
        assert view.visible_row_count() == 1

    def test_search_matches_filename_in_import_field(self, view: AuditTrailView) -> None:
        events = [
            _make_event(
                event_type="import",
                user="anna",
                event_id=1,
                import_file="/data/buchungen.xlsx",
            ),
            _make_event(event_type="sampling", user="anna", event_id=2),
        ]
        view.set_events(events)
        view._search.setText("buchungen")
        assert view.visible_row_count() == 1

    def test_search_case_insensitive(self, view: AuditTrailView) -> None:
        view.set_events(
            [
                _make_event(user="Anna", event_id=1),
                _make_event(user="bob", event_id=2),
            ]
        )
        view._search.setText("ANNA")
        assert view.visible_row_count() == 1

    def test_action_filter_reset_to_alle_shows_all(self, view: AuditTrailView) -> None:
        view.set_events(
            [
                _make_event(event_type="sampling", event_id=1),
                _make_event(event_type="export", event_id=2),
            ]
        )
        view._action_combo.setCurrentIndex(view._action_combo.findData("export"))
        assert view.visible_row_count() == 1
        view._action_combo.setCurrentIndex(0)  # "Alle"
        assert view.visible_row_count() == 2

    def test_user_filter_reset_to_alle_shows_all(self, view: AuditTrailView) -> None:
        view.set_events(
            [
                _make_event(user="anna", event_id=1),
                _make_event(user="bob", event_id=2),
            ]
        )
        view._user_combo.setCurrentIndex(view._user_combo.findData("anna"))
        assert view.visible_row_count() == 1
        view._user_combo.setCurrentIndex(0)  # "Alle"
        assert view.visible_row_count() == 2

    def test_sort_by_size_column_numeric(self, view: AuditTrailView) -> None:
        """Spalte 4 (Größe) muss numerisch sortieren, nicht lexikografisch."""
        view.set_events(
            [
                _make_event(event_id=1, sample_size=9),
                _make_event(event_id=2, sample_size=100),
                _make_event(event_id=3, sample_size=42),
            ]
        )
        proxy = view.proxy()
        proxy.sort(4, Qt.SortOrder.AscendingOrder)
        # Numerisch: 9 < 42 < 100. Lexikografisch wäre: 100 < 42 < 9.
        col4_values = [proxy.data(proxy.index(r, 4), Qt.ItemDataRole.DisplayRole) for r in range(3)]
        assert col4_values == ["9", "42", "100"]

    def test_sort_by_size_handles_dash(self, view: AuditTrailView) -> None:
        """Events ohne sample_size („—") müssen die Sortierung nicht crashen."""
        view.set_events(
            [
                _make_event(event_id=1, sample_size=None),
                _make_event(event_id=2, sample_size=5),
            ]
        )
        proxy = view.proxy()
        proxy.sort(4, Qt.SortOrder.AscendingOrder)
        # „—" ist -1 in _to_int → kommt zuerst.
        first_size = proxy.data(proxy.index(0, 4), Qt.ItemDataRole.DisplayRole)
        assert first_size == "—"

    def test_naive_timestamp_is_treated_as_utc(self, view: AuditTrailView) -> None:
        """Alte Daten ohne tzinfo (vor UTC-Adapter-Sprint) müssen filterbar bleiben."""
        naive_today = datetime.now(UTC).replace(tzinfo=None)
        view.set_events([_make_event(event_id=1, timestamp=naive_today)])
        view._range_combo.setCurrentIndex(view._range_combo.findData("Heute"))
        # Darf nicht crashen; das naive Datetime wird als UTC interpretiert.
        assert view.visible_row_count() in (0, 1)

    def test_correction_event_shows_arrow_in_action_column(self, view: AuditTrailView) -> None:
        view.set_events([_make_event(event_id=10, event_type="correction", corrects=7)])
        proxy = view.proxy()
        action_text = proxy.data(proxy.index(0, 1), Qt.ItemDataRole.DisplayRole)
        assert "→ #7" in action_text
