"""MainWindow – State-Maschine Welcome ↔ Workspace + Menu-Enablement."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

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
    """Sprint 5.6: neuer Toolbar-Button 'Engagement wechseln'."""

    def test_toolbar_action_exists(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        assert hasattr(win, "_action_switch_engagement")
        assert win._action_switch_engagement.text() == "Engagement wechseln"

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
