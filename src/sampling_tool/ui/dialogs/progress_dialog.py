"""Modal-Fortschrittsdialog als Worker-Coordinator (Sprint 17 / P-008).

Vorher (Sprint 14): dünner `QProgressDialog`-Wrapper mit
`progress_callback()`-Adapter. Caller hat synchron im Main-Thread
gearbeitet und den Callback an den Importer übergeben → UI eingefroren.

Sprint 17: der Dialog ist jetzt der Coordinator für einen `TaskWorker`.
`run_task(task)` startet den Worker, blockt die UI per `QDialog.exec()`
(Event-Loop läuft weiter, Maus/Fenster/Cancel reagieren), und liefert
das Task-Resultat oder `None` bei User-Cancel. Bei Task-Exception wird
diese re-raised.

Sprint 98:
- Der Dialog erscheint erst nach `minimumDuration()` (300 ms). Bis dahin
  läuft eine Event-Loop ohne Nutzereingaben (die werden zurückgestellt, nicht
  verworfen) – kurze Läufe lassen keinen Dialog aufblitzen. `exec()` allein
  zeigte den Dialog sofort, `setMinimumDuration` wirkte dort nicht.
- Tasks mit `detach_on_cancel = True` (nur lesende) schließen bei „Abbrechen"
  sofort; der Worker läuft im Hintergrund zu Ende, sein Ergebnis wird
  verworfen (`_DetachedWorkers`). Schreibende Tasks warten wie bisher, damit
  keine zweite Schreibtransaktion mit einer noch laufenden kollidiert.

Verwendung:
    dialog = TaskProgressDialog("Importiere…", parent)
    try:
        result = dialog.run_task(my_task)
    except SomeError as exc:
        ...
    if result is None:
        return  # User hat abgebrochen
"""

from __future__ import annotations

from typing import TypeVar

from PyQt6.QtCore import QCoreApplication, QEventLoop, QObject, Qt, QTimer
from PyQt6.QtWidgets import QProgressDialog, QWidget

from sampling_tool.ui.workers.task_worker import TaskWorker, WorkerTask

T = TypeVar("T")


class _DetachedWorkers(QObject):
    """App-weiter Halter für abgebrochene Lese-Worker, die noch laufen.

    Ein `QThread`, der zerstört wird, solange er läuft, beendet den Prozess
    („QThread: Destroyed while thread is still running"). Der Halter hält eine
    Referenz, bis der Thread endet, räumt ihn dann per `deleteLater` ab und
    wartet bei `aboutToQuit` auf alle noch laufenden.
    """

    def __init__(self) -> None:
        super().__init__()
        self._workers: set[TaskWorker] = set()
        self._quit_hooked = False

    def adopt(self, worker: TaskWorker) -> None:
        self._workers.add(worker)
        # Erst verbinden, dann prüfen – sonst ginge ein Ende dazwischen verloren.
        worker.finished.connect(self._on_worker_finished)
        if worker.isFinished():
            self._release(worker)
        app = QCoreApplication.instance()
        if app is not None and not self._quit_hooked:
            app.aboutToQuit.connect(self.wait_all)
            self._quit_hooked = True

    def running(self) -> int:
        return len(self._workers)

    def wait_all(self) -> None:
        """Wartet auf alle noch laufenden Worker und räumt sie ab."""
        for worker in list(self._workers):
            worker.wait()
            self._release(worker)

    def _on_worker_finished(self) -> None:
        worker = self.sender()
        if isinstance(worker, TaskWorker):
            self._release(worker)

    def _release(self, worker: TaskWorker) -> None:
        if worker in self._workers:
            self._workers.discard(worker)
            worker.deleteLater()


_detached = _DetachedWorkers()


def detached_worker_count() -> int:
    """Anzahl abgebrochener Lese-Worker, die noch im Hintergrund laufen."""
    return _detached.running()


def wait_for_detached_workers() -> None:
    """Wartet auf alle abgebrochenen Lese-Worker (App-Ende, Tests)."""
    _detached.wait_all()


class TaskProgressDialog(QProgressDialog):
    """Modaler Progress-Dialog mit Worker-Backed `run_task`-Pattern."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(label, "Abbrechen", 0, 0, parent)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumDuration(300)
        # AutoClose würde den Dialog schließen, sobald `value == maximum` –
        # das passiert mitten im Worker-Run und beendet `exec()` BEVOR
        # `_on_finished` feuert. Schließen passiert kontrolliert via
        # `accept()`/`reject()` in den Worker-Signal-Slots.
        self.setAutoClose(False)
        self.setAutoReset(False)
        self.setValue(0)

        # Pro `run_task` neu gesetzt.
        self._worker: TaskWorker | None = None
        self._result: object = None
        self._error: BaseException | None = None
        self._was_cancelled = False
        self._detach_on_cancel = False
        self._done = False
        self._quiet_loop: QEventLoop | None = None

        # Cancel-Button feuert `canceled` (default-Verkabelung von
        # QProgressDialog), wir hängen unsere Logik dran.
        self.canceled.connect(self._on_cancel_clicked)

    def run_task(self, task: WorkerTask[T]) -> T | None:
        """Startet ``task`` im Worker-Thread, blockt bis fertig.

        Liefert:
            - das Task-Resultat bei Erfolg,
            - ``None`` bei User-Cancel.
        Wirft die Task-Exception bei Fehler.
        """
        # Ohne Parent: ein abgebrochener Lese-Worker überlebt den Dialog.
        worker = TaskWorker(task)
        self._worker = worker
        self._result = None
        self._error = None
        self._was_cancelled = False
        self._detach_on_cancel = bool(getattr(task, "detach_on_cancel", False))
        self._done = False

        worker.progress.connect(self._on_progress)
        worker.finished_with_result.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)

        worker.start()
        self._wait_quietly()
        if not self._done:
            # `exec()` startet eine modale Event-Loop – Signals vom Worker-
            # Thread werden im Main-Thread (queued) verarbeitet, Maus/Cancel/
            # Fenster-Bewegung reagieren ganz normal.
            self.exec()
        # Stoppt den internen Anzeige-Timer von QProgressDialog: ohne das
        # erschiene der Dialog nach einem schnellen Lauf nachträglich.
        self.reset()

        # Ein abgelöster Worker gehört jetzt `_detached`; sonst sauber abräumen (join).
        if self._worker is not None:
            self._worker.wait()
            self._worker.deleteLater()
            self._worker = None

        if self._error is not None:
            raise self._error
        if self._was_cancelled:
            return None
        return self._result

    def _wait_quietly(self) -> None:
        """Wartet bis `minimumDuration()` ohne Dialog und ohne Nutzereingaben.

        `ExcludeUserInputEvents` stellt Klicks und Tasten zurück (sie kommen
        danach an), Paint- und Worker-Signale laufen weiter. Danach übernimmt
        der modale Dialog das Sperren der übrigen Fenster.
        """
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        self._quiet_loop = loop
        timer.start(self.minimumDuration())
        try:
            if not self._done:
                loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        finally:
            timer.stop()
            self._quiet_loop = None

    def _finish(self) -> None:
        """Beendet die laufende Warte-Schleife (still oder modal)."""
        self._done = True
        if self._quiet_loop is not None:
            self._quiet_loop.quit()
        if self.isVisible():
            self.hide()

    # ---- Worker-Signal-Slots -------------------------------------------

    def _on_progress(self, current: int, total: int) -> None:
        if total != self.maximum():
            self.setMaximum(total)
        self.setValue(current)

    def _on_finished(self, result: object) -> None:
        self._result = result
        self._finish()

    def _on_failed(self, exc: BaseException) -> None:
        self._error = exc
        self._finish()

    def _on_cancelled(self) -> None:
        self._was_cancelled = True
        self._finish()

    def _on_cancel_clicked(self) -> None:
        """User hat „Abbrechen" geklickt – setzt das Cancellation-Token.

        Der Worker prüft das periodisch und emittiert anschließend das
        `cancelled`-Signal. Lese-Tasks (`detach_on_cancel`) warten darauf nicht:
        der Worker wird abgelöst, `run_task` kehrt sofort mit ``None`` zurück.
        """
        worker = self._worker
        if worker is None:
            return
        worker.request_cancel()
        self._was_cancelled = True
        if not self._detach_on_cancel:
            return
        worker.progress.disconnect(self._on_progress)
        worker.finished_with_result.disconnect(self._on_finished)
        worker.failed.disconnect(self._on_failed)
        worker.cancelled.disconnect(self._on_cancelled)
        self._worker = None
        _detached.adopt(worker)
        self._finish()
