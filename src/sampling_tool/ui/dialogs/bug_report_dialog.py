"""Bug-Report-Dialog – konstruiert eine `mailto:`-URL.

Auf Windows wird das in Sprint 7 via `pywin32` durch Outlook-COM ersetzt.
Für Sprint 5 reicht der plattformübergreifende `mailto:`-Pfad: das System
öffnet die Default-Mail-App mit vorbefüllten Feldern.
"""

from __future__ import annotations

import platform
import urllib.parse
from dataclasses import dataclass

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from sampling_tool import __version__
from sampling_tool.config import APP_NAME, BUG_REPORT_EMAIL, BUG_REPORT_SUBJECT_PREFIX


@dataclass(frozen=True, slots=True)
class BugReportPayload:
    """Inhalt des Bug-Reports – wird in der `mailto:`-URL kodiert."""

    what_did_you_do: str
    what_did_you_expect: str
    what_happened_instead: str
    include_system_info: bool

    def subject(self) -> str:
        return f"{BUG_REPORT_SUBJECT_PREFIX} {APP_NAME} v{__version__}"

    def body(self) -> str:
        sections = [
            ("Was hast du gemacht?", self.what_did_you_do),
            ("Was hast du erwartet?", self.what_did_you_expect),
            ("Was ist stattdessen passiert?", self.what_happened_instead),
        ]
        text = "\n\n".join(f"## {head}\n{content.strip() or '—'}" for head, content in sections)
        if self.include_system_info:
            text += (
                f"\n\n---\nApp-Version: {__version__}\n"
                f"OS: {platform.system()} {platform.release()}\n"
                f"Python: {platform.python_version()}"
            )
        return text

    def mailto_url(self) -> str:
        params = urllib.parse.urlencode(
            {"subject": self.subject(), "body": self.body()},
            quote_via=urllib.parse.quote,
        )
        return f"mailto:{BUG_REPORT_EMAIL}?{params}"


class BugReportDialog(QDialog):
    """Drei Freitextfelder + Checkbox „System-Info mitschicken"."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bug melden")
        self.setModal(True)
        self.setMinimumWidth(540)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(10)

        intro = QLabel(
            'Bitte beschreibe den Bug. Beim Klick auf „E-Mail vorbereiten" '
            "wird die System-Mail-App mit vorausgefüllten Feldern geöffnet."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #7F7F7F;")
        outer.addWidget(intro)

        self._did = _make_field("Was hast du gemacht?", outer)
        self._expected = _make_field("Was hast du erwartet?", outer)
        self._actual = _make_field("Was ist stattdessen passiert?", outer)

        self._include_system_info = QCheckBox("App-Version und OS mitschicken")
        self._include_system_info.setChecked(True)
        outer.addWidget(self._include_system_info)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._send_button = self._buttons.addButton(
            "E-Mail vorbereiten", QDialogButtonBox.ButtonRole.AcceptRole
        )
        outer.addWidget(self._buttons)

        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)

    # ---- Public API -----------------------------------------------------

    def get_payload(self) -> BugReportPayload:
        return BugReportPayload(
            what_did_you_do=self._did.toPlainText(),
            what_did_you_expect=self._expected.toPlainText(),
            what_happened_instead=self._actual.toPlainText(),
            include_system_info=self._include_system_info.isChecked(),
        )

    # ---- intern --------------------------------------------------------

    def _on_accept(self) -> None:
        payload = self.get_payload()
        QDesktopServices.openUrl(QUrl(payload.mailto_url()))
        self.accept()


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _make_field(label: str, layout: QVBoxLayout) -> QPlainTextEdit:
    caption = QLabel(label)
    caption.setStyleSheet("color: #555555; font-weight: 600;")
    layout.addWidget(caption)
    edit = QPlainTextEdit()
    edit.setFixedHeight(70)
    layout.addWidget(edit)
    return edit
