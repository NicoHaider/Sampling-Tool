"""Deutsche Beschriftung der Qt-Standardbuttons (Sprint 85 / A).

Qt beschriftet `Yes/No/Cancel/Close/Save/Open` in `QMessageBox`,
`QDialogButtonBox`, `QFileDialog` und `QWizard` selbst; ohne geladene
Übersetzung auf Englisch. `qtbase_de.qm` liegt im PyQt6-Wheel und wird von
PyInstaller mit ins Bundle genommen. Fehlt die Datei trotzdem, startet die App
mit englischen Buttons weiter – das ist ein Schönheitsfehler, kein Grund für
einen Absturz.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

import PyQt6
from PyQt6.QtCore import QCoreApplication, QLibraryInfo, QTranslator

logger = logging.getLogger(__name__)

TRANSLATION_NAME: Final = "qtbase_de"

# Die Anwendung hält den Translator nur als C++-Zeiger; ohne Python-Referenz
# räumte der Garbage Collector ihn ab und die Buttons würden wieder englisch.
_installed: list[QTranslator] = []


def _candidate_dirs() -> list[Path]:
    """Wo `qtbase_de.qm` liegen kann: Qts eigener Pfad, sonst der Wheel-Ordner.

    Der zweite Eintrag fängt ein Bundle ab, in dem `QLibraryInfo` den
    Übersetzungspfad nicht auf den mitgelieferten Ordner auflöst.
    """
    return [
        Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)),
        Path(PyQt6.__file__).parent / "Qt6" / "translations",
    ]


def install_german_qt_translation(app: QCoreApplication) -> bool:
    """Lädt `qtbase_de` und installiert sie an `app`; `True`, wenn geladen."""
    translator = QTranslator(app)
    for directory in _candidate_dirs():
        if translator.load(TRANSLATION_NAME, str(directory)):
            app.installTranslator(translator)
            _installed.append(translator)
            logger.info("Qt translation loaded: %s", translator.filePath())
            return True
    logger.warning(
        "Qt translation %s not found in %s; standard buttons stay English",
        TRANSLATION_NAME,
        [str(d) for d in _candidate_dirs()],
    )
    return False


def uninstall_qt_translation(app: QCoreApplication) -> None:
    """Entfernt alle hier installierten Übersetzungen wieder (für Tests)."""
    while _installed:
        app.removeTranslator(_installed.pop())
