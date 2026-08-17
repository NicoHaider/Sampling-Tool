"""Der Testmengen-Wächter und der Beweis, dass er greift (Sprint 77 / Befund #8).

Der Wächter ist ein Netz gegen eine Klasse von Fehlern, die per Definition
niemanden rot macht: Tests hören still auf, gesammelt zu werden. Ein Netz, das
nie geprüft wird, ob es hält, ist wieder nur ein grüner Check – deshalb hier
beide Richtungen: der Hook schweigt, wo er schweigen soll, und schlägt an, wo er
anschlagen soll.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from tests._test_floor import ENFORCE_TEST_FLOOR_ENV, TEST_FLOOR, check_test_floor
from tests.conftest import pytest_sessionfinish

pytestmark = pytest.mark.unit


class _Reporter:
    """Minimaler Ersatz für den `terminalreporter`; sammelt die Ausgabe."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def write_line(self, line: str, **_: Any) -> None:
        self.lines.append(line)


class _PluginManager:
    def __init__(self, reporter: _Reporter) -> None:
        self._reporter = reporter

    def get_plugin(self, name: str) -> _Reporter | None:
        return self._reporter if name == "terminalreporter" else None


class _PluginManagerWithoutReporter:
    """Der Zustand unter `-p no:terminal`: `get_plugin` liefert nichts."""

    def get_plugin(self, name: str) -> None:
        return None


class _Config:
    def __init__(self, reporter: _Reporter) -> None:
        self.pluginmanager = _PluginManager(reporter)


class _Session:
    """Gerade so viel Session, wie der Hook anfasst.

    Ein echter Sub-pytest-Lauf wäre der Alternativweg – der wäre langsam und
    würde beim Prüfen des No-Op-Falls nur beweisen, dass ein zweiter Prozess
    grün ist, nicht dass DIESER Hook stillhält.
    """

    def __init__(self, collected: int) -> None:
        self.testscollected = collected
        self.reporter = _Reporter()
        self.config = _Config(self.reporter)
        self.exitstatus: int = pytest.ExitCode.OK


def run_hook(session: _Session) -> None:
    pytest_sessionfinish(cast(pytest.Session, session), int(session.exitstatus))


class TestTestFloorGuard:
    """Reine Prüflogik plus die drei Zustände des Hooks."""

    # -- die reine Funktion ------------------------------------------------

    def test_returns_none_when_above_floor(self) -> None:
        assert check_test_floor(collected=1700, floor=1600) is None

    def test_returns_none_when_exactly_at_floor(self) -> None:
        """Sperrklinke, keine Gleichheitsprüfung: `>=`, nie `==`."""
        assert check_test_floor(collected=1600, floor=1600) is None

    def test_reports_actual_and_expected_when_below_floor(self) -> None:
        message = check_test_floor(collected=1599, floor=1600)
        assert message is not None
        assert "1599" in message
        assert "1600" in message

    def test_message_names_the_difference(self) -> None:
        message = check_test_floor(collected=1200, floor=1600)
        assert message is not None
        assert "400" in message

    def test_message_forbids_lowering_the_constant(self) -> None:
        """Die Meldung muss den Reflex adressieren, den Wert zu senken – das ist
        genau das, was den Wächter wertlos machen würde."""
        message = check_test_floor(collected=0, floor=TEST_FLOOR)
        assert message is not None
        assert "NICHT gesenkt" in message

    # -- der Hook ----------------------------------------------------------

    def test_hook_is_a_noop_without_the_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ohne die Variable bleibt selbst eine absurd niedrige Zahl folgenlos.

        Das ist der Grund für die Variable: sonst schlüge jeder lokale
        `pytest tests/unit/test_rng.py` fehl und der Wächter würde zur Plage.
        """
        monkeypatch.delenv(ENFORCE_TEST_FLOOR_ENV, raising=False)
        session = _Session(collected=1)
        run_hook(session)
        assert session.exitstatus == pytest.ExitCode.OK
        assert session.reporter.lines == []

    def test_hook_is_a_noop_when_env_var_is_not_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENFORCE_TEST_FLOOR_ENV, "0")
        session = _Session(collected=1)
        run_hook(session)
        assert session.exitstatus == pytest.ExitCode.OK

    def test_hook_fails_the_run_below_the_floor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENFORCE_TEST_FLOOR_ENV, "1")
        session = _Session(collected=TEST_FLOOR - 1)
        run_hook(session)
        assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
        assert any(str(TEST_FLOOR) in line for line in session.reporter.lines)
        assert any(str(TEST_FLOOR - 1) in line for line in session.reporter.lines)

    def test_hook_stays_silent_above_the_floor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENFORCE_TEST_FLOOR_ENV, "1")
        session = _Session(collected=TEST_FLOOR + 500)
        run_hook(session)
        assert session.exitstatus == pytest.ExitCode.OK
        assert session.reporter.lines == []

    def test_hook_does_not_mask_a_more_severe_exit_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ein abgebrochener oder intern gescheiterter Lauf behält seinen Status –
        der Wächter kippt nur den grünen Lauf."""
        monkeypatch.setenv(ENFORCE_TEST_FLOOR_ENV, "1")
        session = _Session(collected=0)
        session.exitstatus = pytest.ExitCode.INTERNAL_ERROR
        run_hook(session)
        assert session.exitstatus == pytest.ExitCode.INTERNAL_ERROR
        assert session.reporter.lines, "Die Meldung muss trotzdem erscheinen"

    def test_hook_survives_a_missing_terminal_reporter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unter `-p no:terminal` gibt es keinen Reporter – der Lauf muss trotzdem
        rot werden statt am Hook zu zerschellen."""
        monkeypatch.setenv(ENFORCE_TEST_FLOOR_ENV, "1")
        session = _Session(collected=0)
        session.config.pluginmanager = cast(Any, _PluginManagerWithoutReporter())
        run_hook(session)
        assert session.exitstatus == pytest.ExitCode.TESTS_FAILED


class TestTestFloorConstant:
    """Der Wert selbst – gemessen, mit Abstand, und nur nach oben zu bewegen.

    Dass der Floor unter der tatsächlichen Sammelzahl liegt, prüft nicht dieser
    Test, sondern der Wächter selbst im vollen CI-Lauf. Ein Test, der die
    Sammelzahl aus einem Teil-Lauf liest, würde hier nur überspringen – und ein
    Test, der immer überspringt, ist genau der grüne Check, den dieser Sprint
    abschafft.
    """

    def test_floor_keeps_a_meaningful_distance(self) -> None:
        """Größenordnung: der zuletzt gemessene Stand minus einige Prozent.

        Zu nah dran, und jeder gelöschte Test wird zum Fehlalarm; zu weit weg,
        und ein echter Sammel-Ausfall bleibt unbemerkt. Die Zahl wird beim
        bewussten Anheben des Floors mitgezogen – sie ist die Messung, gegen
        die der Abstand gilt (Sprint 78: 1765 gesammelt, Floor 1700).
        """
        measured_at_last_sprint = 1765
        assert measured_at_last_sprint > TEST_FLOOR
        assert int(measured_at_last_sprint * 0.95) <= TEST_FLOOR
