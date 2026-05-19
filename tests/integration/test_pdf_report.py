"""Integration: AuditTrailPDF – Audit-Events → PDF mit optionalem Briefpapier."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sampling_tool.core.models import AuditEvent, Engagement
from sampling_tool.io.pdf_report import AuditTrailPDF

pypdf = pytest.importorskip("pypdf", reason="pypdf wird für die Inhalts-Prüfung gebraucht")
PdfReader = pypdf.PdfReader


@pytest.fixture
def engagement() -> Engagement:
    return Engagement(
        auditor_name="Anna Auditorin",
        client_name="ACME GmbH",
        auditor_position="Senior Auditor",
        audit_type="ISAE 3402 Typ II",
        id=1,
    )


def _evt(
    event_type: str,
    *,
    seconds: int = 0,
    user: str = "anna",
    sample_size: int | None = None,
    seed: int | None = None,
    corrects: int | None = None,
    evt_id: int | None = None,
) -> AuditEvent:
    base = datetime(2026, 5, 11, 8, 0, 0, tzinfo=UTC)
    return AuditEvent(
        event_type=event_type,
        engagement_id=1,
        user_name=user,
        timestamp=base + timedelta(seconds=seconds),
        sample_size=sample_size,
        sample_percent=(sample_size / 1000 * 100) if sample_size is not None else None,
        seed=seed,
        corrects_event_id=corrects,
        id=evt_id,
    )


@pytest.fixture
def events() -> list[AuditEvent]:
    return [
        _evt("import", seconds=0, evt_id=1),
        _evt("sampling", seconds=10, sample_size=25, seed=42, evt_id=2),
        _evt("export", seconds=20, sample_size=25, evt_id=3),
        _evt("correction", seconds=30, corrects=2, evt_id=4),
    ]


@pytest.fixture
def briefpapier_png(tmp_path: Path) -> Path:
    """Echtes 200x280 PNG (per Pillow erzeugt) – simuliert ein DIN-A4-Briefpapier."""
    pil_image = pytest.importorskip("PIL.Image")
    path = tmp_path / "briefpapier.png"
    img = pil_image.new("RGB", (200, 280), color=(245, 245, 245))
    img.save(path, format="PNG")
    return path


class TestAuditTrailPDF:
    def test_generiert_pdf_mit_korrektem_pfad(
        self, engagement: Engagement, events: list[AuditEvent], tmp_path: Path
    ) -> None:
        out = tmp_path / "audit.pdf"
        result = AuditTrailPDF().render(engagement, events, out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 1000  # plausible Mindestgröße

    def test_pdf_enthaelt_engagement_info(
        self, engagement: Engagement, events: list[AuditEvent], tmp_path: Path
    ) -> None:
        out = tmp_path / "audit.pdf"
        AuditTrailPDF().render(engagement, events, out)

        reader = PdfReader(str(out))
        text = "\n".join(page.extract_text() for page in reader.pages)
        assert "ACME GmbH" in text
        assert "Anna Auditorin" in text
        assert "ISAE 3402 Typ II" in text
        assert "Senior Auditor" in text

    def test_briefpapier_layer_wird_gerendert(
        self,
        engagement: Engagement,
        events: list[AuditEvent],
        briefpapier_png: Path,
        tmp_path: Path,
    ) -> None:
        from sampling_tool.io.briefpapier import BriefpapierConfig

        out_without = tmp_path / "ohne.pdf"
        out_with = tmp_path / "mit.pdf"
        # Default-Lookup explizit umgehen, damit das Paket-Platzhalter-PDF
        # die Größen-Vergleichsprüfung nicht beeinflusst.
        AuditTrailPDF(briefpapier=BriefpapierConfig(background_image=None)).render(
            engagement, events, out_without
        )
        AuditTrailPDF(briefpapier=briefpapier_png).render(engagement, events, out_with)

        # Briefpapier-Variante muss zumindest ein paar Bytes mehr enthalten
        # (Bild eingebettet). Genauer ist mit reportlab schwer prüfbar.
        assert out_with.stat().st_size > out_without.stat().st_size

    def test_briefpapier_datei_muss_existieren(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            AuditTrailPDF(briefpapier=tmp_path / "gibtsnicht.png")

    def test_korrekturen_werden_markiert(
        self, engagement: Engagement, events: list[AuditEvent], tmp_path: Path
    ) -> None:
        out = tmp_path / "audit.pdf"
        AuditTrailPDF().render(engagement, events, out)

        text = "\n".join(p.extract_text() for p in PdfReader(str(out)).pages)
        # In der Aktion-Spalte taucht der Verweis auf den korrigierten Event auf
        assert "correction" in text
        assert "#2" in text

    def test_leerer_audit_trail_enthaelt_hinweis(
        self, engagement: Engagement, tmp_path: Path
    ) -> None:
        out = tmp_path / "empty.pdf"
        AuditTrailPDF().render(engagement, [], out)
        assert out.exists()
        text = "\n".join(p.extract_text() for p in PdfReader(str(out)).pages)
        assert "keine Audit-Events" in text

    def test_mehrseitig_bei_vielen_events(self, engagement: Engagement, tmp_path: Path) -> None:
        many = [
            _evt("sampling", seconds=i, sample_size=i + 1, seed=i, evt_id=i) for i in range(120)
        ]
        out = tmp_path / "lang.pdf"
        AuditTrailPDF().render(engagement, many, out)
        assert out.exists()
        reader = PdfReader(str(out))
        assert len(reader.pages) >= 2

    def test_statistik_block_default_enthaelt_eventtypen(
        self, engagement: Engagement, events: list[AuditEvent], tmp_path: Path
    ) -> None:
        out = tmp_path / "mit_stats.pdf"
        AuditTrailPDF().render(engagement, events, out)
        text = "\n".join(p.extract_text() for p in PdfReader(str(out)).pages)
        assert "Statistiken" in text
        assert "Gesamt" in text

    def test_include_statistics_false_laesst_block_weg(
        self, engagement: Engagement, events: list[AuditEvent], tmp_path: Path
    ) -> None:
        out = tmp_path / "ohne_stats.pdf"
        AuditTrailPDF().render(engagement, events, out, include_statistics=False)
        text = "\n".join(p.extract_text() for p in PdfReader(str(out)).pages)
        assert "Statistiken" not in text


class TestEventTableChunking:
    """Sprint 10.4: Event-Tabelle wird in Sub-Tables zu CHUNK_SIZE gesplittet."""

    def test_chunk_size_konstante_existiert(self) -> None:
        from sampling_tool.io.pdf_report import CHUNK_SIZE

        assert CHUNK_SIZE > 0

    def test_500_events_landen_in_einer_sub_table(self) -> None:
        from reportlab.platypus import Table

        from sampling_tool.io.pdf_report import _build_event_table

        events = [_evt("sampling", seconds=i, evt_id=i) for i in range(500)]
        flowables = _build_event_table(events)
        tables = [f for f in flowables if isinstance(f, Table)]
        assert len(tables) == 1

    def test_1500_events_landen_in_drei_sub_tables(self) -> None:
        from reportlab.platypus import Table

        from sampling_tool.io.pdf_report import _build_event_table

        events = [_evt("sampling", seconds=i, evt_id=i) for i in range(1500)]
        flowables = _build_event_table(events)
        tables = [f for f in flowables if isinstance(f, Table)]
        assert len(tables) == 3

    def test_korrektur_highlight_nur_fuer_corrections(self) -> None:
        # Drei Events, davon eines mit corrects_event_id → genau eine
        # zusätzliche BACKGROUND-Style-Command für Korrektur-Highlight.
        from sampling_tool.io.pdf_report import _GREY_CORRECTION, _build_chunk_style

        style_one_correction = _build_chunk_style([2])
        commands = list(style_one_correction.getCommands())
        correction_bgs = [
            cmd for cmd in commands if cmd[0] == "BACKGROUND" and cmd[3] == _GREY_CORRECTION
        ]
        assert len(correction_bgs) == 1
        # Row 2 (Header ist Index 0)
        assert correction_bgs[0][1] == (0, 2)
        assert correction_bgs[0][2] == (-1, 2)

        style_no_correction = _build_chunk_style([])
        commands = list(style_no_correction.getCommands())
        correction_bgs = [
            cmd for cmd in commands if cmd[0] == "BACKGROUND" and cmd[3] == _GREY_CORRECTION
        ]
        assert correction_bgs == []


class TestFormatCell:
    """Sprint 10.4: Kurze Strings bleiben Strings, lange werden Paragraph."""

    def test_kurze_strings_bleiben_strings(self) -> None:
        from reportlab.lib.styles import ParagraphStyle

        from sampling_tool.io.pdf_report import _format_cell

        style = ParagraphStyle("dummy", fontName="Helvetica", fontSize=8)
        assert _format_cell("Sampling", style) == "Sampling"
        assert _format_cell("anna", style) == "anna"

    def test_lange_strings_werden_paragraph(self) -> None:
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import Paragraph

        from sampling_tool.io.pdf_report import _format_cell

        style = ParagraphStyle("dummy", fontName="Helvetica", fontSize=8)
        long = "x" * 200
        result = _format_cell(long, style)
        assert isinstance(result, Paragraph)

    def test_markup_zeichen_werden_paragraph(self) -> None:
        # `<`, `>`, `&` müssen escaped + als Paragraph gerendert werden,
        # sonst frisst reportlab das.
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import Paragraph

        from sampling_tool.io.pdf_report import _format_cell

        style = ParagraphStyle("dummy", fontName="Helvetica", fontSize=8)
        assert isinstance(_format_cell("a<b>", style), Paragraph)
        assert isinstance(_format_cell("A & B", style), Paragraph)


class TestPdfPerformanceSmoke:
    """Sprint 10.4: 1k Events müssen schnell durchlaufen (Regressions-Sanity)."""

    def test_render_1000_events_unter_3s(self, engagement: Engagement, tmp_path: Path) -> None:
        import time

        events = [
            _evt("sampling", seconds=i, sample_size=i + 1, seed=i, evt_id=i) for i in range(1000)
        ]
        out = tmp_path / "perf_smoke.pdf"
        t0 = time.perf_counter()
        AuditTrailPDF().render(engagement, events, out)
        elapsed = time.perf_counter() - t0
        assert elapsed < 3.0, f"PDF-Render für 1000 Events brauchte {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# Sprint 18 / Q-001: pdfrw-ImportError-Logging
# ---------------------------------------------------------------------------


class TestPdfrwFallback:
    """Q-001: fehlende pdfrw-Dependency muss eine sichtbare Log-Warnung
    produzieren statt das PDF-Briefpapier silent zu droppen."""

    def test_pdf_renders_without_pdfrw_logs_warning(
        self,
        engagement: Engagement,
        events: list[AuditEvent],
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Wenn pdfrw beim PDF-Briefpapier-Embedding fehlt, soll WARN
        geloggt werden (mit dem Substring 'pdfrw'), aber der Report wird
        trotzdem erzeugt – ohne Briefpapier-Layer."""
        import sys

        from sampling_tool.io.briefpapier import BriefpapierConfig

        # PDF-Briefpapier vorbereiten (nicht PNG – nur PDF triggert pdfrw).
        bp_pdf = tmp_path / "letterhead.pdf"
        # Minimales PDF erzeugen, damit Path.exists() True ist.
        AuditTrailPDF(briefpapier=BriefpapierConfig(background_image=None)).render(
            engagement, events[:1], bp_pdf
        )

        # pdfrw aus sys.modules entfernen und Re-Imports blockieren.
        for mod in ("pdfrw", "pdfrw.buildxobj", "pdfrw.toreportlab"):
            monkeypatch.setitem(sys.modules, mod, None)

        out = tmp_path / "ohne_pdfrw.pdf"
        with caplog.at_level("WARNING", logger="sampling_tool.io.pdf_report"):
            AuditTrailPDF(briefpapier=BriefpapierConfig(background_image=bp_pdf)).render(
                engagement, events, out
            )

        # PDF wurde erzeugt.
        assert out.exists()
        # WARNING-Log mit Substring "pdfrw".
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("pdfrw" in r.message.lower() for r in warnings), (
            f"Erwartete WARNING mit 'pdfrw' im Text, gefangen: {[r.message for r in warnings]}"
        )
