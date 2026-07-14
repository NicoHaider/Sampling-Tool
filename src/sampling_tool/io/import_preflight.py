"""Billiger Main-Thread-Preflight für Excel-/CSV-Importe (Sprint 48 / S2.3b, S-003).

`preflight_import(path)` läuft auf dem Main-Thread VOR dem Import-Worker und
prüft rein lesend (kein Entpacken, keine Materialisierung, kein UI-Code hier):
reguläre Datei → ZIP-Signatur (nur XLSX/XLSM) → Dateigröße → ZIP-Zentral-
verzeichnis (Member-Anzahl / entpackte Gesamtgröße / Kompressionsverhältnis,
nur XLSX/XLSM) → Sheet-Dimensionen (billig via calamine `sheet.height`/
`width`, nur XLSX/XLSM). Bricht bei der ersten Hard-Reject-Bedingung ab.

Zwei-Stufen-Modell (Backlog S-003 Trade-off): Massendaten sind Kernfunktion,
starre niedrige Limits wären fachlich falsch. WARN_*-Schwellen sind über
einen Confirm-Dialog im Controller übergehbar; MAX_*-Schwellen sind es
nicht. CSV bekommt nur die Regulär-Datei- und Dateigrößen-Prüfung – ein
echter CSV-Streaming-Umbau ist bewusst NICHT Teil dieses Preflights (siehe
SPRINT_48_PROMPT.md).
"""

from __future__ import annotations

import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from python_calamine import CalamineError

# `as CalamineWorkbook` ist kein Stilfehler: Tests patchen
# `import_preflight.CalamineWorkbook.from_path` direkt, mypy (`no_implicit_reexport`
# via `strict = true`) verlangt dafür einen expliziten Re-Export.
from python_calamine import CalamineWorkbook as CalamineWorkbook

from sampling_tool.config import (
    MAX_IMPORT_COLUMNS,
    MAX_IMPORT_FILE_SIZE_BYTES,
    MAX_IMPORT_ROWS,
    MAX_ZIP_COMPRESSION_RATIO,
    MAX_ZIP_MEMBERS,
    MAX_ZIP_UNCOMPRESSED_BYTES,
    SUPPORTED_EXCEL_SUFFIXES,
    WARN_IMPORT_FILE_SIZE_BYTES,
    WARN_IMPORT_ROWS,
)

_ZIP_MAGIC: Final[bytes] = b"PK\x03\x04"


@dataclass(frozen=True, slots=True)
class ImportPreflight:
    """Ergebnis von `preflight_import`.

    `reject_reason` gesetzt ⇒ Hard-Reject, der Import darf nicht starten.
    Sonst ⇒ `warnings` (leer = unauffällig, sonst Confirm-Kandidat).
    """

    reject_reason: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def rejected(self) -> bool:
        return self.reject_reason is not None


def preflight_import(path: Path) -> ImportPreflight:
    """Billiger, rein lesender Preflight-Check vor dem Import-Worker."""
    resolved = path.resolve()

    reject = _check_regular_file(resolved)
    if reject is not None:
        return ImportPreflight(reject_reason=reject)

    is_excel = path.suffix.lower() in SUPPORTED_EXCEL_SUFFIXES
    if is_excel:
        reject = _check_zip_signature(resolved)
        if reject is not None:
            return ImportPreflight(reject_reason=reject)

    warnings: list[str] = []
    size = resolved.stat().st_size
    reject = _check_file_size(size, warnings)
    if reject is not None:
        return ImportPreflight(reject_reason=reject)

    if is_excel:
        reject = _check_zip_container(resolved)
        if reject is not None:
            return ImportPreflight(reject_reason=reject)

        reject = _check_dimensions(resolved, warnings)
        if reject is not None:
            return ImportPreflight(reject_reason=reject)

    return ImportPreflight(warnings=tuple(warnings))


def _check_regular_file(resolved: Path) -> str | None:
    """Devices/FIFOs/Sockets ablehnen. `resolved` ist bereits durch
    `Path.resolve()` gelaufen – ein Symlink-Ziel wird hier erneut geprüft."""
    try:
        st = resolved.stat()
    except OSError:
        return f"Datei nicht gefunden oder nicht lesbar: {resolved.name}"
    if not stat.S_ISREG(st.st_mode):
        return f"Keine reguläre Datei (Gerät, FIFO oder Socket?): {resolved.name}"
    return None


def _check_zip_signature(resolved: Path) -> str | None:
    try:
        with resolved.open("rb") as fh:
            head = fh.read(4)
    except OSError:
        return f"Datei nicht lesbar: {resolved.name}"
    if head != _ZIP_MAGIC:
        return f"Datei '{resolved.name}' hat keine gültige Excel-Signatur (ZIP-Container erwartet)."
    return None


def _check_file_size(size: int, warnings: list[str]) -> str | None:
    if size > MAX_IMPORT_FILE_SIZE_BYTES:
        return (
            f"Datei ist zu groß ({size / (1024 * 1024):.0f} MB, erlaubt: "
            f"{MAX_IMPORT_FILE_SIZE_BYTES / (1024 * 1024):.0f} MB)."
        )
    if size > WARN_IMPORT_FILE_SIZE_BYTES:
        warnings.append(f"Datei ist groß ({size / (1024 * 1024):.0f} MB).")
    return None


def _check_zip_container(resolved: Path) -> str | None:
    try:
        with zipfile.ZipFile(resolved) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile:
        return (
            f"Datei '{resolved.name}' ist kein gültiges ZIP-Archiv "
            "(beschädigt oder kein Excel-Container)."
        )

    if len(infos) > MAX_ZIP_MEMBERS:
        return (
            f"ZIP-Container enthält zu viele Einträge ({len(infos)}, erlaubt: {MAX_ZIP_MEMBERS})."
        )

    total_uncompressed = sum(i.file_size for i in infos)
    total_compressed = sum(i.compress_size for i in infos)

    if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
        return (
            f"ZIP-Container ist entpackt zu groß "
            f"({total_uncompressed / (1024 * 1024):.0f} MB, erlaubt: "
            f"{MAX_ZIP_UNCOMPRESSED_BYTES / (1024 * 1024):.0f} MB)."
        )

    ratio = total_uncompressed / max(total_compressed, 1)
    if ratio > MAX_ZIP_COMPRESSION_RATIO:
        return (
            f"ZIP-Container hat ein verdächtiges Kompressionsverhältnis "
            f"({ratio:.0f}:1, erlaubt: {MAX_ZIP_COMPRESSION_RATIO}:1) – "
            "möglicherweise eine ZIP-Bombe."
        )

    return None


def _check_dimensions(resolved: Path, warnings: list[str]) -> str | None:
    try:
        wb = CalamineWorkbook.from_path(str(resolved))
    except (CalamineError, OSError) as exc:
        # `OSError` deckt TOCTOU-Fälle ab: `_check_zip_container` hat sein
        # eigenes `ZipFile`-Handle schon geschlossen, bevor calamine die
        # Datei hier erneut öffnet – zwischen beiden Checks kann sie
        # verschwinden/gesperrt werden (analog `briefpapier.py`).
        return f"Excel-Datei konnte nicht gelesen werden: {resolved.name} ({exc})."

    for name in wb.sheet_names:
        sheet = wb.get_sheet_by_name(name)
        height = int(sheet.height)
        width = int(sheet.width)

        if width > MAX_IMPORT_COLUMNS:
            return f"Sheet '{name}' hat zu viele Spalten ({width}, erlaubt: {MAX_IMPORT_COLUMNS})."
        if height > MAX_IMPORT_ROWS:
            return f"Sheet '{name}' hat zu viele Zeilen ({height:,}, erlaubt: {MAX_IMPORT_ROWS:,})."
        if height > WARN_IMPORT_ROWS:
            warnings.append(f"Sheet '{name}' hat {height:,} Zeilen.")

    return None
