"""MainWindow – State-Maschine Welcome ↔ Workspace + Menu-Enablement."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PyQt6.QtCore import QRect, QSettings, QSize, Qt
from pytestqt.qtbot import QtBot

from sampling_tool.config import APP_NAME, APP_ORG
from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    Engagement,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import DatasetRepo, EngagementRepo
from sampling_tool.ui._geometry import fit_to_available
from sampling_tool.ui._window_state import _DESIRED_HEIGHT, _DESIRED_WIDTH, _int_or_none
from sampling_tool.ui.main_window import MainWindow
from sampling_tool.ui.recent import RecentEntry

pytestmark = pytest.mark.ui


def _engagement() -> Engagement:
    return Engagement(
        auditor_name="Anna",
        auditor_position="Senior",
        client_name="ACME",
        audit_type="ISAE 3402",
        id=1,
    )


@pytest.fixture
def dataset_with_repo(tmp_path: Path) -> Iterator[tuple[Dataset, DatasetRepo]]:
    """Persistiert ein 3-Zeilen-Dataset und liefert (Dataset, Repo).

    Sprint-11.2: `MainWindow.show_dataset` braucht ein Repo statt rows.
    """
    db = Database(tmp_path / "mw.db")
    db.migrate()
    eng = EngagementRepo(db.connect()).get_or_create(
        Engagement(auditor_name="A", client_name="C", auditor_position="S", audit_type="ISAE 3402")
    )
    assert eng.id is not None
    repo = DatasetRepo(db.connect())
    rows = tuple(
        DatasetRow(row_id=i, values={"Konto": f"K{i}", "Betrag": i * 10}) for i in range(1, 4)
    )
    dataset = repo.create(
        Dataset(name="Buchungen", columns=("Konto", "Betrag"), engagement_id=eng.id),
        rows,
    )
    try:
        yield dataset, repo
    finally:
        db.close()


def _sample() -> SampleResult:
    return SampleResult(
        config=SampleConfig(method=SamplingMethod.SIMPLE, size=2, seed=42),
        selected_row_ids=(1, 3),
        population_size=3,
        id=1,
    )


class TestMainWindowState:
    def test_initial_state_is_welcome(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        assert win.is_workspace_visible() is False

    def test_show_workspace_switches_state(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        assert win.is_workspace_visible() is True
        assert win._action_close.isEnabled() is True
        assert win._action_import.isEnabled() is True

    def test_show_welcome_disables_workspace_actions(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.show_welcome()
        assert win._action_close.isEnabled() is False
        assert win._action_import.isEnabled() is False

    def test_show_dataset_enables_sampling(
        self, qtbot: QtBot, dataset_with_repo: tuple[Dataset, DatasetRepo]
    ) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.show_dataset(*dataset_with_repo)
        assert win._action_new_sample.isEnabled() is True
        assert win.data_table().table_model().rowCount() == 3

    def test_highlight_sample_enables_export(
        self, qtbot: QtBot, dataset_with_repo: tuple[Dataset, DatasetRepo]
    ) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.show_dataset(*dataset_with_repo)
        win.highlight_sample(_sample())
        assert win._action_export_sample.isEnabled() is True
        assert 1 in win.data_table().table_model().highlighted_row_ids()

    def test_set_recent_entries_builds_menu(self, qtbot: QtBot, tmp_path: Path) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        db_path = tmp_path / "x.db"
        db_path.write_text("")
        entry = RecentEntry(
            path=db_path,
            client_name="ACME",
            audit_type="ISAE 3402",
            last_opened=datetime.now(UTC),
            opened_count=1,
        )
        win.set_recent_entries([entry])
        assert win._recent_menu.isEnabled() is True
        assert len(win._recent_menu.actions()) == 1
        assert win.welcome_screen().recent_card_count() == 1

    def test_set_engagement_updates_sidebar_and_status(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.set_engagement(_engagement())
        assert win._status_engagement.text() == "ACME"

    def test_active_sample_status_label_filled(
        self, qtbot: QtBot, dataset_with_repo: tuple[Dataset, DatasetRepo]
    ) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.show_dataset(*dataset_with_repo)
        win.set_samples([_sample()])
        win.highlight_sample(_sample())
        text = win._status_sample.text()
        assert "Aktive Stichprobe" in text
        assert "#1" in text
        assert "Einfach" in text
        assert "2/3" in text

    def test_active_sample_status_label_empty_when_cleared(
        self, qtbot: QtBot, dataset_with_repo: tuple[Dataset, DatasetRepo]
    ) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.show_dataset(*dataset_with_repo)
        win.set_samples([_sample()])
        win.highlight_sample(_sample())
        win.clear_active_sample()
        assert win._status_sample.text() == "Aktive Stichprobe: keine"

    def test_active_sample_status_label_filtered_suffix(
        self, qtbot: QtBot, dataset_with_repo: tuple[Dataset, DatasetRepo]
    ) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.show_dataset(*dataset_with_repo)
        win.set_samples([_sample()])
        win.highlight_sample(_sample(), filtered=True)
        assert "– gefiltert" in win._status_sample.text()

    def test_active_sample_status_label_no_suffix_when_not_filtered(
        self, qtbot: QtBot, dataset_with_repo: tuple[Dataset, DatasetRepo]
    ) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.show_dataset(*dataset_with_repo)
        win.set_samples([_sample()])
        win.highlight_sample(_sample(), filtered=False)
        assert "gefiltert" not in win._status_sample.text()


class TestSwitchEngagementToolbar:
    """Sprint 5.6: neuer Toolbar-Button 'Projekt wechseln' (Sprint 27 umbenannt)."""

    def test_toolbar_action_exists(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        assert hasattr(win, "_action_switch_engagement")
        assert win._action_switch_engagement.text() == "Projekt wechseln"

    def test_toolbar_action_emits_close_signal(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        with qtbot.waitSignal(win.close_engagement_requested, timeout=500):
            win._action_switch_engagement.trigger()

    def test_close_action_in_file_menu_emits_close_signal(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()  # Aktion ist nur enabled, wenn Workspace sichtbar.
        with qtbot.waitSignal(win.close_engagement_requested, timeout=500):
            win._action_close.trigger()


class TestSettingsAction:
    """Sprint 9.6: Einstellungen-Menüpunkt sichtbar im Datei-Menü."""

    def test_settings_action_im_datei_menue(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        assert win._action_settings in win._file_menu.actions()

    def test_settings_action_hat_preferences_role(self, qtbot: QtBot) -> None:
        from PyQt6.QtGui import QAction

        win = MainWindow()
        qtbot.addWidget(win)
        assert win._action_settings.menuRole() == QAction.MenuRole.PreferencesRole

    def test_settings_action_hat_preferences_shortcut(self, qtbot: QtBot) -> None:
        from PyQt6.QtGui import QKeySequence

        win = MainWindow()
        qtbot.addWidget(win)
        expected = QKeySequence(QKeySequence.StandardKey.Preferences)
        assert win._action_settings.shortcut() == expected

    def test_settings_action_emittiert_settings_signal(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        with qtbot.waitSignal(win.settings_requested, timeout=500):
            win._action_settings.trigger()


class TestSettingsToolbarButton:
    """Sprint 9.7: Einstellungen zusätzlich als Toolbar-Button."""

    def test_toolbar_enthaelt_settings_action(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        assert win._action_settings in win._toolbar.actions()

    def test_menue_und_toolbar_teilen_dieselbe_settings_action(self, qtbot: QtBot) -> None:
        # Identitäts-Check: dieselbe QAction-Instanz in Menü + Toolbar.
        win = MainWindow()
        qtbot.addWidget(win)
        assert win._action_settings in win._file_menu.actions()
        assert win._action_settings in win._toolbar.actions()

    def test_settings_action_hat_icon(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        assert not win._action_settings.icon().isNull()

    def test_settings_steht_in_toolbar_vor_bug_report(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        actions = win._toolbar.actions()
        settings_idx = actions.index(win._action_settings)
        bug_report_idx = actions.index(win._action_bug_report)
        assert settings_idx < bug_report_idx

    def test_settings_tooltip_enthaelt_shortcut(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        tooltip = win._action_settings.toolTip()
        assert "Einstellungen" in tooltip
        # Tooltip soll die plattformnative Shortcut-Repräsentation
        # enthalten – Format ist OS-abhängig (Mac "⌘,", Win "Ctrl+,",
        # offscreen-Plattform liefert "Settings"). Sanity: Klammer-Suffix
        # ist vorhanden, also wurde der Shortcut-Text angehängt.
        assert "(" in tooltip
        assert ")" in tooltip


class TestBugReportToolbarButton:
    """Sprint 9.2: Bug-Report jetzt zusätzlich rechtsbündig in der Toolbar."""

    def test_toolbar_enthaelt_bug_report_action(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        assert win._action_bug_report in win._toolbar.actions()

    def test_menue_und_toolbar_teilen_dieselbe_action(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        # Identitäts-Check: dieselbe QAction-Instanz in Menü + Toolbar.
        assert win._action_bug_report in win._help_menu.actions()
        assert win._action_bug_report in win._toolbar.actions()

    def test_toolbar_button_emittiert_bug_report_signal(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        with qtbot.waitSignal(win.bug_report_requested, timeout=500):
            win._action_bug_report.trigger()


class TestToolbarCompactOverflow:
    """Sprint 27: kompaktere Toolbar + Überlauf-Erreichbarkeit."""

    def test_toolbar_is_qtoolbar(self, qtbot: QtBot) -> None:
        # Eine echte QToolBar (kein Custom-Widget-Layout) → automatischer
        # Überlauf-/„»"-Extension-Button bei schmalem Fenster ist gegeben.
        from PyQt6.QtWidgets import QToolBar

        win = MainWindow()
        qtbot.addWidget(win)
        assert isinstance(win._toolbar, QToolBar)

    def test_toolbar_icons_are_compact(self, qtbot: QtBot) -> None:
        from sampling_tool.ui._window_toolbar import _TOOLBAR_ICON_SIZE

        win = MainWindow()
        qtbot.addWidget(win)
        assert win._toolbar.iconSize() == QSize(_TOOLBAR_ICON_SIZE, _TOOLBAR_ICON_SIZE)

    def test_all_main_actions_registered_in_toolbar(self, qtbot: QtBot) -> None:
        # Alle Haupt-Aktionen sind als QToolBar-Actions registriert und damit
        # auch bei Überlauf über das „»"-Menü erreichbar.
        win = MainWindow()
        qtbot.addWidget(win)
        actions = win._toolbar.actions()
        for attr in (
            "_action_switch_engagement",
            "_action_new",
            "_action_open",
            "_action_import",
            "_action_new_sample",
            "_action_reset_sampling",
            "_action_undo",
            "_action_redo",
            "_action_export_sample",
            "_action_export_pdf",
            "_action_excel_report",
            "_action_html_report",
            "_action_settings",
            "_action_bug_report",
        ):
            assert getattr(win, attr) in actions, f"{attr} fehlt in der Toolbar"

    def test_bug_report_action_hat_tooltip_und_icon(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        action = win._action_bug_report
        assert action.toolTip() == "Fehler melden oder Feedback senden"
        assert not action.icon().isNull()


class TestPanelVisibility:
    """Sprint 9.4: Dashboard- und AuditTrail-Tab via Settings togglebar."""

    def test_default_zeigt_beide_tabs(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        # Initial sind beide Tabs aktiv (Controller-Default).
        win.apply_panel_visibility(show_dashboard=True, show_audit_trail=True)
        assert win._lower_tabs.indexOf(win._dashboard_view) != -1
        assert win._lower_tabs.indexOf(win._audit_trail_view) != -1

    def test_nur_dashboard(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.apply_panel_visibility(show_dashboard=True, show_audit_trail=False)
        assert win._lower_tabs.indexOf(win._dashboard_view) != -1
        assert win._lower_tabs.indexOf(win._audit_trail_view) == -1

    def test_nur_audit_trail(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.apply_panel_visibility(show_dashboard=False, show_audit_trail=True)
        assert win._lower_tabs.indexOf(win._dashboard_view) == -1
        assert win._lower_tabs.indexOf(win._audit_trail_view) != -1

    def test_beide_aus_versteckt_tabwidget(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        win.apply_panel_visibility(show_dashboard=False, show_audit_trail=False)
        # `isVisible` ist False, weil das Widget explizit versteckt wurde.
        assert win._lower_tabs.isVisible() is False
        # Beide Tabs sind weg
        assert win._lower_tabs.count() == 0

    def test_beide_aus_cacht_splitter_sizes(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        # Aktuellen Splitter-Zustand merken.
        before = win._workspace_splitter.sizes()
        assert sum(before) > 0  # sanity: Splitter hat Größen
        win.apply_panel_visibility(show_dashboard=False, show_audit_trail=False)
        assert win._cached_splitter_sizes == before
        # Untere Hälfte ist auf 0 kollabiert, Datentabelle nutzt die volle Höhe.
        sizes_now = win._workspace_splitter.sizes()
        assert sizes_now[1] == 0
        assert sizes_now[0] == sum(before)

    def test_roundtrip_restored_splitter_sizes(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        before = win._workspace_splitter.sizes()
        win.apply_panel_visibility(show_dashboard=False, show_audit_trail=False)
        win.apply_panel_visibility(show_dashboard=True, show_audit_trail=True)
        assert win._cached_splitter_sizes is None
        assert win._workspace_splitter.sizes() == before

    def test_toggle_einzeln_aendert_splitter_nicht(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        before = win._workspace_splitter.sizes()
        win.apply_panel_visibility(show_dashboard=True, show_audit_trail=False)
        # Splitter bleibt unverändert, Cache leer (kein Collapse).
        assert win._cached_splitter_sizes is None
        assert win._workspace_splitter.sizes() == before

    def test_save_workspace_state_nutzt_cached_sizes(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        before = win._workspace_splitter.sizes()
        win.apply_panel_visibility(show_dashboard=False, show_audit_trail=False)
        # In dem Moment ist der Splitter auf [total, 0] kollabiert.
        win._save_workspace_state()
        # Save hat den Cache temporär gesetzt → Splitter hat echte Größen.
        assert win._workspace_splitter.sizes() == before


class TestWindowStateController:
    """Sprint 19 / F-006: QSettings-/Panel-State im WindowStateController."""

    def test_apply_panel_visibility_hides_both_panels(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        win._window_state.apply_panel_visibility(show_dashboard=False, show_audit_trail=False)
        assert win._lower_tabs.isVisible() is False
        assert win._lower_tabs.count() == 0

    def test_splitter_sizes_cached_and_restored_on_collapse(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        before = win._workspace_splitter.sizes()
        win._window_state.apply_panel_visibility(show_dashboard=False, show_audit_trail=False)
        assert win._window_state._cached_splitter_sizes == before
        win._window_state.apply_panel_visibility(show_dashboard=True, show_audit_trail=True)
        assert win._window_state._cached_splitter_sizes is None
        assert win._workspace_splitter.sizes() == before

    def test_restore_falls_back_to_default_tab_on_garbage(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win._settings.setValue("workspace/lower_tab", "kein-int")
        win._window_state.restore()
        assert win._lower_tabs.currentIndex() == 0


class TestMainWindowComposition:
    """Sprint 19 / F-006: MainWindow bleibt dünner Compositor, API unverändert."""

    def test_public_api_attributes_present(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        for name in (
            "_file_menu",
            "_help_menu",
            "_recent_menu",
            "_toolbar",
            "_action_new",
            "_action_settings",
            "_action_bug_report",
            "_action_switch_engagement",
        ):
            assert hasattr(win, name), name
        assert win.data_table() is not None
        assert win.workspace_splitter() is not None
        assert win.lower_tabs() is not None

    def test_helper_modules_qt_importable(self) -> None:
        from sampling_tool.ui import (
            _window_layout,
            _window_menu,
            _window_state,
            _window_toolbar,
        )

        assert callable(_window_layout.build_workspace)
        assert callable(_window_menu.build_menu)
        assert callable(_window_menu.rebuild_recent_menu)
        assert callable(_window_toolbar.build_toolbar)
        assert _window_state.WindowStateController is not None

    def test_sidebar_is_resizable(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        sidebar = win.sidebar()
        assert sidebar.minimumWidth() < sidebar.maximumWidth()


class TestResetSamplingToolbar:
    """Sprint 20: Toolbar-Button „Sampling zurücksetzen"."""

    def test_toolbar_contains_reset_sampling_action(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        assert hasattr(win, "_action_reset_sampling")
        assert win._action_reset_sampling in win._toolbar.actions()

    def test_reset_sampling_action_adjacent_to_new_sample(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        actions = win._toolbar.actions()
        i_new = actions.index(win._action_new_sample)
        i_reset = actions.index(win._action_reset_sampling)
        assert i_reset == i_new + 1

    def test_reset_sampling_action_emits_signal(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.set_reset_enabled(True)
        with qtbot.waitSignal(win.reset_sampling_requested, timeout=1000):
            win._action_reset_sampling.trigger()

    def test_set_reset_enabled_toggles_toolbar_and_menu_actions(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.set_reset_enabled(True)
        assert win._action_reset_sampling.isEnabled() is True
        assert win._action_reset_sample.isEnabled() is True
        win.set_reset_enabled(False)
        assert win._action_reset_sampling.isEnabled() is False
        assert win._action_reset_sample.isEnabled() is False

    def test_reset_sampling_disabled_on_welcome(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.set_reset_enabled(True)
        win.show_welcome()
        assert win._action_reset_sampling.isEnabled() is False


class TestWindowGeometryFitsScreen:
    """Sprint 67 / Teil A: Startgröße passt in den verfügbaren Bildschirmbereich."""

    @pytest.fixture(autouse=True)
    def _isolated_qsettings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Schiebt `QSettings`-IO in einen tmp-Pfad, damit echte Prefs unangetastet
        bleiben (gleiches Muster wie `test_feature_toggles`/`test_settings_store`).

        Zusatz (Code-Review-Nachtrag zu Sprint 67 Task 2): `QSettings(org, app)`
        ist laut Qt-Doku fest auf `NativeFormat`/`UserScope` verdrahtet und
        ignoriert `setDefaultFormat`/`setPath` (siehe ausführlicher Kommentar in
        `TestWindowGeometryPersistence._isolated_qsettings`). Seit Task 2 liest
        `restore()` echte `window/*`-Werte – ohne diesen Patch würde dieser Test
        von zufällig echten (auf diesem Rechner bereits gespeicherten) Prefs
        abhängen und könnte je nach Ausführungsreihenfolge/Vorlauf flackern.
        """
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        monkeypatch.setattr(
            "sampling_tool.ui.main_window.QSettings",
            lambda organization, application: QSettings(
                QSettings.Format.IniFormat, QSettings.Scope.UserScope, organization, application
            ),
        )

    def test_initial_geometry_fits_available_screen(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        screen = win.screen()
        assert screen is not None
        assert screen.availableGeometry().contains(win.geometry())


class TestWindowGeometryPersistence:
    """Sprint 67 / Teil A: Fenstergeometrie (Größe/Position/Maximiert) überlebt einen Neustart."""

    @pytest.fixture(autouse=True)
    def _isolated_qsettings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Schiebt `QSettings`-IO in einen tmp-Pfad, damit echte Prefs unangetastet
        bleiben (gleiches Muster wie `test_feature_toggles`/`test_settings_store`).

        Zusatz (Code-Review-Nachtrag): der 2-Arg-Konstruktor `QSettings(org, app)`
        ist laut Qt-Doku fest auf `NativeFormat`/`UserScope` verdrahtet und
        ignoriert `setDefaultFormat`/`setPath` – verifiziert via `fileName()`,
        das trotz obigem `setPath` weiterhin auf die echte
        `~/Library/Preferences/…plist` zeigte. `MainWindow.__init__` nutzt genau
        diesen Konstruktor fest verdrahtet (kein überschreibbares Factory wie
        `settings_store._qsettings`) – deshalb hier zusätzlich `main_window.
        QSettings` patchen, analog zum Muster in `test_settings_store.py`.
        """
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        monkeypatch.setattr(
            "sampling_tool.ui.main_window.QSettings",
            lambda organization, application: QSettings(
                QSettings.Format.IniFormat, QSettings.Scope.UserScope, organization, application
            ),
        )

    def test_geometry_roundtrip(self, qtbot: QtBot) -> None:
        """Größe/Position/Maximiert überleben einen Save/Restore-Zyklus."""
        win1 = MainWindow()
        qtbot.addWidget(win1)
        win1.show()
        qtbot.waitExposed(win1)
        # 1000×650 statt eines kleineren Werts: `MainWindow` hat (unabhängig von
        # Sprint 67) über Sidebar + AuditTrail-Filterzeile eine echte Layout-
        # Mindestbreite von ca. 810–870px – ein kleinerer Zielwert würde beim
        # `setGeometry` auf einem bereits `show()`n Fenster von Qt sofort auf
        # die Mindestgröße hochgeklemmt und damit den Roundtrip verfälschen.
        win1.setGeometry(20, 20, 1000, 650)
        win1._window_state.save()

        win2 = MainWindow()
        qtbot.addWidget(win2)
        win2.show()
        qtbot.waitExposed(win2)
        assert win2.geometry() == QRect(20, 20, 1000, 650)

        win3 = MainWindow()
        qtbot.addWidget(win3)
        win3.show()
        qtbot.waitExposed(win3)
        win3.setWindowState(win3.windowState() | Qt.WindowState.WindowMaximized)
        win3._window_state.save()

        win4 = MainWindow()
        qtbot.addWidget(win4)
        win4.show()
        qtbot.waitExposed(win4)
        assert bool(win4.windowState() & Qt.WindowState.WindowMaximized) is True

    def test_invalid_geometry_falls_back(self, qtbot: QtBot) -> None:
        """Eine außerhalb aller Screens liegende gespeicherte Geometrie wird verworfen."""
        # Explizites Format/Scope statt `QSettings(APP_ORG, APP_NAME)`: der
        # 2-Arg-Konstruktor ignoriert `setPath`/`setDefaultFormat` (siehe
        # `_isolated_qsettings`) – ohne dies würde hier in die echten,
        # ungeschützten Prefs geschrieben statt in den isolierten tmp-Pfad.
        settings = QSettings(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG, APP_NAME
        )
        settings.setValue("window/x", 50_000)
        settings.setValue("window/y", 50_000)
        settings.setValue("window/width", 700)
        settings.setValue("window/height", 500)

        win = MainWindow()
        qtbot.addWidget(win)

        screen = win.screen()
        assert screen is not None
        expected = fit_to_available(
            QSize(_DESIRED_WIDTH, _DESIRED_HEIGHT), screen.availableGeometry()
        )
        assert win.geometry() == expected

    def test_partial_geometry_falls_back(self, qtbot: QtBot) -> None:
        """Nur x/y ohne width/height gesetzt → `_read_saved_rect` verwirft, Fallback greift."""
        # Siehe Kommentar in `test_invalid_geometry_falls_back`: explizites
        # Format/Scope statt des isolierungslosen 2-Arg-Konstruktors.
        settings = QSettings(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG, APP_NAME
        )
        settings.setValue("window/x", 100)
        settings.setValue("window/y", 100)
        # width/height bewusst NICHT gesetzt.

        win = MainWindow()
        qtbot.addWidget(win)

        screen = win.screen()
        assert screen is not None
        expected = fit_to_available(
            QSize(_DESIRED_WIDTH, _DESIRED_HEIGHT), screen.availableGeometry()
        )
        assert win.geometry() == expected

    def test_non_positive_size_falls_back(self, qtbot: QtBot) -> None:
        """width=0 (alle 4 Werte vorhanden, aber kaputt) → `_read_saved_rect` verwirft.

        Andere Fehlerart als `test_partial_geometry_falls_back` (dort fehlen
        Werte komplett) – deckt den separaten `width <= 0 or height <= 0`-Zweig
        in `_read_saved_rect` ab.
        """
        settings = QSettings(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG, APP_NAME
        )
        settings.setValue("window/x", 100)
        settings.setValue("window/y", 100)
        settings.setValue("window/width", 0)
        settings.setValue("window/height", 500)

        win = MainWindow()
        qtbot.addWidget(win)

        screen = win.screen()
        assert screen is not None
        expected = fit_to_available(
            QSize(_DESIRED_WIDTH, _DESIRED_HEIGHT), screen.availableGeometry()
        )
        assert win.geometry() == expected


class TestIntOrNone:
    """Sprint 67 / Teil A: `_int_or_none` – QSettings liefert str (Windows/INI) oder nativen Typ."""

    def test_rejects_bool_despite_bool_being_an_int_subtype(self) -> None:
        assert _int_or_none(True) is None
        assert _int_or_none(False) is None

    def test_accepts_native_int(self) -> None:
        assert _int_or_none(42) == 42

    def test_parses_numeric_string(self) -> None:
        assert _int_or_none("42") == 42

    def test_rejects_malformed_string(self) -> None:
        assert _int_or_none("not-a-number") is None

    def test_rejects_none_and_other_types(self) -> None:
        assert _int_or_none(None) is None
        assert _int_or_none(3.5) is None


class TestOuterSplitterPersistence:
    """Sprint 67 / Teil A: Sidebar-Breite (äußerer Splitter) überlebt einen Neustart."""

    @pytest.fixture(autouse=True)
    def _isolated_qsettings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Schiebt `QSettings`-IO in einen tmp-Pfad, damit echte Prefs unangetastet
        bleiben. Siehe `TestWindowGeometryPersistence._isolated_qsettings` für den
        vollständigen Hintergrund (QSettings(org, app) ignoriert setPath/setDefaultFormat,
        `main_window.QSettings` muss deshalb zusätzlich gepatcht werden)."""
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        monkeypatch.setattr(
            "sampling_tool.ui.main_window.QSettings",
            lambda organization, application: QSettings(
                QSettings.Format.IniFormat, QSettings.Scope.UserScope, organization, application
            ),
        )

    def test_outer_splitter_persisted(self, qtbot: QtBot) -> None:
        win1 = MainWindow()
        qtbot.addWidget(win1)
        win1.show()
        qtbot.waitExposed(win1)
        # Der äußere Splitter liegt auf der Workspace-Seite des Welcome/
        # Workspace-`QStackedWidget`, die anfangs NICHT die aktuelle Seite ist
        # (siehe `show_welcome()` am Ende von `MainWindow.__init__`). Eine
        # nicht-aktuelle Stack-Seite bekommt von Qt keine reale Layout-Größe
        # zugewiesen – jede `setSizes`-Anfrage würde sonst wirkungslos auf die
        # winzige Default-Größe zurückfallen, weshalb hier zuerst auf den
        # Workspace umgeschaltet wird. Zusätzlich braucht das Fenster – analog
        # zu `TestWindowGeometryPersistence.test_geometry_roundtrip` – eine
        # reale Breite oberhalb seiner Layout-Mindestbreite (~810–870px),
        # sonst ist für den Splitter kein Spielraum zum Verschieben vorhanden.
        win1.show_workspace()
        win1.setGeometry(20, 20, 1000, 650)
        win1.outer_splitter().setSizes([300, 400])
        win1._window_state.save()

        win2 = MainWindow()
        qtbot.addWidget(win2)
        win2.show()
        qtbot.waitExposed(win2)
        win2.show_workspace()
        win2.setGeometry(20, 20, 1000, 650)
        assert win2.outer_splitter().sizes()[0] == 300


class TestMainWindowMinimumSize:
    """Sprint 67 / Teil A: Mindestgröße passt auf 1280×720 (13-Zoll-Zielgerät)."""

    def test_minimum_size_fits_target_device(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        assert 0 < win.minimumWidth() <= 1280
        assert 0 < win.minimumHeight() <= 720
