"""Einstiegspunkt – `python -m sampling_tool` bzw. Console-Script `sampling-tool`."""

from __future__ import annotations

import logging
import sys
from dataclasses import replace
from pathlib import Path

from sampling_tool.config import APP_NAME, APP_ORG, APP_ORG_DOMAIN
from sampling_tool.logging_setup import configure_logging, install_excepthook
from sampling_tool.ui._scaling import load_scaled_stylesheet, scale_factor
from sampling_tool.ui.settings_store import AppSettings, load_settings, save_settings

logger = logging.getLogger(__name__)


def main() -> int:
    """Startet die Qt-Anwendung (MainWindow + Controller)."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtWidgets import QApplication

    from sampling_tool.ui.controllers.main_controller import MainController
    from sampling_tool.ui.main_window import MainWindow

    # Sprint 78 / B2 – schreibt den HEUTIGEN Qt-6-Default fest, ändert aber
    # bewusst NICHTS am Erscheinungsbild. Gemessen mit Qt 6.11.0:
    # `QGuiApplication.highDpiScaleFactorRoundingPolicy()` liefert ohne diese
    # Zeile bereits `PassThrough`.
    #
    # `PassThrough` ist auch der gewünschte Wert: eine Windows-Skalierung von
    # 125 % bleibt damit 1.25. `Round` würde daraus 1.0 machen – Fenster und
    # Schriften auf jedem Rechner der Bestandsnutzer schlagartig kleiner. Die
    # Zeile schützt genau davor, falls eine künftige Qt-Version den Default
    # ändert.
    #
    # Die Reihenfolge ist lasttragend: NACH `QApplication(...)` gesetzt bleibt
    # die Policy wirkungslos. Festgenagelt in
    # `tests/ui/test_main_entry.py::TestHighDpiRoundingPolicy`.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    app.setOrganizationDomain(APP_ORG_DOMAIN)

    settings = load_settings()
    factor = scale_factor(settings.ui_scale)
    app.setStyleSheet(load_scaled_stylesheet(factor))

    log_path = configure_logging(settings.log_level)
    install_excepthook()
    logger.info("Sampling-Tool gestartet (Log-Datei: %s)", log_path)

    if not settings.first_run_completed:
        settings = run_first_run_wizard(settings)
        save_settings(settings)

    window = MainWindow()
    window.apply_ui_scale(factor)
    # Reference muss am Leben bleiben (sonst werden Signal-Slots GC'd).
    window.controller = MainController(window, settings=settings)  # type: ignore[attr-defined]
    window.show()
    return app.exec()


def run_first_run_wizard(initial: AppSettings) -> AppSettings:
    """Zeigt den Erst-Einrichtungs-Wizard und merged das Ergebnis in `initial`.

    Bei Accept werden die User-Wahlen übernommen. Bei Cancel/Close bleiben
    die Defaults erhalten. In beiden Fällen wird `first_run_completed` auf
    True gesetzt, damit der Wizard nicht erneut auftaucht.
    """
    from PyQt6.QtWidgets import QWizard

    from sampling_tool.ui.dialogs.first_run_wizard import FirstRunWizard

    wizard = FirstRunWizard(ui_scale_factor=scale_factor(initial.ui_scale))
    if wizard.exec() == QWizard.DialogCode.Accepted:
        result = wizard.result_data()
        return replace(
            initial,
            engagements_dir=Path(result.engagements_dir),
            default_auditor_name=result.default_auditor_name,
            first_run_completed=True,
        )
    return replace(initial, first_run_completed=True)


if __name__ == "__main__":
    sys.exit(main())
