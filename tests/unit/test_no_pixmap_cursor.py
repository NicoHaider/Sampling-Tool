"""Kein `setOverrideCursor` mehr in `src/` (Sprint 91 / A).

Qt baut `WaitCursor`/`BusyCursor` auf macOS aus einer Pixmap und wandelt sie
über `QImage::toCGImage()` um; ein ungültiger Farbraum dabei hat die App am
28.09.2026 zweimal beim Klick auf OK im Stichproben-Dialog abstürzen lassen
(SIGTRAP in `QGuiApplication::setOverrideCursor`). Ersetzt durch
`ui._busy_indicator.busy_indicator` (Widget-Disable statt Cursor, wirkt auf
allen Plattformen gleich) – dieser AST-Scan verhindert die Rückkehr eines
Pixmap-Cursors, ganz gleich welchen Typs.

Positiv-Kontrolle: `TestPolicyDetectsViolation` unten belegt, dass der Scan
greift (analog zu `test_no_english_button_text.py`).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

_SRC: Final = Path(__file__).resolve().parents[2] / "src" / "sampling_tool"


def find_override_cursor_calls(source: str, relpath: str) -> list[tuple[str, int]]:
    """``(Datei, Zeile)`` je Aufruf von `...setOverrideCursor(...)` im Quelltext."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name == "setOverrideCursor":
            found.append((relpath, node.lineno))
    return found


class TestNoPixmapCursor:
    def test_src_has_no_set_override_cursor_call(self) -> None:
        found: list[tuple[str, int]] = []
        for path in sorted(_SRC.rglob("*.py")):
            relpath = path.relative_to(_SRC).as_posix()
            found += find_override_cursor_calls(path.read_text(encoding="utf-8"), relpath)
        assert found == []


class TestPolicyDetectsViolation:
    def test_finds_qapplication_call(self) -> None:
        source = "QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)\n"
        assert find_override_cursor_calls(source, "x.py") == [("x.py", 1)]

    def test_finds_call_on_arbitrary_receiver(self) -> None:
        source = "app.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))\n"
        assert find_override_cursor_calls(source, "x.py") == [("x.py", 1)]

    def test_unrelated_widget_calls_pass(self) -> None:
        source = "widget.setEnabled(False)\nwidget.setCursor(Qt.CursorShape.ArrowCursor)\n"
        assert find_override_cursor_calls(source, "x.py") == []
