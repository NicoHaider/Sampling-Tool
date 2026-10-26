"""Tests für den Paket-Selbsttest `--self-check` (Sprint 95)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sampling_tool import self_check
from sampling_tool.self_check import (
    RNG_EXPECTED,
    RNG_POPULATION,
    RNG_SEED,
    RNG_SIZE,
    SELF_CHECK_FLAG,
    run_self_check,
)
from tests.unit.test_golden_vectors import GOLDEN_SIMPLE, _population

pytestmark = pytest.mark.unit

_EXPECTED_CHECKS = (
    "pillow",
    "briefpapier",
    "pypdf",
    "reportlab",
    "matplotlib",
    "xlsx",
    "rng",
    "pyqt6",
)


class TestSelfCheck:
    def test_all_checks_pass_in_dev_env(self) -> None:
        report = run_self_check()
        assert tuple(c.name for c in report.checks) == _EXPECTED_CHECKS
        assert report.ok, [c for c in report.checks if not c.ok]
        assert all(c.ok for c in report.checks)

    def test_failing_check_does_not_stop_others(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "python_calamine", None)

        report = run_self_check()

        by_name = {c.name: c for c in report.checks}
        assert report.ok is False
        assert tuple(by_name) == _EXPECTED_CHECKS
        assert by_name["xlsx"].ok is False
        assert "python_calamine" in by_name["xlsx"].detail
        others = [c for c in report.checks if c.name != "xlsx"]
        assert all(c.ok for c in others), [c for c in others if not c.ok]

    def test_missing_pillow_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "PIL", None)

        report = run_self_check()

        by_name = {c.name: c for c in report.checks}
        assert report.ok is False
        assert by_name["pillow"].ok is False
        assert "PIL" in by_name["pillow"].detail
        assert by_name["briefpapier"].ok is False
        assert "Pillow" in by_name["briefpapier"].detail

    def test_rng_constant_matches_golden_vector(self) -> None:
        assert GOLDEN_SIMPLE[RNG_SEED] == RNG_EXPECTED
        # Dieselbe Ziehung wie im Golden-Test: size und Population müssen passen,
        # sonst wäre die gleiche Konstante ein Zufallstreffer.
        assert len(_population()) == RNG_POPULATION
        assert len(GOLDEN_SIMPLE[RNG_SEED]) == RNG_SIZE


class TestRunEntry:
    """`run_entry` im eigenen Prozess – Exit-Codes und Bericht."""

    @pytest.fixture(autouse=True)
    def _keep_mplconfigdir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # `run_entry` setzt MPLCONFIGDIR per setdefault auf ein Temp-Verzeichnis,
        # das danach gelöscht ist – im Testprozess darf das nicht hängen bleiben.
        monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))

    def test_green_report_returns_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report = tmp_path / "out" / "self_check.json"

        assert self_check.run_entry(report) == 0

        payload = json.loads(report.read_text(encoding="utf-8"))
        assert payload["ok"] is True
        assert payload["frozen"] is False
        assert "Self-check OK" in capsys.readouterr().out

    def test_red_check_returns_one_and_still_writes_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setitem(sys.modules, "pypdf", None)
        report = tmp_path / "self_check.json"

        assert self_check.run_entry(report) == 1

        checks = json.loads(report.read_text(encoding="utf-8"))["checks"]
        assert "pypdf" in [c["name"] for c in checks if not c["ok"]]
        assert "FAILED" in capsys.readouterr().out

    def test_unwritable_report_returns_two(self, tmp_path: Path) -> None:
        blocker = tmp_path / "datei"
        blocker.write_text("kein Ordner", encoding="utf-8")

        assert self_check.run_entry(blocker / "self_check.json") == 2


@pytest.fixture(scope="module")
def mpl_config_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Ein Font-Cache für alle Subprozesse – sonst baut ihn jeder Lauf neu."""
    return tmp_path_factory.mktemp("mplconfig")


def _run_entry(
    args: list[str], mpl_config_dir: Path, *, drop_qpa: bool = False
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "MPLCONFIGDIR": str(mpl_config_dir)}
    if drop_qpa:
        env.pop("QT_QPA_PLATFORM", None)
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=180,
        check=False,
    )


# Treiber für den Isolations-Test: biegt QSettings wie `conftest._isolate_qsettings`
# auf ein INI-Verzeichnis um (kein HOME-Umbiegen) und verbietet die
# Einstellungs-Türen, dann `main()` mit `--self-check`.
_DRIVER = """
import sys
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QSettings

ini_dir, report = Path(sys.argv[1]), sys.argv[2]
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(ini_dir))
QSettings.setDefaultFormat(QSettings.Format.IniFormat)

from sampling_tool.ui import settings_store

def _forbidden(*args, **kwargs):
    raise AssertionError("self-check touched the settings")

settings_store._qsettings = _forbidden
import sampling_tool.__main__ as entry

entry.load_settings = _forbidden
entry.save_settings = _forbidden
sys.argv = ["sampling_tool", "--self-check", report]
rc = entry.main()
assert QCoreApplication.instance() is None, "self-check created a Q*Application"
assert not ini_dir.exists() or not any(ini_dir.rglob("*")), list(ini_dir.rglob("*"))
sys.exit(rc)
"""


@pytest.mark.slow
class TestSelfCheckEntry:
    def test_exit_zero_and_json_written(self, tmp_path: Path, mpl_config_dir: Path) -> None:
        report = tmp_path / "nested" / "self_check.json"

        result = _run_entry(["-m", "sampling_tool", SELF_CHECK_FLAG, str(report)], mpl_config_dir)

        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(report.read_text(encoding="utf-8"))
        assert payload["ok"] is True
        assert [c["name"] for c in payload["checks"]] == list(_EXPECTED_CHECKS)
        assert "Self-check OK" in result.stdout

    def test_no_window_and_no_settings_touched(self, tmp_path: Path, mpl_config_dir: Path) -> None:
        report = tmp_path / "self_check.json"
        ini_dir = tmp_path / "qsettings"

        result = _run_entry(
            ["-c", _DRIVER, str(ini_dir), str(report)], mpl_config_dir, drop_qpa=True
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(report.read_text(encoding="utf-8"))["ok"] is True

    @pytest.mark.parametrize(
        "argv",
        [
            [],
            ["-psn_0_12345"],
            [SELF_CHECK_FLAG],
            [SELF_CHECK_FLAG, "a.json", "extra"],
            ["a.json", SELF_CHECK_FLAG],
        ],
    )
    def test_other_args_start_normal_path(
        self, argv: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from PyQt6.QtGui import QGuiApplication

        import sampling_tool.__main__ as entry

        class _NormalPathReachedError(Exception):
            pass

        def _self_check_called() -> None:
            raise AssertionError("run_self_check darf hier nicht laufen")

        def _first_step_of_normal_path(*_args: object) -> None:
            raise _NormalPathReachedError

        monkeypatch.setattr(self_check, "run_self_check", _self_check_called)
        monkeypatch.setattr(
            QGuiApplication, "setHighDpiScaleFactorRoundingPolicy", _first_step_of_normal_path
        )
        monkeypatch.setattr(sys, "argv", ["sampling_tool", *argv])

        with pytest.raises(_NormalPathReachedError):
            entry.main()
