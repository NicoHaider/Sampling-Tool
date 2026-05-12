"""PDF-Report für den Audit-Trail eines Engagements.

`AuditTrailPDF` rendert eine PDF-Datei via `reportlab.platypus`:

- A4 Portrait, Engagement-Block oben, Tabelle aller Events, Footer mit
  Seitenzahl und Erstellungszeit.
- Korrektur-Events (`event_type='correction'`) erhalten einen Verweis
  („korrigiert #N") in der Aktion-Spalte.
- Optional liegt ein **Briefpapier-Layer** (PNG oder einseitige PDF) hinter
  jeder Seite – dafür wird der `onPage`-Hook des `SimpleDocTemplate` genutzt.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from sampling_tool.config import BDO_RED
from sampling_tool.core.models import AuditEvent, Engagement
from sampling_tool.io.briefpapier import BriefpapierConfig, get_default_briefpapier

_BDO_RED_COLOR: Final = colors.HexColor(BDO_RED)
_GREY_LIGHT: Final = colors.HexColor("#D9D9D9")
_GREY_CORRECTION: Final = colors.HexColor("#FFF3D6")


class AuditTrailPDF:
    """Erzeugt das AuditTrail-PDF für ein Engagement.

    `briefpapier` kann sein:
    - `Path` – nutzt explizit diese Datei als Hintergrund,
    - `BriefpapierConfig` – komplette Konfiguration inkl. Rändern,
    - `None` – das System sucht nach einem Default (User-Ordner +
      Resource-Ordner). Findet sich nichts, läuft der Report ohne
      Briefpapier-Layer.
    """

    def __init__(
        self,
        briefpapier: Path | BriefpapierConfig | None = None,
    ) -> None:
        if isinstance(briefpapier, Path):
            if not briefpapier.exists():
                raise FileNotFoundError(f"Briefpapier-Datei nicht gefunden: {briefpapier}")
            self.briefpapier_config: BriefpapierConfig | None = BriefpapierConfig(
                background_image=briefpapier
            )
        elif isinstance(briefpapier, BriefpapierConfig):
            self.briefpapier_config = briefpapier
        else:
            self.briefpapier_config = get_default_briefpapier()

    @property
    def briefpapier(self) -> Path | None:
        """Pfad zum aktiven Briefpapier oder `None`."""
        if self.briefpapier_config is None:
            return None
        return self.briefpapier_config.background_image

    def render(
        self,
        engagement: Engagement,
        events: list[AuditEvent],
        output_path: Path,
        include_statistics: bool = True,
    ) -> Path:
        """Schreibt das PDF nach `output_path` und gibt den Pfad zurück.

        `include_statistics=False` lässt den abschließenden Statistik-Block
        weg – nützlich für minimale Trail-Exports.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=22 * mm,
            bottomMargin=22 * mm,
            title=f"AuditTrail – {engagement.client_name}",
            author=engagement.auditor_name,
        )

        story: list[Any] = []
        story.extend(_build_header(engagement))
        story.append(Spacer(1, 6 * mm))
        story.extend(_build_event_table(events))
        if include_statistics:
            story.extend(_build_statistics(events))

        on_page = _make_on_page(self.briefpapier)
        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
        return output_path


# ---------------------------------------------------------------------------
# Story-Bausteine
# ---------------------------------------------------------------------------


def _build_header(engagement: Engagement) -> list[Any]:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "BDOTitle",
        parent=styles["Title"],
        textColor=_BDO_RED_COLOR,
        fontSize=18,
        leading=22,
        spaceAfter=4,
    )
    meta_style = ParagraphStyle(
        "BDOMeta",
        parent=styles["BodyText"],
        fontSize=10,
        leading=14,
    )

    block: list[Any] = [
        Paragraph("AuditTrail", title_style),
        Paragraph(f"<b>Mandant:</b> {_escape(engagement.client_name)}", meta_style),
        Paragraph(
            f"<b>Prüfungstyp:</b> {_escape(engagement.audit_type or '—')}",
            meta_style,
        ),
        Paragraph(
            f"<b>Auditor:</b> {_escape(engagement.auditor_name)} "
            f"({_escape(engagement.auditor_position or '—')})",
            meta_style,
        ),
    ]
    return block


def _build_event_table(events: list[AuditEvent]) -> list[Any]:
    styles = getSampleStyleSheet()
    if not events:
        empty = ParagraphStyle(
            "BDOEmpty",
            parent=styles["BodyText"],
            fontSize=11,
            textColor=colors.grey,
            leading=16,
        )
        return [
            Paragraph(
                "Für dieses Engagement liegen noch keine Audit-Events vor.",
                empty,
            )
        ]

    header = [
        "Zeitstempel",
        "Aktion",
        "User",
        "Größe",
        "%",
        "Seed",
        "Datei",
    ]
    cell_style = ParagraphStyle(
        "BDOTableCell",
        fontName="Helvetica",
        fontSize=8,
        leading=10,
    )
    data: list[list[Any]] = [header]

    # Korrektur-Events visuell markieren – wir merken uns die Zeilen-Indices.
    correction_rows: list[int] = []

    # `events` darf von der Persistenz nach timestamp DESC kommen; für die
    # PDF wollen wir chronologisch (älteste zuerst) – stabil sortieren.
    chronological = sorted(events, key=lambda e: (e.timestamp, e.id or 0))

    for i, evt in enumerate(chronological, start=1):
        action_text = evt.event_type
        if evt.corrects_event_id is not None:
            action_text = f"{evt.event_type} → #{evt.corrects_event_id}"
            correction_rows.append(i)

        percent = f"{evt.sample_percent:.2f} %" if evt.sample_percent is not None else "—"
        size = str(evt.sample_size) if evt.sample_size is not None else "—"
        seed = str(evt.seed) if evt.seed is not None else "—"
        filename = evt.export_file or evt.import_file or "—"
        if filename != "—":
            # Lange Pfade umbrechen, indem wir nur den Dateinamen anzeigen
            filename = Path(filename).name

        data.append(
            [
                Paragraph(_escape(_format_timestamp(evt.timestamp)), cell_style),
                Paragraph(_escape(action_text), cell_style),
                Paragraph(_escape(evt.user_name), cell_style),
                size,
                percent,
                seed,
                Paragraph(_escape(filename), cell_style),
            ]
        )

    table = Table(
        data,
        colWidths=[33 * mm, 30 * mm, 22 * mm, 14 * mm, 16 * mm, 20 * mm, 35 * mm],
        repeatRows=1,
    )
    style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), _BDO_RED_COLOR),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("ALIGN", (3, 1), (5, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.25, _GREY_LIGHT),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.whitesmoke]),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
    )
    for row_idx in correction_rows:
        style.add("BACKGROUND", (0, row_idx), (-1, row_idx), _GREY_CORRECTION)

    table.setStyle(style)
    return [table]


def _build_statistics(events: list[AuditEvent]) -> list[Any]:
    """Abschließender Statistik-Block: Event-Typen-Verteilung."""
    if not events:
        return []
    styles = getSampleStyleSheet()
    heading = ParagraphStyle(
        "BDOStatsHeading",
        parent=styles["Heading2"],
        textColor=_BDO_RED_COLOR,
        fontSize=13,
        leading=18,
        spaceBefore=10,
        spaceAfter=4,
    )

    counts = Counter(e.event_type for e in events)
    rows: list[list[Any]] = [["Eventtyp", "Anzahl"]]
    for event_type, count in counts.most_common():
        rows.append([event_type, str(count)])
    rows.append(["Gesamt", str(len(events))])

    table = Table(rows, colWidths=[60 * mm, 30 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _BDO_RED_COLOR),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, _GREY_LIGHT),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.whitesmoke),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return [Spacer(1, 8 * mm), Paragraph("Statistiken", heading), table]


# ---------------------------------------------------------------------------
# Page-Hook: Briefpapier + Footer
# ---------------------------------------------------------------------------


def _make_on_page(briefpapier: Path | None):  # type: ignore[no-untyped-def]
    """Baut einen onPage-Callback für `SimpleDocTemplate.build`.

    Der Callback hat die reportlab-Signatur `(canvas, doc)` – die akzeptieren
    wir hier dynamisch, weil reportlab keine sauberen Typ-Stubs hat.
    """

    def _on_page(canvas: Canvas, doc: Any) -> None:
        if briefpapier is not None:
            _draw_background(canvas, briefpapier, doc.pagesize)
        _draw_footer(canvas, doc)

    return _on_page


def _draw_background(canvas: Canvas, source: Path, pagesize: tuple[float, float]) -> None:
    """Zeichnet das Briefpapier (PNG oder einseitiges PDF) hinter den Content."""
    width, height = pagesize
    suffix = source.suffix.lower()
    canvas.saveState()
    if suffix == ".pdf":
        try:
            from pdfrw import PdfReader
            from pdfrw.buildxobj import pagexobj
            from pdfrw.toreportlab import makerl
        except ImportError:
            # Fallback: PDF-Briefpapier ohne pdfrw nicht unterstützt – wir
            # rendern unauffällig ohne Layer, damit der Report-Build nicht
            # crasht.
            canvas.restoreState()
            return
        pages = PdfReader(str(source)).pages
        if not pages:
            canvas.restoreState()
            return
        xobj = pagexobj(pages[0])
        canvas.doForm(makerl(canvas, xobj))
    else:
        # Annahme: Bildformat, das reportlab nativ kann (PNG/JPG).
        canvas.drawImage(
            str(source),
            0,
            0,
            width=width,
            height=height,
            preserveAspectRatio=True,
            mask="auto",
        )
    canvas.restoreState()


def _draw_footer(canvas: Canvas, doc: Any) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    footer_text = f"Generiert am {datetime.now().strftime('%Y-%m-%d %H:%M')} – Seite {doc.page}"
    canvas.drawCentredString(doc.pagesize[0] / 2, 12 * mm, footer_text)
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _escape(text: str) -> str:
    """Minimaler HTML-Escape für Paragraph-Text."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_timestamp(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d %H:%M:%S")
