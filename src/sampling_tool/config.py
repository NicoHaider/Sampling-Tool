"""Globale Konstanten und Default-Werte für das Sampling-Tool.

Hier landet alles, was projektweit hartcodiert sein muss (CI-Farben, Defaults,
Bug-Mail-Adresse). Keine Logik, nur Konstanten.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Anwendungs-Metadaten
# ---------------------------------------------------------------------------
APP_NAME: Final[str] = "BDO Audit Sampling Tool"
APP_ORG: Final[str] = "BDO"
APP_ORG_DOMAIN: Final[str] = "bdo.at"

# ---------------------------------------------------------------------------
# BDO Corporate-Identity – Farb-Palette (Hex-Codes)
# Wird in den Stylesheets unter ui/styles/*.qss referenziert.
# ---------------------------------------------------------------------------
BDO_RED: Final[str] = "#E81A3B"  # Primärfarbe (Logo-Rot)
BDO_DARK_RED: Final[str] = "#A41229"  # Hover / aktive Buttons
BDO_BLACK: Final[str] = "#000000"
BDO_DARK_GREY: Final[str] = "#333333"  # Haupt-Schriftfarbe
BDO_GREY: Final[str] = "#7F7F7F"  # sekundärer Text
BDO_LIGHT_GREY: Final[str] = "#D9D9D9"  # Trennlinien, Borders
BDO_BACKGROUND: Final[str] = "#F5F5F5"  # Fenster-Hintergrund
BDO_WHITE: Final[str] = "#FFFFFF"

BDO_SUCCESS: Final[str] = "#2E7D32"  # grün – z. B. Sample erfolgreich
BDO_WARNING: Final[str] = "#ED6C02"  # orange – Validierungs-Warnung
BDO_ERROR: Final[str] = "#C62828"  # rot – Fehler-State (UI-Variante,
#                                           bewusst dezenter als BDO_RED)

# ---------------------------------------------------------------------------
# Sampling-Defaults
# ---------------------------------------------------------------------------
DEFAULT_SAMPLE_SIZE: Final[int] = 25  # Branchenüblicher Default
MIN_SAMPLE_SIZE: Final[int] = 1
MAX_SAMPLE_SIZE: Final[int] = 10_000  # Hard-Cap (UI + Validierung)
DEFAULT_SEED: Final[int] = 42  # Doku-Default; Prod erzeugt zufällig
SEED_MIN: Final[int] = 0
SEED_MAX: Final[int] = 2**32 - 1  # numpy default_rng-Range

# ---------------------------------------------------------------------------
# Bug-Reporting (Sprint 7 – Outlook-Integration via pywin32)
# ---------------------------------------------------------------------------
BUG_REPORT_EMAIL: Final[str] = "nicohaider47@gmail.com"
BUG_REPORT_SUBJECT_PREFIX: Final[str] = "[Sampling-Tool Bug]"

# ---------------------------------------------------------------------------
# Datei-/Pfad-Konventionen
# ---------------------------------------------------------------------------
DB_FILE_SUFFIX: Final[str] = ".db"
EXPORT_DIR_NAME: Final[str] = "exports"
SUPPORTED_EXCEL_SUFFIXES: Final[tuple[str, ...]] = (".xlsx", ".xlsm")
SUPPORTED_CSV_SUFFIXES: Final[tuple[str, ...]] = (".csv", ".tsv")
