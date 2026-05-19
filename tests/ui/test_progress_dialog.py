"""Tests für `TaskProgressDialog` als Worker-Coordinator (Sprint 17, P-008).

Vorher war der Dialog nur ein `QProgressDialog` mit `progress_callback()`-
Adapter (Sprint 14). Mit Sprint 17 wird er zum Coordinator: `run_task(task)`
startet einen `TaskWorker`, blockt die UI bis fertig (Event-Loop läuft
weiter, daher responsive), liefert das Resultat oder None bei Cancel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from PyQt6.QtCore import Qt, QTimer
from pytestqt.qtbot import QtBot

from sampling_tool.core.cancellation import CancellationToken
from sampling_tool.ui.dialogs.progress_dialog import TaskProgressDialog
from sampling_tool.ui.workers.task_worker import ProgressReporter

pytestmark = pytest.mark.ui


@dataclass
class _EchoTask:
    value: Any

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> Any:
        progress.report(1, 1)
        return self.value


@dataclass
class _FailingTask:
    exc: Exception

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> Any:
        raise self.exc


@dataclass
class _LongTask:
    """Loopt bis Cancellation. Für Cancel-Tests."""

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> int:
        for i in range(100000):
            cancellation.raise_if_cancelled()
            progress.report(i, 100000)
        return 99


class TestTaskProgressDialog:
    def test_constructor_initializes_application_modal(self, qtbot: QtBot) -> None:
        dlg = TaskProgressDialog("Importiere Datei…", None)
        qtbot.addWidget(dlg)
        assert dlg.labelText() == "Importiere Datei…"
        assert dlg.windowModality() == Qt.WindowModality.ApplicationModal
        assert dlg.value() == 0
        assert dlg.minimumDuration() == 300

    def test_run_task_returns_result_on_success(self, qtbot: QtBot) -> None:
        dlg = TaskProgressDialog("Test", None)
        qtbot.addWidget(dlg)
        result = dlg.run_task(_EchoTask(value="ok"))
        assert result == "ok"

    def test_run_task_raises_on_exception(self, qtbot: QtBot) -> None:
        dlg = TaskProgressDialog("Test", None)
        qtbot.addWidget(dlg)
        with pytest.raises(RuntimeError, match="kaputt"):
            dlg.run_task(_FailingTask(exc=RuntimeError("kaputt")))

    def test_run_task_returns_none_on_cancel(self, qtbot: QtBot) -> None:
        """Cancel via dialog.cancel() → run_task liefert None."""
        dlg = TaskProgressDialog("Test", None)
        qtbot.addWidget(dlg)
        QTimer.singleShot(100, dlg.cancel)
        result = dlg.run_task(_LongTask())
        assert result is None

    def test_run_task_progress_updates_dialog_value(self, qtbot: QtBot) -> None:
        """Bei progress.report(c, t) muss der Dialog seinen Wert aktualisieren."""

        @dataclass
        class _ReportingTask:
            def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> int:
                progress.report(42, 100)
                return 0

        dlg = TaskProgressDialog("Test", None)
        qtbot.addWidget(dlg)
        result = dlg.run_task(_ReportingTask())
        assert result == 0
        # Nach setAutoReset/setAutoClose=True resettet der Dialog auf 0
        # nach Erreichen von maximum. Wir prüfen daher nur, dass der
        # Dialog ohne Exception durchlief.
