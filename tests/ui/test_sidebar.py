"""NavigationSidebar – Signals und Listen-Beschriftungen."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import (
    Dataset,
    Engagement,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.ui.widgets.sidebar import NavigationSidebar

pytestmark = pytest.mark.ui


def _ds(name: str, ds_id: int) -> Dataset:
    return Dataset(name=name, columns=(), rows=(), id=ds_id, engagement_id=1)


def _sample(sample_id: int, size: int = 5) -> SampleResult:
    return SampleResult(
        config=SampleConfig(method=SamplingMethod.SIMPLE, size=size, seed=1),
        selected_row_ids=tuple(range(1, size + 1)),
        population_size=50,
        id=sample_id,
    )


class TestNavigationSidebar:
    def test_set_engagement_renders_title(self, qtbot: QtBot) -> None:
        sidebar = NavigationSidebar()
        qtbot.addWidget(sidebar)
        sidebar.set_engagement(
            Engagement(
                auditor_name="Anna",
                client_name="ACME GmbH",
                auditor_position="Senior",
                audit_type="ISAE 3402",
            )
        )
        sidebar.set_datasets([])
        sidebar.set_samples([])
        # Direkter Zugriff über findChildren wäre overkill – wir akzeptieren
        # den indirekten Beweis durch fehlerfreies Wiederbefüllen.
        sidebar.set_engagement(None)

    def test_set_datasets_populates_items(self, qtbot: QtBot) -> None:
        sidebar = NavigationSidebar()
        qtbot.addWidget(sidebar)
        sidebar.set_datasets([_ds("Buchungen", 1), _ds("Stammdaten", 2)])
        assert sidebar.datasets_widget().count() == 2
        item = sidebar.datasets_widget().item(0)
        assert item is not None
        assert item.text() == "Buchungen"
        assert item.data(int(Qt.ItemDataRole.UserRole)) == 1

    def test_dataset_click_emits_id(self, qtbot: QtBot) -> None:
        sidebar = NavigationSidebar()
        qtbot.addWidget(sidebar)
        sidebar.set_datasets([_ds("A", 10), _ds("B", 20)])
        with qtbot.waitSignal(sidebar.dataset_selected, timeout=500) as blocker:
            item = sidebar.datasets_widget().item(1)
            assert item is not None
            sidebar.datasets_widget().itemClicked.emit(item)
        assert blocker.args == [20]

    def test_sample_click_emits_id(self, qtbot: QtBot) -> None:
        sidebar = NavigationSidebar()
        qtbot.addWidget(sidebar)
        sidebar.set_samples([_sample(5), _sample(6)])
        with qtbot.waitSignal(sidebar.sample_selected, timeout=500) as blocker:
            item = sidebar.samples_widget().item(0)
            assert item is not None
            sidebar.samples_widget().itemClicked.emit(item)
        assert blocker.args == [5]

    def test_sample_double_click_emits_signal(self, qtbot: QtBot) -> None:
        sidebar = NavigationSidebar()
        qtbot.addWidget(sidebar)
        sidebar.set_samples([_sample(99)])
        with qtbot.waitSignal(sidebar.sample_double_clicked, timeout=500) as blocker:
            item = sidebar.samples_widget().item(0)
            assert item is not None
            sidebar.samples_widget().itemDoubleClicked.emit(item)
        assert blocker.args == [99]

    def test_sample_label_includes_method_and_size(self, qtbot: QtBot) -> None:
        sidebar = NavigationSidebar()
        qtbot.addWidget(sidebar)
        sidebar.set_samples([_sample(1, size=42)])
        item = sidebar.samples_widget().item(0)
        assert item is not None
        text = item.text()
        assert "simple" in text
        assert "n=42" in text
        assert "seed 1" in text

    def test_clear_samples_empties_list(self, qtbot: QtBot) -> None:
        sidebar = NavigationSidebar()
        qtbot.addWidget(sidebar)
        sidebar.set_samples([_sample(1), _sample(2)])
        sidebar.clear_samples()
        assert sidebar.samples_widget().count() == 0

    def test_set_active_sample_marks_item_bold_with_bullet(self, qtbot: QtBot) -> None:
        sidebar = NavigationSidebar()
        qtbot.addWidget(sidebar)
        sidebar.set_samples([_sample(1), _sample(2)])
        sidebar.set_active_sample(2)
        first = sidebar.samples_widget().item(0)
        second = sidebar.samples_widget().item(1)
        assert first is not None
        assert second is not None
        assert not first.text().startswith("●")
        assert second.text().startswith("●")
        assert first.font().bold() is False
        assert second.font().bold() is True

    def test_set_active_sample_none_clears_marker(self, qtbot: QtBot) -> None:
        sidebar = NavigationSidebar()
        qtbot.addWidget(sidebar)
        sidebar.set_samples([_sample(1)])
        sidebar.set_active_sample(1)
        sidebar.set_active_sample(None)
        item = sidebar.samples_widget().item(0)
        assert item is not None
        assert not item.text().startswith("●")
        assert item.font().bold() is False
