"""Tests für `briefpapier`: Default-Discovery + apply auf reportlab-Canvas."""

from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from sampling_tool.io import briefpapier as bp
from sampling_tool.io.briefpapier import (
    BriefpapierConfig,
    apply_briefpapier_to_pdf,
    briefpapier_from_path,
    get_default_briefpapier,
)

pytestmark = pytest.mark.integration


def _make_png(path: Path) -> Path:
    """Schreibt ein winziges, gültiges 1×1-PNG für die Tests."""
    payload = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
        b"\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x03\x05\x00\x01\x01\x00"
        b"\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    path.write_bytes(payload)
    return path


class TestBriefpapierConfig:
    def test_is_active_false_when_no_image(self) -> None:
        cfg = BriefpapierConfig(background_image=None)
        assert cfg.is_active() is False

    def test_is_active_true_for_existing_image(self, tmp_path: Path) -> None:
        png = _make_png(tmp_path / "letter.png")
        cfg = BriefpapierConfig(background_image=png)
        assert cfg.is_active() is True

    def test_is_active_false_for_missing_image(self, tmp_path: Path) -> None:
        missing = tmp_path / "ghost.png"
        cfg = BriefpapierConfig(background_image=missing)
        assert cfg.is_active() is False

    def test_default_margins(self) -> None:
        cfg = BriefpapierConfig(background_image=None)
        assert cfg.margin_top_mm == 25.0
        assert cfg.margin_left_mm == 20.0


class TestGetDefaultBriefpapier:
    def test_returns_none_when_nothing_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(bp, "BRIEFPAPIER_DIR", tmp_path / "empty")
        monkeypatch.setattr(bp, "DEFAULT_BRIEFPAPIER", tmp_path / "no-placeholder.pdf")
        assert get_default_briefpapier() is None

    def test_finds_png_in_user_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        _make_png(user_dir / "bdo_letterhead.png")
        monkeypatch.setattr(bp, "BRIEFPAPIER_DIR", user_dir)
        monkeypatch.setattr(bp, "DEFAULT_BRIEFPAPIER", tmp_path / "missing.pdf")

        cfg = get_default_briefpapier()
        assert cfg is not None
        assert cfg.background_image is not None
        assert cfg.background_image.name == "bdo_letterhead.png"

    def test_user_dir_overrides_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        _make_png(user_dir / "bdo_letterhead.png")

        default_pdf = tmp_path / "placeholder.pdf"
        default_pdf.write_bytes(b"%PDF-1.4\n%\xc4\xe5\xf2\xe5\xeb\xa7\xf3\xa0\xd0\xc4\xc6\n")

        monkeypatch.setattr(bp, "BRIEFPAPIER_DIR", user_dir)
        monkeypatch.setattr(bp, "DEFAULT_BRIEFPAPIER", default_pdf)

        cfg = get_default_briefpapier()
        assert cfg is not None
        assert cfg.background_image is not None
        assert cfg.background_image.parent == user_dir

    def test_falls_back_to_default_placeholder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        default_pdf = tmp_path / "bdo_placeholder.pdf"
        default_pdf.write_bytes(b"%PDF-1.4\n%\xc4\xe5\xf2\xe5\xeb\xa7\xf3\xa0\xd0\xc4\xc6\n")
        monkeypatch.setattr(bp, "BRIEFPAPIER_DIR", tmp_path / "no-user")
        monkeypatch.setattr(bp, "DEFAULT_BRIEFPAPIER", default_pdf)

        cfg = get_default_briefpapier()
        assert cfg is not None
        assert cfg.background_image == default_pdf


class TestBriefpapierFromPath:
    def test_valid_png(self, tmp_path: Path) -> None:
        png = _make_png(tmp_path / "letter.png")
        cfg = briefpapier_from_path(png)
        assert cfg.background_image == png

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            briefpapier_from_path(tmp_path / "ghost.png")

    def test_unsupported_suffix_raises(self, tmp_path: Path) -> None:
        weird = tmp_path / "letter.txt"
        weird.write_text("nope")
        with pytest.raises(ValueError, match="nicht unterstützt"):
            briefpapier_from_path(weird)


class TestApplyBriefpapierToPdf:
    def test_apply_on_canvas_does_not_raise(self, tmp_path: Path) -> None:
        png = _make_png(tmp_path / "letter.png")
        out = tmp_path / "out.pdf"
        canvas = Canvas(str(out), pagesize=A4)
        cfg = BriefpapierConfig(background_image=png)

        apply_briefpapier_to_pdf(canvas, cfg)
        canvas.showPage()
        canvas.save()

        assert out.exists()
        assert out.stat().st_size > 0

    def test_apply_with_inactive_config_is_noop(self, tmp_path: Path) -> None:
        out = tmp_path / "noop.pdf"
        canvas = Canvas(str(out), pagesize=A4)
        cfg = BriefpapierConfig(background_image=None)
        apply_briefpapier_to_pdf(canvas, cfg)  # darf nicht crashen
        canvas.showPage()
        canvas.save()
        assert out.exists()
