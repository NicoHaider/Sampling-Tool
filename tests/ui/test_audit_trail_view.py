"""Tests für `AuditTrailView` – Model, Proxy-Filter, Sortierung, Doppelklick."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from PyQt6.QtCore import QModelIndex, Qt
from pytestqt.qtbot import QtBot

from sampling_tool.core.formatting import format_optional_timestamp
from sampling_tool.core.models import AuditEvent
from sampling_tool.ui.widgets import audit_trail_view
from sampling_tool.ui.widgets.audit_trail_view import (
    _FILTER_ALL,
    _RANGE_MONTH,
    _RANGE_TODAY,
    _RANGE_WEEK,
    AuditTrailModel,
    AuditTrailView,
)

pytestmark = pytest.mark.ui

# ---------------------------------------------------------------------------
# Sprint 73: eingefrorene Testuhr
# ---------------------------------------------------------------------------
# Vorher rechneten Tests UND Produktionsfilter je gegen ihre eigene
# `datetime.now(UTC)`. Der Zeitraum-Filter vergleicht aber gegen KALENDER-
# grenzen (Montag 00:00, Monatserster) – in der ersten Stunde jedes Montags
# lag ein "vor 1 Stunde"-Event damit in der Vorwoche und
# `test_range_week_includes_yesterday_excludes_last_month` wurde auf allen drei
# OS rot (PR #105).
#
# Anker: Mittwoch, Wochenmitte, Monatsmitte, Jahresmitte – maximal weit von
# jeder Grenze entfernt. SSOT für alle zeitrelativen Zeitpunkte dieser Datei:
# abgeleitet wird per `timedelta`/`replace`, NIE per zweitem Datums-Literal.
FROZEN_NOW: Final = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)

# Montag 00:00 UTC der Woche, in der FROZEN_NOW liegt (= 2026-05-11).
_WEEK_START: Final = (FROZEN_NOW - timedelta(days=FROZEN_NOW.weekday())).replace(
    hour=0, minute=0, second=0, microsecond=0
)

# Grenz-Anker, alle von FROZEN_NOW abgeleitet.
MONDAY_AFTER_MIDNIGHT: Final = _WEEK_START.replace(minute=30)  # Mo 2026-05-11 00:30
WEDNESDAY_MIDDAY: Final = FROZEN_NOW  # Mi 2026-05-13 12:00
SUNDAY_BEFORE_MIDNIGHT: Final = (_WEEK_START + timedelta(days=6)).replace(
    hour=23, minute=30
)  # So 2026-05-17 23:30
NEW_YEAR_AFTER_MIDNIGHT: Final = FROZEN_NOW.replace(
    month=1, day=1, hour=0, minute=30
)  # Do 2026-01-01 00:30
FIRST_OF_MONTH_AFTER_MIDNIGHT: Final = FROZEN_NOW.replace(
    day=1, hour=0, minute=30
)  # Fr 2026-05-01 00:30
JUST_BEFORE_MIDNIGHT: Final = FROZEN_NOW.replace(hour=23, minute=59, second=30)

# Wiederholungs-Gate (§5.4): derselbe Test an vier Kalender-Positionen.
_WEEK_GATE_ANCHORS = [
    pytest.param(MONDAY_AFTER_MIDNIGHT, id="montag-00-30"),
    pytest.param(WEDNESDAY_MIDDAY, id="mittwoch-12-00"),
    pytest.param(SUNDAY_BEFORE_MIDNIGHT, id="sonntag-23-30"),
    pytest.param(NEW_YEAR_AFTER_MIDNIGHT, id="1-januar-00-30"),
]


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
        timestamp=timestamp if timestamp is not None else FROZEN_NOW,
        sample_id=sample_id,
        sample_size=sample_size,
        sample_percent=sample_percent,
        seed=seed,
        import_file=import_file,
        export_file=export_file,
        corrects_event_id=corrects,
        id=event_id,
    )


def _view_at(qtbot: QtBot, now: datetime) -> AuditTrailView:
    """View mit auf `now` eingefrorener Uhr."""
    v = AuditTrailView(now_provider=lambda: now)
    qtbot.addWidget(v)
    return v


@pytest.fixture
def view(qtbot: QtBot) -> AuditTrailView:
    return _view_at(qtbot, FROZEN_NOW)


def _set_range(view: AuditTrailView, label: str) -> None:
    """Zeitraum-Filter über den echten UI-Pfad setzen (Combo → Slot → Proxy).

    Das Assert ist der Schutz gegen einen stillen Fehlschlag: `findData` gibt
    bei unbekanntem Label -1 zurück, `setCurrentIndex(-1)` liefert
    `currentData() is None`, und der Slot fällt auf „Alle" zurück – der Filter
    wäre dann wirkungslos, statt dass der Test es merkt (Sprint-72-Falle).
    Die Labels kommen als Konstanten aus dem Widget-Modul, nicht als Literal.
    """
    idx = view._range_combo.findData(label)
    assert idx >= 0, f"Zeitraum-Label {label!r} nicht in der ComboBox"
    view._range_combo.setCurrentIndex(idx)


def _search_via_ui(view: AuditTrailView, text: str) -> None:
    """Suchtext über den echten UI-Pfad setzen und den Debounce sofort flushen.

    Sprint 34 / WP1: `textChanged` startet nur noch den 150-ms-Timer. Die
    Bestands-Tests prüfen Treffer-Semantik (nicht Timing) – der manuelle
    Flush hält sie deterministisch und schnell. Das Timer-Verhalten selbst
    ist in `TestAuditSearchDebounce` abgedeckt.
    """
    view._search.setText(text)
    view._search_debounce.stop()
    view._apply_search_text()


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
            _make_event(event_id=1, timestamp=FROZEN_NOW),
            _make_event(event_id=2, timestamp=FROZEN_NOW - timedelta(days=10)),
        ]
        view.set_events(events)
        _set_range(view, _RANGE_TODAY)
        assert view.visible_row_count() == 1

    def test_search_filter_by_user(self, view: AuditTrailView) -> None:
        events = [
            _make_event(user="anna", event_id=1),
            _make_event(user="bob", event_id=2),
        ]
        view.set_events(events)
        _search_via_ui(view, "bob")
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

    @pytest.mark.parametrize("anchor", _WEEK_GATE_ANCHORS)
    def test_range_week_includes_current_week_excludes_last_month(
        self, qtbot: QtBot, anchor: datetime
    ) -> None:
        """Wiederholungs-Gate (Sprint 73 / §5.4) für den Wochen-Filter.

        Umbenannt: der Test hieß `…includes_yesterday…` und legte sein
        „recent"-Event auf `now - 1h`. Eine Stunde ist nicht „gestern", und in
        der ersten Stunde eines Montags fällt `now - 1h` auf Sonntag, also in
        die VORwoche – genau das hat PR #105 auf allen drei OS rot gemacht.

        Die Absicht des Tests („etwas aus dieser Woche ist drin, etwas von vor
        60 Tagen nicht") ist ankerunabhängig, sobald das Event tatsächlich in
        der laufenden Woche liegt. Der Grenzfall `now - 1h` ist nicht
        weggefallen, sondern in
        `test_range_week_one_hour_ago_is_deterministic_per_anchor` und
        `TestRangeFilterBoundaries` explizit gepinnt.
        """
        view = _view_at(qtbot, anchor)
        current = _make_event(event_id=1, timestamp=anchor)
        long_past = _make_event(event_id=2, timestamp=anchor - timedelta(days=60))
        view.set_events([current, long_past])
        _set_range(view, _RANGE_WEEK)
        assert _visible_event_ids(view) == [1]

    @pytest.mark.parametrize(
        ("anchor", "expected_ids"),
        [
            # Mo 00:30 → `now - 1h` ist So 23:30 und liegt VOR dem Wochenstart
            # (Montag 00:00) → nicht sichtbar. Der PR-#105-Fall.
            pytest.param(MONDAY_AFTER_MIDNIGHT, [], id="montag-00-30"),
            pytest.param(WEDNESDAY_MIDDAY, [1], id="mittwoch-12-00"),
            pytest.param(SUNDAY_BEFORE_MIDNIGHT, [1], id="sonntag-23-30"),
            # 1. Januar 2026 ist ein Donnerstag; die Kalenderwoche beginnt am
            # Mo 2025-12-29 → das Silvester-Event liegt noch drin.
            pytest.param(NEW_YEAR_AFTER_MIDNIGHT, [1], id="1-januar-00-30"),
        ],
    )
    def test_range_week_one_hour_ago_is_deterministic_per_anchor(
        self, qtbot: QtBot, anchor: datetime, expected_ids: list[int]
    ) -> None:
        """Dieselbe `now - 1h`-Konstruktion wie vor Sprint 73, aber gepinnt.

        Das Ergebnis hängt von der Position im Kalender ab – das ist die
        Produktions-Semantik, nicht ein Fehler. Vorher war es eine Wette auf
        den Ausführungszeitpunkt, jetzt ist es pro Anker festgeschrieben.
        """
        view = _view_at(qtbot, anchor)
        view.set_events([_make_event(event_id=1, timestamp=anchor - timedelta(hours=1))])
        _set_range(view, _RANGE_WEEK)
        assert _visible_event_ids(view) == expected_ids

    def test_range_month_includes_today_excludes_two_months_ago(self, view: AuditTrailView) -> None:
        now = FROZEN_NOW
        today = _make_event(event_id=1, timestamp=now)
        old = _make_event(event_id=2, timestamp=now - timedelta(days=70))
        view.set_events([today, old])
        _set_range(view, _RANGE_MONTH)
        assert view.visible_row_count() == 1

    def test_range_reset_to_alle_shows_all_events(self, view: AuditTrailView) -> None:
        now = FROZEN_NOW
        view.set_events(
            [
                _make_event(event_id=1, timestamp=now),
                _make_event(event_id=2, timestamp=now - timedelta(days=400)),
            ]
        )
        _set_range(view, _RANGE_TODAY)
        assert view.visible_row_count() == 1
        _set_range(view, _FILTER_ALL)
        assert view.visible_row_count() == 2

    def test_combined_action_user_range_filter(self, view: AuditTrailView) -> None:
        now = FROZEN_NOW
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
        _set_range(view, _RANGE_TODAY)
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
        _search_via_ui(view, "Stichprobe_BDO")
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
        _search_via_ui(view, "buchungen")
        assert view.visible_row_count() == 1

    def test_search_case_insensitive(self, view: AuditTrailView) -> None:
        view.set_events(
            [
                _make_event(user="Anna", event_id=1),
                _make_event(user="bob", event_id=2),
            ]
        )
        _search_via_ui(view, "ANNA")
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
        """Alte Daten ohne tzinfo (vor UTC-Adapter-Sprint) müssen filterbar bleiben.

        Sprint 73: vorher stand hier `in (0, 1)` – das musste die Unschärfe
        zweier unabhängig laufender Uhren abfangen und hätte auch einen echten
        Regress durchgelassen. Mit eingefrorener Uhr ist das Ergebnis exakt:
        `ensure_utc` interpretiert das naive Datetime als UTC, es liegt damit
        auf dem Kalendertag von FROZEN_NOW und ist sichtbar.
        """
        naive_today = FROZEN_NOW.replace(tzinfo=None)
        view.set_events([_make_event(event_id=1, timestamp=naive_today)])
        _set_range(view, _RANGE_TODAY)
        assert view.visible_row_count() == 1

    def test_correction_event_shows_arrow_in_action_column(self, view: AuditTrailView) -> None:
        view.set_events([_make_event(event_id=10, event_type="correction", corrects=7)])
        proxy = view.proxy()
        action_text = proxy.data(proxy.index(0, 1), Qt.ItemDataRole.DisplayRole)
        assert "→ #7" in action_text


# ---------------------------------------------------------------------------
# Sprint 73: Grenzwerte des Zeitraum-Filters
# ---------------------------------------------------------------------------


class TestRangeFilterBoundaries:
    """Kalendergrenzen des Zeitraum-Filters – mit eingefrorener Uhr testbar.

    Diese Fälle traten vorher nur zufällig auf (und dann als roter Check zur
    Unzeit). Die Erwartungen pinnen, was `_in_range` TUT; die Semantik ist in
    Sprint 73 unverändert geblieben:

    - „Heute"        – gleicher UTC-Kalendertag, BEIDSEITIG begrenzt.
    - „Diese Woche"  – ab Montag 00:00 UTC der laufenden Kalenderwoche,
                       EINSEITIG (keine Obergrenze). Nicht rollende 7 Tage.
    - „Dieser Monat" – ab dem 1. des Monats 00:00 UTC, ebenfalls einseitig.
    """

    def test_week_filter_at_monday_shortly_after_midnight(self, qtbot: QtBot) -> None:
        """Uhr Mo 00:30, Event vor 1 h → So 23:30 → VORwoche → nicht sichtbar.

        Genau dieser Fall hat PR #105 rot gemacht. Kein Fehler im Filter: die
        Kalenderwoche beginnt am Montag um 00:00, „vor einer Stunde" liegt
        davor.
        """
        view = _view_at(qtbot, MONDAY_AFTER_MIDNIGHT)
        view.set_events(
            [
                _make_event(event_id=1, timestamp=MONDAY_AFTER_MIDNIGHT - timedelta(hours=1)),
                _make_event(event_id=2, timestamp=MONDAY_AFTER_MIDNIGHT),
            ]
        )
        _set_range(view, _RANGE_WEEK)
        assert _visible_event_ids(view) == [2]

    def test_week_filter_at_sunday_shortly_before_midnight(self, qtbot: QtBot) -> None:
        """Uhr So 23:30 – letzte halbe Stunde der Woche.

        Event vor 1 h liegt noch in der Woche. Das Event in 1 h liegt bereits
        in der Folgewoche, ist aber TROTZDEM sichtbar: „Diese Woche" hat keine
        Obergrenze (`when >= start`). Dieser Test hält diese Einseitigkeit
        fest, damit sie nicht unbemerkt verloren geht.
        """
        view = _view_at(qtbot, SUNDAY_BEFORE_MIDNIGHT)
        view.set_events(
            [
                _make_event(event_id=1, timestamp=SUNDAY_BEFORE_MIDNIGHT - timedelta(hours=1)),
                _make_event(event_id=2, timestamp=SUNDAY_BEFORE_MIDNIGHT + timedelta(hours=1)),
                _make_event(event_id=3, timestamp=SUNDAY_BEFORE_MIDNIGHT - timedelta(days=8)),
            ]
        )
        _set_range(view, _RANGE_WEEK)
        assert _visible_event_ids(view) == [1, 2]

    def test_month_filter_on_first_day_of_month(self, qtbot: QtBot) -> None:
        """Uhr 1. des Monats 00:30, Event am letzten Tag des Vormonats → raus."""
        view = _view_at(qtbot, FIRST_OF_MONTH_AFTER_MIDNIGHT)
        view.set_events(
            [
                _make_event(
                    event_id=1, timestamp=FIRST_OF_MONTH_AFTER_MIDNIGHT - timedelta(days=1)
                ),
                _make_event(event_id=2, timestamp=FIRST_OF_MONTH_AFTER_MIDNIGHT),
            ]
        )
        _set_range(view, _RANGE_MONTH)
        assert _visible_event_ids(view) == [2]

    def test_today_filter_shortly_before_midnight(self, qtbot: QtBot) -> None:
        """Uhr 23:59:30. Event vor 1 min ist heute, Event in 1 min ist morgen.

        Belegt die BEIDSEITIGE Begrenzung von „Heute" (Datumsvergleich, kein
        `>=`): das Event 1 Minute in der Zukunft fällt auf den Folgetag und ist
        damit draußen – anders als bei Woche/Monat.
        """
        view = _view_at(qtbot, JUST_BEFORE_MIDNIGHT)
        view.set_events(
            [
                _make_event(event_id=1, timestamp=JUST_BEFORE_MIDNIGHT - timedelta(minutes=1)),
                _make_event(event_id=2, timestamp=JUST_BEFORE_MIDNIGHT + timedelta(minutes=1)),
            ]
        )
        _set_range(view, _RANGE_TODAY)
        assert _visible_event_ids(view) == [1]

    def test_year_boundary_week_filter(self, qtbot: QtBot) -> None:
        """Uhr 1. Januar 00:30, Event am 31. Dezember des Vorjahres.

        Kontraintuitiv, aber korrekt: der 1.1.2026 ist ein Donnerstag, seine
        Kalenderwoche beginnt am Mo 29.12.2025 – das Silvester-Event ist in
        „Diese Woche" also DRIN. In „Dieser Monat" ist es draußen, weil der
        Monat am 1.1. um 00:00 beginnt. Der Jahreswechsel selbst spielt in der
        Rechnung keine Rolle; sie kennt nur Wochen- und Monatsanfänge.
        """
        silvester = NEW_YEAR_AFTER_MIDNIGHT - timedelta(hours=1)
        assert silvester.year == NEW_YEAR_AFTER_MIDNIGHT.year - 1

        view = _view_at(qtbot, NEW_YEAR_AFTER_MIDNIGHT)
        view.set_events(
            [
                _make_event(event_id=1, timestamp=silvester),
                _make_event(event_id=2, timestamp=NEW_YEAR_AFTER_MIDNIGHT),
            ]
        )
        _set_range(view, _RANGE_WEEK)
        assert _visible_event_ids(view) == [1, 2]

        _set_range(view, _RANGE_MONTH)
        assert _visible_event_ids(view) == [2]

        _set_range(view, _RANGE_TODAY)
        assert _visible_event_ids(view) == [2]

    def test_default_clock_is_the_real_wall_clock(self, qtbot: QtBot) -> None:
        """Ohne `now_provider` bleibt der Produktionspfad an der Wanduhr.

        Bewusst KEIN „Event jetzt ist unter Heute sichtbar"-Test: der würde
        selbst wieder zwei Uhren vergleichen und um Mitternacht kippen – also
        genau die Flakiness, die dieser Sprint entfernt. Stattdessen wird die
        Default-Bindung direkt geprüft und dass `_utc_now` wirklich die
        Wanduhr liest.
        """
        view = AuditTrailView()
        qtbot.addWidget(view)
        assert view.proxy()._now_provider is audit_trail_view._utc_now

        before = datetime.now(UTC)
        value = audit_trail_view._utc_now()
        after = datetime.now(UTC)
        assert before <= value <= after
        assert value.tzinfo is UTC


# ---------------------------------------------------------------------------
# Sprint 18 / T-002-Rest: Coverage-Ausbau audit_trail_view 82 → 85+ %
# ---------------------------------------------------------------------------


class TestModelEdgeCases:
    def test_data_invalid_index_returns_none(self, qtbot: QtBot) -> None:
        """`data()` mit ungültigem Index → None (kein Crash)."""
        model = AuditTrailModel()
        model.set_events([_make_event(event_id=1)])
        invalid = QModelIndex()
        assert model.data(invalid, Qt.ItemDataRole.DisplayRole) is None

    def test_data_event_id_role_returns_event_id(self, qtbot: QtBot) -> None:
        """`_EVENT_ID_ROLE` gibt die Event-ID als Sortier-Datum zurück."""
        from sampling_tool.ui.widgets.audit_trail_view import _EVENT_ID_ROLE

        model = AuditTrailModel()
        model.set_events([_make_event(event_id=42)])
        assert model.data(model.index(0, 0), _EVENT_ID_ROLE) == 42

    def test_data_sample_id_role_returns_sample_id(self, qtbot: QtBot) -> None:
        from sampling_tool.ui.widgets.audit_trail_view import _SAMPLE_ID_ROLE

        model = AuditTrailModel()
        model.set_events([_make_event(event_id=1, sample_id=7)])
        assert model.data(model.index(0, 0), _SAMPLE_ID_ROLE) == 7

    def test_data_event_type_role_returns_event_type(self, qtbot: QtBot) -> None:
        from sampling_tool.ui.widgets.audit_trail_view import _EVENT_TYPE_ROLE

        model = AuditTrailModel()
        model.set_events([_make_event(event_id=1, event_type="export")])
        assert model.data(model.index(0, 0), _EVENT_TYPE_ROLE) == "export"

    def test_data_user_role_returns_user(self, qtbot: QtBot) -> None:
        from sampling_tool.ui.widgets.audit_trail_view import _USER_ROLE

        model = AuditTrailModel()
        model.set_events([_make_event(event_id=1, user="carla")])
        assert model.data(model.index(0, 0), _USER_ROLE) == "carla"

    def test_data_text_alignment_role_for_numeric_columns(self, qtbot: QtBot) -> None:
        """Numerische Spalten (3-6) bekommen Right-Alignment."""
        model = AuditTrailModel()
        model.set_events([_make_event(event_id=1)])
        # Col 4 = sample_size (numerisch).
        alignment = model.data(model.index(0, 4), Qt.ItemDataRole.TextAlignmentRole)
        assert alignment is not None
        assert int(alignment) & int(Qt.AlignmentFlag.AlignRight)

    def test_data_unknown_role_returns_none(self, qtbot: QtBot) -> None:
        """Roles, die nicht behandelt werden, geben None zurück."""
        model = AuditTrailModel()
        model.set_events([_make_event(event_id=1)])
        # Col 0 (timestamp, NICHT numerisch) mit TextAlignmentRole → None.
        assert model.data(model.index(0, 0), Qt.ItemDataRole.TextAlignmentRole) is None

    def test_header_data_vertical_returns_none(self, qtbot: QtBot) -> None:
        model = AuditTrailModel()
        # Vertical Header (Zeilennummern) hat kein eigenes Label.
        result = model.headerData(0, Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole)
        assert result is None

    def test_header_data_wrong_role_returns_none(self, qtbot: QtBot) -> None:
        model = AuditTrailModel()
        result = model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)
        assert result is None

    def test_double_click_event_without_id_does_not_emit(
        self, view: AuditTrailView, qtbot: QtBot
    ) -> None:
        """Doppelklick auf Event ohne id darf NICHT das Signal feuern."""
        view.set_events([_make_event(event_id=None)])
        emitted: list[int] = []
        view.event_double_clicked.connect(lambda eid: emitted.append(eid))
        proxy_idx = view.proxy().index(0, 0)
        view._on_double_click(proxy_idx)
        assert emitted == []


# ---------------------------------------------------------------------------
# Sprint 24 / P-010: Haystack-Cache im Filter-Proxy
# ---------------------------------------------------------------------------


def _reference_haystack(evt: AuditEvent) -> str:
    """Unabhängige Kopie des Inline-Haystack-Aufbaus vor Sprint 24 (Oracle).

    Bewusst NICHT aus dem Widget-Modul importiert – der Test vergleicht die
    Cache-Implementierung gegen die alte Semantik, nicht gegen sich selbst.
    Felder + Reihenfolge wie `filterAcceptsRow` vor dem Cache-Umbau.
    """
    file_path = evt.export_file or evt.import_file
    file_label = Path(file_path).name if file_path else "—"
    return " ".join(
        [
            format_optional_timestamp(evt.timestamp),
            evt.event_type,
            evt.user_name or "",
            file_label,
        ]
    ).lower()


def _visible_event_ids(view: AuditTrailView) -> list[int]:
    """Event-IDs aller nach Filter sichtbaren Zeilen (sortiert)."""
    proxy = view.proxy()
    ids: list[int] = []
    for row in range(proxy.rowCount()):
        source = proxy.mapToSource(proxy.index(row, 0))
        evt = view.model().event_at(source.row())
        assert evt is not None
        assert evt.id is not None
        ids.append(evt.id)
    return sorted(ids)


def _synthetic_events(count: int) -> list[AuditEvent]:
    """Synthetische Events mit Varianz in allen Haystack-Feldern."""
    types = ["sampling", "reset", "import", "export", "undo", "redo", "correction"]
    users = ["Anna", "bob", "Jörg", "", "X-Üser"]
    events: list[AuditEvent] = []
    for i in range(1, count + 1):
        events.append(
            _make_event(
                event_id=i,
                event_type=types[i % len(types)],
                user=users[i % len(users)],
                import_file=f"buchungen_{i}.csv" if i % 3 == 0 else None,
                export_file=f"Sample_{i}_BDO.xlsx" if i % 3 == 1 else None,
                # Von FROZEN_NOW abgeleitet statt zweitem Datums-Literal; ergibt
                # dieselben Zeitstempel wie vor Sprint 73 (Mai 2026, Minute 30).
                timestamp=FROZEN_NOW.replace(day=(i % 28) + 1, hour=i % 24, minute=30),
            )
        )
    return events


class TestAuditTrailFilterHaystackCache:
    """Sprint 24 / P-010: Haystack einmal pro set_events, nicht pro Tastenanschlag."""

    def test_haystack_built_once_on_set_events(self, view: AuditTrailView) -> None:
        view.set_events(_synthetic_events(100))
        assert len(view.proxy()._haystack_cache) == 100

    def test_set_events_replaces_stale_cache(self, view: AuditTrailView) -> None:
        view.set_events(_synthetic_events(100))
        view.set_events(_synthetic_events(7))
        assert len(view.proxy()._haystack_cache) == 7

    def test_filter_uses_cache_not_per_keystroke_rebuild(
        self, view: AuditTrailView, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[AuditEvent] = []
        original = audit_trail_view._build_haystack

        def counting(evt: AuditEvent) -> str:
            calls.append(evt)
            return original(evt)

        monkeypatch.setattr(audit_trail_view, "_build_haystack", counting)

        view.set_events(_synthetic_events(100))
        assert len(calls) == 100  # genau einmal pro Event beim set_events

        proxy = view.proxy()
        for keystroke in ("a", "an", "ann", "anna"):
            proxy.set_search_text(keystroke)  # Re-Filter über alle 100 Rows
        for row in range(10):
            proxy.filterAcceptsRow(row, QModelIndex())
        assert len(calls) == 100  # 0 zusätzliche Builds beim Filtern

    def test_filter_results_identical_to_pre_cache_implementation(
        self, view: AuditTrailView
    ) -> None:
        events = _synthetic_events(50)
        view.set_events(events)
        proxy = view.proxy()
        needles = [
            "anna",
            "EXPORT",
            "xlsx",
            "2026",
            "keintrefferxyz",
            "Jörg",
            "csv",
            "sampling",
        ]
        for needle in needles:
            proxy.set_search_text(needle)
            # Referenz: literales, case-insensitives Substring-Matching gegen
            # die unabhängige Haystack-Kopie. Für Wort-Zeichen-Needles ist das
            # bit-identisch zum Pre-Sprint-25-Verhalten; Needles mit
            # Nicht-Wort-Zeichen ("Jörg") treffen seit Sprint 25 literal.
            expected = sorted(
                evt.id
                for evt in events
                if evt.id is not None and needle.lower() in _reference_haystack(evt)
            )
            assert _visible_event_ids(view) == expected, f"needle={needle!r}"

    def test_repeated_set_source_model_keeps_cache_fresh(self, view: AuditTrailView) -> None:
        """Erneutes setSourceModel mit demselben Model darf den Rebuild-Slot
        nicht per Disconnect+Reconnect hinter Qts internen Reset-Handler
        schieben – sonst filtert ein Same-Length-Reset mit stalem Cache."""
        proxy = view.proxy()
        proxy.set_search_text("anna")
        view.set_events([_make_event(event_id=1, user="Anna"), _make_event(event_id=2, user="bob")])
        assert _visible_event_ids(view) == [1]

        proxy.setSourceModel(view.model())  # No-op-Aufruf, von Qt erlaubt

        # Gleiche Event-Anzahl, aber "Anna" ist weg → kein Treffer mehr.
        view.set_events([_make_event(event_id=3, user="bob"), _make_event(event_id=4, user="bob")])
        assert _visible_event_ids(view) == []

    def test_out_of_range_row_falls_back_to_inline_build(self, view: AuditTrailView) -> None:
        """Race bei Modell-Reset: leerer/zu kurzer Cache darf nicht crashen."""
        view.set_events(_synthetic_events(5))
        proxy = view.proxy()
        proxy.set_search_text("anna")
        proxy._haystack_cache = []  # Race simulieren: Cache leer trotz gefülltem Model
        accepted = [proxy.filterAcceptsRow(row, QModelIndex()) for row in range(5)]
        # users-Zyklus in _synthetic_events: Event 5 hat user "Anna", alle anderen nicht.
        assert accepted == [False, False, False, False, True]


class TestAuditSearchSpecialChars:
    """Sprint 25: Volltextsuche ist literales, case-insensitives Substring-Matching.

    Bug seit Sprint 6: der Suchtext lief über `setFilterFixedString`, dessen
    escaptes Pattern (".csv" → "\\.csv", "ö" → "\\ö", auch Leerzeichen!) als
    Substring-Nadel gegen den Haystack geprüft wurde – Begriffe mit
    Nicht-Wort-Zeichen trafen deshalb NIE. Alle Tests laufen über den echten
    UI-Pfad (`view._search.setText`).
    """

    def test_search_matches_dot_extension(self, view: AuditTrailView) -> None:
        view.set_events(
            [
                _make_event(event_id=1, import_file="/tmp/report.csv"),
                _make_event(event_id=2, export_file="/tmp/report.xlsx"),
                _make_event(event_id=3),
            ]
        )
        _search_via_ui(view, ".csv")
        assert _visible_event_ids(view) == [1]

    def test_search_matches_umlaut(self, view: AuditTrailView) -> None:
        view.set_events(
            [
                _make_event(event_id=1, user="Größe"),
                _make_event(event_id=2, user="Öffnung"),
                _make_event(event_id=3, user="anna"),
            ]
        )
        _search_via_ui(view, "ö")
        assert _visible_event_ids(view) == [1, 2]
        # Case-insensitiv auch für Nicht-ASCII.
        _search_via_ui(view, "Ö")
        assert _visible_event_ids(view) == [1, 2]

    def test_search_matches_other_regex_metachars(self, view: AuditTrailView) -> None:
        view.set_events(
            [
                _make_event(event_id=1, user="Team (Audit)+QA*"),
                _make_event(event_id=2, user="Team Audit QA"),
            ]
        )
        _search_via_ui(view, "(audit)")
        assert _visible_event_ids(view) == [1]
        _search_via_ui(view, "+qa*")
        assert _visible_event_ids(view) == [1]
        # Literal, NICHT als Regex: "a*" (null-oder-mehr 'a') würde als Regex
        # beide Events treffen – literal kommt "a*" nur in Event 1 vor.
        _search_via_ui(view, "a*")
        assert _visible_event_ids(view) == [1]

    def test_search_matches_phrase_with_space(self, view: AuditTrailView) -> None:
        """Qt escapet auch Leerzeichen ('anna export' → 'anna\\ export') –
        Mehrwort-Suchen trafen vor Sprint 25 deshalb ebenfalls nie."""
        view.set_events(
            [
                _make_event(event_id=1, user="Team Audit QA"),
                _make_event(event_id=2, user="Team (Audit)+QA*"),
            ]
        )
        _search_via_ui(view, "team audit")
        assert _visible_event_ids(view) == [1]

    def test_plain_text_search_unchanged(self, view: AuditTrailView) -> None:
        """Oracle: für Begriffe aus reinen Wort-Zeichen ist das Verhalten
        bit-identisch zu vor dem Fix (Escape ist dort die Identität)."""
        events = _synthetic_events(30)
        view.set_events(events)
        for needle in ["bob", "sampling", "xlsx", "2026", "keintrefferxyz", "BOB"]:
            _search_via_ui(view, needle)
            expected = sorted(
                evt.id
                for evt in events
                if evt.id is not None and needle.lower() in _reference_haystack(evt)
            )
            assert _visible_event_ids(view) == expected, f"needle={needle!r}"

    def test_empty_search_shows_all(self, view: AuditTrailView) -> None:
        view.set_events(_synthetic_events(10))
        _search_via_ui(view, "anna")
        assert view.visible_row_count() < 10
        _search_via_ui(view, "")
        assert view.visible_row_count() == 10


# ---------------------------------------------------------------------------
# Sprint 34 / WP1: Debounce der Volltextsuche
# ---------------------------------------------------------------------------


class TestAuditSearchDebounce:
    """Sprint 34 / WP1: `textChanged` startet nur noch den Debounce-Timer.

    Gefiltert wird genau einmal pro Tipp-Pause (nach `AUDIT_SEARCH_DEBOUNCE_MS`)
    statt einmal pro Tastenanschlag. Die Treffer-Semantik (literal,
    case-insensitiv, Sprint 25) bleibt unverändert – der Proxy selbst ist
    weiterhin synchron.
    """

    def test_typing_coalesces_filter_runs(
        self, view: AuditTrailView, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        view.set_events(_synthetic_events(10))
        proxy = view.proxy()
        calls: list[str] = []
        original = proxy.set_search_text

        def spy(text: str) -> None:
            calls.append(text)
            original(text)

        monkeypatch.setattr(proxy, "set_search_text", spy)

        for fragment in (
            "a",
            "an",
            "ann",
            "anna",
            "anna ",
            "anna e",
            "anna ex",
            "anna exp",
            "anna expo",
            "anna export",
        ):
            view._search.setText(fragment)
        assert calls == []  # während des Tippens läuft KEIN Filterlauf

        qtbot.waitUntil(lambda: not view._search_debounce.isActive(), timeout=2000)
        qtbot.wait(50)  # Settle-Fenster: ein fälschlicher Zweit-Lauf würde auffallen
        assert calls == ["anna export"]  # genau EIN Lauf, mit dem finalen Text

    def test_debounced_result_matches_immediate(self, qtbot: QtBot) -> None:
        events = _synthetic_events(20)
        debounced = AuditTrailView()
        qtbot.addWidget(debounced)
        debounced.set_events(events)
        oracle = AuditTrailView()
        qtbot.addWidget(oracle)
        oracle.set_events(events)

        oracle.proxy().set_search_text("anna")  # synchroner Direkt-Aufruf (Referenz)
        debounced._search.setText("anna")
        qtbot.waitUntil(lambda: not debounced._search_debounce.isActive(), timeout=2000)

        assert _visible_event_ids(debounced) == _visible_event_ids(oracle)
        assert debounced.visible_row_count() == oracle.visible_row_count()

    def test_clear_after_debounce_shows_all_rows(self, view: AuditTrailView, qtbot: QtBot) -> None:
        view.set_events(_synthetic_events(10))
        view._search.setText("anna")
        qtbot.waitUntil(lambda: not view._search_debounce.isActive(), timeout=2000)
        assert view.visible_row_count() < 10

        view._search.setText("")  # Feld leeren – läuft über denselben Debounce-Pfad
        qtbot.waitUntil(lambda: not view._search_debounce.isActive(), timeout=2000)
        assert view.visible_row_count() == 10
