"""Dashboard auf Deutsch und aktuell (Sprint 85 / D).

Rohwerte aus der DB (`simple`, `sampling`) gehören nicht auf die Achsen; die
Zähl-Diagramme brauchen ganzzahlige Achsenstriche (vorher 0.25-Schritte); und
das Dashboard muss nach jeder Aktion stimmen, ohne dass jemand „Aktualisieren"
drückt.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QLabel, QMessageBox
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import (
    AuditEvent,
    Dataset,
    DatasetRow,
    Engagement,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.io import charts
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import DatasetRepo, EngagementRepo
from sampling_tool.ui.controllers.main_controller import MainController
from sampling_tool.ui.dialogs.sampling_dialog import SamplingDialogResult
from sampling_tool.ui.main_window import MainWindow
from sampling_tool.ui.recent import RecentEngagementsStore
from sampling_tool.ui.widgets import chart_renderer, dashboard_view
from sampling_tool.ui.widgets.dashboard_view import DashboardView, _ClickableSampleLabel

pytestmark = pytest.mark.ui

_NOW = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)


def _sample(sample_id: int, method: SamplingMethod) -> SampleResult:
    config = SampleConfig(method=method, size=1, seed=1, cluster_field="a", stratum_field="a")
    return SampleResult(
        config=config,
        selected_row_ids=(1,),
        population_size=3,
        id=sample_id,
        drawn_at=_NOW,
    )


def _event(event_type: str) -> AuditEvent:
    return AuditEvent(event_type=event_type, engagement_id=1, timestamp=_NOW)


class TestGermanLabelsAndIntegerTicks:
    @pytest.fixture
    def charts_seen(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        seen: list[dict[str, Any]] = []
        real_bar = chart_renderer.render_bar_chart
        real_line = chart_renderer.render_line_chart

        def spy(real: Any) -> Any:
            def wrapper(labels: list[str], values: list[float], **kwargs: Any) -> Any:
                seen.append({"labels": list(labels), **kwargs})
                return real(labels, values, **kwargs)

            return wrapper

        monkeypatch.setattr(dashboard_view, "render_bar_chart", spy(real_bar))
        monkeypatch.setattr(dashboard_view, "render_line_chart", spy(real_line))
        return seen

    def _fill(self, qtbot: QtBot) -> DashboardView:
        view = DashboardView()
        qtbot.addWidget(view)
        view.set_data(
            Engagement(auditor_name="A", client_name="C", id=1),
            [Dataset(name="d", columns=("a",), id=1)],
            [_sample(1, SamplingMethod.SIMPLE), _sample(2, SamplingMethod.CLUSTER)],
            [_event("sampling"), _event("import"), _event("sampling")],
        )
        return view

    def test_axes_use_german_labels(self, qtbot: QtBot, charts_seen: list[dict[str, Any]]) -> None:
        self._fill(qtbot)
        by_title = {c["title"]: c["labels"] for c in charts_seen}
        assert sorted(by_title["Methoden"]) == ["Cluster", "Einfach"]
        assert by_title["Top-Eventtypen"] == ["Stichprobe", "Import"]

    def test_count_charts_request_integer_ticks(
        self, qtbot: QtBot, charts_seen: list[dict[str, Any]]
    ) -> None:
        self._fill(qtbot)
        assert len(charts_seen) == 3
        assert all(c.get("integer_ticks") is True for c in charts_seen)

    def test_recent_samples_list_uses_method_labels(self, qtbot: QtBot) -> None:
        view = self._fill(qtbot)
        texts = [
            lbl.text() for lbl in view.recent_samples_tile().findChildren(_ClickableSampleLabel)
        ]
        assert any("· Cluster ·" in t for t in texts)
        assert any("· Einfach ·" in t for t in texts)
        assert not any("simple" in t or "cluster" in t for t in texts)

    @pytest.mark.parametrize(
        "render", [charts.render_bar_chart_bytes, charts.render_line_chart_bytes]
    )
    def test_integer_ticks_are_whole_numbers(
        self, render: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        figures: list[Figure] = []
        real = charts._figure_to_bytes

        def capture(fig: Figure, scale: float = 1.0) -> bytes:
            figures.append(fig)
            return real(fig, scale)

        monkeypatch.setattr(charts, "_figure_to_bytes", capture)
        render(["a", "b"], [1.0, 2.0], integer_ticks=True)
        ticks = figures[0].axes[0].get_yticks()
        assert all(float(t).is_integer() for t in ticks)

    def test_default_keeps_report_charts_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Berichte (HTML/Excel) rufen ohne `integer_ticks` – ihre Bytes bleiben gleich."""
        assert charts.render_bar_chart_bytes(["a"], [1.0]) == charts.render_bar_chart_bytes(
            ["a"], [1.0], integer_ticks=False
        )


# ---------------------------------------------------------------------------
# Aktualisierung nach Aktionen
# ---------------------------------------------------------------------------


class _AcceptingSamplingDialog:
    DialogCode = QDialog.DialogCode

    def __init__(self, result: SamplingDialogResult) -> None:
        self._result = result

    def set_initial_seed(self, seed: int) -> None:
        pass

    def set_validators(self, **_kwargs: object) -> None:
        pass

    def exec(self) -> int:
        return int(QDialog.DialogCode.Accepted)

    def get_result(self) -> SamplingDialogResult:
        return self._result


def _big_numbers(view: DashboardView) -> list[str]:
    return [
        label.text()
        for tile in (view.datasets_tile(), view.samples_tile(), view.events_tile())
        for label in tile.findChildren(QLabel)
        if label.text().isdigit()
    ]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    db_path = tmp_path / "p.db"
    db = Database(db_path)
    db.migrate()
    eng = EngagementRepo(db.connect()).get_or_create(
        Engagement(auditor_name="A", client_name="C", audit_type="ISAE 3402")
    )
    assert eng.id is not None
    ds = DatasetRepo(db.connect()).create(
        Dataset(name="d", columns=("a",), engagement_id=eng.id),
        tuple(DatasetRow(row_id=i, values={"a": i}) for i in range(1, 6)),
    )
    assert ds.id is not None
    db.close()
    return db_path


@pytest.fixture
def controller(qtbot: QtBot, tmp_path: Path, project: Path) -> Iterator[MainController]:
    window = MainWindow()
    qtbot.addWidget(window)
    result = SamplingDialogResult(config=SampleConfig(method=SamplingMethod.SIMPLE, size=2, seed=7))
    ctrl = MainController(
        window,
        recent_store=RecentEngagementsStore(path=tmp_path / "recent.json"),
        sampling_dialog_factory=lambda *_a, **_k: _AcceptingSamplingDialog(result),  # type: ignore[arg-type]
    )
    ctrl.engagement.handle_open_engagement(project)
    item = window.sidebar().datasets_widget().item(0)
    assert item is not None
    ctrl.selection.handle_dataset_selected(item.data(int(Qt.ItemDataRole.UserRole)))
    yield ctrl
    ctrl.engagement.handle_close_engagement()


class TestDashboardRefreshesAfterSampling:
    def _view(self, controller: MainController) -> DashboardView:
        return controller.session.window._dashboard_view

    def test_sampling_updates_counts_without_refresh_button(
        self, controller: MainController
    ) -> None:
        before = _big_numbers(self._view(controller))
        controller.workspace.handle_new_sampling()
        after = _big_numbers(self._view(controller))
        assert before[1] == "0"
        assert after[1] == "1"

    def test_reset_undo_redo_update_event_count(self, controller: MainController) -> None:
        controller.workspace.handle_new_sampling()
        counts = [int(_big_numbers(self._view(controller))[2])]
        with patch(
            "sampling_tool.ui.controllers.workspace_controller.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            controller.workspace.handle_reset()
        counts.append(int(_big_numbers(self._view(controller))[2]))
        controller.workspace.handle_undo()
        counts.append(int(_big_numbers(self._view(controller))[2]))
        controller.workspace.handle_redo()
        counts.append(int(_big_numbers(self._view(controller))[2]))
        assert counts == sorted(counts)
        assert len(set(counts)) == len(counts)
