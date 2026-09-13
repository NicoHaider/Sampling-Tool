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
from PyQt6.QtWidgets import QLabel, QWidget
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
    return window._status_saved


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

    def test_label_and_its_separator_are_hidden_before_any_write(self, window: MainWindow) -> None:
        """Ein leeres Feld zwischen zwei Trennstrichen sähe kaputt aus."""
        window.show_workspace()
        assert window._status_saved.isHidden()
        assert window._status_saved_separator.isHidden()

    def test_indicator_is_a_permanent_statusbar_widget(self, window: MainWindow) -> None:
        status = window.statusBar()
        assert status is not None
        assert window._status_saved in status.findChildren(QLabel)


# ---------------------------------------------------------------------------
# persist_state() ist die eine Naht
# ---------------------------------------------------------------------------


class TestPersistStateUpdatesIndicator:
    """Nach erfolgreichem Schreiben – und nur dann – tickt die Anzeige."""

    def test_persist_state_sets_the_time(self, session: WorkspaceSession) -> None:
        session.persist_state()
        assert _saved_label(session.window).text() == "Gespeichert 14:32"

    def test_persist_state_shows_label_and_separator(self, session: WorkspaceSession) -> None:
        session.window.show_workspace()
        session.persist_state()
        assert not session.window._status_saved.isHidden()
        assert not session.window._status_saved_separator.isHidden()

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
            f"Breite mit fünf permanenten Feldern – die lange Fassung gehört "
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


class TestFifthColumnDoesNotCauseTheOverflow:
    """§5 des Auftrags: sprengt die FÜNFTE Spalte auf 13" die Breite?

    Gefragt ist die Ursache, nicht der Zustand – und genau so wird geprüft:
    der natürliche Platzbedarf der permanenten Felder wird einmal MIT und
    einmal OHNE „Gespeichert HH:MM" gemessen. Rot wird der Test nur, wenn
    die fünfte Spalte den Ausschlag gibt: ohne sie passte es, mit ihr nicht.

    Warum nicht einfach „ist das Feld sichtbar?": die Statusleiste ist auf
    Windows schon ohne das fünfte Feld randvoll (bei 1280 px blieben im
    CI-Lauf 2 px für die temporäre Meldung, die bestehenden Meldungen der
    App werden dort ebenfalls beschnitten). Ein absoluter Test wäre dort
    rot, ohne dass dieses Feature etwas verbrochen hätte – dieselbe Falle,
    die `tests/ui/test_toolbar_overflow.py` im Modul-Docstring beschreibt
    und ebenfalls mit einem RELATIVEN Vergleich löst.

    Gemessen wird an einem breiten Fenster, damit Qt nichts staucht: der
    natürliche Bedarf ist dann die rechte Kante minus linke Kante.
    """

    TARGET_WIDTH = 1280
    #: Breit genug, dass das Layout nichts zusammenquetscht.
    ROOMY_WIDTH = 3000

    def _natural_width(self, window: MainWindow, *, with_saved_field: bool) -> int:
        window.set_saved_at(FROZEN_NOW if with_saved_field else None)
        status = window.statusBar()
        assert status is not None
        layout = status.layout()
        if layout is not None:
            layout.activate()
        boxes = [
            child
            for child in status.children()
            if isinstance(child, QWidget) and not child.isHidden()
        ]
        assert boxes, "keine permanenten Widgets – die Messung wäre vakuum"
        return max(c.x() + c.width() for c in boxes) - min(c.x() for c in boxes)

    def test_fifth_column_is_not_what_breaks_the_target_width(
        self, window: MainWindow, qtbot: QtBot
    ) -> None:
        window.show_workspace()
        window.resize(self.ROOMY_WIDTH, 720)
        window.show()
        qtbot.waitExposed(window)
        window.set_engagement(
            Engagement(
                auditor_name="Anna Auditorin",
                auditor_position="Senior Auditor",
                client_name="ACME GmbH",
                audit_type="ISAE 3402 Typ II",
                id=1,
            )
        )
        window._status_dataset.setText("Buchungen.xlsx")
        window._status_rows.setText("12.500 Zeilen")
        window._status_sample.setText("Aktive Stichprobe: #3 (Einfach, 25/1500)")

        without = self._natural_width(window, with_saved_field=False)
        with_field = self._natural_width(window, with_saved_field=True)
        assert with_field > without, "Messung vakuum: das fünfte Feld kostet keine Breite"

        if without > self.TARGET_WIDTH:
            pytest.skip(
                f"Statusleiste ist auf dieser Plattform schon mit VIER Feldern "
                f"zu breit ({without} px > {self.TARGET_WIDTH} px) – ein "
                f"Vorzustand, den dieses Feature nicht verursacht hat."
            )
        assert with_field <= self.TARGET_WIDTH, (
            f"Die fünfte Spalte gibt den Ausschlag: ohne sie {without} px, mit "
            f"ihr {with_field} px bei {self.TARGET_WIDTH} px Zielbreite. Laut "
            f"Auftrag §5 dann lieber 'Gespeichert' ohne Uhrzeit."
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
