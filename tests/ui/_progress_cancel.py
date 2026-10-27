"""Test-Helfer: „Abbrechen" im Fortschrittsdialog über den echten Knopf drücken (Sprint 98).

`QProgressDialog.cancel()` allein sendet `canceled` nicht – das Token wird so nie
gesetzt (Sprint 97). Seit Sprint 98 erscheint der Dialog außerdem erst nach
`minimumDuration()`; ein fester Timer vorher fände ihn nicht. Der Helfer fragt
deshalb in kurzen Abständen, bis ein Fortschrittsdialog sichtbar ist, und
klickt dann dessen „Abbrechen"-Knopf.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QPushButton

from sampling_tool.ui.dialogs.progress_dialog import TaskProgressDialog


class CancelClicker:
    """Klickt „Abbrechen" im nächsten sichtbaren `TaskProgressDialog`.

    `labels` protokolliert die Beschriftung jedes Dialogs, in dem geklickt
    wurde. `times` – nur für die erste Klick-Zeit – die `perf_counter`-Zeit des
    Klicks. Mit `count` > 1 klickt der Helfer in so vielen Dialogen nacheinander.
    """

    def __init__(self, *, count: int = 1, timeout_s: float = 10.0) -> None:
        self.labels: list[str] = []
        self.times: list[float] = []
        self._remaining = count
        self._deadline = time.monotonic() + timeout_s
        # Referenzen statt id(): eine id kann nach dem Löschen wiederverwendet werden.
        self._clicked: list[TaskProgressDialog] = []
        self._timer = QTimer()
        self._timer.setInterval(10)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _poll(self) -> None:
        if self._remaining <= 0 or time.monotonic() > self._deadline:
            self._timer.stop()
            return
        for widget in QApplication.allWidgets():
            if (
                isinstance(widget, TaskProgressDialog)
                and widget.isVisible()
                and not any(widget is done for done in self._clicked)
            ):
                buttons = [b for b in widget.findChildren(QPushButton) if b.text() == "Abbrechen"]
                assert len(buttons) == 1
                self._clicked.append(widget)
                self.labels.append(widget.labelText())
                self.times.append(time.perf_counter())
                self._remaining -= 1
                buttons[0].click()
                return
