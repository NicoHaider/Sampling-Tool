"""Tests für den Resource-Resolver (Dev + PyInstaller-Bundle)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from sampling_tool.resources import is_frozen, package_resource, shared_resource


class TestIsFrozen:
    def test_returns_false_in_dev(self) -> None:
        assert is_frozen() is False


class TestPackageResourceInDev:
    def test_qss_exists(self) -> None:
        path = package_resource("ui/styles/bdo_light.qss")
        assert path.exists(), f"Stylesheet sollte in Dev existieren: {path}"

    def test_migrations_dir_exists(self) -> None:
        path = package_resource("persistence/migrations")
        assert path.is_dir(), f"Migrations-Ordner sollte existieren: {path}"

    def test_returns_path_inside_package(self) -> None:
        path = package_resource("ui/styles/bdo_light.qss")
        assert path.parent.parent.parent.name == "sampling_tool"


class TestSharedResourceInDev:
    def test_briefpapier_exists(self) -> None:
        path = shared_resource("briefpapier/bdo_placeholder.pdf")
        assert path.exists(), f"Briefpapier sollte in Dev existieren: {path}"

    def test_template_exists(self) -> None:
        path = shared_resource("templates/audit_report.html")
        assert path.exists(), f"HTML-Template sollte in Dev existieren: {path}"

    def test_returns_path_in_project_resources(self) -> None:
        path = shared_resource("briefpapier/bdo_placeholder.pdf")
        assert path.parent.parent.name == "resources"


class TestFrozenResolution:
    def test_package_resource_uses_meipass_when_frozen(self, tmp_path: Path) -> None:
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", str(tmp_path), create=True),
        ):
            qss_dir = tmp_path / "sampling_tool" / "ui" / "styles"
            qss_dir.mkdir(parents=True)
            expected = qss_dir / "bdo_light.qss"
            expected.write_text("/* test */", encoding="utf-8")

            result = package_resource("ui/styles/bdo_light.qss")
            assert result == expected
            assert result.read_text(encoding="utf-8") == "/* test */"

    def test_shared_resource_uses_meipass_when_frozen(self, tmp_path: Path) -> None:
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", str(tmp_path), create=True),
        ):
            bp_dir = tmp_path / "resources" / "briefpapier"
            bp_dir.mkdir(parents=True)
            expected = bp_dir / "bdo_placeholder.pdf"
            expected.write_bytes(b"%PDF-1.4 stub")

            result = shared_resource("briefpapier/bdo_placeholder.pdf")
            assert result == expected
            assert result.read_bytes().startswith(b"%PDF")

    def test_is_frozen_true_only_when_both_attrs_set(self, tmp_path: Path) -> None:
        with patch.object(sys, "frozen", True, create=True):
            if hasattr(sys, "_MEIPASS"):
                pytest.skip("running unter PyInstaller, sys._MEIPASS bereits gesetzt")
            assert is_frozen() is False

        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", str(tmp_path), create=True),
        ):
            assert is_frozen() is True
