"""Einstiegspunkt – `python -m sampling_tool` bzw. Console-Script `sampling-tool`."""

from __future__ import annotations

import sys
from pathlib import Path

from sampling_tool.config import APP_NAME, APP_ORG, APP_ORG_DOMAIN


def main() -> int:
    """Startet die Qt-Anwendung (MainWindow + Controller)."""
    from PyQt6.QtWidgets import QApplication

    from sampling_tool.ui.controllers.main_controller import MainController
    from sampling_tool.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    app.setOrganizationDomain(APP_ORG_DOMAIN)

    qss_path = Path(__file__).parent / "ui" / "styles" / "bdo_light.qss"
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    window = MainWindow()
    # Reference muss am Leben bleiben (sonst werden Signal-Slots GC'd).
    window.controller = MainController(window)  # type: ignore[attr-defined]
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
