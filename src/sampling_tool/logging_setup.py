"""Zentrale Logging-Konfiguration + globaler Excepthook (Sprint 44 / S1.6, N-005).

Konfiguriert genau einen `RotatingFileHandler` am Root-Logger unter einem
app-weiten (nicht Projekt-gebundenen) Log-Verzeichnis via `platformdirs`,
damit auch Startup-/Kein-Projekt-Fehler erfasst werden. `install_excepthook`
sorgt dafür, dass eine ungefangene Exception nicht mehr spurlos die App
beendet, sondern geloggt und dem Anwender gemeldet wird.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from types import TracebackType
from typing import Final

from platformdirs import user_log_dir
from PyQt6.QtWidgets import QApplication, QMessageBox

from sampling_tool.ui import recent

_LOG_FILENAME: Final[str] = "app.log"
_MAX_BYTES: Final[int] = 1_000_000
_BACKUP_COUNT: Final[int] = 3
_LOG_FORMAT: Final[str] = "%(asctime)s %(levelname)s %(name)s: %(message)s"

_logger = logging.getLogger(__name__)


def log_file_path() -> Path:
    """Zentraler Log-Pfad – app-weit unter `platformdirs.user_log_dir`.

    Nutzt dieselben `appname`/`appauthor`-Konstanten wie `ui.recent`
    (`recent.json`), damit Logs und Recent-Store unter derselben
    App-Identität liegen. Bewusst NICHT pro Projekt (fängt auch
    Startup-/Kein-Projekt-Fehler, immer auffindbar).
    """
    base = Path(user_log_dir(appname=recent.APP_NAME, appauthor=recent.APP_AUTHOR))
    return base / _LOG_FILENAME


def resolve_log_level(level: str) -> int:
    """Mappt einen `AppSettings.log_level`-String auf eine `logging`-Konstante.

    Unbekannte Werte fallen defensiv auf `INFO` zurück (der Store validiert
    bereits gegen `LOG_LEVELS` — das hier ist nur ein zusätzliches Netz).
    """
    resolved = getattr(logging, level, None)
    return resolved if isinstance(resolved, int) else logging.INFO


def configure_logging(level: str) -> Path:
    """Registriert einen `RotatingFileHandler` am Root-Logger (idempotent).

    Legt das Log-Verzeichnis bei Bedarf an, setzt das Root-Level aus
    `level` und liefert den Log-Pfad zurück. Ein zweiter Aufruf fügt
    keinen weiteren Handler hinzu.
    """
    path = log_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(resolve_log_level(level))

    has_handler = any(
        isinstance(handler, logging.handlers.RotatingFileHandler) for handler in root.handlers
    )
    if not has_handler:
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(handler)

    return path


def install_excepthook() -> None:
    """Setzt einen globalen `sys.excepthook`.

    Jede ungefangene Exception landet mit vollem Traceback im Log
    (`CRITICAL`); läuft eine `QApplication`, zeigt zusätzlich eine
    Fehlermeldung mit dem Log-Pfad. `KeyboardInterrupt` geht unverändert
    an den Default-Hook (Ctrl+C bleibt funktional).
    """
    sys.excepthook = _handle_uncaught_exception


def _handle_uncaught_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    _logger.critical("Unbehandelte Ausnahme", exc_info=(exc_type, exc_value, exc_traceback))

    app = QApplication.instance()
    if app is not None:
        QMessageBox.critical(
            None,
            "Unerwarteter Fehler",
            "Es ist ein unerwarteter Fehler aufgetreten und wurde protokolliert unter:\n"
            f"{log_file_path()}",
        )
