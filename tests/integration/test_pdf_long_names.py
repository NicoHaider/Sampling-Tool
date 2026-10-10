"""Lange Namen im AuditTrail-PDF bleiben in ihrer Zelle (Sprint 92 / C).

Geprüft wird über die Fläche, nicht über einen Messpunkt: jedes Textfragment
jeder Seite (pypdf liefert Position, Schrift, Größe) muss rechts innerhalb
seiner Tabellenzelle bzw. des Satzspiegels enden. Die Spaltengrenzen leiten
sich aus der Kopfzelle „Zeitstempel" der jeweiligen Seite plus den
Spaltenbreiten ab – derselbe Ursprung, den reportlab beim Zeichnen nutzt.

Vor dem Fix lief die User-Spalte über: ein User-Name bis 60 Zeichen ging als
roher String in die Zelle (Schnellpfad von `_format_cell`), den reportlab nie
umbricht – er überschrieb „Größe" und „%".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth

from sampling_tool.config import DEFAULT_BRIEFPAPIER
from sampling_tool.core.models import AuditEvent, Engagement
from sampling_tool.io.bdo_locations import company_by_key, location_by_key
from sampling_tool.io.briefpapier import BriefpapierConfig
from sampling_tool.io.pdf_report import (
    _CELL_STRING_THRESHOLD,
    _EVENT_TABLE_COL_WIDTHS,
    _HEADER_LEFT_WIDTH,
    AuditTrailPDF,
)

pytestmark = pytest.mark.integration

# Satzspiegel: A4 quer, 20 mm Rand links/rechts → 257 mm Breite.
_PAGE_WIDTH: Final = landscape(A4)[0]
_TEXT_LEFT: Final = 20 * mm
_TEXT_RIGHT: Final = _PAGE_WIDTH - 20 * mm
_BOTTOM_MARGIN: Final = 22 * mm
_CELL_PADDING: Final = 4.0
_TOLERANCE: Final = 0.5
_CELL_FONT_SIZE: Final = 8.0
_DETAIL_FONT_SIZE: Final = 7.0

# 48 Zeichen ohne Leerzeichen: unter `_CELL_STRING_THRESHOLD`, lief also über
# den rohen String-Schnellpfad.
_USER: Final = "maximiliane.mustermann-oberhuber@bdo-pruefung.at"
_CLIENT: Final = "Mandantengesellschaft_für_Überwachungsdienstleistungen_und_Prüfungsangelegenheit"
_EXPORT_NAME: Final = ("Kundenstammdaten_" + "Q" * 82 + "_ID_20261002_BDO_sampling.xlsx")[-120:]
_IMPORT_NAME: Final = (
    "Größenübersicht_Übertragungsprüfung_Änderungsprotokoll_Öffentlich_Mandantenäquivalenz.xlsx"
)


@dataclass(frozen=True, slots=True)
class _Fragment:
    page: int
    text: str
    x: float
    y: float
    font: str
    size: float
    right: float


def _fragments(pdf: Path) -> list[_Fragment]:
    """Textfragmente je Zeile. Fragmente mit gleichem Zeilenursprung (pypdf meldet
    bei Schriftwechsel in einer Zeile denselben Startpunkt) werden aneinandergehängt –
    so zählt die volle Zeilenbreite, nicht nur ihr erstes Stück."""
    result: list[_Fragment] = []
    for page_no, page in enumerate(PdfReader(str(pdf)).pages, start=1):
        lines: dict[tuple[float, float], list[tuple[str, str, float]]] = {}

        def visit(
            text: str,
            cm: list[float],
            tm: list[float],
            font_dict: dict[str, Any] | None,
            font_size: float,
            lines: dict[tuple[float, float], list[tuple[str, str, float]]] = lines,
        ) -> None:
            if not text.strip() or font_dict is None:
                return
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            font = str(font_dict.get("/BaseFont", "/Helvetica")).lstrip("/")
            lines.setdefault((round(x, 2), round(y, 2)), []).append(
                (text.replace("\n", ""), font, font_size * cm[0])
            )

        page.extract_text(visitor_text=visit)
        for (x, y), parts in lines.items():
            # pypdf setzt beim Zeilenwechsel ein Leerzeichen VOR das erste Stück –
            # reportlab beginnt keine Zeile mit einem Leerzeichen.
            parts[0] = (parts[0][0].lstrip(), parts[0][1], parts[0][2])
            width = sum(stringWidth(t, f, s) for t, f, s in parts)
            text = "".join(t for t, _, _ in parts)
            result.append(_Fragment(page_no, text, x, y, parts[0][1], parts[0][2], x + width))
    return result


def overflows(pdf: Path, *, header_left_width: float | None = None) -> list[str]:
    """Alle Fragmente, die rechts über ihre Zelle bzw. den Satzspiegel hinausgehen."""
    fragments = _fragments(pdf)
    problems: list[str] = []
    for page in sorted({f.page for f in fragments}):
        on_page = [f for f in fragments if f.page == page]
        heads = [f for f in on_page if f.text.strip() == "Zeitstempel" and "Bold" in f.font]
        header_y = heads[0].y if heads else None
        edges = _column_edges(heads[0].x - _CELL_PADDING) if heads else []
        head_limit = (
            _TEXT_LEFT + header_left_width if header_left_width is not None and page == 1 else None
        )
        for f in on_page:
            problem = _fragment_problem(f, header_y, edges, head_limit)
            if problem is not None:
                problems.append(f"S.{page} {f.text[:40]!r} endet bei {f.right:.1f}: {problem}")
    return problems


def _column_edges(table_left: float) -> list[float]:
    edges = [table_left]
    for width in _EVENT_TABLE_COL_WIDTHS:
        edges.append(edges[-1] + width)
    return edges


def _fragment_problem(
    f: _Fragment, header_y: float | None, edges: list[float], head_limit: float | None
) -> str | None:
    """Grenze, über die `f` hinausläuft – `None`, wenn es passt.

    Tabellenzellen (8 pt) enden in ihrer Spalte, Details-Zeilen (7 pt, über die
    volle Breite) in der Tabelle, die linke Kopfspalte (mit Adressblock) vor der
    Adresse, alles andere im Satzspiegel.
    """
    if f.x < _TEXT_LEFT - _TOLERANCE or f.right > _TEXT_RIGHT + _TOLERANCE:
        return "außerhalb des Satzspiegels"
    limit: float | None = None
    in_table = header_y is not None and _BOTTOM_MARGIN < f.y < header_y
    if in_table and f.size == _CELL_FONT_SIZE and "Bold" not in f.font:
        col = max(i for i in range(len(edges) - 1) if f.x >= edges[i] - _TOLERANCE)
        limit = edges[col + 1] - _CELL_PADDING
    elif in_table and f.size == _DETAIL_FONT_SIZE:
        limit = edges[-1] - _CELL_PADDING
    elif head_limit is not None and header_y is not None and f.y > header_y and f.x < head_limit:
        limit = head_limit
    if limit is not None and f.right > limit + _TOLERANCE:
        return f"Grenze bei {limit:.1f}"
    return None


def _long_name_events() -> list[AuditEvent]:
    base = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
    events = [
        AuditEvent(
            event_type="import",
            engagement_id=1,
            user_name=_USER,
            timestamp=base,
            import_file=str(Path("ablage") / _IMPORT_NAME),
            details={"dataset_name": _IMPORT_NAME},
            id=1,
        ),
        AuditEvent(
            event_type="export",
            engagement_id=1,
            user_name=_USER,
            timestamp=base + timedelta(seconds=1),
            sample_id=3,
            export_file=str(Path("ablage") / _EXPORT_NAME),
            details={"report": "Stichprobe exportiert nach " + _EXPORT_NAME},
            id=2,
        ),
        AuditEvent(
            event_type="sampling",
            engagement_id=1,
            user_name=_USER,
            timestamp=base + timedelta(seconds=2),
            sample_id=3,
            sample_size=5,
            sample_percent=1.67,
            total_count=300,
            seed=4711,
            details={"method": "simple", "population_basis": "filtered"},
            id=3,
        ),
    ]
    # Genug Events für mehrere Seiten: der Tabellenkopf wiederholt sich.
    events.extend(
        AuditEvent(
            event_type="export",
            engagement_id=1,
            user_name=_USER,
            timestamp=base + timedelta(seconds=10 + i),
            export_file=str(Path("ablage") / _EXPORT_NAME),
            id=10 + i,
        )
        for i in range(30)
    )
    return events


_ENGAGEMENT: Final = Engagement(
    auditor_name=_USER, client_name=_CLIENT, auditor_position="Senior", audit_type="ISAE 3402"
)


class TestAuditPdfLongNames:
    def test_inputs_are_the_hard_cases(self) -> None:
        assert len(_EXPORT_NAME) == 120
        assert " " not in _EXPORT_NAME
        assert len(_CLIENT) == 80
        assert len(_USER) <= _CELL_STRING_THRESHOLD
        assert any(ch in _IMPORT_NAME for ch in "äöüÄÖÜß")

    def test_nothing_leaves_cell_or_page(self, tmp_path: Path) -> None:
        out = tmp_path / "lang.pdf"
        AuditTrailPDF(briefpapier=BriefpapierConfig(background_image=None)).render(
            _ENGAGEMENT, _long_name_events(), out
        )
        assert len(PdfReader(str(out)).pages) >= 2
        assert overflows(out) == []

    def test_header_with_address_block(self, tmp_path: Path) -> None:
        # Der Adressblock ersetzt nur den Kopf des Platzhalter-Briefpapiers.
        out = tmp_path / "lang_adresse.pdf"
        AuditTrailPDF(
            briefpapier=BriefpapierConfig(background_image=DEFAULT_BRIEFPAPIER),
            company=company_by_key("austria_gmbh"),
            location=location_by_key("wien"),
        ).render(_ENGAGEMENT, _long_name_events(), out)
        assert overflows(out, header_left_width=_HEADER_LEFT_WIDTH) == []

    def test_gate_detects_overflow(self, tmp_path: Path) -> None:
        """Positiv-Kontrolle des Gates: ein von Hand zu breit gesetzter Text fällt auf."""
        from reportlab.pdfgen.canvas import Canvas

        out = tmp_path / "kontrolle.pdf"
        canvas = Canvas(str(out), pagesize=landscape(A4))
        canvas.setFont("Helvetica", 8)
        canvas.drawString(_TEXT_LEFT, 300, "X" * 400)
        canvas.save()
        assert overflows(out) != []
