"""Einstiegspunkt – `python -m sampling_tool` bzw. Console-Script `sampling-tool`."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

from sampling_tool.config import APP_NAME, APP_ORG, APP_ORG_DOMAIN
from sampling_tool.resources import package_resource
from sampling_tool.ui.settings_store import AppSettings, load_settings, save_settings


def main() -> int:
    """Startet die Qt-Anwendung (MainWindow + Controller)."""
    from PyQt6.QtWidgets import QApplication

    from sampling_tool.ui.controllers.main_controller import MainController
    from sampling_tool.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    app.setOrganizationDomain(APP_ORG_DOMAIN)

    qss_path = package_resource("ui/styles/bdo_light.qss")
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    settings = load_settings()
    if not settings.first_run_completed:
        settings = run_first_run_wizard(settings)
        save_settings(settings)

    window = MainWindow()
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

    wizard = FirstRunWizard()
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
