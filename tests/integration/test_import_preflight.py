"""Tests für `import_preflight`: billiger Main-Thread-Preflight (Sprint 48 / S2.3b, S-003)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from sampling_tool.io import import_preflight
from sampling_tool.io.import_preflight import ImportPreflight, preflight_import

pytestmark = pytest.mark.integration


class TestPreflightImport:
    def test_legit_import_is_byte_identical(self, simple_xlsx: Path, utf8_csv: Path) -> None:
        """Reale Defaults dürfen die bestehenden Fixtures nie flaggen –
        sonst würde ein legitimer Import unerwartet einen Confirm-Dialog
        auslösen (Regression ggü. Vor-Sprint-48-Verhalten)."""
        xlsx_result = preflight_import(simple_xlsx)
        csv_result = preflight_import(utf8_csv)

        assert xlsx_result == ImportPreflight()
        assert csv_result == ImportPreflight()

    def test_import_rejects_non_regular_file(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "a_directory"
        target_dir.mkdir()
        alias = tmp_path / "not_a_file.xlsx"
        alias.symlink_to(target_dir)

        result = preflight_import(alias)

        assert result.rejected
        assert result.reject_reason is not None
        assert "reguläre Datei" in result.reject_reason

    def test_import_rejects_missing_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.xlsx"

        result = preflight_import(missing)

        assert result.rejected
        assert result.reject_reason is not None

    def test_import_rejects_file_without_zip_signature(self, tmp_path: Path) -> None:
        fake = tmp_path / "fake.xlsx"
        fake.write_text("this is not an excel file", encoding="utf-8")

        result = preflight_import(fake)

        assert result.rejected
        assert result.reject_reason is not None
        assert "Signatur" in result.reject_reason

    def test_import_rejects_bad_signature_without_invoking_calamine(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail-fast: eine Datei ohne ZIP-Signatur darf calamine nie erreichen."""
        fake = tmp_path / "fake.xlsx"
        fake.write_text("not excel", encoding="utf-8")

        def _boom(*_a: object, **_k: object) -> None:
            raise AssertionError("calamine darf ohne gültige ZIP-Signatur nicht aufgerufen werden")

        monkeypatch.setattr(import_preflight.CalamineWorkbook, "from_path", staticmethod(_boom))

        result = preflight_import(fake)

        assert result.rejected

    def test_import_rejects_corrupt_zip_container(self, tmp_path: Path) -> None:
        corrupt = tmp_path / "corrupt.xlsx"
        corrupt.write_bytes(b"PK\x03\x04" + b"not a real central directory, just garbage bytes")

        result = preflight_import(corrupt)

        assert result.rejected
        assert result.reject_reason is not None
        assert "ZIP-Archiv" in result.reject_reason

    def test_import_rejects_oversize_file(
        self, simple_xlsx: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(import_preflight, "MAX_IMPORT_FILE_SIZE_BYTES", 10)

        result = preflight_import(simple_xlsx)

        assert result.rejected
        assert result.reject_reason is not None
        assert "groß" in result.reject_reason

    def test_preflight_warns_but_allows_large_legit_file(
        self, simple_xlsx: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(import_preflight, "WARN_IMPORT_FILE_SIZE_BYTES", 10)

        result = preflight_import(simple_xlsx)

        assert not result.rejected
        assert result.warnings
        assert any("groß" in w for w in result.warnings)

    def test_import_rejects_too_many_zip_members(
        self, simple_xlsx: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(import_preflight, "MAX_ZIP_MEMBERS", 1)

        result = preflight_import(simple_xlsx)

        assert result.rejected
        assert result.reject_reason is not None
        assert "Einträge" in result.reject_reason

    def test_import_rejects_zip_bomb_ratio(self, tmp_path: Path) -> None:
        """Kern-Regression: winziges Archiv, absurdes Kompressionsverhältnis
        (viel komprimierbarer Nullpadding) → Reject unter den ECHTEN
        Default-Grenzen, calamine wird nie aufgerufen."""
        bomb = tmp_path / "bomb.xlsx"
        with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("xl/worksheets/sheet1.xml", b"\x00" * 5_000_000)

        result = preflight_import(bomb)

        assert result.rejected
        assert result.reject_reason is not None
        assert "Kompressionsverhältnis" in result.reject_reason

    def test_import_rejects_too_many_columns(
        self, simple_xlsx: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(import_preflight, "MAX_IMPORT_COLUMNS", 1)

        result = preflight_import(simple_xlsx)

        assert result.rejected
        assert result.reject_reason is not None
        assert "Spalten" in result.reject_reason

    def test_import_warns_on_row_count_over_threshold(
        self, simple_xlsx: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(import_preflight, "WARN_IMPORT_ROWS", 1)

        result = preflight_import(simple_xlsx)

        assert not result.rejected
        assert any("Zeilen" in w for w in result.warnings)

    def test_csv_skips_zip_checks(self, utf8_csv: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """CSV hat keinen ZIP-Container – ein absurd niedriges ZIP-Limit darf
        eine CSV-Datei nicht treffen."""
        monkeypatch.setattr(import_preflight, "MAX_ZIP_MEMBERS", 0)

        result = preflight_import(utf8_csv)

        assert not result.rejected
