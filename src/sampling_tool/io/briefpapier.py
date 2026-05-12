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
from typing import TYPE_CHECKING, Final

from sampling_tool.config import (
    BRIEFPAPIER_DEFAULT_NAME,
    BRIEFPAPIER_DIR,
    DEFAULT_BRIEFPAPIER,
)

if TYPE_CHECKING:
    from reportlab.pdfgen.canvas import Canvas

_SUFFIX_PRIORITY: Final[tuple[str, ...]] = (".png", ".jpg", ".jpeg", ".pdf")


@dataclass(frozen=True, slots=True)
class BriefpapierConfig:
    """Konfiguration eines Briefpapier-Layers für PDF-Reports.

    `background_image` kann ein PNG/JPG (drauf gezeichnet) oder ein PDF
    (per `pdfrw` mit `PageMerge` vorne eingefügt) sein. Die Seitenränder
    geben dem Report-Builder Hinweise, wieviel Platz an den Rändern für
    Briefpapier-Elemente reserviert bleiben soll.
    """

    background_image: Path | None
    margin_top_mm: float = 25.0
    margin_bottom_mm: float = 25.0
    margin_left_mm: float = 20.0
    margin_right_mm: float = 20.0

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


def apply_briefpapier_to_pdf(canvas: Canvas, config: BriefpapierConfig) -> None:
    """Zeichnet das Briefpapier (PNG/JPG) als Hintergrund-Layer.

    Diese Funktion behandelt nur Bitmap-Briefpapier. PDF-Briefpapier wird im
    `pdf_report._draw_background`-Pfad via `pdfrw.PageMerge` integriert.
    """
    if not config.is_active() or config.background_image is None:
        return
    suffix = config.background_image.suffix.lower()
    if suffix == ".pdf":
        return
    page_width, page_height = canvas._pagesize
    canvas.saveState()
    try:
        canvas.drawImage(
            str(config.background_image),
            0,
            0,
            width=page_width,
            height=page_height,
            preserveAspectRatio=True,
            mask="auto",
        )
    finally:
        canvas.restoreState()


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
