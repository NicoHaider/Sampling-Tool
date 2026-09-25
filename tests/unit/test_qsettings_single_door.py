"""`QSettings` wird in `src/` genau einmal konstruiert: in `settings_store._qsettings` (Sprint 84 / A).

Hintergrund: Die Testsuite isoliert die App-Einstellungen, indem sie
`settings_store._qsettings` auf eine tmp-INI umbiegt (`tests/conftest.py`).
Das schützt Nicos echte Prefs nur, wenn es keine zweite Tür gibt. Bis
Sprint 83 baute `MainWindow` seinen Handle selbst (`QSettings(APP_ORG,
APP_NAME)`) – jeder Test mit echtem Fenster schrieb dadurch Fensterzustand
in die echten Prefs, sofern er nicht zusätzlich `main_window.QSettings`
patchte. Der zweite 2-Argument-Konstruktor ignoriert `setPath` und
`setDefaultFormat`, eine globale Umleitung per Qt-API reicht also nicht.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

_SRC: Final = Path(__file__).resolve().parents[2] / "src" / "sampling_tool"
_DOOR: Final = ("ui/settings_store.py", "_qsettings")


def find_qsettings_constructions(source: str, relpath: str) -> list[tuple[str, str]]:
    """``(Datei, umschließende Funktion)`` je `QSettings(...)`-Aufruf; Modulebene = ``""``.

    Erkennt auch `QtCore.QSettings(...)` und Import-Aliase (`import QSettings as QS`).
    """
    tree = ast.parse(source)
    names = {"QSettings"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {a.asname for a in node.names if a.name == "QSettings" and a.asname}
    found: list[tuple[str, str]] = []

    def is_qsettings(func: ast.expr) -> bool:
        if isinstance(func, ast.Name):
            return func.id in names
        return isinstance(func, ast.Attribute) and func.attr == "QSettings"

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Call) and is_qsettings(child.func):
                found.append((relpath, scope))
            visit(child, scope)

    visit(tree, "")
    return found


def _scan_src() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in sorted(_SRC.rglob("*.py")):
        relpath = path.relative_to(_SRC).as_posix()
        found += find_qsettings_constructions(path.read_text(encoding="utf-8"), relpath)
    return found


class TestSingleQSettingsDoor:
    def test_exactly_one_construction_in_qsettings_helper(self) -> None:
        assert _scan_src() == [_DOOR]


class TestPolicyDetectsViolation:
    """Positiv-Kontrolle: eine Prüffunktion, die immer ``[]`` liefert, bestünde den
    Test oben nicht – sie muss eine eingeschleuste zweite Tür finden."""

    def test_two_argument_constructor_in_method_is_found(self) -> None:
        source = (
            "from PyQt6.QtCore import QSettings\n"
            "class W:\n"
            "    def __init__(self):\n"
            "        self._settings = QSettings(APP_ORG, APP_NAME)\n"
        )
        assert find_qsettings_constructions(source, "x.py") == [("x.py", "__init__")]

    def test_module_attribute_and_alias_are_found(self) -> None:
        source = (
            "from PyQt6 import QtCore\n"
            "from PyQt6.QtCore import QSettings as QS\n"
            "A = QtCore.QSettings('o', 'a')\n"
            "def f():\n"
            "    return QS('o', 'a')\n"
        )
        assert find_qsettings_constructions(source, "x.py") == [("x.py", ""), ("x.py", "f")]

    def test_enum_access_is_not_a_construction(self) -> None:
        source = "fmt = QSettings.Format.IniFormat\n"
        assert find_qsettings_constructions(source, "x.py") == []
