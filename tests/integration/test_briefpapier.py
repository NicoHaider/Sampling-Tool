"""Tests für `briefpapier`: Default-Discovery + Validierung."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

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


def _make_corrupt_png(path: Path) -> Path:
    path.write_bytes(b"this is not a real png file at all")
    return path


def _make_corrupt_pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.4\nnot a real xref table, just garbage\n")
    return path


def _make_valid_pdf(path: Path) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen.canvas import Canvas

    canvas = Canvas(str(path), pagesize=A4)
    canvas.drawString(100, 700, "Briefpapier")
    canvas.save()
    return path


class TestMissingDecoderFailsLoud:
    """Sprint 95: fehlt Pillow oder pypdf, schlägt die Prüfung fehl statt still zu passen.

    `sys.modules[name] = None` lässt den lazy Import im Validator mit
    `ImportError` scheitern – genau der Zustand eines Pakets, dem das Modul fehlt.
    """

    def test_image_validation_raises_without_pillow(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        corrupt = _make_corrupt_png(tmp_path / "corrupt.png")
        monkeypatch.setitem(sys.modules, "PIL", None)
        with pytest.raises(BriefpapierError, match="Pillow"):
            validate_briefpapier(corrupt)

    def test_pdf_validation_raises_without_pypdf(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        corrupt = _make_corrupt_pdf(tmp_path / "corrupt.pdf")
        monkeypatch.setitem(sys.modules, "pypdf", None)
        with pytest.raises(BriefpapierError, match="pypdf"):
            validate_briefpapier(corrupt)

    def test_error_is_logged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        png = _make_png(tmp_path / "letter.png")
        monkeypatch.setitem(sys.modules, "PIL", None)
        with (
            caplog.at_level(logging.ERROR, logger="sampling_tool.io.briefpapier"),
            pytest.raises(BriefpapierError),
        ):
            validate_briefpapier(png)
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert any("Pillow" in r.getMessage() for r in errors), [r.getMessage() for r in errors]
        assert all(r.exc_info is not None for r in errors)

    @pytest.mark.ui
    def test_settings_dialog_rejects_when_decoder_missing(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from PyQt6.QtWidgets import QMessageBox

        from sampling_tool.ui.dialogs.settings_dialog import SettingsDialog
        from sampling_tool.ui.settings_store import AppSettings

        dialog = SettingsDialog(AppSettings.defaults())
        qtbot.addWidget(dialog)
        png = _make_png(tmp_path / "letter.png")
        monkeypatch.setattr(
            "sampling_tool.ui.dialogs.settings_dialog.QFileDialog.getOpenFileName",
            lambda *a, **k: (str(png), ""),
        )
        warnings: list[tuple[str, str]] = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda _self, title, text, *a, **k: warnings.append((title, text)),
        )
        monkeypatch.setitem(sys.modules, "PIL", None)

        dialog._on_browse_briefpapier()

        assert dialog._custom_briefpapier.text() == ""
        assert dialog._radio_custom.isChecked() is False
        assert len(warnings) == 1
        title, text = warnings[0]
        assert title == "Ungültiges Briefpapier"
        assert "Pillow" in text

    @pytest.mark.ui
    def test_resolve_falls_back_to_default_when_decoder_missing(
        self,
        qtbot: QtBot,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from dataclasses import replace

        from sampling_tool.ui.controllers.workspace_session import WorkspaceSession
        from sampling_tool.ui.main_window import MainWindow
        from sampling_tool.ui.recent import RecentEngagementsStore
        from sampling_tool.ui.settings_store import AppSettings

        window = MainWindow()
        qtbot.addWidget(window)
        png = _make_png(tmp_path / "letter.png")
        settings = replace(AppSettings.defaults(), custom_briefpapier_path=png)
        session = WorkspaceSession(
            window, settings, RecentEngagementsStore(path=tmp_path / "recent.json")
        )
        default = bp.BriefpapierConfig(background_image=tmp_path / "default.pdf")
        monkeypatch.setattr(
            "sampling_tool.ui.controllers.workspace_session.get_default_briefpapier",
            lambda: default,
        )
        monkeypatch.setitem(sys.modules, "PIL", None)

        with caplog.at_level(
            logging.WARNING, logger="sampling_tool.ui.controllers.workspace_session"
        ):
            cfg = session.resolve_briefpapier()

        assert cfg is default
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("ungültig" in r.getMessage() for r in warnings), [
            r.getMessage() for r in warnings
        ]


class TestValidBriefpapierUnchanged:
    """Sprint 95, rote Linie: ein gültiges Briefpapier verhält sich wie vorher."""

    def test_valid_png_jpg_pdf_still_accepted(self, tmp_path: Path) -> None:
        from PIL import Image

        png = _make_png(tmp_path / "letter.png")
        jpg = tmp_path / "letter.jpg"
        Image.new("RGB", (4, 4), color=(200, 0, 0)).save(jpg, format="JPEG")
        pdf = _make_valid_pdf(tmp_path / "letter.pdf")
        for path in (png, jpg, pdf):
            validate_briefpapier(path)  # darf nicht werfen

    def test_pixel_cap_still_enforced(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from PIL import Image

        big = tmp_path / "huge.png"
        Image.new("RGB", (10, 10)).save(big, format="PNG")
        monkeypatch.setattr(bp, "BRIEFPAPIER_MAX_IMAGE_PIXELS", 50)
        with pytest.raises(BriefpapierError, match="zu groß"):
            validate_briefpapier(big)
