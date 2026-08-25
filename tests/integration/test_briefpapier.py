"""Tests für `briefpapier`: Default-Discovery + Validierung."""

from __future__ import annotations

from pathlib import Path

import pytest

from sampling_tool.io import briefpapier as bp
from sampling_tool.io.briefpapier import (
    BriefpapierConfig,
    BriefpapierError,
    briefpapier_from_path,
    get_default_briefpapier,
    validate_briefpapier,
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


class TestValidateBriefpapier:
    """Sprint 47 / N-010: Fail-Fast-Validierung bei der Briefpapier-Auswahl."""

    def test_accepts_valid_png(self, tmp_path: Path) -> None:
        png = _make_png(tmp_path / "letter.png")
        validate_briefpapier(png)  # darf nicht werfen

    def test_rejects_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            validate_briefpapier(tmp_path / "ghost.png")

    def test_rejects_unsupported_suffix(self, tmp_path: Path) -> None:
        weird = tmp_path / "letter.txt"
        weird.write_text("nope")
        with pytest.raises(ValueError, match="nicht unterstützt"):
            validate_briefpapier(weird)

    def test_validate_briefpapier_rejects_corrupt_pdf(self, tmp_path: Path) -> None:
        corrupt = tmp_path / "corrupt.pdf"
        corrupt.write_bytes(b"%PDF-1.4\nnot a real xref table, just garbage\n")
        with pytest.raises(BriefpapierError):
            validate_briefpapier(corrupt)

    def test_rejects_corrupt_image(self, tmp_path: Path) -> None:
        corrupt = tmp_path / "corrupt.png"
        corrupt.write_bytes(b"this is not a real png file at all")
        with pytest.raises(BriefpapierError):
            validate_briefpapier(corrupt)

    def test_validate_briefpapier_rejects_oversized_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        png = _make_png(tmp_path / "letter.png")
        monkeypatch.setattr(bp, "BRIEFPAPIER_MAX_BYTES", 10)
        with pytest.raises(BriefpapierError, match="zu groß"):
            validate_briefpapier(png)

    def test_rejects_oversized_image_without_fully_decoding(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Die Pixel-Obergrenze muss VOR dem vollen Decode (`img.load()`)
        greifen – sonst schützt sie nicht vor dem teuren Decode selbst
        (Decompression-Bomb-artiges Verhalten)."""
        from PIL import Image, ImageFile

        big = tmp_path / "huge.png"
        img = Image.new("RGB", (10, 10), color=(1, 2, 3))
        img.save(big, format="PNG")
        monkeypatch.setattr(bp, "BRIEFPAPIER_MAX_IMAGE_PIXELS", 50)  # 10x10=100 > 50

        def _boom(self: object, *a: object, **k: object) -> None:
            raise AssertionError("img.load() darf für ein zu großes Bild nicht laufen")

        monkeypatch.setattr(ImageFile.ImageFile, "load", _boom)

        with pytest.raises(BriefpapierError, match="zu groß"):
            validate_briefpapier(big)
