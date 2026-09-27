"""Deutsche Qt-Standardbuttons (Sprint 85 / A).

Qt beschriftet Standardbuttons (`QMessageBox`, `QDialogButtonBox`,
`QFileDialog`, `QWizard`) selbst – ohne geladene Übersetzung englisch
(„Yes/No/Cancel"). Die Zielgruppe (Prüfer ohne Technik-Hintergrund) soll keine
englischen Knöpfe sehen; `install_german_qt_translation` lädt `qtbase_de` beim
Start, bevor der erste Dialog (die Erst-Einrichtung) erscheint.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox

from sampling_tool.ui import _translation
from sampling_tool.ui._translation import install_german_qt_translation


@pytest.fixture
def german(qapp: QApplication) -> Iterator[bool]:
    """Installiert die Übersetzung nur für diesen Test – andere Tests sehen Qt-Englisch."""
    loaded = install_german_qt_translation(qapp)
    yield loaded
    _translation.uninstall_qt_translation(qapp)


def _plain(text: str) -> str:
    return text.replace("&", "")


class TestGermanStandardButtons:
    def test_message_box_yes_no_are_german(self, german: bool) -> None:
        assert german is True
        box = QMessageBox()
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        yes = box.button(QMessageBox.StandardButton.Yes)
        no = box.button(QMessageBox.StandardButton.No)
        assert yes is not None
        assert no is not None
        assert _plain(yes.text()) == "Ja"
        assert _plain(no.text()) == "Nein"

    def test_button_box_cancel_close_are_german(self, german: bool) -> None:
        assert german is True
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Close
        )
        cancel = box.button(QDialogButtonBox.StandardButton.Cancel)
        close = box.button(QDialogButtonBox.StandardButton.Close)
        assert cancel is not None
        assert close is not None
        assert _plain(cancel.text()) == "Abbrechen"
        assert _plain(close.text()) == "Schließen"

    def test_uninstall_restores_qt_default(self, qapp: QApplication) -> None:
        """Gegenprobe: ohne Übersetzung beschriftet Qt englisch – der Test oben
        prüft also wirklich die Übersetzung, nicht einen Zufall der Plattform."""
        install_german_qt_translation(qapp)
        _translation.uninstall_qt_translation(qapp)
        assert QCoreApplication.translate("QPlatformTheme", "Cancel") == "Cancel"


class TestMissingTranslationStillStarts:
    def test_missing_file_returns_false_and_logs(
        self,
        qapp: QApplication,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(_translation, "_candidate_dirs", lambda: [tmp_path])
        with caplog.at_level(logging.WARNING, logger=_translation.__name__):
            loaded = install_german_qt_translation(qapp)
        _translation.uninstall_qt_translation(qapp)

        assert loaded is False
        assert "qtbase_de" in caplog.text
        assert QCoreApplication.translate("QPlatformTheme", "Cancel") == "Cancel"


class TestInstalledBeforeFirstDialog:
    """In `main()` muss die Übersetzung VOR der Erst-Einrichtung stehen – sonst
    zeigt genau der erste Dialog eines neuen Anwenders englische Knöpfe."""

    def test_translation_precedes_first_run_wizard(self) -> None:
        import sampling_tool.__main__ as entry

        lines = [
            line.strip()
            for line in inspect.getsource(entry.main).splitlines()
            if not line.strip().startswith("#")
        ]

        def index_of(needle: str) -> int:
            return next(i for i, line in enumerate(lines) if needle in line)

        assert index_of("install_german_qt_translation(") < index_of("run_first_run_wizard(")
        assert index_of("QApplication(sys.argv)") < index_of("install_german_qt_translation(")
