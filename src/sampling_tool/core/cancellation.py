"""Cooperative-Cancellation für Long-Running-Operations (Sprint 17).

Bewusst Qt-frei – wird sowohl von `io/`-Modulen (Importer, PDF/Excel/
HTML-Renderer) als auch von `ui/workers/` genutzt. Ein `CancellationToken`
ist ein einfaches Flag, das vom UI-Thread gesetzt und vom Worker-Thread
periodisch geprüft wird. Setter und Getter sind thread-safe.

Im Worker:
    if token.is_set():
        raise OperationCancelled()
    # oder kompakt:
    token.raise_if_cancelled()

`OperationCancelled` ist kein Fehler im klassischen Sinn – Worker
emittieren bei diesem Exception-Typ das ``cancelled``-Signal statt
``failed``.
"""

from __future__ import annotations

import threading


class OperationCancelled(Exception):  # noqa: N818 – Kontroll-Fluss, kein Error
    """Wird vom Worker geworfen, wenn der User abgebrochen hat.

    Kein Fehler – der Worker (siehe `ui/workers/task_worker.py`) fängt
    diese Exception speziell und emittiert das ``cancelled``-Signal.
    Der Name folgt bewusst der ``Cancelled``-Konvention statt der
    ``-Error``-PEP-8-N818-Konvention, weil das Signal ein Kontroll-
    Fluss-Marker ist (vergleichbar mit ``KeyboardInterrupt``).
    """


class CancellationToken:
    """Thread-safe Boolean-Flag für cooperative Cancellation.

    UI-Thread setzt via `set()`, Worker prüft periodisch via `is_set()`
    bzw. `raise_if_cancelled()`. Einmal gesetzt, bleibt das Token gesetzt
    (keine Reset-Operation – ein Task ist entweder abgebrochen oder läuft).
    """

    __slots__ = ("_cancelled", "_lock")

    def __init__(self) -> None:
        self._cancelled = False
        self._lock = threading.Lock()

    def set(self) -> None:
        """Markiert die Operation als abgebrochen."""
        with self._lock:
            self._cancelled = True

    def is_set(self) -> bool:
        """True, wenn `set()` aufgerufen wurde."""
        with self._lock:
            return self._cancelled

    def raise_if_cancelled(self) -> None:
        """Wirft `OperationCancelled`, wenn das Token gesetzt ist."""
        if self.is_set():
            raise OperationCancelled()
