"""Modal-Fortschrittsdialog als Worker-Coordinator (Sprint 17 / P-008).

Vorher (Sprint 14): dünner `QProgressDialog`-Wrapper mit
`progress_callback()`-Adapter. Caller hat synchron im Main-Thread
gearbeitet und den Callback an den Importer übergeben → UI eingefroren.

Sprint 17: der Dialog ist jetzt der Coordinator für einen `TaskWorker`.
`run_task(task)` startet den Worker, blockt die UI per `QDialog.exec()`
(Event-Loop läuft weiter, Maus/Fenster/Cancel reagieren), und liefert
das Task-Resultat oder `None` bei User-Cancel. Bei Task-Exception wird
diese re-raised.

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

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QProgressDialog, QWidget

from sampling_tool.ui.workers.task_worker import TaskWorker, WorkerTask

T = TypeVar("T")


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
        self._worker = TaskWorker(task, parent=self)
        self._result = None
        self._error = None
        self._was_cancelled = False

        self._worker.progress.connect(self._on_progress)
        self._worker.finished_with_result.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)

        self._worker.start()
        # `exec()` startet eine modale Event-Loop – Signals vom Worker-
        # Thread werden im Main-Thread (queued) verarbeitet, Maus/Cancel/
        # Fenster-Bewegung reagieren ganz normal.
        self.exec()

        # Worker sauber abräumen (join), bevor wir zurückgeben.
        if self._worker is not None:
            self._worker.wait()
            self._worker = None

        if self._error is not None:
            raise self._error
        if self._was_cancelled:
            return None
        return self._result

    # ---- Worker-Signal-Slots -------------------------------------------

    def _on_progress(self, current: int, total: int) -> None:
        if total != self.maximum():
            self.setMaximum(total)
        self.setValue(current)

    def _on_finished(self, result: object) -> None:
        self._result = result
        self.accept()

    def _on_failed(self, exc: BaseException) -> None:
        self._error = exc
        self.reject()

    def _on_cancelled(self) -> None:
        self._was_cancelled = True
        self.reject()

    def _on_cancel_clicked(self) -> None:
        """User hat „Abbrechen" geklickt – setzt das Cancellation-Token.

        Der Worker prüft das periodisch und emittiert anschließend das
        `cancelled`-Signal.
        """
        if self._worker is not None:
            self._worker.request_cancel()
