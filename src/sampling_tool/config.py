"""Globale Konstanten und Default-Werte für das Sampling-Tool.

Hier landet alles, was projektweit hartcodiert sein muss (CI-Farben, Defaults,
Bug-Mail-Adresse). Keine Logik, nur Konstanten.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from sampling_tool.resources import shared_resource

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
BDO_DARK_GREY: Final[str] = "#333333"  # Haupt-Schriftfarbe
BDO_GREY: Final[str] = "#7F7F7F"  # sekundärer Text
BDO_LIGHT_GREY: Final[str] = "#D9D9D9"  # Trennlinien, Borders

# Hintergrund-Farbe für markierte Sample-Zeilen in der Tabelle.
# Kräftiges Grün mit moderater Deckkraft, damit Text lesbar bleibt.
SAMPLE_HIGHLIGHT_COLOR: Final[str] = "#28A745"
SAMPLE_HIGHLIGHT_ALPHA: Final[int] = 90  # 0-255 (≈ 35 % Deckkraft)

# ---------------------------------------------------------------------------
# Sampling-Defaults
# ---------------------------------------------------------------------------
DEFAULT_SAMPLE_SIZE: Final[int] = 25  # Branchenüblicher Default
MIN_SAMPLE_SIZE: Final[int] = 1
SEED_MIN: Final[int] = 0
SEED_MAX: Final[int] = 2**32 - 1  # numpy default_rng-Range

# ---------------------------------------------------------------------------
# Bug-Reporting (plattformübergreifend via QDesktopServices/mailto)
# ---------------------------------------------------------------------------
BUG_REPORT_EMAIL: Final[str] = "nico.haider@bdo.at"
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

# Paket-Default: das Platzhalter-Briefpapier wird mit dem Build ausgeliefert
# (Projekt-Root `resources/briefpapier/`, im PyInstaller-Bundle unter
# `sys._MEIPASS/resources/briefpapier/`). Es wird genau dann genutzt, wenn kein
# User-Override unter `BRIEFPAPIER_DIR` liegt. Sobald das echte BDO-Briefpapier
# verfügbar ist, kann diese Datei ohne Code-Änderung ausgetauscht werden.
DEFAULT_BRIEFPAPIER: Final[Path] = shared_resource("briefpapier/bdo_placeholder.pdf")

# Briefpapier-Limits (Sprint 47 / N-010, S-003-Teil): Briefpapier bleibt
# optional, diese Werte sind ein Fail-Fast-Netz gegen kaputte/exotische
# Dateien bei der Auswahl – bewusst großzügig, damit reale BDO-Briefpapiere
# nie ausgebremst werden.
BRIEFPAPIER_MAX_BYTES: Final[int] = 50 * 1024 * 1024  # 50 MB
BRIEFPAPIER_MAX_IMAGE_PIXELS: Final[int] = 50_000_000  # ~50 MP

# Import-Ressourcengrenzen (Sprint 48 / S2.3b, S-003): Massendaten sind
# Kernfunktion – deshalb zwei Stufen statt eines starren Limits. WARN_*
# zeigt dem Auditor einen Confirm-Dialog (übergehbar für legitime große
# Prüfungsdaten), MAX_* ist eine harte, nicht übergehbare Sicherheitsgrenze
# gegen Speicher-/CPU-/Platten-Erschöpfung durch eine sehr große oder
# präparierte Datei (ZIP-Bombe, endlose CSV, absurde Dimensionen).
WARN_IMPORT_FILE_SIZE_BYTES: Final[int] = 200 * 1024 * 1024  # 200 MB → Confirm
MAX_IMPORT_FILE_SIZE_BYTES: Final[int] = 1024 * 1024 * 1024  # 1 GB → Reject
WARN_IMPORT_ROWS: Final[int] = 1_000_000  # → Confirm (getestete Baseline)
MAX_IMPORT_ROWS: Final[int] = 10_000_000  # → Hard-Abort
MAX_IMPORT_COLUMNS: Final[int] = 16_384  # Excel-Max → Reject
MAX_IMPORT_CELL_LENGTH: Final[int] = 32_767  # Excel-Max → Hard-Abort
MAX_ZIP_UNCOMPRESSED_BYTES: Final[int] = 2 * 1024 * 1024 * 1024  # 2 GB entpackt → Reject
MAX_ZIP_MEMBERS: Final[int] = 10_000  # → Reject
MAX_ZIP_COMPRESSION_RATIO: Final[int] = 100  # entpackt/komprimiert → ZIP-Bombe → Reject


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

# Reservierte Windows-Gerätenamen (Sprint 51 / N-009): case-insensitive, ein
# `mkdir`/`open` auf einen dieser Namen schlägt auf Windows mit `OSError` fehl,
# unabhängig vom Suffix (auch `CON.db` ist reserviert).
_RESERVED_DEVICE_NAMES: Final[frozenset[str]] = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

# Dateisystem-Grenzen (Sprint 51 / N-009): großzügig genug für reale Mandanten-
# /Prüfungstyp-Namen, klein genug um mit Suffixen/Zeitstempeln nie an
# Pfadlängen-Limits (v. a. Windows) zu stoßen.
_SANITIZED_MAX_LENGTH: Final[int] = 100


def sanitize_for_path(name: str) -> str:
    """Macht aus einem Mandanten-/Auditor-Namen einen filesystem-tauglichen Token.

    - Umlaute werden transliteriert (ä → ae, ß → ss, …).
    - Leerzeichen werden zu Underscores.
    - Erhalten bleibt Unicode-Alphanumerik (kyrillisch, CJK, akzentuierte
      Buchstaben, …) sowie `_`/`-`; alles andere wird entfernt (Case bleibt
      erhalten) – `str.isalnum()` ist NICHT auf ASCII beschränkt.
    - Wird auf ~100 Zeichen gekappt.
    - Reservierte Windows-Gerätenamen (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`,
      `LPT1`–`LPT9`; case-insensitive, auch als Stem vor einem Suffix wie
      `.db` – z. B. `CON.db`) bekommen einen Unterstrich angehängt (z. B.
      `CON` → `CON_`), damit nie ein reservierter Name als Pfadbestandteil
      entsteht. Der Stem wird VOR dem Zeichen-Filter geprüft, weil der Filter
      `.` entfernt und einen eingebetteten Suffix sonst unerkennbar mit dem
      Rest verschmelzen würde (`CON.db` → `CONdb`).
    - Leerer Output fällt auf `"engagement"` zurück, damit nie ein leerer
      Pfadbestandteil entsteht.
    """
    translated = "".join(_UMLAUT_MAP.get(c, c) for c in name)
    translated = translated.replace(" ", "_")
    # Stem vor einem etwaigen Suffix, VOR dem Zeichen-Filter berechnet (der
    # `.` entfernen würde) – reines String-Split statt `Path(...).stem`, damit
    # ein `/`/`\` im Namen nicht als Verzeichnis-Trenner fehlinterpretiert wird.
    pre_filter_stem = translated.rsplit(".", 1)[0] if "." in translated else translated
    cleaned = "".join(c for c in translated if c.isalnum() or c in ("_", "-"))
    cleaned = cleaned[:_SANITIZED_MAX_LENGTH]
    if (
        cleaned.upper() in _RESERVED_DEVICE_NAMES
        or pre_filter_stem.upper() in _RESERVED_DEVICE_NAMES
    ):
        cleaned = f"{cleaned}_"
    return cleaned or "engagement"


def sanitize_export_filename_token(token: str) -> str:
    """Filesystem-untaugliche Zeichen in einem Export-Dateinamen-Token ersetzen.

    Gegenstück zu `sanitize_for_path` (Familie A) für **Export-Dateinamen**
    (Familie B): Blacklist statt Whitelist, erhält Umlaute/Unicode, keine
    Transliteration, keine Kappung, kein Reserved-Name-Handling – ein
    Export-Dateiname soll den vom Anwender eingegebenen lesbaren Namen
    behalten. Wird von `io/exporter.py` (finaler Schreib-Pfad) UND
    `ui/dialogs/_export_base.py` (Live-Vorschau im `ExportTargetWidget`)
    genutzt, damit Vorschau und tatsächlicher Dateiname garantiert
    übereinstimmen.
    """
    forbidden = '<>:"/\\|?*\0'
    cleaned = "".join("_" if c in forbidden else c for c in token).strip()
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned
