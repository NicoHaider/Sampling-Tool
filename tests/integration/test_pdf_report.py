"""Integration: AuditTrailPDF – Audit-Events → PDF mit optionalem Briefpapier."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from reportlab.platypus import SimpleDocTemplate

from sampling_tool.core.models import AuditEvent, Engagement
from sampling_tool.io.bdo_locations import company_by_key, location_by_key
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

    def test_pdf_report_atomic_no_partial_on_build_error(
        self, engagement: Engagement, events: list[AuditEvent], tmp_path: Path
    ) -> None:
        """N-010-PDF-Write: `SimpleDocTemplate`/`doc.build` schrieben bisher
        direkt auf `output_path` – ein Fehler mittendrin im Rendering (z. B.
        ein defektes Briefpapier, das trotz Sprint-47-Robustheit eine andere
        Exception auslöst, oder schlicht ein reportlab-interner Fehler)
        hinterließ eine halbe/korrupte PDF am Ziel. Jetzt: atomar.

        reportlab puffert den kompletten Inhalt im Speicher und schreibt erst
        ganz am Ende (`canvas.save()` → `PDFDocument.SaveToFile`) – ein Mock,
        der `.build()` sofort mit einer Exception abbricht, würde nie echte
        Bytes aufs Ziel schreiben und den Bug damit nicht reproduzieren.
        Der Side-Effect hier schreibt deshalb erst selbst ein paar Bytes an
        den tatsächlich von `SimpleDocTemplate` verwendeten Pfad (`self.
        filename` – vor der Migration `output_path`, danach der atomare
        Tmp-Pfad), bevor er abstürzt – das simuliert einen echten
        Mitten-im-Schreiben-Crash.
        """

        def _boom(doc: SimpleDocTemplate, *args: object, **kwargs: object) -> None:
            Path(doc.filename).write_bytes(b"%PDF-1.4\n% truncated by reportlab boom")
            raise RuntimeError("reportlab boom")

        out = tmp_path / "audit.pdf"
        with (
            patch(
                "sampling_tool.io.pdf_report.SimpleDocTemplate.build",
                autospec=True,
                side_effect=_boom,
            ),
            pytest.raises(RuntimeError, match="reportlab boom"),
        ):
            AuditTrailPDF().render(engagement, events, out)
        assert not out.exists()
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == [], f"Kein .tmp-Rest erwartet, gefunden: {leftovers}"

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

    def test_sampling_event_details_erscheinen_kompakt(
        self, engagement: Engagement, tmp_path: Path
    ) -> None:
        """A-001: additiv, kompakte Sampling-Details in der Aktion-Zelle –
        keine neue Spalte, kein Layout-Redesign (Sprint-33-Tabelle bleibt)."""
        evt = replace(
            _evt("sampling", seconds=0, sample_size=7, seed=99, evt_id=1),
            details={
                "filter_operator": "gte",
                "parent_sample_id": 17,
                "algorithm_version": "bdo-v1",
            },
        )
        out = tmp_path / "details.pdf"
        AuditTrailPDF().render(engagement, [evt], out)
        text = "\n".join(p.extract_text() for p in PdfReader(str(out)).pages)
        assert "filter_operator" in text
        assert "bdo-v1" in text

    def test_korrektur_und_details_komponieren_korrekt(
        self, engagement: Engagement, tmp_path: Path
    ) -> None:
        """A-001: ein korrigiertes Event mit `details` zeigt BEIDES – den
        Korrektur-Pfeil UND die kompakte Details-Zeile – keins verdrängt
        das andere."""
        evt = replace(
            _evt("sampling", seconds=0, sample_size=7, seed=99, corrects=2, evt_id=3),
            details={"filter_operator": "gte", "algorithm_version": "bdo-v1"},
        )
        out = tmp_path / "korrektur_details.pdf"
        AuditTrailPDF().render(engagement, [evt], out)
        text = "\n".join(p.extract_text() for p in PdfReader(str(out)).pages)
        assert "#2" in text
        assert "filter_operator" in text
        assert "bdo-v1" in text


class TestLandscapeLayout:
    """Sprint 33: AuditTrail-PDF läuft im A4-Querformat, damit die „Datei"-
    Spalte nicht mehr rechts aus der Tabelle/Seite läuft."""

    def test_seite_ist_querformat(
        self, engagement: Engagement, events: list[AuditEvent], tmp_path: Path
    ) -> None:
        out = tmp_path / "landscape.pdf"
        AuditTrailPDF().render(engagement, events, out)
        page = PdfReader(str(out)).pages[0]
        assert float(page.mediabox.width) > float(page.mediabox.height)

    def test_spaltenbreiten_summe_passt_in_nutzbare_breite(self) -> None:
        # Nutzbare Breite A4-Querformat = 297mm − 2×20mm Rand = 257mm.
        from reportlab.lib.units import mm

        from sampling_tool.io.pdf_report import _EVENT_TABLE_COL_WIDTHS

        assert sum(_EVENT_TABLE_COL_WIDTHS) <= 257 * mm


class TestBdoAddressBlock:
    """Sprint 33: gewählte BDO-Gesellschaft (fett oben) + Standort-Adresse
    ersetzen den Platzhalter-Adressblock oben rechts. Gesellschaft und Standort
    sind frei kombinierbar."""

    def test_adressblock_mit_gesellschaft_und_standort(
        self, engagement: Engagement, events: list[AuditEvent], tmp_path: Path
    ) -> None:
        company = company_by_key("austria_gmbh")
        location = location_by_key("wien")
        out = tmp_path / "addr.pdf"
        AuditTrailPDF(company=company, location=location).render(engagement, events, out)
        text = "\n".join(p.extract_text() for p in PdfReader(str(out)).pages)
        assert "BDO Austria GmbH" in text
        assert "Am Belvedere" in text  # Straße
        assert "1100" in text  # PLZ
        assert "Wien" in text  # Ort
        assert "1000" in text  # Telefon-Suffix (+43 5 70 375 1000)

    def test_freie_kombination_consulting_plus_linz(
        self, engagement: Engagement, events: list[AuditEvent], tmp_path: Path
    ) -> None:
        # Kern der Anforderung: jede Gesellschaft mit jedem Standort kombinierbar.
        company = company_by_key("consulting_gmbh")
        location = location_by_key("linz")
        out = tmp_path / "combo.pdf"
        AuditTrailPDF(company=company, location=location).render(engagement, events, out)
        text = "\n".join(p.extract_text() for p in PdfReader(str(out)).pages)
        assert "BDO Consulting GmbH" in text
        assert "Reuchlinstra" in text  # Straße (Prefix umgeht ß-Extraktions-Edgecase)
        assert "4020" in text  # PLZ
        assert "Linz" in text  # Ort
        assert "4200" in text  # Telefon-Suffix (+43 5 70 375 4200)

    def test_adressblock_ersetzt_platzhalter(
        self, engagement: Engagement, events: list[AuditEvent], tmp_path: Path
    ) -> None:
        # Default-Briefpapier == Platzhalter-PDF. Mit gewählter Auswahl wird der
        # Platzhalter NICHT mehr gezeichnet (kein doppelter Kopf).
        out = tmp_path / "no_placeholder.pdf"
        AuditTrailPDF(
            company=company_by_key("consulting_gmbh"),
            location=location_by_key("linz"),
        ).render(engagement, events, out)
        text = "\n".join(p.extract_text() for p in PdfReader(str(out)).pages)
        assert "[BDO Austria GmbH]" not in text
        assert "Adresse Zeile" not in text

    def test_ohne_auswahl_bleibt_platzhalter(
        self, engagement: Engagement, events: list[AuditEvent], tmp_path: Path
    ) -> None:
        # Backward-compatible: ohne company/location bleibt der Platzhalter.
        out = tmp_path / "placeholder.pdf"
        AuditTrailPDF().render(engagement, events, out)
        text = "\n".join(p.extract_text() for p in PdfReader(str(out)).pages)
        assert "[BDO Austria GmbH]" in text

    def test_echtes_briefpapier_unterdrueckt_adressblock(
        self,
        engagement: Engagement,
        events: list[AuditEvent],
        briefpapier_png: Path,
        tmp_path: Path,
    ) -> None:
        # Echtes (User-)Briefpapier hat eigenen Kopf → Adressblock NICHT zeichnen.
        out = tmp_path / "real_bp.pdf"
        AuditTrailPDF(
            company=company_by_key("consulting_gmbh"),
            location=location_by_key("linz"),
            briefpapier=briefpapier_png,
        ).render(engagement, events, out)
        text = "\n".join(p.extract_text() for p in PdfReader(str(out)).pages)
        assert "BDO Consulting GmbH" not in text

    def test_draws_address_block_logik(self, briefpapier_png: Path) -> None:
        company = company_by_key("consulting_gmbh")
        location = location_by_key("linz")
        # Platzhalter aktiv + Auswahl → Adressblock zeichnen, Hintergrund weglassen.
        pdf_placeholder = AuditTrailPDF(company=company, location=location)
        assert pdf_placeholder._draws_address_block() is True
        assert pdf_placeholder._resolve_background() is None
        # Echtes Briefpapier → kein Adressblock, Hintergrund bleibt.
        pdf_real = AuditTrailPDF(company=company, location=location, briefpapier=briefpapier_png)
        assert pdf_real._draws_address_block() is False
        assert pdf_real._resolve_background() == briefpapier_png
        # Keine Auswahl → kein Adressblock.
        assert AuditTrailPDF()._draws_address_block() is False

    def test_leere_adressfelder_werden_ausgelassen(
        self, engagement: Engagement, events: list[AuditEvent], tmp_path: Path
    ) -> None:
        # Lustenau hat keine Straße hinterlegt → keine leere Zeile, Ort/Tel bleiben.
        out = tmp_path / "lustenau.pdf"
        AuditTrailPDF(
            company=company_by_key("austria_gmbh"),
            location=location_by_key("lustenau"),
        ).render(engagement, events, out)
        text = "\n".join(p.extract_text() for p in PdfReader(str(out)).pages)
        assert "Lustenau" in text
        assert "6890" in text

    def test_zweimaliges_rendern_liefert_identischen_text(
        self,
        engagement: Engagement,
        events: list[AuditEvent],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Determinismus-Schutz: gleiche Inputs (engagement/events/company/location)
        # ⇒ identischer extrahierter Text. Footer-Zeitstempel wird gepinnt, weil
        # er von der Uhrzeit (nicht den Inputs) abhängt – Byte-Identität des Files
        # ist deshalb ohnehin nicht garantiert (siehe Sprint-Plan §4).
        from datetime import datetime as _dt
        from types import SimpleNamespace

        fixed = _dt(2026, 6, 29, 12, 0, 0)
        monkeypatch.setattr(
            "sampling_tool.io.pdf_report.datetime", SimpleNamespace(now=lambda: fixed)
        )
        company = company_by_key("consulting_gmbh")
        location = location_by_key("linz")
        out1 = tmp_path / "det1.pdf"
        out2 = tmp_path / "det2.pdf"
        AuditTrailPDF(company=company, location=location).render(engagement, events, out1)
        AuditTrailPDF(company=company, location=location).render(engagement, events, out2)
        text1 = "\n".join(p.extract_text() for p in PdfReader(str(out1)).pages)
        text2 = "\n".join(p.extract_text() for p in PdfReader(str(out2)).pages)
        assert text1 == text2
        assert "BDO Consulting GmbH" in text1


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


# ---------------------------------------------------------------------------
# Sprint 47 / N-010: Briefpapier-Parsefehler dürfen den Export nicht crashen
# ---------------------------------------------------------------------------


class TestBriefpapierRobustness:
    """N-010: ein korruptes Briefpapier lässt den Export weiterlaufen –
    WARN-Log + Report ohne Briefpapier-Layer statt ungefangener Exception."""

    def test_corrupt_briefpapier_pdf_does_not_crash_export(
        self,
        engagement: Engagement,
        events: list[AuditEvent],
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from sampling_tool.io.briefpapier import BriefpapierConfig

        corrupt_pdf = tmp_path / "corrupt.pdf"
        corrupt_pdf.write_bytes(b"%PDF-1.4\nnot a real xref table, just garbage\n")

        out = tmp_path / "export.pdf"
        with caplog.at_level("WARNING", logger="sampling_tool.io.pdf_report"):
            result = AuditTrailPDF(
                briefpapier=BriefpapierConfig(background_image=corrupt_pdf)
            ).render(engagement, events, out)

        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("konnte nicht eingebettet werden" in r.message for r in warnings), (
            f"Erwartete WARNING zum Briefpapier, gefangen: {[r.message for r in warnings]}"
        )

    def test_corrupt_image_briefpapier_does_not_crash_export(
        self,
        engagement: Engagement,
        events: list[AuditEvent],
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from sampling_tool.io.briefpapier import BriefpapierConfig

        corrupt_png = tmp_path / "corrupt.png"
        corrupt_png.write_bytes(b"this is not a real png file at all")

        out = tmp_path / "export.pdf"
        with caplog.at_level("WARNING", logger="sampling_tool.io.pdf_report"):
            result = AuditTrailPDF(
                briefpapier=BriefpapierConfig(background_image=corrupt_png)
            ).render(engagement, events, out)

        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("konnte nicht eingebettet werden" in r.message for r in warnings), (
            f"Erwartete WARNING zum Briefpapier, gefangen: {[r.message for r in warnings]}"
        )
