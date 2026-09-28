"""Resource-Pfade für Development und PyInstaller-Bundles.

Im Dev-Modus liegen Resources entweder im Paket (z. B. `ui/styles/`,
`persistence/migrations/`) oder im Projekt-Root unter `resources/`
(`briefpapier/`, `templates/`, `icons/`).

Im PyInstaller-Bundle werden alle Files unter `sys._MEIPASS` extrahiert –
unter `sampling_tool/...` für Paket-interne und unter `resources/...`
für Top-Level-Resources. Diese Modul-Funktionen kapseln den Unterschied,
damit der restliche Code Resources einheitlich adressieren kann.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """True, wenn die App als PyInstaller-Bundle läuft."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def _meipass() -> Path:
    """Liest `sys._MEIPASS` als `Path`. Nur aufrufen, wenn `is_frozen()` True ist."""
    return Path(sys._MEIPASS)  # type: ignore[attr-defined]


def package_resource(relative: str) -> Path:
    """Findet eine Resource INNERHALB des `sampling_tool`-Pakets.

    Beispiele:
        - `"ui/styles/bdo_light.qss"`
        - `"persistence/migrations"`
    """
    base = _meipass() / "sampling_tool" if is_frozen() else Path(__file__).parent
    return base / relative


def shared_resource(relative: str) -> Path:
    """Findet eine Resource im `resources/`-Ordner des Projekts/Bundles.

    Beispiele:
        - `"briefpapier/bdo_placeholder.pdf"`
        - `"templates/audit_report.html"`
        - `"icons/app.icns"`
    """
    base = (
        _meipass() / "resources"
        if is_frozen()
        else Path(__file__).resolve().parents[2] / "resources"
    )
    return base / relative


def doc_resource(relative: str) -> Path:
    """Findet eine Datei im `docs/`-Ordner des Projekts/Bundles (Sprint 89 / F).

    Das Handbuch (`USER_GUIDE.md`) liegt im Repo unter `docs/`, nicht unter
    `resources/` – im Bundle landet es per `sampling_tool.spec` unter
    `_MEIPASS/docs/`.
    """
    base = _meipass() / "docs" if is_frozen() else Path(__file__).resolve().parents[2] / "docs"
    return base / relative
