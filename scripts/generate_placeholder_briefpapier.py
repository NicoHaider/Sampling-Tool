"""Generiert ein Platzhalter-Briefpapier für Tests und Development.

Wird einmalig ausgeführt und commitet das resultierende PDF unter
`resources/briefpapier/bdo_placeholder.pdf`. Damit wird es vom Build-
Skript (PyInstaller-Spec, `datas`-Eintrag für `resources/`) mit dem
Bundle ausgeliefert und vom Resolver `sampling_tool.resources.shared_resource`
gefunden.

Sobald das echte BDO-Briefpapier verfügbar ist, kann es ohne Code-
Änderung ausgetauscht werden (User-Override in `BRIEFPAPIER_DIR` oder
direktes Ersetzen der Paket-Ressource).
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPO_ROOT / "resources" / "briefpapier" / "bdo_placeholder.pdf"


def main() -> None:
    """Schreibt die Platzhalter-PDF nach `OUTPUT`."""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(OUTPUT), pagesize=A4)
    width, height = A4

    # Logo-Box oben links – kräftiges Grau, damit „Platzhalter" sofort erkennbar.
    c.setFillColor(HexColor("#A0A0A0"))
    c.rect(20 * mm, height - 50 * mm, 40 * mm, 25 * mm, fill=1, stroke=0)
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(40 * mm, height - 38 * mm, "[BDO LOGO]")

    # Adress-Block oben rechts.
    c.setFillColor(HexColor("#7F7F7F"))
    c.setFont("Helvetica", 9)
    right_x = width - 20 * mm
    top_y = height - 25 * mm
    address_lines = (
        "[BDO Austria GmbH]",
        "[Adresse Zeile 1]",
        "[Adresse Zeile 2]",
        "Tel: [+43 ...]",
        "Web: [www.bdo.at]",
    )
    for i, line in enumerate(address_lines):
        c.drawRightString(right_x, top_y - i * 4 * mm, line)

    # Footer-Platzhalter unten zentriert.
    c.setFillColor(HexColor("#A0A0A0"))
    c.setFont("Helvetica-Oblique", 8)
    c.drawCentredString(
        width / 2,
        15 * mm,
        "[Platzhalter-Briefpapier – wird ausgetauscht sobald BDO-Original verfügbar]",
    )

    c.save()
    print(f"Generated: {OUTPUT}")


if __name__ == "__main__":
    main()
