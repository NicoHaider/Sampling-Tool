"""MainWindow – State-Maschine Welcome ↔ Workspace + Menu-Enablement."""

from __future__ import annotations

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


def _dataset() -> Dataset:
    return Dataset(
        name="Buchungen",
        columns=("Konto", "Betrag"),
        rows=tuple(
            DatasetRow(row_id=i, values={"Konto": f"K{i}", "Betrag": i * 10}) for i in range(1, 4)
        ),
        engagement_id=1,
        id=1,
    )


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

    def test_show_dataset_enables_sampling(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.show_dataset(_dataset())
        assert win._action_new_sample.isEnabled() is True
        assert win.data_table().table_model().rowCount() == 3

    def test_highlight_sample_enables_export(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.show_dataset(_dataset())
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

    def test_active_sample_status_label_filled(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.show_dataset(_dataset())
        win.set_samples([_sample()])
        win.highlight_sample(_sample())
        text = win._status_sample.text()
        assert "Aktive Stichprobe" in text
        assert "#1" in text
        assert "Einfach" in text
        assert "2/3" in text

    def test_active_sample_status_label_empty_when_cleared(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.show_dataset(_dataset())
        win.set_samples([_sample()])
        win.highlight_sample(_sample())
        win.clear_active_sample()
        assert win._status_sample.text() == "Aktive Stichprobe: keine"
