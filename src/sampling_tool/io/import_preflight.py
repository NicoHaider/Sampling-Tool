"""Vorprüfung für Excel-/CSV-Importe (Sprint 48 / S2.3b, S-003; Sprint 97).

Zwei Stufen, damit der UI-Thread keine Datei parst (Sprint 97):

1. `preflight_file(path)` – auf dem UI-Thread, VOR jedem Worker. Rein lesend,
   kein Entpacken, kein calamine, kein CSV-Parse: reguläre Datei → ZIP-Signatur
   (nur XLSX/XLSM) → Dateigröße → ZIP-Zentralverzeichnis (Member-Anzahl /
   entpackte Gesamtgröße / Kompressionsverhältnis, nur XLSX/XLSM). Millisekunden.
2. `check_sheet_dimensions(sheets, warnings)` – im Worker, aus
   `ExcelImporter.probe`. Prüft Höhe/Breite der dort ohnehin geladenen Blätter.
   calamine kennt die Dimensionen erst nach dem vollständigen Laden eines
   Blatts – deshalb gehört diese Prüfung nicht auf den UI-Thread.

Beide brechen bei der ersten Hard-Reject-Bedingung ab.

Schwellen (Backlog S-003 Trade-off): Massendaten sind Kernfunktion, starre
niedrige Limits wären fachlich falsch. WARN_*-Schwellen sind über einen
Confirm-Dialog im Controller übergehbar (Dateigröße und Zeilen erscheinen
gemeinsam in EINEM Dialog); MAX_*-Schwellen sind es nicht. CSV bekommt nur die
Regulär-Datei- und Dateigrößen-Prüfung.
"""

from __future__ import annotations

import stat
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

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

if TYPE_CHECKING:
    from sampling_tool.io.importer import SheetInfo

_ZIP_MAGIC: Final[bytes] = b"PK\x03\x04"


@dataclass(frozen=True, slots=True)
class ImportPreflight:
    """Ergebnis von `preflight_file`.

    `reject_reason` gesetzt ⇒ Hard-Reject, der Import darf nicht starten.
    Sonst ⇒ `warnings` (leer = unauffällig, sonst Confirm-Kandidat).
    """

    reject_reason: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def rejected(self) -> bool:
        return self.reject_reason is not None


def preflight_file(path: Path) -> ImportPreflight:
    """Billiger, rein lesender Preflight-Check auf dem UI-Thread, vor jedem Worker."""
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


def unreadable_excel_reason(path: Path, exc: Exception) -> str:
    """Reject-Text, wenn calamine die Arbeitsmappe nicht öffnen kann.

    Tritt auch nach bestandenem `preflight_file` auf (TOCTOU): `_check_zip_container`
    hat sein `ZipFile`-Handle geschlossen, bevor calamine die Datei im Worker
    erneut öffnet – dazwischen kann sie verschwinden/gesperrt werden (analog
    `briefpapier.py`).
    """
    return f"Excel-Datei konnte nicht gelesen werden: {path.resolve().name} ({exc})."


def check_sheet_dimensions(sheets: Sequence[SheetInfo], warnings: list[str]) -> str | None:
    """Reject-Text beim ersten Blatt über den Hard-Grenzen, sonst ``None``.

    Hängt Zeilen-Warnungen an ``warnings`` an. Prüfwerte sind `SheetInfo.row_count`
    / `column_count` = calamine `height` / `width` – dieselben Werte, die der
    Preflight vor Sprint 97 direkt am Blatt gelesen hat.
    """
    for info in sheets:
        name = info.name
        height = info.row_count
        width = info.column_count

        if width > MAX_IMPORT_COLUMNS:
            return f"Sheet '{name}' hat zu viele Spalten ({width}, erlaubt: {MAX_IMPORT_COLUMNS})."
        if height > MAX_IMPORT_ROWS:
            return f"Sheet '{name}' hat zu viele Zeilen ({height:,}, erlaubt: {MAX_IMPORT_ROWS:,})."
        if height > WARN_IMPORT_ROWS:
            warnings.append(f"Sheet '{name}' hat {height:,} Zeilen.")

    return None
