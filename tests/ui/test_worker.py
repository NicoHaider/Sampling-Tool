"""Tests für die Worker-Architektur (Sprint 17, P-008).

`TaskWorker` läuft in einem Hintergrund-Thread, kommuniziert mit dem
UI-Thread via Qt-Signals. Diese Tests nutzen `qtbot.waitSignal`
(asynchron), kein `time.sleep`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import pytest
from pytestqt.qtbot import QtBot

from sampling_tool.core.cancellation import CancellationToken, OperationCancelled
from sampling_tool.ui.workers.task_worker import (
    ProgressReporter,
    TaskWorker,
    WorkerTask,
)

pytestmark = pytest.mark.ui


# ---------------------------------------------------------------------------
# Test-Tasks
# ---------------------------------------------------------------------------


@dataclass
class _EchoTask:
    """Liefert seinen `value` direkt zurück. Für Erfolgstests."""

    value: object

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> object:
        progress.report(1, 1)
        return self.value


@dataclass
class _FailingTask:
    exc: Exception

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> object:
        raise self.exc


@dataclass
class _CancellableTask:
    """Loopt bis das Cancellation-Token gesetzt wird."""

    steps: int = 1000

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> int:
        for i in range(self.steps):
            cancellation.raise_if_cancelled()
            progress.report(i, self.steps)
            time.sleep(0.001)
        return self.steps


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTaskWorker:
    def test_successful_task_emits_finished_with_result(self, qtbot: QtBot) -> None:
        task: WorkerTask[object] = _EchoTask(value="hello")
        worker = TaskWorker(task)
        with qtbot.waitSignal(worker.finished_with_result, timeout=2000) as blocker:
            worker.start()
        assert blocker.args == ["hello"]
        worker.wait()

    def test_failing_task_emits_failed_with_exception(self, qtbot: QtBot) -> None:
        boom = RuntimeError("kaputt")
        worker = TaskWorker(_FailingTask(exc=boom))
        with qtbot.waitSignal(worker.failed, timeout=2000) as blocker:
            worker.start()
        assert isinstance(blocker.args[0], RuntimeError)
        assert str(blocker.args[0]) == "kaputt"
        worker.wait()

    def test_cancelled_task_emits_cancelled(self, qtbot: QtBot) -> None:
        worker = TaskWorker(_CancellableTask(steps=10000))
        with qtbot.waitSignal(worker.cancelled, timeout=3000):
            worker.start()
            # Direkt nach Start abbrechen.
            qtbot.wait(50)
            worker.request_cancel()
        worker.wait()

    def test_progress_signal_emitted_during_run(self, qtbot: QtBot) -> None:
        worker = TaskWorker(_EchoTask(value=42))
        with qtbot.waitSignal(worker.progress, timeout=2000) as blocker:
            worker.start()
        assert blocker.args == [1, 1]
        worker.wait()

    def test_request_cancel_before_start_marks_token(self, qtbot: QtBot) -> None:
        worker = TaskWorker(_EchoTask(value=None))
        worker.request_cancel()
        # Token ist schon gesetzt – wenn Task startet, soll cancelled emittiert
        # werden (CancellableTask raises OperationCancelled bei is_set()).
        # _EchoTask prüft nicht selbst – also kommt finished trotzdem.
        # Aber: TaskWorker.run() checked am Ende nochmal `is_set()`, also
        # sollte cancelled feuern obwohl die Task durchlief.
        with qtbot.waitSignal(worker.cancelled, timeout=2000):
            worker.start()
        worker.wait()


class TestProgressReporter:
    def test_reporter_emits_signal_with_args(self, qtbot: QtBot) -> None:
        worker = TaskWorker(_EchoTask(value=None))
        emitted: list[tuple[int, int]] = []
        worker.progress.connect(lambda c, t: emitted.append((c, t)))
        with qtbot.waitSignal(worker.finished_with_result, timeout=2000):
            worker.start()
        worker.wait()
        assert emitted == [(1, 1)]


class TestOperationCancelledFromTask:
    """Tasks, die OperationCancelled werfen, müssen als cancelled gelten,
    nicht als failed."""

    def test_explicit_operation_cancelled_in_task_emits_cancelled(self, qtbot: QtBot) -> None:
        worker = TaskWorker(_FailingTask(exc=OperationCancelled("user-cancel")))
        with qtbot.waitSignal(worker.cancelled, timeout=2000):
            worker.start()
        worker.wait()
