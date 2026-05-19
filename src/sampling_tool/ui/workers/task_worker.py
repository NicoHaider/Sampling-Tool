"""TaskWorker (QThread) + ProgressReporter + WorkerTask-Protocol.

Sprint 17 / P-008: Long-Running-Operations laufen im Hintergrund-Thread
und kommunizieren mit dem UI-Thread via Qt-Signals.

Design-Entscheidungen (siehe Sprint-17-Plan):
- `QThread`-Subclass statt `QThreadPool`+`QRunnable` – Operationen sind
  sequenziell (User importiert eine Datei ODER rendert einen Report,
  nicht parallel), Pool-Vorteile entfallen.
- Genau ein Task pro Worker. Cancellation via `CancellationToken`
  (cooperative, kein OS-Kill).
- `ProgressReporter` ist der Adapter zwischen dem Task (der `report(c, t)`
  ruft) und dem Qt-Signal (`progress(int, int)`). Damit kann der Task
  Qt-frei bleiben.
"""

from __future__ import annotations

from typing import Any, Generic, Protocol, TypeVar

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from sampling_tool.core.cancellation import CancellationToken, OperationCancelled

T_co = TypeVar("T_co", covariant=True)


class _ProgressEmitter(QObject):
    """QObject-Wrapper für ein Progress-Signal.

    `QObject` ist erforderlich, weil pyqtSignal an einer Klasse hängen
    muss, die von QObject erbt. Wir packen den Emitter in einen eigenen
    Wrapper, damit der `ProgressReporter` selbst kein QObject sein muss
    – das macht ihn leichter in Tests benutzbar.
    """

    progress = pyqtSignal(int, int)


class ProgressReporter:
    """Thread-safer Progress-Adapter: Worker ruft `report()`,
    UI-Signal feuert im Main-Thread (Qt-Queued-Connection).

    Wird vom TaskWorker an die Task-`run()`-Methode übergeben.
    """

    def __init__(self, emitter: _ProgressEmitter) -> None:
        self._emitter = emitter

    def report(self, current: int, total: int) -> None:
        """Meldet Fortschritt. Threadsafe – Signal-Emission über Qt-Queue."""
        self._emitter.progress.emit(current, total)


class WorkerTask(Protocol, Generic[T_co]):
    """Protocol für alle Worker-Aufgaben.

    Eine Task-Implementation muss `run(progress, cancellation) -> T`
    bereitstellen. Die `run`-Methode läuft im Worker-Thread und darf nur
    via `progress.report()` und `cancellation.is_set()` /
    `cancellation.raise_if_cancelled()` mit der UI kommunizieren.
    """

    def run(self, progress: ProgressReporter, cancellation: CancellationToken) -> T_co: ...


class TaskWorker(QThread):
    """Führt eine `WorkerTask` in einem Hintergrund-Thread aus.

    Signals:
        progress(int, int): aktueller / gesamt-Fortschritt.
        finished_with_result(object): bei Erfolg, mit dem Task-Resultat.
        failed(Exception): bei beliebiger Exception im Task (außer
            `OperationCancelled`).
        cancelled(): bei `OperationCancelled` im Task ODER wenn das
            Cancellation-Token während des Runs gesetzt wurde.
    """

    progress = pyqtSignal(int, int)
    finished_with_result = pyqtSignal(object)
    failed = pyqtSignal(Exception)
    cancelled = pyqtSignal()

    def __init__(self, task: WorkerTask[Any], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._task = task
        self._cancellation = CancellationToken()
        self._emitter = _ProgressEmitter()
        # Das Emitter-Signal ans Worker-Signal weiterreichen, sodass
        # Caller `worker.progress.connect(...)` schreiben können.
        self._emitter.progress.connect(self.progress)

    def request_cancel(self) -> None:
        """Vom UI-Thread aufgerufen – setzt das Cancellation-Token."""
        self._cancellation.set()

    @property
    def cancellation_token(self) -> CancellationToken:
        """Read-Only-Zugriff auf das Token, für Test-Inspektion."""
        return self._cancellation

    def run(self) -> None:
        """QThread-Override. Läuft im Worker-Thread."""
        try:
            reporter = ProgressReporter(self._emitter)
            result = self._task.run(reporter, self._cancellation)
        except OperationCancelled:
            # Saubere Cancel-Variante: explizites cancelled-Signal,
            # KEIN failed.
            self.cancelled.emit()
            return
        except Exception as exc:
            self.failed.emit(exc)
            return
        # Cancel-Check NACH erfolgreichem Run – falls der Task selbst
        # nicht prüft, der User aber doch abgebrochen hat.
        if self._cancellation.is_set():
            self.cancelled.emit()
        else:
            self.finished_with_result.emit(result)
