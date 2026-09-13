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
from PyQt6.QtGui import QFontMetrics, QKeySequence
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


class TestConfirmationFitsTheStatusBar:
    """Die Erklärung muss lesbar sein – gerade auf dem kleinsten Zielgerät.

    Die temporäre `showMessage`-Fläche teilt sich die Statusleiste mit den
    nun FÜNF permanenten Feldern. Wird der Satz länger, schneidet Qt ihn
    ausgerechnet auf dem 13"-Laptop ab – also dort, wo die Beruhigung am
    nötigsten ist.

    Gemessen wird die ECHTE Geometrie nach dem Layout, nicht eine Summe von
    `sizeHint()`s: die unterschlägt Layout-Spacing, das Padding der
    Trennstriche und den `QSizeGrip` und liefert deshalb einen viel zu
    optimistischen Wert (erst der Screenshot zeigte die Kollision). Der
    freie Platz endet exakt an der linken Kante des am weitesten links
    stehenden permanenten Widgets.

    Der Vergleich ist relativ (Satz vs. tatsächlich freier Platz), damit
    breitere Windows-Fonts beide Seiten mitskalieren statt den Test rot zu
    machen.
    """

    #: Richtwert fürs kleinste Zielgerät, wie `main_window.py` ihn nennt.
    TARGET_WIDTH = 1280

    def _available_px(self, window: MainWindow, qtbot: QtBot) -> int:
        window.show_workspace()
        window.resize(self.TARGET_WIDTH, 720)
        window.show()
        qtbot.waitExposed(window)
        # Realistische, KEINE extremen Inhalte: ein Mandantenname mittlerer
        # Länge, ein gewöhnlicher Dateiname und eine aktive Stichprobe. Ohne
        # `set_engagement` bliebe hier „Kein Projekt" stehen – das breiteste
        # Feld wäre künstlich schmal und der Test damit zahnlos.
        window.set_engagement(
            Engagement(
                auditor_name="Anna Auditorin",
                auditor_position="Senior Auditor",
                client_name="Mustermann Handels GmbH",
                audit_type="ISAE 3402 Typ II",
                id=1,
            )
        )
        window._status_dataset.setText("Buchungssaetze_2025.xlsx")
        window._status_rows.setText("1.234.567 Zeilen")
        window._status_sample.setText("Aktive Stichprobe: #12 (Einfach, 60/1234567)")
        window.set_saved_at(FROZEN_NOW)
        status = window.statusBar()
        assert status is not None
        layout = status.layout()
        if layout is not None:
            layout.activate()
        permanent = [
            child
            for child in status.children()
            if isinstance(child, QWidget) and not child.isHidden()
        ]
        assert permanent, "keine permanenten Widgets gefunden – Messung wäre vakuum"
        return min(child.x() for child in permanent)

    def test_message_fits_next_to_the_five_permanent_fields(
        self, window: MainWindow, qtbot: QtBot
    ) -> None:
        available = self._available_px(window, qtbot)
        status = window.statusBar()
        assert status is not None
        needed = QFontMetrics(status.font()).horizontalAdvance(SAVE_CONFIRMATION_MESSAGE)
        assert needed <= available, (
            f"Bestätigungstext braucht {needed} px, frei sind nur {available} px "
            f"(bei {self.TARGET_WIDTH} px Fensterbreite, aktive Stichprobe "
            f"angezeigt). Kürzen – die lange Fassung gehört in den Tooltip."
        )

    def test_the_full_rule_lives_in_the_tooltip(self, window: MainWindow) -> None:
        """Was nicht in die Statuszeile passt, muss trotzdem erreichbar sein."""
        tooltip = window._action_save.toolTip().lower()
        assert "automatisch" in tooltip
        assert "nach jeder änderung" in tooltip


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
