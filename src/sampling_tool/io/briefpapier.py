"""Briefpapier-Template-System für PDF-Reports.

`BriefpapierConfig` bündelt Hintergrund-Bild + Seitenränder.
`get_default_briefpapier()` löst das aktive Briefpapier in dieser
Reihenfolge auf:

1. **User-Override** unter `config.BRIEFPAPIER_DIR/bdo_letterhead.{png,jpg,jpeg,pdf}`.
2. **Paket-Default** (`config.DEFAULT_BRIEFPAPIER` – mitgeliefertes
   `bdo_placeholder.pdf`).
3. `None` – Reports werden ohne Briefpapier-Layer generiert.

Sobald das echte BDO-Briefpapier verfügbar ist, kann es entweder als
User-Override hinterlegt oder direkt unter dem Paket-Pfad ausgetauscht
werden – beides ohne Code-Änderung.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sampling_tool.config import (
    BRIEFPAPIER_DEFAULT_NAME,
    BRIEFPAPIER_DIR,
    BRIEFPAPIER_MAX_BYTES,
    BRIEFPAPIER_MAX_IMAGE_PIXELS,
    DEFAULT_BRIEFPAPIER,
)

_SUFFIX_PRIORITY: Final[tuple[str, ...]] = (".png", ".jpg", ".jpeg", ".pdf")


class BriefpapierError(ValueError):
    """Briefpapier-Datei ist zu groß oder nicht parsebar (Sprint 47 / N-010)."""


@dataclass(frozen=True, slots=True)
class BriefpapierConfig:
    """Konfiguration eines Briefpapier-Layers für PDF-Reports.

    `background_image` kann ein PNG/JPG (im `onPage`-Hook drauf gezeichnet)
    oder ein PDF (per `pypdf`-Post-Merge unter jede Seite gelegt, siehe
    `pdf_report._merge_briefpapier_pdf`) sein.
    """

    background_image: Path | None

    def is_active(self) -> bool:
        """`True`, wenn ein konkretes Hintergrund-Bild geladen ist."""
        return self.background_image is not None and self.background_image.exists()


def get_default_briefpapier() -> BriefpapierConfig | None:
    """Sucht ein Default-Briefpapier in User-Verzeichnis bzw. Paket-Default.

    Reihenfolge der Suche:

    1. `BRIEFPAPIER_DIR/bdo_letterhead.{png,jpg,jpeg,pdf}` (User-Override).
    2. `DEFAULT_BRIEFPAPIER` (Platzhalter-PDF aus den Paket-Resourcen).

    Gibt `None` zurück, wenn beides nicht existiert – Reports laufen dann
    ohne Briefpapier-Layer (kein Fehler).
    """
    user_override = _find_briefpapier_file(BRIEFPAPIER_DIR)
    if user_override is not None:
        return BriefpapierConfig(background_image=user_override)
    if DEFAULT_BRIEFPAPIER.exists():
        return BriefpapierConfig(background_image=DEFAULT_BRIEFPAPIER)
    return None


def briefpapier_from_path(path: Path) -> BriefpapierConfig:
    """Explizite Config-Erzeugung; wirft, wenn die Datei nicht existiert."""
    if not path.exists():
        raise FileNotFoundError(f"Briefpapier-Datei nicht gefunden: {path}")
    if path.suffix.lower() not in _SUFFIX_PRIORITY:
        raise ValueError(
            f"Briefpapier-Format '{path.suffix}' wird nicht unterstützt "
            f"(erlaubt: {', '.join(_SUFFIX_PRIORITY)})."
        )
    return BriefpapierConfig(background_image=path)


def validate_briefpapier(path: Path) -> None:
    """Fail-Fast-Prüfung für die Briefpapier-Auswahl (Sprint 47 / N-010).

    Prüft Existenz + Format (wie `briefpapier_from_path`), zusätzlich
    Dateigröße und echte Parsebarkeit (PDF: mind. eine Seite via `pypdf`;
    Bild: vollständig decodierbar via Pillow + Pixel-Obergrenze). Rein
    lesend, keine Seiteneffekte. Wirft `FileNotFoundError`/`ValueError` für
    Existenz/Format (wie bisher) oder `BriefpapierError` für Größe/Parsefehler.
    Fehlt `pypdf`/Pillow, wird die jeweilige Parseprüfung übersprungen
    (Q-001-Pfad).
    """
    briefpapier_from_path(path)

    try:
        size = path.stat().st_size
    except OSError as exc:
        raise BriefpapierError(f"Briefpapier-Datei ist nicht lesbar: {path}") from exc
    if size > BRIEFPAPIER_MAX_BYTES:
        raise BriefpapierError(
            f"Briefpapier-Datei ist zu groß ({size / (1024 * 1024):.1f} MB, "
            f"erlaubt: {BRIEFPAPIER_MAX_BYTES / (1024 * 1024):.0f} MB)."
        )

    if path.suffix.lower() == ".pdf":
        _validate_pdf_parseable(path)
    else:
        _validate_image_parseable(path)


def _validate_pdf_parseable(path: Path) -> None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return
    try:
        pages = PdfReader(str(path)).pages
    except Exception as exc:
        raise BriefpapierError(f"Briefpapier-PDF konnte nicht gelesen werden: {path.name}") from exc
    if not pages:
        raise BriefpapierError(f"Briefpapier-PDF hat keine Seiten: {path.name}")


def _validate_image_parseable(path: Path) -> None:
    try:
        from PIL import Image
    except ImportError:
        return
    try:
        with Image.open(path) as img:
            # Größe zuerst aus dem Header lesen (kein Decode nötig) und
            # gegen den Pixel-Cap prüfen, BEVOR `img.load()` das ganze Bild
            # in den Speicher dekodiert – sonst schützt der Cap nicht vor
            # dem teuren Decode selbst.
            width, height = img.size
            if width * height > BRIEFPAPIER_MAX_IMAGE_PIXELS:
                raise BriefpapierError(
                    f"Briefpapier-Bild ist zu groß ({width}x{height} Pixel, "
                    f"erlaubt: {BRIEFPAPIER_MAX_IMAGE_PIXELS:,} Pixel)."
                )
            img.load()
    except BriefpapierError:
        raise
    except Exception as exc:
        raise BriefpapierError(
            f"Briefpapier-Bild konnte nicht gelesen werden: {path.name}"
        ) from exc


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _find_briefpapier_file(directory: Path) -> Path | None:
    """Findet die erste passende Briefpapier-Datei in `directory`.

    Endungs-Reihenfolge laut `_SUFFIX_PRIORITY` – PNG schlägt JPG schlägt PDF.
    """
    if not directory.exists():
        return None
    for suffix in _SUFFIX_PRIORITY:
        candidate = directory / f"{BRIEFPAPIER_DEFAULT_NAME}{suffix}"
        if candidate.exists():
            return candidate
    return None
