"""Globale Konstanten und Default-Werte für das Sampling-Tool.

Hier landet alles, was projektweit hartcodiert sein muss (CI-Farben, Defaults,
Bug-Mail-Adresse). Keine Logik, nur Konstanten.
"""

from __future__ import annotations

from pathlib import Path
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

# Hintergrund-Farbe für markierte Sample-Zeilen in der Tabelle.
# Kräftiges Grün mit moderater Deckkraft, damit Text lesbar bleibt.
SAMPLE_HIGHLIGHT_COLOR: Final[str] = "#28A745"
SAMPLE_HIGHLIGHT_ALPHA: Final[int] = 90  # 0-255 (≈ 35 % Deckkraft)

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
ARCHIVE_DIR_NAME: Final[str] = "archiv"
SUPPORTED_EXCEL_SUFFIXES: Final[tuple[str, ...]] = (".xlsx", ".xlsm")
SUPPORTED_CSV_SUFFIXES: Final[tuple[str, ...]] = (".csv", ".tsv")

# Standard-Ablageort aller Engagement-Dateien. Pro Mandant entsteht ein
# Unterordner mit der `.db`-Datei und einem `archiv/`-Verzeichnis für
# Auto-Snapshots beim Öffnen.
ENGAGEMENTS_DIR: Final[Path] = Path.home() / "Documents" / "BDO Audit Sampling"

# Ablage für ein optionales Briefpapier (PNG/JPG/PDF), das beim Generieren
# von PDF-Reports als Hintergrund eingelegt wird. User-Override für das
# echte BDO-Briefpapier; wenn dort nichts liegt, fällt die App auf das in
# `DEFAULT_BRIEFPAPIER` mitgelieferte Platzhalter-PDF zurück (Sprint 7).
BRIEFPAPIER_DIR: Final[Path] = ENGAGEMENTS_DIR / "briefpapier"
BRIEFPAPIER_DEFAULT_NAME: Final[str] = "bdo_letterhead"

# Paket-Default: das Platzhalter-Briefpapier wird mit dem Wheel ausgeliefert
# (siehe `[tool.setuptools.package-data]` in `pyproject.toml`). Es wird genau
# dann genutzt, wenn kein User-Override unter `BRIEFPAPIER_DIR` liegt. Sobald
# das echte BDO-Briefpapier verfügbar ist, kann diese Datei ohne Code-Änderung
# ausgetauscht werden.
DEFAULT_BRIEFPAPIER: Final[Path] = (
    Path(__file__).parent / "resources" / "briefpapier" / "bdo_placeholder.pdf"
)


# ---------------------------------------------------------------------------
# Pfad-/Datei-Helfer
# ---------------------------------------------------------------------------

# Umlaut-Transliteration vor der Sanitisierung, damit Mandantennamen wie
# "Müller & Söhne GmbH" als "Mueller__Soehne_GmbH" erhalten bleiben statt
# Buchstaben zu verlieren.
_UMLAUT_MAP: Final[dict[str, str]] = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ß": "ss",
    "Ä": "Ae",
    "Ö": "Oe",
    "Ü": "Ue",
}


def sanitize_for_path(name: str) -> str:
    """Macht aus einem Mandanten-/Auditor-Namen einen filesystem-tauglichen Token.

    - Umlaute werden transliteriert (ä → ae, ß → ss, …).
    - Leerzeichen werden zu Underscores.
    - Alles außer `A-Za-z0-9_-` wird entfernt (Case bleibt erhalten).
    - Leerer Output fällt auf `"engagement"` zurück, damit nie ein leerer
      Pfadbestandteil entsteht.
    """
    translated = "".join(_UMLAUT_MAP.get(c, c) for c in name)
    translated = translated.replace(" ", "_")
    cleaned = "".join(c for c in translated if c.isalnum() or c in ("_", "-"))
    return cleaned or "engagement"
