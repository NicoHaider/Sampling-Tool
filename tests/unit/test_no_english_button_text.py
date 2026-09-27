"""Kein englischer Standard-Buttontext als Literal in `src/` (Sprint 85 / A).

Die Qt-Standardbuttons übersetzt `qtbase_de` zur Laufzeit. Ein Button, den
unser Code SELBST beschriftet, entgeht dieser Übersetzung – steht dort
„Cancel", sieht der Anwender „Cancel". Der AST-Scan prüft die String-Literale
an den Stellen, an denen Buttontext entsteht: `setText(...)`,
`setButtonText(..., text)`, `QPushButton(text, ...)` und
`addButton(text, ...)`.

Positiv-Kontrolle: Auf `origin/main` (Sprint 84) gibt es keine solche
Fundstelle – der Test ist dort also grün und kann nicht rot vorgeführt werden.
Dass die Prüffunktion greift, belegen stattdessen die Mutationen in
`TestPolicyDetectsViolation`.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

_SRC: Final = Path(__file__).resolve().parents[2] / "src" / "sampling_tool"
ENGLISH_BUTTON_WORDS: Final = frozenset(
    {"Cancel", "Yes", "No", "Close", "OK", "Ok", "Save", "Open", "Apply", "Back", "Next", "Finish"}
)
_TEXT_METHODS: Final = frozenset({"setText", "addButton", "setButtonText"})


def _literal_texts(call: ast.Call) -> list[str]:
    return [
        arg.value.replace("&", "")
        for arg in call.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
    ]


def find_english_button_texts(source: str, relpath: str) -> list[tuple[str, int, str]]:
    """``(Datei, Zeile, Text)`` je englischem Buttontext an einer Beschriftungsstelle."""
    found: list[tuple[str, int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in _TEXT_METHODS and name != "QPushButton":
            continue
        found += [
            (relpath, node.lineno, text)
            for text in _literal_texts(node)
            if text.strip() in ENGLISH_BUTTON_WORDS
        ]
    return found


class TestNoEnglishButtonText:
    def test_src_has_no_english_button_literal(self) -> None:
        found: list[tuple[str, int, str]] = []
        for path in sorted(_SRC.rglob("*.py")):
            relpath = path.relative_to(_SRC).as_posix()
            found += find_english_button_texts(path.read_text(encoding="utf-8"), relpath)
        assert found == []


class TestPolicyDetectsViolation:
    def test_push_button_constructor_is_found(self) -> None:
        source = "b = QPushButton('Cancel', self)\n"
        assert find_english_button_texts(source, "x.py") == [("x.py", 1, "Cancel")]

    def test_set_text_with_mnemonic_is_found(self) -> None:
        source = "button.setText('&Yes')\n"
        assert find_english_button_texts(source, "x.py") == [("x.py", 1, "Yes")]

    def test_add_button_and_wizard_text_are_found(self) -> None:
        source = (
            "box.addButton('Close', QMessageBox.ButtonRole.RejectRole)\n"
            "w.setButtonText(QWizard.WizardButton.NextButton, 'Next')\n"
        )
        assert find_english_button_texts(source, "x.py") == [
            ("x.py", 1, "Close"),
            ("x.py", 2, "Next"),
        ]

    def test_german_and_non_button_strings_pass(self) -> None:
        source = "b = QPushButton('Abbrechen')\nlabel.setText('No data')\nlog('Cancel')\n"
        assert find_english_button_texts(source, "x.py") == []
