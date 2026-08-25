"""Die beiden Wächter und der Beweis, dass sie greifen (Sprint 77 / #8, Sprint 79).

Beide sind Netze gegen eine Klasse von Fehlern, die per Definition niemanden rot
macht: Tests hören still auf, gesammelt (Sprint 77) bzw. ausgeführt (Sprint 79)
zu werden. Ein Netz, das nie geprüft wird, ob es hält, ist wieder nur ein grüner
Check – deshalb hier beide Richtungen: der Hook schweigt, wo er schweigen soll,
und schlägt an, wo er anschlagen soll.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

import tests.conftest as conftest_module
from tests._test_floor import (
    ENFORCE_TEST_FLOOR_ENV,
    EXECUTED_FLOOR,
    TEST_FLOOR,
    check_executed_floor,
    check_test_floor,
)
from tests.conftest import pytest_runtest_logreport, pytest_sessionfinish

pytestmark = pytest.mark.unit

#: Textbaustein, an dem eine Verstoß-Meldung erkennbar ist. Die Mess-Zeile, die
#: der Hook seit Sprint 79 IMMER schreibt, enthält ihn nicht – so lässt sich
#: „geschwiegen" von „gemeldet" unterscheiden, ohne die Meldung nachzutippen.
VIOLATION_MARKER = "erwartet mindestens"


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


def violations_of(session: _Session) -> list[str]:
    """Nur die Verstoß-Zeilen – ohne die Mess-Zeile, die immer geschrieben wird."""
    return [line for line in session.reporter.lines if VIOLATION_MARKER in line]


def set_skipped(monkeypatch: pytest.MonkeyPatch, count: int) -> None:
    """Ersetzt die Skip-Menge des Hooks durch `count` synthetische nodeids.

    Ersetzt statt befüllt: die Menge im Modul ist die LAUFENDE Zählung dieser
    Session. Würde ein Test sie befüllen, verfälschte er die Messung des eigenen
    CI-Laufs – der Wächter würde sich selbst belügen.
    """
    monkeypatch.setattr(
        conftest_module,
        "_skipped_nodeids",
        {f"tests/synthetisch.py::test_{i}" for i in range(count)},
    )


class _Report:
    """Gerade so viel `TestReport`, wie `pytest_runtest_logreport` anfasst."""

    def __init__(self, nodeid: str, *, skipped: bool, wasxfail: bool = False) -> None:
        self.nodeid = nodeid
        self.skipped = skipped
        if wasxfail:
            self.wasxfail = ""


def log_report(report: _Report) -> None:
    pytest_runtest_logreport(cast(pytest.TestReport, report))


@pytest.fixture(autouse=True)
def isolated_skip_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Jeder Test dieser Datei bekommt eine EIGENE, leere Skip-Menge.

    Zwei Gründe, und beide sind nötig: kein Test darf die laufende Zählung
    dieses CI-Laufs verfälschen, und kein Test darf von ihr abhängen (auf macOS
    ist sie 0, auf Windows nicht – ein Ergebnis, das mit der Plattform kippt,
    wäre kein Ergebnis).
    """
    monkeypatch.setattr(conftest_module, "_skipped_nodeids", set())


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
        assert session.reporter.lines == [], "Ohne die Variable wird auch nichts gemessen"

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

    def test_hook_reports_no_violation_above_both_floors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Über beiden Floors meldet der Hook nichts – er misst aber trotzdem.

        Bis Sprint 79 stand hier `reporter.lines == []`. Seit die Mess-Zeile in
        JEDEM scharfen Lauf geschrieben wird (§2.5: der Floor wird aus echten
        CI-Läufen abgelesen), ist die schweigende Zusage nicht mehr „keine
        Ausgabe", sondern „keine Verstoß-Meldung".
        """
        monkeypatch.setenv(ENFORCE_TEST_FLOOR_ENV, "1")
        session = _Session(collected=TEST_FLOOR + 500)
        run_hook(session)
        assert session.exitstatus == pytest.ExitCode.OK
        assert violations_of(session) == []

    def test_hook_always_logs_the_measurement_when_armed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Die drei Zahlen stehen im Protokoll, auch wenn nichts zu melden ist.

        Ohne sie wäre die Messreihe in `_test_floor.py` nicht nachprüfbar: der
        Floor wird je Plattform aus einem echten CI-Lauf abgelesen, und was nur
        im Verstoß-Fall gedruckt wird, steht im grünen Lauf nirgends.
        """
        monkeypatch.setenv(ENFORCE_TEST_FLOOR_ENV, "1")
        set_skipped(monkeypatch, 7)
        session = _Session(collected=TEST_FLOOR + 500)
        run_hook(session)
        measurement = " ".join(session.reporter.lines)
        assert str(TEST_FLOOR + 500) in measurement
        assert "7 übersprungen" in measurement
        assert f"{TEST_FLOOR + 500 - 7} ausgeführt" in measurement

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


class TestExecutedFloorGuard:
    """Der Ausführungs-Wächter (Sprint 79): `gesammelt − übersprungen`.

    Die Lücke, die er schließt: `session.testscollected` zählt übersprungene
    Tests mit. Kippt ein `skipif`, bleibt die gesammelte Zahl exakt stehen – und
    der Sprint-77-Wächter schweigt zu Recht, weil er die falsche Größe misst.
    """

    # -- die reine Funktion ------------------------------------------------

    def test_returns_none_without_skips(self) -> None:
        assert check_executed_floor(collected=1700, skipped=0, floor=1600) is None

    def test_returns_none_when_skips_stay_above_the_floor(self) -> None:
        """Ein paar legitime Plattform-Skips sind kein Verstoß – dafür der Abstand."""
        assert check_executed_floor(collected=1700, skipped=50, floor=1600) is None

    def test_returns_none_when_exactly_at_floor(self) -> None:
        """Sperrklinke, keine Gleichheitsprüfung: `>=`, nie `==`."""
        assert check_executed_floor(collected=1700, skipped=100, floor=1600) is None

    def test_reports_when_skips_push_execution_below_the_floor(self) -> None:
        message = check_executed_floor(collected=1700, skipped=101, floor=1600)
        assert message is not None
        assert "1599" in message
        assert "1600" in message

    def test_message_names_collected_and_skipped_separately(self) -> None:
        """Die Meldung muss die Ursache zeigen, nicht nur die Differenz: dieselbe
        Zahl ausgeführter Tests entsteht aus „weniger gesammelt" und aus „mehr
        übersprungen" – und die beiden Befunde haben verschiedene Ursachen."""
        message = check_executed_floor(collected=1800, skipped=300, floor=1600)
        assert message is not None
        assert "1800" in message
        assert "300" in message

    def test_message_forbids_lowering_the_constant(self) -> None:
        message = check_executed_floor(collected=0, skipped=0, floor=EXECUTED_FLOOR)
        assert message is not None
        assert "NICHT gesenkt" in message

    def test_is_blind_to_which_test_is_skipped(self) -> None:
        """Der Kern der Kennzahl: ein Deckel auf die Skip-ZAHL wäre lose.

        Fängt ein Test an zu skippen und hört ein anderer auf, bleibt die Summe
        gleich – ein „höchstens N Skips"-Wächter sähe nichts. Der Ratchet auf die
        ausgeführte Menge sieht nur, WIE VIELE laufen, und genau das ist die
        Eigenschaft, um die es geht.
        """
        assert check_executed_floor(collected=1700, skipped=3, floor=1690) is None
        assert check_executed_floor(collected=1700, skipped=11, floor=1690) is not None

    # -- der Hook ----------------------------------------------------------

    def test_hook_is_a_noop_without_the_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Gleiches Gate wie der Sammel-Wächter – deshalb kein `.github/`-Diff."""
        monkeypatch.delenv(ENFORCE_TEST_FLOOR_ENV, raising=False)
        set_skipped(monkeypatch, 5000)
        session = _Session(collected=TEST_FLOOR + 500)
        run_hook(session)
        assert session.exitstatus == pytest.ExitCode.OK
        assert session.reporter.lines == []

    def test_hook_fails_when_skips_eat_the_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Der Fall, den Sprint 77 offen ließ: die Sammlung ist voll, die
        Ausführung nicht. Der Sammel-Wächter schweigt, dieser hier nicht."""
        monkeypatch.setenv(ENFORCE_TEST_FLOOR_ENV, "1")
        # Aus BEIDEN Konstanten abgeleitet, nicht aus einer: der Test soll die
        # Lücke prüfen, nicht zufällig an einer bestimmten Zahlenlage hängen.
        collected = max(TEST_FLOOR, EXECUTED_FLOOR) + 500
        set_skipped(monkeypatch, collected - EXECUTED_FLOOR + 1)
        session = _Session(collected=collected)
        run_hook(session)
        assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
        assert check_test_floor(collected, TEST_FLOOR) is None, (
            "Vorbedingung: der Sammel-Wächter ist hier zufrieden – sonst prüfte "
            "dieser Test nicht die Lücke, sondern die alte Zusage"
        )
        assert any("AUSFÜHRUNG" in line for line in violations_of(session))

    def test_hook_stays_green_with_the_platform_skips(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Die legitimen Plattform-Skips (Windows: 2 aus `test_platform_imports`,
        dazu Symlink-/Toolbar-Fälle) dürfen den Wächter nie auslösen."""
        monkeypatch.setenv(ENFORCE_TEST_FLOOR_ENV, "1")
        set_skipped(monkeypatch, 10)
        session = _Session(collected=max(TEST_FLOOR, EXECUTED_FLOOR) + 200)
        run_hook(session)
        assert session.exitstatus == pytest.ExitCode.OK
        assert violations_of(session) == []

    # -- die Skip-Zählung --------------------------------------------------

    def test_logreport_counts_a_skipped_test(self) -> None:
        log_report(_Report("tests/unit/test_a.py::test_x", skipped=True))
        assert conftest_module._skipped_nodeids == {"tests/unit/test_a.py::test_x"}

    def test_logreport_ignores_a_passed_test(self) -> None:
        log_report(_Report("tests/unit/test_a.py::test_x", skipped=False))
        assert conftest_module._skipped_nodeids == set()

    def test_logreport_ignores_xfail(self) -> None:
        """`xfail` liefert ebenfalls `report.skipped`, ist aber ausgeführt worden.

        Ohne die `wasxfail`-Abfrage rechnete jeder erwartete Fehlschlag den
        Ausführungsstand klein – der Wächter meldete dann einen Ausfall, wo
        jemand nur einen bekannten Bug dokumentiert hat.
        """
        log_report(_Report("tests/unit/test_a.py::test_x", skipped=True, wasxfail=True))
        assert conftest_module._skipped_nodeids == set()

    def test_logreport_counts_a_nodeid_only_once(self) -> None:
        """Setup- und Call-Phase melden denselben Test – ein `skipif` in der einen,
        ein `pytest.skip()` in der anderen. Ohne Set-Dedup hinge die Kennzahl
        daran, WIE ein Test übersprungen wird statt DASS er es wird."""
        for _ in range(3):
            log_report(_Report("tests/unit/test_a.py::test_x", skipped=True))
        assert len(conftest_module._skipped_nodeids) == 1

    def test_logreport_counts_distinct_tests_separately(self) -> None:
        log_report(_Report("tests/unit/test_a.py::test_x", skipped=True))
        log_report(_Report("tests/unit/test_a.py::test_y", skipped=True))
        assert len(conftest_module._skipped_nodeids) == 2


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

    def test_executed_floor_keeps_a_meaningful_distance(self) -> None:
        """Dieselbe Größenordnung, aber gemessen auf der striktesten Plattform.

        Die Zahl ist Windows aus CI-Lauf 32843165645 (1826 gesammelt, 3
        übersprungen). Auf macOS und Ubuntu liefen 1826 – wer den Floor dort
        misst, setzt ihn drei Tests zu hoch und macht den nächsten
        Windows-Lauf rot.
        """
        measured_on_windows = 1823
        assert measured_on_windows > EXECUTED_FLOOR
        assert int(measured_on_windows * 0.95) <= EXECUTED_FLOOR

    def test_the_platform_gap_is_smaller_than_the_margin(self) -> None:
        """Der Abstand muss den Plattform-Unterschied aushalten, nicht nur die
        Messung treffen.

        Windows führt 3 Tests weniger aus als Ubuntu/macOS. Ein Floor, der diesen
        Unterschied nicht überdeckt, wäre auf einer Plattform grün und auf einer
        anderen rot – die Sprint-78-Lehre: nicht mit knapper Reserve an eine
        plattformabhängige Grenze legen.
        """
        measured_on_windows, measured_elsewhere = 1823, 1826
        assert measured_elsewhere - measured_on_windows < measured_on_windows - EXECUTED_FLOOR
