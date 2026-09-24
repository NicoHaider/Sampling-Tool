"""Kein neues `"system"` als Benutzername in `ui/`, `audit/`, `persistence/` (Sprint 83 / C).

Ersetzt den Textgate ``rg '"system"' src/sampling_tool/ui src/sampling_tool/audit
src/sampling_tool/persistence`` aus SPRINT_83_PROMPT.md §5: der hat auf `main` zwei
legitime Treffer, die mit `created_by` nichts zu tun haben –

* `WorkspaceSession.user_name` – Rückfall, wenn das Betriebssystem keinen
  Login-Namen liefert (`getpass.getuser()` wirft `OSError`). Das ist die
  dokumentierte Quelle des Benutzernamens, nicht der Dataclass-Default, der den
  Befund verursacht hat.
* `_build_snapshot_name` – Dateinamen-Token eines Snapshots ohne Auditor-Namen.

Statt eines Textgates, der nie 0 erreichen kann, prüft dieser Test per AST, dass
genau diese beiden Fundstellen existieren und keine dritte dazukommt. Das
Verhalten selbst (Audit-Details, Provenienz, Export tragen den Login-Namen)
belegt `tests/ui/test_main_controller.py::TestCreatedByIsUser`.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

_SRC: Final = Path(__file__).resolve().parents[2] / "src" / "sampling_tool"
_PACKAGES: Final = ("ui", "audit", "persistence")

_ALLOWED: Final = frozenset(
    {
        ("ui/controllers/workspace_session.py", "user_name"),
        ("persistence/version_manager.py", "_build_snapshot_name"),
    }
)


def find_system_literals(source: str, relpath: str) -> set[tuple[str, str]]:
    """``(Datei, umschließende Funktion)`` je String-Literal ``"system"``; Modulebene = ``""``."""
    found: set[tuple[str, str]] = set()

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Constant) and child.value == "system":
                found.add((relpath, scope))
            visit(child, scope)

    visit(ast.parse(source), "")
    return found


def _scan_packages() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for package in _PACKAGES:
        for path in sorted((_SRC / package).rglob("*.py")):
            relpath = path.relative_to(_SRC).as_posix()
            found |= find_system_literals(path.read_text(encoding="utf-8"), relpath)
    return found


class TestNoNewSystemUserLiteral:
    def test_only_the_documented_fallbacks_remain(self) -> None:
        assert _scan_packages() == _ALLOWED


class TestPolicyDetectsViolation:
    """Positiv-Kontrolle: eine Prüffunktion, die immer ``set()`` liefert, bestünde
    den Test oben nicht – sie muss ein eingeschleustes Literal finden."""

    def test_literal_in_function_is_found(self) -> None:
        source = "def persist(result):\n    return replace(result, created_by='system')\n"
        assert find_system_literals(source, "x.py") == {("x.py", "persist")}

    def test_default_argument_is_found(self) -> None:
        source = 'def log(user: str = "system") -> None:\n    pass\n'
        assert find_system_literals(source, "x.py") == {("x.py", "log")}

    def test_other_strings_are_ignored(self) -> None:
        assert find_system_literals("X = 'systemd'\n", "x.py") == set()
