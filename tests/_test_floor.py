"""Testmengen-Wächter (Sprint 77 / Befund #8, erweitert in Sprint 79).

Tests können still aufhören, gesammelt zu werden. Fällt eine Testdatei durch
einen Tippfehler im Dateinamen, ein `collect_ignore`, ein verschobenes
`testpaths` oder eine umbenannte Test-Klasse aus der Sammlung, sinkt die Zahl –
und kein einziger Test wird rot. Genau diese Klasse hat in Sprint 74 Monate
gebraucht, bis sie auffiel (`test_html_report.py` war grün und leer).

Zwei Wächter, dieselbe Familie, verschiedene Lücken:

* `check_test_floor` zählt, was **gesammelt** wurde – der Sprint-77-Wächter.
* `check_executed_floor` zählt, was **ausgeführt** wurde (`gesammelt −
  übersprungen`) – Sprint 79. `session.testscollected` zählt übersprungene Tests
  MIT: kippt ein `skipif` (falsche Plattform-Abfrage, ein `sys.platform`-Vergleich
  der immer wahr ist), bleibt die gesammelte Zahl exakt stehen und die
  Ausführung verschwindet lautlos.

Warum `gesammelt − übersprungen` und nicht „höchstens N Skips": ein Zähler-Deckel
ist lose. Fängt ein Test an zu skippen und hört ein anderer damit auf, bleibt die
Summe gleich – und genau der Fall, um den es geht, rutscht durch.

Beide sind **Sperrklinken-Werte (Ratchets)**, keine Gleichheitsprüfungen:
`>= FLOOR`, nie `==`. Normales Test-Hinzufügen darf sie nie auslösen, ein echter
Ausfall sofort.

Die Prüflogik liegt als reine Funktion vor, damit sie ohne
Sub-pytest-Lauf testbar ist (`tests/unit/test_test_floor.py`); die Hooks, die sie
aufrufen, sitzen in `tests/conftest.py`.
"""

from __future__ import annotations

#: Schaltet BEIDE Wächter scharf. Ohne diese Variable (Wert exakt `"1"`) sind die
#: Hooks ein No-Op – sonst schlüge jeder lokale Teil-Lauf wie
#: `pytest tests/ui/test_worker.py` fehl und der Wächter würde zur Plage statt
#: zum Netz. Gesetzt wird sie ausschließlich im pytest-Step beider Workflows;
#: dass sie dort wirklich steht, prüft
#: `tests/_workflow_policy.py::check_test_floor_is_armed`.
#:
#: Sprint 79 nutzt bewusst dasselbe Gate: die Variable steht bereits in beiden
#: Workflows, der Ausführungs-Wächter braucht deshalb KEINE `.github/`-Änderung –
#: und `check_test_floor_is_armed` bleibt unverändert grün.
ENFORCE_TEST_FLOOR_ENV = "SAMPLING_TOOL_ENFORCE_TEST_FLOOR"

#: Messreihe (voller Lauf auf macOS, jeweils am Sprint-Ende):
#:   2026-08-17, Sprint 77: 1642 gesammelt → Floor 1600 (2,6 % Abstand)
#:   2026-08-17, Sprint 78: 1765 gesammelt → Floor 1700 (3,7 % Abstand)
#: Der Abstand hält plattformbedingte Schwankung und normales Test-Hinzufügen
#: aus dem Wächter heraus; ein echter Sammel-Ausfall (eine Datei fällt raus)
#: liegt deutlich darüber.
#:
#: NUR NACH OBEN ANPASSEN. Sinkt die gesammelte Zahl unter diesen Wert, ist das
#: der Befund – nicht der Anlass, die Konstante zu senken.
TEST_FLOOR = 1700

#: Zahl der AUSGEFÜHRTEN Tests (`gesammelt − übersprungen`), Sprint 79.
#:
#: PROVISORISCHER WERT – wird vor dem Merge aus dem echten CI-Lauf ersetzt.
EXECUTED_FLOOR = 1600


def check_test_floor(collected: int, floor: int) -> str | None:
    """Meldung, wenn `collected` unter `floor` liegt – sonst `None`.

    Reine Funktion über zwei Zahlen: so ist der Wächter ohne verschachtelten
    pytest-Lauf prüfbar, inklusive der Fälle, die im echten Lauf nie eintreten
    sollen.
    """
    if collected >= floor:
        return None
    return (
        f"Testmengen-Wächter: nur {collected} Tests gesammelt, erwartet mindestens "
        f"{floor} (Differenz: {floor - collected}). Es sind Tests aus der Sammlung "
        f"gefallen, ohne dass einer rot wurde – typische Ursachen: Import-Fehler in "
        f"einer Testdatei, Datei außerhalb von `python_files`, verschobenes "
        f"`testpaths`, ein `collect_ignore` oder eine umbenannte Test-Klasse. "
        f"Der Wert in tests/_test_floor.py wird NICHT gesenkt, um diesen Lauf grün "
        f"zu machen."
    )


def check_executed_floor(collected: int, skipped: int, floor: int) -> str | None:
    """Meldung, wenn `collected - skipped` unter `floor` liegt – sonst `None`.

    Die Kennzahl ist die Zahl der tatsächlich ausgeführten Tests. Sie ist die
    einzige, die den Fall erfasst, den `check_test_floor` nicht sieht: ein Test
    bleibt in der Sammlung (`testscollected` unverändert), wird aber nicht mehr
    ausgeführt.

    Reine Funktion über drei Zahlen – prüfbar ohne verschachtelten pytest-Lauf,
    inklusive der Fälle, die im echten Lauf nie eintreten sollen.
    """
    executed = collected - skipped
    if executed >= floor:
        return None
    return (
        f"Ausführungs-Wächter: nur {executed} von {collected} gesammelten Tests "
        f"ausgeführt ({skipped} übersprungen), erwartet mindestens {floor} "
        f"(Differenz: {floor - executed}). Tests sind aus der AUSFÜHRUNG gefallen, "
        f"ohne aus der Sammlung zu fallen – typische Ursachen: ein `skipif`, dessen "
        f"Bedingung jetzt immer wahr ist, ein `pytest.skip()` in einem Fixture oder "
        f"ein `importorskip` auf eine Dependency, die stillschweigend fehlt. "
        f"Der Wert in tests/_test_floor.py wird NICHT gesenkt, um diesen Lauf grün "
        f"zu machen."
    )
