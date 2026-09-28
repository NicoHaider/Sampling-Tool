"""Sprint 89 / D4: Info-Meldungen zeigen unter macOS ein „i", kein Ausrufezeichen."""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QApplication, QMessageBox, QStyle
from pytestqt.qtbot import QtBot

from sampling_tool.config import BDO_GREY
from sampling_tool.ui._info_icon import InfoIconStyle, info_icon, install_info_icon

pytestmark = pytest.mark.ui


def _image(icon_pixmap: QPixmap) -> QImage:
    return icon_pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)


class TestInfoIconStyle:
    def test_information_icon_is_replaced(self, qtbot: QtBot) -> None:
        style = InfoIconStyle("Fusion")
        icon = style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
        assert _image(icon.pixmap(64, 64)) == _image(info_icon().pixmap(64, 64))

    def test_warning_stays_the_system_icon(self, qtbot: QtBot) -> None:
        style = InfoIconStyle("Fusion")
        warning = style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        assert _image(warning.pixmap(64, 64)) != _image(info_icon().pixmap(64, 64))

    def test_message_box_uses_it(self, qtbot: QtBot) -> None:
        box = QMessageBox()
        qtbot.addWidget(box)
        box.setStyle(InfoIconStyle("Fusion"))
        box.setIcon(QMessageBox.Icon.Information)
        image = _image(box.iconPixmap())
        # Grauer Kreis, weißer Balken des „i" in der Mitte, grau daneben.
        w, h = image.width(), image.height()
        assert image.pixelColor(w // 2, int(h * 0.9)).name() == BDO_GREY.lower()
        assert image.pixelColor(w // 2, int(h * 0.6)).name() == "#ffffff"
        assert image.pixelColor(int(w * 0.3), int(h * 0.6)).name() == BDO_GREY.lower()


class TestInstall:
    def test_only_on_macos(self) -> None:
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        assert install_info_icon(app, platform="win32") is False
        assert install_info_icon(app, platform="linux") is False
