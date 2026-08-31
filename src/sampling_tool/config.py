"""Globale Konstanten und Default-Werte für das Sampling-Tool.

Hier landet alles, was projektweit hartcodiert sein muss (CI-Farben, Defaults,
Bug-Mail-Adresse). Keine Logik, nur Konstanten.
"""

from __future__ import annotations

from datetime import datetime
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
BDO_RED: Final[str] = "#E81A3B"  # FLÄCHE: Buttons, Tabellenkopf, Logo, Fokus

# Sprint 81: das Marken-Rot als SCHRIFTFARBE. Kein neuer Wert – dieser Ton steht
# bereits 10× in `bdo_light.qss` als Hover-/Pressed-/Auswahl-Zustand. Als
# Textfarbe ist `BDO_RED` mit 4,52:1 nur 0,02 über der AA-Grenze und damit
# fragil; dieser Ton liegt bei 7,8:1. Die Trennung ist der Punkt: rot GEFÜLLT
# und rot GESCHRIEBEN sind zwei Rollen, nicht eine Farbe.
BDO_RED_INK: Final[str] = "#A41229"

BDO_DARK_GREY: Final[str] = "#333333"  # Primärtext                    12,6:1
BDO_GREY: Final[str] = "#6B6B6B"  # Sekundärtext (war #7F7F7F)          5,3:1
BDO_LIGHT_GREY: Final[str] = "#D9D9D9"  # Trennlinien, Borders

# Sprint 81: NUR für deaktivierte Steuerelemente. Bis Sprint 80 trug #B0B0B0
# zwei Bedeutungen – „deaktiviert" UND „Leerzustand". Die zweite ist echte
# Information (2,2:1 auf Weiß, faktisch unlesbar) und liegt seither auf
# `BDO_GREY`; die erste ist von WCAG ausdrücklich ausgenommen und darf hell
# bleiben. Ein Wert, eine Bedeutung.
BDO_DISABLED: Final[str] = "#B0B0B0"

# Sprint 81: drei Flächen-Stufen mit klarer Zuständigkeit statt sechs
# zufälligen (#F5F5F5, #F4F4F4, #EEEEEE, #E4E4E4, #F8F8F8, #FAFAFA standen
# nebeneinander, ohne dass ein Unterschied eine Bedeutung trug).
SURFACE_CHROME: Final[str] = "#F8F8F8"  # Menü, Toolbar, Statusbar
SURFACE_DATA: Final[str] = "#FAFAFA"  # Sidebar, Wechselzeile
SURFACE_HOVER: Final[str] = "#F4F4F4"  # Hover, Scrollbar-Rinne, Zeilennummern
SURFACE_SELECTED: Final[str] = "#FFE6E6"  # Auswahl – überall dieselbe Sprache


def excel_argb(hex_color: str, alpha: str = "FF") -> str:
    """`#RRGGBB` → `AARRGGBB` für openpyxl-Farbwerte (Sprint 81).

    openpyxl erwartet ARGB ohne `#`. Bis Sprint 80 stand das Marken-Rot deshalb
    ein fünftes Mal im Projekt, als vier `"FFE81A3B"`-Literale in
    `io/multi_report_exporter.py`. Das war die gefährlichste der fünf Stellen:
    ein Suchen nach `#E81A3B` findet sie nicht, ein Ändern von `BDO_RED` wäre
    dort also stillschweigend nicht durchgeschlagen – der Excel-Report hätte
    weiter das alte Rot getragen, ohne dass ein Test etwas merkt.

    Ein bereits achtstelliger Wert wird unverändert durchgereicht (er trägt
    seinen Alpha-Kanal schon); alles andere ist ein Tippfehler und wirft, statt
    eine Farbe zu erfinden, die openpyxl dann kommentarlos verwirft.
    """
    value = hex_color.lstrip("#").upper()
    if len(value) == 8:
        return value
    if len(value) == 6:
        return f"{alpha.upper()}{value}"
    raise ValueError(f"Unerwartetes Farbformat: {hex_color}")


# Hintergrund-Farbe für markierte Sample-Zeilen in der Tabelle.
# Kräftiges Grün mit moderater Deckkraft, damit Text lesbar bleibt.
SAMPLE_HIGHLIGHT_COLOR: Final[str] = "#28A745"
SAMPLE_HIGHLIGHT_ALPHA: Final[int] = 90  # 0-255 (≈ 35 % Deckkraft)

# ---------------------------------------------------------------------------
# Semantische Farben – was sie BEDEUTEN, nicht wie sie aussehen
# ---------------------------------------------------------------------------
# Schriftfarbe für Labels, die den Anwender zum Handeln auffordern: ein Export,
# der noch nicht startbar ist, eine ungültige Sampling-Eingabe, eine nicht
# eindeutig erkannte Kopfzeile.
#
# Bewusst NICHT `BDO_RED`: das Marken-Rot trägt in dieser App die Marke – primäre
# Buttons, jeder Tabellenkopf, das Logo, der Fokus-Rahmen. Eine Warnung in
# derselben Farbe ist kein Signal mehr, sondern Dekoration (Sprint 80).
WARNING_COLOR: Final[str] = "#C62828"

# ---------------------------------------------------------------------------
# Anzeige-Namen der Sampling-Methoden (Sprint 81)
# ---------------------------------------------------------------------------
# EINE Quelle für die deutschen Methodennamen. Bis Sprint 80 standen sie
# zweimal im Code – als `dict` in `ui/main_window.py` für die Statusbar und als
# `list[tuple]` in `ui/dialogs/template_manager_dialog.py` für das Dropdown –,
# und die Sidebar zeigte stattdessen den ROH-Enum-Wert (`simple`,
# `stratified`). Das Ergebnis war zwei Sprachen für dasselbe Feld, zwei Zeilen
# voneinander entfernt auf demselben Bildschirm: die Sidebar sagte „simple", die
# Statusbar darunter „Einfach".
#
# Schlüssel ist der Enum-WERT (`SamplingMethod.SIMPLE.value`), nicht das
# Enum-Objekt: `config.py` steht unter `core/` in der Layer-Ordnung und darf
# `core.models` nicht importieren. Die Aufrufer, die das Enum haben, indizieren
# über `.value`.
METHOD_LABELS: Final[dict[str, str]] = {
    "simple": "Einfach",
    "cluster": "Cluster",
    "stratified": "Geschichtet",
}

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


# ---------------------------------------------------------------------------
# Export-Dateinamen (Sprint 74 / Befund B)
# ---------------------------------------------------------------------------

# EIN Pattern für alle Export-Dateinamen. Bis Sprint 74 stand es zweimal im
# Code – einmal in `ui/dialogs/_export_base.py` für die Vorschau, einmal in
# `io/exporter.py` für den Writer. Zwei Wahrheiten über dasselbe Format, die
# nur so lange übereinstimmten, wie der `type`-Token des Sample-Exports
# zufällig „sampling" hieß.
#
# Die Datei-Endung ist BEWUSST nicht Teil des Patterns: sie ist Sache des
# Aufrufers (derselbe Berichtstyp wird als .xlsx und als .html exportiert).
EXPORT_FILENAME_PATTERN: Final[str] = "{name}_ID{id}_BDO_{type}_{date}"

# Typ-Token und Endung des Sample-Exports. Sie stehen hier zusammen, weil
# genau dieses Paar zwischen Dialog (`ui/dialogs/export_sample_dialog.py`)
# und Writer (`io/exporter.py`) übereinstimmen MUSS – nur beim Sample-Export
# baut der Writer den Namen selbst, statt den Pfad des Dialogs zu übernehmen.
EXPORT_TYPE_SAMPLING: Final[str] = "sampling"
EXPORT_SUFFIX_SAMPLING: Final[str] = ".xlsx"

# Format des `{date}`-Tokens.
#
# 🔒 LOKALZEIT, kein UTC – und das ist Absicht, kein übersehener Bug: ein
# Prüfer erwartet im Dateinamen den Tag, an dem ER exportiert hat. Eine
# Umstellung auf UTC würde in Europe/Vienna (UTC+2) kurz nach Mitternacht den
# VORTAG in den Dateinamen schreiben – eine Regression, die wie eine
# Verbesserung aussieht. Festgenagelt in
# tests/ui/test_export_target_widget.py::TestDateTokenSemantics.
EXPORT_DATE_TOKEN_FORMAT: Final[str] = "%Y%m%d"


def export_date_token(now: datetime) -> str:
    """`{date}`-Token eines Export-Dateinamens aus einem KONKRETEN Zeitpunkt.

    Nimmt den Zeitpunkt entgegen, statt ihn selbst zu lesen – damit Vorschau
    und geschriebene Datei per Konstruktion denselben Tag tragen und nicht
    nur dann, wenn zwischen beiden Ablesungen kein Tageswechsel liegt.
    """
    return now.strftime(EXPORT_DATE_TOKEN_FORMAT)


def local_export_now() -> datetime:
    """Default-Uhr aller Export-Dateinamen (naive Lokalzeit, siehe §2.4).

    Gemeinsame Modulfunktion statt eines Modul-globalen Patch-Punkts: die
    Konsumenten nehmen sie als Default eines injizierbaren `now_provider`
    entgegen (Muster aus Sprint 73, `ui/widgets/audit_trail_view.py`).
    """
    return datetime.now()


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
