"""Sprint 75 / Befund A: stdout der `scripts/`-Skripte übersteht cp1252.

Auf Windows-CI ist `sys.stdout` bei umgeleitetem Output (Pipe, wie in jedem
`subprocess.run(capture_output=True)` und in jedem Actions-Step) die
ANSI-Codepage cp1252 – nicht UTF-8. Ein einziges Zeichen außerhalb von cp1252
lässt `print()` mit `UnicodeEncodeError` sterben. `scripts/build_app.py:121`
druckt `✓` (U+2713) NACH erfolgreichem PyInstaller-Lauf und hat damit den
Windows-Release-Build gekillt, obwohl das Bundle fertig war.

Der Fix sitzt an der Wurzel (`force_utf8_stdout`), nicht am Zeichen: ein
entferntes Häkchen behebt genau diesen einen Fall und lädt den nächsten Glyph
wieder ein.
"""

from __future__ import annotations

import ast
import io
import sys
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR: Final = REPO_ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _script_io import force_utf8_stdout  # type: ignore[import-not-found]  # noqa: E402

# Der Name des Guards ist SSOT – Tests schreiben ihn nicht als zweites Literal
# hin (Sprint-72-Falle), sondern leiten ihn aus dem importierten Symbol ab.
GUARD_NAME: Final[str] = force_utf8_stdout.__name__

# Das Zeichen, an dem der Windows-Release gestorben ist. Bleibt bewusst im
# Produktionscode (§2.1) – deshalb ist es hier auch ein stabiler Anker.
CHECKMARK: Final = "✓"


def _cp1252_codable(char: str) -> bool:
    """Kann cp1252 dieses Zeichen darstellen? Gemessen, nicht geschätzt."""
    try:
        char.encode("cp1252")
    except UnicodeEncodeError:
        return False
    return True


def _cp1252_stream() -> tuple[io.TextIOWrapper, io.BytesIO]:
    """Ein Text-Stream mit cp1252 über einem BytesIO – wie Windows-CI-stdout."""
    raw = io.BytesIO()
    return io.TextIOWrapper(raw, encoding="cp1252", newline=""), raw


def _script_files() -> list[Path]:
    return sorted(p for p in SCRIPTS_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def _printed_str_constants(tree: ast.AST) -> list[tuple[int, str]]:
    """Alle `str`-Konstanten, die (auch in f-Strings) in einem `print()` landen."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if called != "print":
            continue
        for arg in node.args:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    found.append((getattr(sub, "lineno", node.lineno), sub.value))
    return found


def _uncodable_printed_chars(tree: ast.AST) -> dict[str, list[int]]:
    """Pro cp1252-unkodierbarem Zeichen die Zeilen, in denen es gedruckt wird."""
    hits: dict[str, list[int]] = {}
    for lineno, value in _printed_str_constants(tree):
        for char in value:
            if ord(char) > 127 and not _cp1252_codable(char):
                hits.setdefault(char, []).append(lineno)
    return {char: sorted(set(lines)) for char, lines in hits.items()}


def _calls_guard(tree: ast.AST) -> bool:
    """Ruft das Modul den Guard irgendwo auf?"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if called == GUARD_NAME:
            return True
    return False


def _function_def(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() nicht auf Modulebene gefunden")


class TestStdoutEncoding:
    """Der Guard schützt genau die Skripte, die ihn brauchen – und wird zuerst gerufen."""

    def test_force_utf8_stdout_survives_cp1252_base_stream(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`✓` auf einen cp1252-Stream drucken wirft nach dem Guard nicht mehr."""
        # Vorbedingung: ohne Guard stirbt genau dieser Aufbau. Ohne diese
        # Assertion würde der Test auch dann grün, wenn er den Fehlerpfad
        # überhaupt nicht trifft (Sprint-74-Lehre: "grün" ist kein Nachweis).
        assert not _cp1252_codable(CHECKMARK), "Testaufbau kaputt: ✓ wäre cp1252-kodierbar"
        naked, _ = _cp1252_stream()
        monkeypatch.setattr(sys, "stdout", naked)
        # `TextIOWrapper.write` kodiert sofort – der Fehler kommt beim `print`,
        # nicht erst beim Flush.
        with pytest.raises(UnicodeEncodeError):
            print(CHECKMARK)

        guarded, raw = _cp1252_stream()
        monkeypatch.setattr(sys, "stdout", guarded)
        monkeypatch.setattr(sys, "stderr", guarded)

        force_utf8_stdout()
        print(f"\n{CHECKMARK} Build erfolgreich.")
        sys.stdout.flush()

        assert CHECKMARK.encode("utf-8") in raw.getvalue()

    def test_force_utf8_stdout_tolerates_streams_without_reconfigure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ein Stream ohne `reconfigure` darf den Guard nicht werfen lassen.

        Sonst wäre der Guard selbst die Regression: `io.StringIO` und diverse
        Test-/Capture-Wrapper haben die Methode nicht.
        """
        plain = io.StringIO()
        assert not hasattr(plain, "reconfigure")
        monkeypatch.setattr(sys, "stdout", plain)
        monkeypatch.setattr(sys, "stderr", plain)

        force_utf8_stdout()

        print(CHECKMARK)
        assert CHECKMARK in plain.getvalue()

    def test_force_utf8_stdout_is_called_before_any_print(self) -> None:
        """In jedem geschützten Skript steht der Guard vor der ersten Ausgabe.

        Per AST, nicht per `grep`: ein `print` in einem Kommentar oder in einem
        Docstring darf den Test nicht falsch-rot färben.
        """
        guarded = [
            p for p in _script_files() if _calls_guard(ast.parse(p.read_text("utf-8"), str(p)))
        ]
        assert guarded, "kein Skript ruft den Guard – Testaufbau oder Fix fehlt"

        for path in guarded:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            main = _function_def(tree, "main")

            guard_stmts = [
                index
                for index, stmt in enumerate(main.body)
                if any(
                    isinstance(sub, ast.Call)
                    and (
                        sub.func.id
                        if isinstance(sub.func, ast.Name)
                        else getattr(sub.func, "attr", None)
                    )
                    == GUARD_NAME
                    for sub in ast.walk(stmt)
                )
            ]
            assert guard_stmts, f"{path.name}: main() ruft {GUARD_NAME}() nicht"
            assert guard_stmts[0] == 0, (
                f"{path.name}: {GUARD_NAME}() ist nicht die erste Anweisung in main() "
                f"(steht an Position {guard_stmts[0]})"
            )

            guard_line = main.body[0].lineno
            printed = [line for line, _ in _printed_str_constants(main)]
            assert all(line > guard_line for line in printed), (
                f"{path.name}: print() in Zeile "
                f"{[line for line in printed if line <= guard_line]} vor dem Guard"
            )

    def test_no_script_prints_uncodable_chars_without_guard(self) -> None:
        """§3.1-Inventur als Gate: wer cp1252-Unkodierbares druckt, ruft den Guard.

        Positiv-Kontrolle ist eingebaut: findet der Scanner *nirgends* ein
        unkodierbares Zeichen, ist er kaputt und der Test fällt – ein Gate, das
        still 0 Treffer meldet, ist die Sprint-64-Falle.
        """
        offenders: dict[Path, dict[str, list[int]]] = {}
        unguarded: dict[Path, dict[str, list[int]]] = {}

        for path in _script_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            hits = _uncodable_printed_chars(tree)
            if not hits:
                continue
            offenders[path] = hits
            if not _calls_guard(tree):
                unguarded[path] = hits

        assert offenders, (
            "Scanner findet kein einziges cp1252-unkodierbares Zeichen in einem "
            "print() – entweder ist der Scanner kaputt oder das ✓ aus §2.1 wurde "
            "entfernt statt geschützt"
        )
        assert not unguarded, "\n".join(
            f"{path.relative_to(REPO_ROOT)} druckt {sorted(chars)} in Zeile(n) "
            f"{sorted({line for lines in chars.values() for line in lines})}, "
            f"ruft aber {GUARD_NAME}() nicht"
            for path, chars in unguarded.items()
        )
