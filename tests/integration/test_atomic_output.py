"""Integration: `atomic_output` – gemeinsamer atomarer Schreibpfad (S2.5 / A-004)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sampling_tool.io._atomic import AtomicReplaceError, atomic_output

pytestmark = pytest.mark.integration


class TestAtomicOutput:
    def test_atomic_output_replaces_on_success(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        with atomic_output(target) as tmp:
            assert tmp.parent == tmp_path
            assert not target.exists()  # tmp existiert, Ziel noch nicht
            tmp.write_text("hallo", encoding="utf-8")
        assert target.read_text(encoding="utf-8") == "hallo"
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == [], f"Kein .tmp-Rest erwartet, gefunden: {leftovers}"

    def test_atomic_output_cleans_up_on_write_error(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"

        def _write_partial_then_crash() -> None:
            with atomic_output(target) as tmp:
                tmp.write_text("teilweise", encoding="utf-8")
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            _write_partial_then_crash()
        assert not target.exists()
        assert list(tmp_path.iterdir()) == []

    def test_atomic_output_cleans_up_on_replace_error(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        with (
            patch(
                "sampling_tool.io._atomic.os.replace",
                side_effect=PermissionError("target locked"),
            ),
            pytest.raises(AtomicReplaceError),
            atomic_output(target) as tmp,
        ):
            tmp.write_text("hallo", encoding="utf-8")
        assert not target.exists()
        assert list(tmp_path.iterdir()) == []

    def test_atomic_output_tmp_name_is_unpredictable(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        captured: list[Path] = []
        with atomic_output(target) as tmp:
            captured.append(tmp)
            tmp.write_text("x", encoding="utf-8")
        naive_predictable = target.with_suffix(target.suffix + ".tmp")
        assert captured[0] != naive_predictable
        assert captured[0].name != target.name + ".tmp"

    def test_atomic_output_creates_missing_target_dir(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "sub" / "out.txt"
        with atomic_output(target) as tmp:
            tmp.write_text("x", encoding="utf-8")
        assert target.read_text(encoding="utf-8") == "x"
