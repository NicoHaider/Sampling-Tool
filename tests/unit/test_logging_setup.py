"""Unit-Tests für `logging_setup` – RotatingFileHandler, Level, Excepthook."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sampling_tool import logging_setup

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_root_logger() -> Iterator[None]:
    """Verhindert Handler-/Level-Leaks zwischen Tests (der Root-Logger ist
    Prozess-global, nicht Test-isoliert)."""
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    yield
    for handler in list(root.handlers):
        if handler not in original_handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(original_level)


@pytest.fixture(autouse=True)
def _restore_excepthook() -> Iterator[None]:
    """`install_excepthook` mutiert `sys.excepthook` prozessweit – ohne Restore
    würde er nach diesem Modul für den Rest der Session auf
    `_handle_uncaught_exception` (und dessen inzwischen ungültigen
    tmp_path-Log-Pfad) zeigen bleiben."""
    original = sys.excepthook
    yield
    sys.excepthook = original


@pytest.fixture
def log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(logging_setup, "user_log_dir", lambda **_kwargs: str(tmp_path))
    return tmp_path


class TestLogFilePath:
    def test_log_file_path_under_patched_base_dir(self, log_dir: Path) -> None:
        assert logging_setup.log_file_path() == log_dir / "app.log"


class TestResolveLogLevel:
    def test_known_levels(self) -> None:
        assert logging_setup.resolve_log_level("DEBUG") == logging.DEBUG
        assert logging_setup.resolve_log_level("INFO") == logging.INFO

    def test_unknown_level_falls_back_to_info(self) -> None:
        assert logging_setup.resolve_log_level("NOT_A_REAL_LEVEL") == logging.INFO


class TestConfigureLogging:
    def test_adds_single_rotating_handler(self, log_dir: Path) -> None:
        logging_setup.configure_logging("INFO")
        logging_setup.configure_logging("INFO")
        root = logging.getLogger()
        handlers = [h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
        assert len(handlers) == 1

    def test_sets_level_from_settings(self, log_dir: Path) -> None:
        logging_setup.configure_logging("DEBUG")
        assert logging.getLogger().level == logging.DEBUG
        logging_setup.configure_logging("INFO")
        assert logging.getLogger().level == logging.INFO

    def test_log_file_is_written(self, log_dir: Path) -> None:
        path = logging_setup.configure_logging("INFO")
        logging.getLogger("sampling_tool.test").info("Marker-Zeile")
        for handler in logging.getLogger().handlers:
            handler.flush()
        assert "Marker-Zeile" in path.read_text(encoding="utf-8")

    def test_creates_missing_nested_log_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`user_log_dir` liefert unter macOS/Windows i. d. R. ein noch nicht
        existierendes Verzeichnis (erster App-Start) – im Gegensatz zur
        `log_dir`-Fixture, die auf `tmp_path` zeigt und das Verzeichnis somit
        immer schon existieren lässt."""
        missing = tmp_path / "not" / "yet" / "created"
        monkeypatch.setattr(logging_setup, "user_log_dir", lambda **_kwargs: str(missing))
        assert not missing.exists()

        path = logging_setup.configure_logging("INFO")

        assert path == missing / "app.log"
        assert missing.is_dir()


class TestInstallExcepthook:
    def test_logs_uncaught_exception(self, log_dir: Path) -> None:
        path = logging_setup.configure_logging("INFO")
        logging_setup.install_excepthook()
        # `QApplication.instance()` patchen, damit der Test deterministisch ist,
        # egal ob im selben Pytest-Prozess schon eine QApplication existiert
        # (z. B. durch vorher gelaufene UI-Tests) — sonst würde ein echter,
        # blockierender QMessageBox.critical(...) im Headless-Lauf hängen.
        with patch("PyQt6.QtWidgets.QApplication.instance", return_value=None):
            try:
                raise ValueError("boom-marker")
            except ValueError:
                sys.excepthook(*sys.exc_info())
        for handler in logging.getLogger().handlers:
            handler.flush()
        text = path.read_text(encoding="utf-8")
        assert "boom-marker" in text
        assert "CRITICAL" in text

    def test_keyboard_interrupt_passes_through(self, log_dir: Path) -> None:
        logging_setup.install_excepthook()
        with patch("sys.__excepthook__") as default_hook:
            try:
                raise KeyboardInterrupt()
            except KeyboardInterrupt:
                sys.excepthook(*sys.exc_info())
        default_hook.assert_called_once()
