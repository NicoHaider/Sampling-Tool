"""Briefpapier-Template-System für PDF-Reports.

`BriefpapierConfig` bündelt Hintergrund-Bild + Seitenränder. In Sprint 7 wird
das echte BDO-Briefpapier (PNG/PDF) unter `BRIEFPAPIER_DIR` abgelegt; bis
dahin sucht `get_default_briefpapier()` an folgenden Stellen:

1. Im User-Verzeichnis (`config.BRIEFPAPIER_DIR`).
2. Im paket-internen Resources-Ordner `resources/briefpapier/`.

Findet sie nichts, wird `None` zurückgegeben und Reports werden ohne
Briefpapier generiert.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from sampling_tool.config import BRIEFPAPIER_DEFAULT_NAME, BRIEFPAPIER_DIR

if TYPE_CHECKING:
    from reportlab.pdfgen.canvas import Canvas

_RESOURCES_DIR: Final[Path] = Path(__file__).resolve().parents[1] / "resources" / "briefpapier"
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
    """Sucht ein Default-Briefpapier in User-/Resource-Verzeichnis.

    Reihenfolge der Suche:

    1. `BRIEFPAPIER_DIR/bdo_letterhead.{png,jpg,jpeg,pdf}` (User-Override)
    2. `<package>/resources/briefpapier/bdo_letterhead.{png,jpg,jpeg,pdf}`

    Gibt `None` zurück, wenn nichts gefunden wird – Reports laufen dann
    ohne Briefpapier-Layer (kein Fehler).
    """
    for directory in (BRIEFPAPIER_DIR, _RESOURCES_DIR):
        found = _find_briefpapier_file(directory)
        if found is not None:
            return BriefpapierConfig(background_image=found)
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
