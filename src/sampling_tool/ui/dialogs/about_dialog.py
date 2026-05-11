"""About-Dialog – statische Versions- und Projektinfos."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from sampling_tool import __version__
from sampling_tool.config import APP_NAME

REPO_URL: str = "https://github.com/NicoHaider/Sampling-Tool"

CHANGELOG: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "v0.6.0",
        (
            "Dashboard mit Statistik-Kacheln und Mini-Charts (matplotlib)",
            "AuditTrail-View im UI mit Filter (Aktion / User / Zeitraum)",
            "Multi-Sheet Excel-Report (Übersicht, AuditTrail, Samples, Statistiken)",
            "Selbstständiger HTML-Report mit Base64-Charts für E-Mail-Versand",
            "Briefpapier-Template-System (Default + Resource-Fallback)",
            "Splitter-Layout: Tabelle oben, AuditTrail/Dashboard unten in Tabs",
            "Empty-States in Tabelle, AuditTrail, Dashboard und Sidebar",
        ),
    ),
    (
        "v0.5.6",
        (
            "Grüne Sample-Markierung in der Tabelle",
            'Filter-Default für "Nur markierte Zeilen anzeigen"',
            "Engagement-Wechsel-Button in der Toolbar",
        ),
    ),
    (
        "v0.5.5",
        (
            "Engagement-Auto-Versionierung beim Öffnen (archiv/)",
            "UX-Bugfixes rund um Filter, Highlight und Statusbar",
        ),
    ),
    (
        "v0.5.0",
        (
            "Sampling-Dialog (Simple / Cluster / Stratified) inkl. Resample",
            "Excel-Export mit Spaltenauswahl, AuditTrail-PDF",
            "Undo / Redo mit persistiertem Stack",
            "Bug-Report-Dialog + About-Dialog",
        ),
    ),
)


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

        # Changelog-Block – Trenner + Liste der letzten Releases.
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color: #D9D9D9;")
        outer.addWidget(divider)

        changelog_title = QLabel("Was gibt es Neues")
        changelog_title.setStyleSheet(
            "font-weight: 700; color: #333333; font-size: 13px; padding-top: 4px;"
        )
        outer.addWidget(changelog_title)

        for changelog_version, items in CHANGELOG[:3]:
            version_label = QLabel(changelog_version)
            version_label.setStyleSheet("font-weight: 700; color: #E81A3B; padding-top: 6px;")
            outer.addWidget(version_label)
            bullets = QLabel("\n".join(f"• {entry}" for entry in items))
            bullets.setWordWrap(True)
            bullets.setStyleSheet("color: #333333; padding-left: 6px;")
            outer.addWidget(bullets)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        outer.addWidget(buttons)

    # ---- intern --------------------------------------------------------

    def _open_repo(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))
