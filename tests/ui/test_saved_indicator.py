"""„Gespeichert HH:MM" – die ohnehin laufende Speicherung sichtbar machen.

Die App hat keinen ungespeicherten Zustand: die SQLite-Verbindung läuft im
Autocommit (`persistence/database.py`, `isolation_level=None`) und
`WorkspaceSession.persist_state()` wird nach jeder mutierenden UI-Aktion
gerufen. Ein Speichern-Knopf hätte nichts zu tun – sichtbar war das nur
nicht.

Diese Tests nageln beides fest:

* Die Anzeige tickt **genau dann**, wenn wirklich geschrieben wurde – also
  nicht an den beiden Früh-Ausstiegen von `persist_state()`
  (`restoring_state`, kein Engagement) und nicht bei `clear_view()`, das
  bewusst gar nichts schreibt.
* Die Uhrzeit kommt aus dem injizierten `now_provider` (Sprint 74), nicht
  aus einer zweiten `datetime.now()`. Geprüft wird gegen eine **feste**
  Testuhr – nie gegen eine zweite unabhängige Uhr-Ablesung.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import Engagement
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import EngagementRepo, EngagementStateRepo
from sampling_tool.ui.controllers.main_controller import MainController
from sampling_tool.ui.controllers.workspace_session import (
    SAVE_CONFIRMATION_MESSAGE,
    WorkspaceSession,
)
from sampling_tool.ui.main_window import MainWindow
from sampling_tool.ui.recent import RecentEngagementsStore
from sampling_tool.ui.settings_store import AppSettings
from sampling_tool.ui.widgets.sidebar import _SIDEBAR_WIDTH

pytestmark = pytest.mark.ui

#: Feste Testuhr. Alle Erwartungen werden aus DIESEM Wert abgeleitet – es
#: wird nie eine zweite Uhr gelesen und mit einer ersten verglichen.
FROZEN_NOW = datetime(2026, 9, 13, 14, 32, 9)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Echte MainWindows schreiben im `closeEvent` Geometrie in die Prefs.

    Gleiches Muster wie `test_export_dir_bootstrap._isolated_qsettings`:
    die Klasse am Verwendungsort patchen – bewusst kein HOME-Umbiegen
    (hat in Sprint 67 echte Benutzer-Prefs korrumpiert).
    """
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    monkeypatch.setattr(
        "sampling_tool.ui.main_window.QSettings",
        lambda organization, application: QSettings(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, organization, application
        ),
    )


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    return win


@pytest.fixture
def recent_store(tmp_path: Path) -> RecentEngagementsStore:
    return RecentEngagementsStore(path=tmp_path / "recent.json")


@pytest.fixture
def project_db(tmp_path: Path) -> Iterator[Database]:
    """Echte Projektdatei mit einem Engagement – kein :memory:."""
    db = Database(tmp_path / "projekt.db")
    db.migrate()
    yield db
    db.close()


@pytest.fixture
def engagement(project_db: Database) -> Engagement:
    eng = EngagementRepo(project_db.connect()).get_or_create(
        Engagement(
            auditor_name="Anna Auditorin",
            client_name="ACME GmbH",
            auditor_position="Senior Auditor",
            audit_type="ISAE 3402 Typ II",
        )
    )
    assert eng.id is not None
    return eng


@pytest.fixture
def session(
    window: MainWindow,
    recent_store: RecentEngagementsStore,
    project_db: Database,
    engagement: Engagement,
) -> WorkspaceSession:
    """Session mit fester Testuhr und schreibbereitem `state_repo`."""
    s = WorkspaceSession(
        window=window,
        settings=AppSettings.defaults(),
        recent_store=recent_store,
        now_provider=lambda: FROZEN_NOW,
    )
    s.db = project_db
    s.engagement = engagement
    s.state_repo = EngagementStateRepo(project_db.connect())
    return s


def _saved_label(window: MainWindow) -> QLabel:
    """Die „Gespeichert HH:MM"-Zeile im Engagement-Block der Sidebar."""
    return window._sidebar._engagement_saved


# ---------------------------------------------------------------------------
# Vor dem ersten Schreiben
# ---------------------------------------------------------------------------


class TestIndicatorStartsEmpty:
    """Vor dem ersten Schreiben zeigt das Feld nichts – kein Platzhalter."""

    def test_label_is_empty_before_any_write(self, window: MainWindow) -> None:
        assert _saved_label(window).text() == ""

    def test_label_shows_no_error_looking_placeholder(self, window: MainWindow) -> None:
        """Weder „—" noch „nie" noch „unbekannt" – das sähe nach Fehler aus."""
        assert _saved_label(window).text().strip() == ""

    def test_label_is_hidden_before_any_write(self, window: MainWindow) -> None:
        """Eine leere Zeile im Engagement-Block sähe nach Fehler aus."""
        window.show_workspace()
        assert _saved_label(window).isHidden()

    def test_indicator_lives_in_the_sidebar_engagement_block(self, window: MainWindow) -> None:
        """Nicht in der Statusleiste – die ist auf Windows bereits voll."""
        assert _saved_label(window) in window._sidebar.findChildren(QLabel)

    def test_statusbar_keeps_its_four_permanent_fields(self, window: MainWindow) -> None:
        """Die Statusleiste bleibt unangetastet: kein fünftes Feld."""
        status = window.statusBar()
        assert status is not None
        texts = [lbl for lbl in status.findChildren(QLabel) if lbl.text() != "│"]
        assert len(texts) == 4


# ---------------------------------------------------------------------------
# persist_state() ist die eine Naht
# ---------------------------------------------------------------------------


class TestPersistStateUpdatesIndicator:
    """Nach erfolgreichem Schreiben – und nur dann – tickt die Anzeige."""

    def test_persist_state_sets_the_time(self, session: WorkspaceSession) -> None:
        session.persist_state()
        assert _saved_label(session.window).text() == "Gespeichert 14:32"

    def test_persist_state_reveals_the_label(self, session: WorkspaceSession) -> None:
        session.window.show_workspace()
        session.persist_state()
        assert not _saved_label(session.window).isHidden()

    def test_time_has_no_seconds(self, session: WorkspaceSession) -> None:
        """Beruhigung, keine Messung – die 9 Sekunden aus FROZEN_NOW fehlen."""
        session.persist_state()
        assert "09" not in _saved_label(session.window).text()
        assert _saved_label(session.window).text().count(":") == 1

    def test_no_update_while_restoring_state(self, session: WorkspaceSession) -> None:
        session.restoring_state = True
        session.persist_state()
        assert _saved_label(session.window).text() == ""

    def test_no_update_without_engagement(self, session: WorkspaceSession) -> None:
        session.engagement = None
        session.persist_state()
        assert _saved_label(session.window).text() == ""

    def test_no_update_without_state_repo(self, session: WorkspaceSession) -> None:
        session.state_repo = None
        session.persist_state()
        assert _saved_label(session.window).text() == ""

    def test_restoring_state_does_not_clear_a_previous_time(
        self, session: WorkspaceSession
    ) -> None:
        """Der Früh-Ausstieg darf die Anzeige nicht bewegen – in keine Richtung."""
        session.persist_state()
        session.restoring_state = True
        session.persist_state()
        assert _saved_label(session.window).text() == "Gespeichert 14:32"

    def test_indicator_reflects_a_real_row_in_the_project_file(
        self, session: WorkspaceSession, engagement: Engagement
    ) -> None:
        """Die Anzeige lügt nicht: nach dem Tick steht die Zeile wirklich da."""
        assert engagement.id is not None
        session.persist_state()
        assert session.state_repo is not None
        assert session.state_repo.get(engagement.id) is not None
        assert _saved_label(session.window).text() == "Gespeichert 14:32"

    def test_clear_view_does_not_tick_the_indicator(self, session: WorkspaceSession) -> None:
        """`clear_view()` schreibt nichts – also darf auch nichts ticken."""
        session.datasets = []
        session.dataset = None
        assert session.clear_view() is False
        assert _saved_label(session.window).text() == ""


# ---------------------------------------------------------------------------
# Die Uhr ist injiziert
# ---------------------------------------------------------------------------


class TestClockIsInjected:
    """Eine Uhr, eine Quelle (Sprint 74) – kein neues `datetime.now()`."""

    def test_uses_the_injected_provider(self, session: WorkspaceSession) -> None:
        session.persist_state()
        assert _saved_label(session.window).text() == "Gespeichert 14:32"

    def test_a_second_write_reflects_the_new_provider_value(
        self, session: WorkspaceSession
    ) -> None:
        session.persist_state()
        session._now_provider = lambda: datetime(2026, 9, 13, 16, 5, 0)
        session.persist_state()
        assert _saved_label(session.window).text() == "Gespeichert 16:05"

    def test_default_provider_is_the_shared_app_clock(
        self, window: MainWindow, recent_store: RecentEngagementsStore
    ) -> None:
        """Ohne Injektion hängt die Session an der gemeinsamen Modul-Uhr."""
        from sampling_tool.config import local_export_now

        s = WorkspaceSession(
            window=window, settings=AppSettings.defaults(), recent_store=recent_store
        )
        assert s._now_provider is local_export_now


# ---------------------------------------------------------------------------
# Datei -> Speichern
# ---------------------------------------------------------------------------


class TestSaveActionInFileMenu:
    """Der Reflex Strg+S findet einen Menüpunkt vor."""

    def test_action_is_in_the_file_menu(self, window: MainWindow) -> None:
        assert window._action_save in window._file_menu.actions()

    def test_action_has_the_standard_save_shortcut(self, window: MainWindow) -> None:
        assert window._action_save.shortcut() == QKeySequence(QKeySequence.StandardKey.Save)

    def test_action_sits_before_the_separator_above_close(self, window: MainWindow) -> None:
        actions = window._file_menu.actions()
        assert actions.index(window._action_save) < actions.index(window._action_close)
        separators = [i for i, a in enumerate(actions) if a.isSeparator()]
        first_separator = min(separators)
        assert actions.index(window._action_save) < first_separator

    def test_action_emits_save_requested(self, window: MainWindow, qtbot: QtBot) -> None:
        window.show_workspace()  # ohne offenes Projekt ist die Aktion grau
        with qtbot.waitSignal(window.save_requested, timeout=500):
            window._action_save.trigger()

    def test_disabled_action_emits_nothing(self, window: MainWindow, qtbot: QtBot) -> None:
        """Ohne offenes Projekt läuft auch der Reflex ins Leere – kein Signal."""
        window.show_welcome()
        with (
            pytest.raises(qtbot.TimeoutError),
            qtbot.waitSignal(window.save_requested, timeout=100),
        ):
            window._action_save.trigger()

    def test_action_is_disabled_without_an_open_project(self, window: MainWindow) -> None:
        window.show_welcome()
        assert not window._action_save.isEnabled()

    def test_action_is_enabled_with_an_open_project(self, window: MainWindow) -> None:
        window.show_workspace()
        assert window._action_save.isEnabled()

    def test_shortcut_is_unique_across_all_actions(self, window: MainWindow) -> None:
        """Strg+S darf nichts anderes überschreiben."""
        seen: dict[str, str] = {}
        for action in window.findChildren(type(window._action_save)):
            key = action.shortcut().toString()
            if not key:
                continue
            assert key not in seen, f"{key} doppelt: {seen.get(key)} und {action.text()}"
            seen[key] = action.text()


class TestConfirmationStaysShort:
    """Die Bestätigung muss kurz bleiben – und die lange Fassung woanders stehen.

    Vorgeschichte, damit das hier niemand „aufräumt": der erste Entwurf war
    ein ganzer Satz (83 Zeichen). Im gerenderten Screenshot lief er mitten
    im Wort in die permanenten Felder. Ein Pixel-Test dagegen war der
    nächste Fehlschlag – die Statusleiste ist NICHT plattformstabil
    messbar:

        Platz für die Meldung bei 1280 px, gleiche Inhalte, gleicher Code
          macOS    322 px frei, Satz 216 px  -> passte
          Ubuntu   203 px frei, Satz 226 px  -> passte NICHT
          Windows    2 px frei, Satz 442 px  -> passte weit nicht

    Auf Windows füllen die permanenten Felder die Leiste bereits komplett;
    dort ist die temporäre `showMessage`-Fläche praktisch nicht vorhanden.
    Das gilt für die BESTEHENDEN Meldungen der App genauso (457/476 px auf
    macOS, vgl. `workspace_controller.py:306`/`:501`) – ein Zustand, den
    dieses Projekt seit jeher hat und den ein Feature wie dieses nicht
    nebenbei löst.

    Konsequenz: geprüft wird, was plattformunabhängig gilt – der Satz
    bleibt kurz, und die vollständige Regel lebt im Tooltip, der als Popup
    keiner Breitenbeschränkung unterliegt.
    """

    #: Zeichen-Budget statt Pixel: über alle drei Plattformen identisch.
    #: Der verworfene Erst-Entwurf hatte 83 Zeichen und wäre hier gefallen.
    MAX_CHARS = 40

    def test_message_stays_within_the_character_budget(self) -> None:
        assert len(SAVE_CONFIRMATION_MESSAGE) <= self.MAX_CHARS, (
            f"Bestätigungstext hat {len(SAVE_CONFIRMATION_MESSAGE)} Zeichen, "
            f"erlaubt sind {self.MAX_CHARS}. Die Statusleiste teilt sich die "
            f"Breite mit den vier permanenten Statusfeldern – die lange "
            f"Fassung gehört "
            f"in den Tooltip der Aktion."
        )

    def test_the_full_rule_lives_in_the_tooltip(self, window: MainWindow) -> None:
        """Was nicht in die Statuszeile passt, muss trotzdem erreichbar sein."""
        tooltip = window._action_save.toolTip().lower()
        assert "automatisch" in tooltip
        assert "nach jeder änderung" in tooltip

    def test_tooltip_is_not_length_limited(self, window: MainWindow) -> None:
        """Der Tooltip darf ausführlich sein – er ist ein Popup, kein Feld."""
        assert len(window._action_save.toolTip()) > self.MAX_CHARS


class TestSidebarStaysNarrow:
    """Die Zeile darf die Sidebar nicht breiter zwingen.

    Vorgeschichte: die Anzeige sass zuerst als FUENFTES Feld in der
    Statusleiste. Der CI-Lauf hat das widerlegt – gemessen bei 1280 px
    (13"-Zielgeraet) mit bewusst bescheidenen Inhalten:

        macOS     4 Felder  613 px -> 5 Felder  763 px   passt
        Windows   4 Felder 1162 px -> 5 Felder 1433 px   UEBERLAUF

    Auf Windows brauchen die vier bestehenden Felder bereits 91 % der
    Breite; auch „Gespeichert" ohne Uhrzeit haette dort nicht gepasst
    (~1363 px). Deshalb steht die Zeile jetzt im Engagement-Block der
    Sidebar – und darf DORT keinen neuen Breiten-Zwang erzeugen.

    Die Falle heisst `setWordWrap`: ein QLabel ohne Umbruch zieht die
    Mindestbreite seines Containers auf seine eigene Textbreite hoch. Die
    Sidebar darf aber bis `_SIDEBAR_MIN_WIDTH` (180 px) schrumpfen, und
    auf Windows ist der Text fast doppelt so breit wie auf macOS.
    """

    def test_label_wraps_so_it_cannot_pin_the_minimum_width(self, window: MainWindow) -> None:
        assert _saved_label(window).wordWrap(), (
            "Ohne setWordWrap zwingt die Zeile die Sidebar auf ihre Textbreite "
            "– plattformabhaengig und auf Windows am schlimmsten."
        )

    def test_showing_the_label_does_not_widen_the_sidebar(
        self, window: MainWindow, qtbot: QtBot
    ) -> None:
        window.show_workspace()
        window.show()
        qtbot.waitExposed(window)
        sidebar = window._sidebar
        before = sidebar.minimumSizeHint().width()
        window.set_saved_at(FROZEN_NOW)
        layout = sidebar.layout()
        if layout is not None:
            layout.activate()
        after = sidebar.minimumSizeHint().width()
        assert not _saved_label(window).isHidden(), "Messung vakuum: Zeile unsichtbar"
        assert after <= before, (
            f"Die Zeile hebt die Mindestbreite der Sidebar von {before} px auf "
            f"{after} px – genau das sollte der Wortumbruch verhindern."
        )

    def test_label_fits_the_default_sidebar_width(self, window: MainWindow, qtbot: QtBot) -> None:
        """Bei Default-Breite steht die Zeile auf EINER Zeile, ohne Umbruch."""
        window.show_workspace()
        window.show()
        qtbot.waitExposed(window)
        window.set_saved_at(FROZEN_NOW)
        label = _saved_label(window)
        assert label.sizeHint().width() <= _SIDEBAR_WIDTH, (
            f"{label.text()!r} braucht {label.sizeHint().width()} px, die "
            f"Sidebar ist standardmaessig {_SIDEBAR_WIDTH} px breit."
        )


class TestSaveActionConfirmation:
    """Der Klick schreibt wirklich – und die Rückmeldung sagt die Wahrheit."""

    def test_handler_calls_persist_state(
        self, session: WorkspaceSession, engagement: Engagement
    ) -> None:
        assert engagement.id is not None
        assert session.state_repo is not None
        assert session.state_repo.get(engagement.id) is None
        session.handle_save_requested()
        assert session.state_repo.get(engagement.id) is not None

    def test_handler_updates_the_indicator(self, session: WorkspaceSession) -> None:
        session.handle_save_requested()
        assert _saved_label(session.window).text() == "Gespeichert 14:32"

    def test_handler_shows_the_confirmation(self, session: WorkspaceSession) -> None:
        session.handle_save_requested()
        status = session.window.statusBar()
        assert status is not None
        assert status.currentMessage() == SAVE_CONFIRMATION_MESSAGE

    def test_confirmation_does_not_claim_the_click_caused_the_save(self) -> None:
        """Der Text muss erklären, dass automatisch gespeichert wird."""
        assert "automatisch" in SAVE_CONFIRMATION_MESSAGE.lower()

    def test_confirmation_does_not_overclaim(self) -> None:
        """Nicht „alles gespeichert": die Fenstergeometrie liegt in den
        QSettings und wird erst im `closeEvent` geschrieben. Zugesagt wird
        nur, was `persist_state()` wirklich sofort schreibt."""
        assert "alles" not in SAVE_CONFIRMATION_MESSAGE.lower()

    def test_confirmation_reads_as_a_state_not_as_a_deed(self) -> None:
        """Der Satz darf nicht klingen, als hätte erst der Klick gespeichert."""
        assert SAVE_CONFIRMATION_MESSAGE.lower().startswith("bereits")

    def test_window_signal_is_wired_to_the_session(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        project_db: Database,
        engagement: Engagement,
    ) -> None:
        """Ende zu Ende: die QAction schreibt eine Zeile in die Projektdatei."""
        controller = MainController(
            window,
            recent_store=recent_store,
            settings=AppSettings.defaults(),
        )
        controller.session.db = project_db
        controller.session.engagement = engagement
        controller.session.state_repo = EngagementStateRepo(project_db.connect())
        assert engagement.id is not None
        assert controller.session.state_repo.get(engagement.id) is None

        window.show_workspace()
        window._action_save.trigger()

        assert controller.session.state_repo.get(engagement.id) is not None
