"""Tests für `TaskProgressDialog` als Worker-Coordinator (Sprint 17, P-008).

Vorher war der Dialog nur ein `QProgressDialog` mit `progress_callback()`-
Adapter (Sprint 14). Mit Sprint 17 wird er zum Coordinator: `run_task(task)`
startet einen `TaskWorker`, blockt die UI bis fertig (Event-Loop läuft
weiter, daher responsive), liefert das Resultat oder None bei Cancel.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QObject, Qt
from pytestqt.qtbot import QtBot

from sampling_tool.core.cancellation import CancellationToken, OperationCancelled
from sampling_tool.ui.dialogs.progress_dialog import (
    TaskProgressDialog,
    detached_worker_count,
    wait_for_detached_workers,
)
from sampling_tool.ui.workers.task_worker import ProgressReporter
from tests.ui._progress_cancel import CancelClicker

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
class _TokenWatchingTask:
    """Wartet auf das Token (oder bis `deadline_s`) und merkt sich, ob es kam."""

    deadline_s: float = 10.0
    saw_token: bool = False

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> int:
        deadline = time.monotonic() + self.deadline_s
        while time.monotonic() < deadline:
            if cancellation.is_set():
                self.saw_token = True
                raise OperationCancelled()
            time.sleep(0.005)
        return 99


@dataclass
class _GatedTask:
    """Läuft nach dem Abbruch weiter, bis `release` gesetzt ist (Detach-Tests)."""

    detach: bool
    release: threading.Event = field(default_factory=threading.Event)
    saw_token: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)

    @property
    def detach_on_cancel(self) -> bool:
        return self.detach

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> int:
        try:
            deadline = time.monotonic() + 10
            while not cancellation.is_set():
                assert time.monotonic() < deadline, "Abbruch kam nie an"
                time.sleep(0.005)
            self.saw_token.set()
            assert self.release.wait(10), "Freigabe kam nie an"
            return 1
        finally:
            self.finished.set()


def _cancel_via_button(
    dlg: TaskProgressDialog, deadline_s: float = 10.0
) -> tuple[int | None, _TokenWatchingTask]:
    task = _TokenWatchingTask(deadline_s=deadline_s)
    clicker = CancelClicker()
    try:
        result = dlg.run_task(task)
    finally:
        clicker.stop()
    assert clicker.labels == ["Test"], "der Knopf wurde nie gedrückt"
    return result, task


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
        """Sprint 98 / C.2: Abbruch über den echten Knopf – die Task MUSS das Token sehen.

        Vorher rief der Test `dlg.cancel()`; das sendet `canceled` nicht, das
        Token wurde nie gesetzt, und `None` kam nur zufällig zurück (das
        Ergebnis-Signal war beim Zurückkehren noch nicht verarbeitet).
        """
        dlg = TaskProgressDialog("Test", None)
        qtbot.addWidget(dlg)
        result, task = _cancel_via_button(dlg)
        assert result is None
        assert task.saw_token, "Abbrechen muss das Token im Worker setzen"

    def test_cancel_check_detects_a_dialog_that_never_sets_the_token(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Positiv-Kontrolle zu `test_run_task_returns_none_on_cancel`.

        Setzt der Dialog das Token nicht, kommt trotzdem `None` zurück – nur
        `saw_token` unterscheidet die beiden Fälle. Damit ist belegt, dass der
        Test oben bei diesem Fehler rot wird.
        """
        monkeypatch.setattr(TaskProgressDialog, "_on_cancel_clicked", lambda _self: None)
        dlg = TaskProgressDialog("Test", None)
        qtbot.addWidget(dlg)
        _result, task = _cancel_via_button(dlg, deadline_s=0.5)
        assert not task.saw_token

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


class _ShowRecorder(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.shown = 0

    def eventFilter(self, obj: QObject | None, event: QEvent | None) -> bool:
        if event is not None and event.type() == QEvent.Type.Show:
            self.shown += 1
        return False


class TestDelayedShow:
    """Sprint 98: der Dialog erscheint erst nach `minimumDuration()` (300 ms)."""

    def test_short_task_never_shows_dialog(self, qtbot: QtBot) -> None:
        dlg = TaskProgressDialog("Test", None)
        qtbot.addWidget(dlg)
        recorder = _ShowRecorder()
        dlg.installEventFilter(recorder)
        assert dlg.run_task(_EchoTask(value="ok")) == "ok"
        # Auch der interne Anzeige-Timer von QProgressDialog darf ihn danach nicht zeigen.
        qtbot.wait(dlg.minimumDuration() + 200)
        assert recorder.shown == 0
        assert not dlg.isVisible()

    def test_long_task_shows_dialog(self, qtbot: QtBot) -> None:
        @dataclass
        class _SlowTask:
            def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> int:
                time.sleep(0.6)
                return 7

        dlg = TaskProgressDialog("Test", None)
        qtbot.addWidget(dlg)
        recorder = _ShowRecorder()
        dlg.installEventFilter(recorder)
        assert dlg.run_task(_SlowTask()) == 7
        assert recorder.shown == 1
        assert not dlg.isVisible()


class TestDetachOnCancel:
    """Sprint 98 / C.1: Lese-Tasks schließen bei „Abbrechen" sofort."""

    def test_read_task_returns_while_task_still_runs(self, qtbot: QtBot) -> None:
        dlg = TaskProgressDialog("Test", None)
        qtbot.addWidget(dlg)
        task = _GatedTask(detach=True)
        clicker = CancelClicker()
        try:
            result = dlg.run_task(task)
            returned_at = time.perf_counter()
        finally:
            clicker.stop()
        assert result is None
        assert clicker.labels == ["Test"]
        assert returned_at - clicker.times[0] < 0.5
        assert not task.finished.is_set(), "run_task darf nicht auf die Task warten"
        assert detached_worker_count() == 1
        assert not dlg.isVisible()

        task.release.set()
        wait_for_detached_workers()
        assert task.saw_token.is_set()
        assert task.finished.is_set()
        assert detached_worker_count() == 0

    def test_detached_worker_survives_dialog_deletion(self, qtbot: QtBot) -> None:
        """Kein „QThread: Destroyed while thread is still running" (würde den Prozess beenden)."""
        dlg = TaskProgressDialog("Test", None)
        task = _GatedTask(detach=True)
        clicker = CancelClicker()
        try:
            assert dlg.run_task(task) is None
        finally:
            clicker.stop()
        dlg.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qtbot.wait(50)
        assert not task.finished.is_set()
        assert detached_worker_count() == 1

        task.release.set()
        qtbot.waitUntil(lambda: detached_worker_count() == 0, timeout=5000)
        assert task.finished.is_set()

    def test_ignores_result_of_detached_worker(self, qtbot: QtBot) -> None:
        """Ein abgelöster Worker beeinflusst einen späteren Lauf desselben Dialogs nicht."""
        dlg = TaskProgressDialog("Test", None)
        qtbot.addWidget(dlg)
        task = _GatedTask(detach=True)
        clicker = CancelClicker()
        try:
            assert dlg.run_task(task) is None
        finally:
            clicker.stop()
        task.release.set()
        assert dlg.run_task(_EchoTask(value="zweiter Lauf")) == "zweiter Lauf"

    def test_write_task_still_waits(self, qtbot: QtBot) -> None:
        dlg = TaskProgressDialog("Test", None)
        qtbot.addWidget(dlg)
        task = _GatedTask(detach=False)
        clicker = CancelClicker()

        # Gibt die Task erst frei, nachdem der Knopf gedrückt wurde.
        def _release_after_click() -> None:
            task.saw_token.wait(10)
            time.sleep(0.3)
            task.release.set()

        releaser = threading.Thread(target=_release_after_click)
        releaser.start()
        try:
            result = dlg.run_task(task)
        finally:
            clicker.stop()
            releaser.join()
        assert result is None
        assert clicker.labels == ["Test"]
        assert task.finished.is_set(), "schreibende Tasks warten wie bisher auf das Ende"
        assert detached_worker_count() == 0
