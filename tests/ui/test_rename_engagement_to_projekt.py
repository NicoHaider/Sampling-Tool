"""Sprint 27: „Engagement"/„Engagements" → „Projekt"/„Projekte" (nur sichtbarer Text).

Verifiziert über einen AST-Scan, dass in den user-sichtbaren UI-/Report-Strings
(Menüs, Buttons, Dialogtitel, Labels, Tooltips, Export-Texte) kein „Engagement"
mehr vorkommt. Bewusst NICHT geprüft werden Code-Identifier, Klassen, DB-Spalten,
Datei-/Modulnamen und APIs (Hard Constraint des Sprints) – diese behalten
„Engagement". Ebenfalls ausgenommen: Docstrings, ``__all__``-Einträge und
technische Log-Strings (``logger.*``), da nicht user-sichtbar.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.ui

_SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "sampling_tool"
_TARGETS = [
    *sorted(_SRC.glob("ui/**/*.py")),
    _SRC / "io" / "pdf_report.py",
    _SRC / "io" / "multi_report_exporter.py",
    _SRC / "io" / "html_report.py",
    _SRC / "io" / "exporter.py",
]
_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}


def _is_docstring_or_bare_string(node: ast.AST) -> bool:
    """Bare-String-Statement (Docstring oder „Kommentar-String") – nicht sichtbar."""
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_logger_call(node: ast.AST) -> bool:
    """``logger.*``/``logging.*``-Aufruf – Argumente sind technische Logs."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _LOG_METHODS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"logger", "log", "logging"}
    )


def _is_all_assignment(node: ast.AST) -> bool:
    return isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
    )


def _non_visible_constant_ids(tree: ast.AST) -> set[int]:
    """IDs der String-Constants, die NICHT user-sichtbar sind.

    Docstrings/Bare-String-Statements, ``__all__``-Einträge und Argumente von
    ``logger.*``-Aufrufen (technische Logs, laut CLAUDE.md englisch/technisch).
    """
    excluded: set[int] = set()
    for node in ast.walk(tree):
        if _is_docstring_or_bare_string(node):
            excluded.add(id(node.value))  # type: ignore[attr-defined]
        elif _is_all_assignment(node) or _is_logger_call(node):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Constant):
                    excluded.add(id(inner))
    return excluded


def _visible_strings(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    excluded = _non_visible_constant_ids(tree)
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in excluded
    ]


class TestRenameEngagementToProjekt:
    def test_no_user_facing_engagement_string(self) -> None:
        offenders: list[str] = []
        for path in _TARGETS:
            for value in _visible_strings(path):
                if "Engagement" in value:
                    offenders.append(f"{path.relative_to(_SRC)}: {value!r}")
        assert not offenders, "Sichtbarer Engagement-Text in UI-Strings gefunden:\n" + "\n".join(
            offenders
        )

    def test_projekt_appears_in_visible_strings(self) -> None:
        # Positiv-Gegenprobe: „Projekt" steht jetzt in sichtbaren Strings.
        found = any("Projekt" in value for path in _TARGETS for value in _visible_strings(path))
        assert found
