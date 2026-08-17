"""Testmengen-Wächter (Sprint 77 / Befund #8).

Tests können still aufhören, gesammelt zu werden. Fällt eine Testdatei durch
einen Tippfehler im Dateinamen, ein `collect_ignore`, ein verschobenes
`testpaths` oder eine umbenannte Test-Klasse aus der Sammlung, sinkt die Zahl –
und kein einziger Test wird rot. Genau diese Klasse hat in Sprint 74 Monate
gebraucht, bis sie auffiel (`test_html_report.py` war grün und leer).

Der Wächter ist ein **Sperrklinken-Wert (Ratchet)**, keine Gleichheitsprüfung:
`>= FLOOR`, nie `==`. Normales Test-Hinzufügen darf ihn nie auslösen, ein
echter Sammel-Ausfall sofort.

Die Prüflogik liegt als reine Funktion vor, damit sie ohne
Sub-pytest-Lauf testbar ist (`tests/unit/test_test_floor.py`); der Hook, der sie
aufruft, sitzt in `tests/conftest.py`.
"""

from __future__ import annotations

#: Schaltet den Wächter scharf. Ohne diese Variable (Wert exakt `"1"`) ist der
#: Hook ein No-Op – sonst schlüge jeder lokale Teil-Lauf wie
#: `pytest tests/ui/test_worker.py` fehl und der Wächter würde zur Plage statt
#: zum Netz. Gesetzt wird sie ausschließlich im pytest-Step beider Workflows;
#: dass sie dort wirklich steht, prüft
#: `tests/_workflow_policy.py::check_test_floor_is_armed`.
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
