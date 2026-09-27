"""`ui/_trash.move_to_trash` (Sprint 88 / A3) – ohne den echten Papierkorb.

`QFile` wird im Modul ersetzt; die globale Attrappe aus `tests/conftest.py`
greift hier nicht, weil die echte Funktion schon beim Import gebunden wurde.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from sampling_tool.ui import _trash
from sampling_tool.ui._trash import move_to_trash

pytestmark = pytest.mark.ui


class _FakeQFile:
    calls: ClassVar[list[str]] = []
    result: ClassVar[tuple[bool, str]] = (True, "")

    @classmethod
    def moveToTrash(cls, name: str) -> tuple[bool, str]:
        cls.calls.append(name)
        return cls.result


@pytest.fixture
def fake_qfile(monkeypatch: pytest.MonkeyPatch) -> type[_FakeQFile]:
    _FakeQFile.calls = []
    monkeypatch.setattr(_trash, "QFile", _FakeQFile)
    return _FakeQFile


def test_success_is_reported(fake_qfile: type[_FakeQFile], tmp_path: Path) -> None:
    fake_qfile.result = (True, str(tmp_path / "Trash" / "x.db"))
    assert move_to_trash(tmp_path / "x.db") is True
    assert fake_qfile.calls == [str(tmp_path / "x.db")]


def test_failure_is_reported_without_deleting(fake_qfile: type[_FakeQFile], tmp_path: Path) -> None:
    target = tmp_path / "x.db"
    target.write_bytes(b"kopie")
    fake_qfile.result = (False, "")
    assert move_to_trash(target) is False
    assert target.read_bytes() == b"kopie"


def test_tests_never_reach_the_real_trash() -> None:
    """Die globale Attrappe lehnt ab – der echte Papierkorb bleibt unberührt."""
    assert _trash.move_to_trash is not move_to_trash
    assert _trash.move_to_trash(Path("egal.db")) is False
