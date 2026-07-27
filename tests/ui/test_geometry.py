"""_geometry – reine Fenstergeometrie-Berechnungen (Sprint 67 / Teil A).

Pure Funktionen (keine Qt-Screen-Abhängigkeit) – lässt sich unabhängig vom
offscreen-Fixed-Screen aus `conftest.py` mit synthetischen Rects testen.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QRect, QSize

from sampling_tool.ui._geometry import fit_to_available, is_geometry_visible

pytestmark = pytest.mark.unit


class TestFitToAvailable:
    def test_desired_smaller_than_available_stays_unchanged(self) -> None:
        available = QRect(0, 0, 1920, 1080)
        result = fit_to_available(QSize(800, 600), available)
        assert result.size() == QSize(800, 600)

    def test_desired_larger_than_available_is_clamped(self) -> None:
        """Kernfall: 1280×800 auf 1280×720 verfügbar → Höhe wird reduziert."""
        available = QRect(0, 0, 1280, 720)
        result = fit_to_available(QSize(1280, 800), available)
        assert result.height() < 800
        assert available.contains(result)

    def test_result_is_centered(self) -> None:
        available = QRect(100, 50, 1920, 1080)
        result = fit_to_available(QSize(1280, 800), available)
        assert result.x() == 100 + (1920 - 1280) // 2
        assert result.y() == 50 + (1080 - 800) // 2

    def test_result_always_within_available(self) -> None:
        available = QRect(0, 0, 1024, 600)
        result = fit_to_available(QSize(1280, 800), available)
        assert available.contains(result)

    def test_result_never_smaller_than_one_pixel(self) -> None:
        available = QRect(0, 0, 10, 10)
        result = fit_to_available(QSize(1280, 800), available)
        assert result.width() >= 1
        assert result.height() >= 1


class TestIsGeometryVisible:
    def test_fully_on_screen_is_visible(self) -> None:
        screens = [QRect(0, 0, 1920, 1080)]
        saved = QRect(100, 100, 800, 600)
        assert is_geometry_visible(saved, screens) is True

    def test_fully_outside_all_screens_is_not_visible(self) -> None:
        screens = [QRect(0, 0, 1920, 1080)]
        saved = QRect(5000, 5000, 800, 600)
        assert is_geometry_visible(saved, screens) is False

    def test_mostly_overlapping_is_visible(self) -> None:
        """90% der Fläche liegt noch auf dem Screen → sichtbar."""
        screens = [QRect(0, 0, 1920, 1080)]
        saved = QRect(1200, 100, 800, 600)
        assert is_geometry_visible(saved, screens) is True

    def test_barely_overlapping_is_not_visible(self) -> None:
        """Nur eine winzige Ecke ragt noch auf den Screen → nicht sichtbar."""
        screens = [QRect(0, 0, 1920, 1080)]
        saved = QRect(1870, 100, 800, 600)
        assert is_geometry_visible(saved, screens) is False

    def test_visible_across_multiple_screens(self) -> None:
        screens = [QRect(0, 0, 1920, 1080), QRect(1920, 0, 1920, 1080)]
        saved = QRect(1800, 100, 800, 600)
        assert is_geometry_visible(saved, screens) is True

    def test_zero_size_geometry_is_not_visible(self) -> None:
        screens = [QRect(0, 0, 1920, 1080)]
        saved = QRect(100, 100, 0, 0)
        assert is_geometry_visible(saved, screens) is False
