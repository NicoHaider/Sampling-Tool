"""Worker-Architektur für Long-Running-Operations (Sprint 17, P-008).

Long-Running-Operations (Excel-Import, DB-Persist, PDF/Excel/HTML-Report)
laufen im Hintergrund-Thread, damit die UI responsiv bleibt und der
Abbrechen-Button funktioniert.

Eintrittspunkt:
- `WorkerTask` (Protocol): die zu erledigende Arbeit.
- `TaskWorker` (QThread): führt einen Task aus, kommuniziert via Signals
  (`progress`, `finished_with_result`, `failed`, `cancelled`).
- `ProgressReporter`: thread-safer Progress-Adapter (Worker → UI-Signal).
- `tasks.py`: konkrete Task-Implementierungen (ExcelImportTask, …).
"""

from sampling_tool.ui.workers.task_worker import (
    ProgressReporter,
    TaskWorker,
    WorkerTask,
)

__all__ = ["ProgressReporter", "TaskWorker", "WorkerTask"]
