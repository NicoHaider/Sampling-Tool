"""Sprint 89 / D3: englische Reste aus sichtbaren Texten bleiben draußen."""

from __future__ import annotations

import ast

import pytest

from sampling_tool.resources import package_resource, shared_resource

pytestmark = pytest.mark.unit

_FORBIDDEN = ("Parent-Sample-ID", "Sample-Hervorhebung")


def _string_literals() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in sorted(package_resource("").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found.extend(
            (path.name, node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
    for template in sorted(shared_resource("templates").glob("*.html")):
        found.append((template.name, template.read_text(encoding="utf-8")))
    return found


@pytest.mark.parametrize("term", _FORBIDDEN)
def test_term_is_gone(term: str) -> None:
    hits = sorted({name for name, text in _string_literals() if term in text})
    assert hits == [], f"„{term}“ steht noch in: {hits}"


def test_replacement_is_used() -> None:
    from sampling_tool.config import AUDIT_DETAIL_LABELS

    assert AUDIT_DETAIL_LABELS["parent_sample_id"] == "Übergeordnete Stichprobe"


def test_scan_actually_sees_the_sources() -> None:
    texts = _string_literals()
    assert len(texts) > 1000
    assert any("Übergeordnete Stichprobe" in text for _name, text in texts)
