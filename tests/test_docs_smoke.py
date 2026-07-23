"""Doku-Smokes (D.6a): Versions-SSOT + Existenz referenzierter Doku-Pfade.

Leichtgewichtige Konsistenz-Checks, damit Doku und Code nicht wieder
auseinanderlaufen (Backlog D-001):

* Die Version lebt an genau **einer** Stelle (`sampling_tool.__version__`),
  aus der `pyproject.toml` (dynamisch) und `sampling_tool.spec` (Import)
  ableiten – kein dreifaches Literal.
* In `docs/*.md` per Backtick referenzierte, repo-relative Dateipfade
  existieren wirklich (fängt u. a. den früher falschen Briefpapier-Pfad).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import sampling_tool


def _repo_root() -> Path:
    root = Path(__file__).resolve()
    for parent in root.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise AssertionError("pyproject.toml nicht gefunden – REPO_ROOT unklar")


REPO_ROOT = _repo_root()


class TestVersionSingleSource:
    """Die Version ist an genau einer Stelle gepflegt und wird abgeleitet."""

    def test_runtime_version_is_the_ssot(self) -> None:
        version = sampling_tool.__version__
        assert version, "sampling_tool.__version__ darf nicht leer sein"
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), version

    def test_pyproject_derives_version_dynamically(self) -> None:
        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = data["project"]
        # Kein statisches Literal mehr im [project]-Block …
        assert "version" not in project, "pyproject.toml hat wieder ein statisches version-Literal"
        # … sondern dynamisch aus der SSOT abgeleitet.
        assert "version" in project.get("dynamic", [])
        attr = data["tool"]["setuptools"]["dynamic"]["version"]["attr"]
        assert attr == "sampling_tool.__version__"

    def test_package_metadata_matches_runtime(self) -> None:
        import importlib.metadata as metadata

        assert metadata.version("sampling-tool") == sampling_tool.__version__

    def test_spec_reads_version_from_ssot(self) -> None:
        spec = (REPO_ROOT / "sampling_tool.spec").read_text(encoding="utf-8")
        assert "from sampling_tool import __version__" in spec
        # Kein hartes APP_VERSION = "x.y.z"-Literal mehr.
        assert not re.search(r'APP_VERSION\s*=\s*["\']\d', spec), (
            "spec hat wieder ein Versions-Literal"
        )

    def test_no_second_version_literal_in_build_files(self) -> None:
        version = sampling_tool.__version__
        for name in ("pyproject.toml", "sampling_tool.spec"):
            text = (REPO_ROOT / name).read_text(encoding="utf-8")
            assert version not in text, f"{name} enthält ein zweites Versions-Literal ({version})"


# Zeichen, die einen Backtick-Token als „kein konkreter Repo-Pfad" ausweisen
# (Platzhalter `<…>`, Globs `*`, Brace-Expansions `{…}`, Home/Absolut, URLs,
# Registry-Backslashes, Whitespace).
_NON_PATH_CHARS = set(" \t\n*{}<>~|:\\")
_FILE_SUFFIXES = (
    ".pdf",
    ".db",
    ".sql",
    ".qss",
    ".html",
    ".htm",
    ".py",
    ".xlsx",
    ".xlsm",
    ".json",
    ".md",
    ".ico",
    ".icns",
    ".png",
    ".jpg",
    ".jpeg",
    ".csv",
    ".tsv",
    ".toml",
    ".yml",
    ".yaml",
    ".txt",
    ".cfg",
    ".sh",
)
_FENCED_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]+)`")


def _referenced_repo_paths(markdown: str) -> list[str]:
    """Backtick-Tokens, die wie konkrete repo-relative Dateipfade aussehen."""
    text = _FENCED_BLOCK.sub("", markdown)
    found: list[str] = []
    for match in _INLINE_CODE.finditer(text):
        token = match.group(1).strip()
        if "/" not in token:
            continue
        if any(char in _NON_PATH_CHARS for char in token):
            continue
        if token.startswith(("/", ".", "http")):
            continue
        if not token.lower().endswith(_FILE_SUFFIXES):
            continue
        found.append(token)
    return found


class TestDocsReferencedPaths:
    """In docs/*.md referenzierte relative Dateipfade existieren."""

    def test_referenced_paths_exist(self) -> None:
        docs = sorted((REPO_ROOT / "docs").glob("*.md"))
        assert docs, "keine docs/*.md gefunden"

        checked: list[str] = []
        missing: list[str] = []
        for doc in docs:
            for token in _referenced_repo_paths(doc.read_text(encoding="utf-8")):
                checked.append(token)
                if not (REPO_ROOT / token).exists():
                    missing.append(f"{doc.name}: {token}")

        assert not missing, "Nicht existierende Doku-Pfade: " + "; ".join(missing)
        # Sanity: der Extractor findet überhaupt etwas (sonst wäre der Test blind).
        assert checked, "kein einziger konkreter Dateipfad in docs/*.md geprüft"
