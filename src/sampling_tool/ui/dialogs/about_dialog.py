"""About-Dialog – statische Versions- und Projektinfos."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from sampling_tool import __version__
from sampling_tool.config import APP_NAME

REPO_URL: str = "https://github.com/NicoHaider/Sampling-Tool"


class AboutDialog(QDialog):
    """Über-Dialog mit Version, Beschreibung und Repo-Link."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Über {APP_NAME}")
        self.setModal(True)
        self.setMinimumWidth(480)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(16)

        logo = QLabel("BDO")
        logo.setObjectName("LogoPlaceholder")
        head.addWidget(logo, alignment=Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        title = QLabel(APP_NAME)
        title.setStyleSheet("font-size: 22px; font-weight: 800; color: #E81A3B;")
        version = QLabel(f"Version {__version__}")
        version.setStyleSheet("color: #7F7F7F;")
        description = QLabel(
            "Reproduzierbare Stichproben für Prüfungshandlungen – "
            "konform mit ISAE 3402.\n\n"
            "Entwickelt von Nico Haider mit Claude (Anthropic)."
        )
        description.setWordWrap(True)
        text.addWidget(title)
        text.addWidget(version)
        text.addSpacing(4)
        text.addWidget(description)
        text.addStretch(1)
        head.addLayout(text, stretch=1)

        outer.addLayout(head)

        self._repo_label = QLabel(f'<a href="{REPO_URL}">{REPO_URL}</a>')
        self._repo_label.setOpenExternalLinks(False)
        self._repo_label.linkActivated.connect(self._open_repo)
        outer.addWidget(self._repo_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        outer.addWidget(buttons)

    # ---- intern --------------------------------------------------------

    def _open_repo(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))
