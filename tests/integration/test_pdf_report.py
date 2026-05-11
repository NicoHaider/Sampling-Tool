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
        out_without = tmp_path / "ohne.pdf"
        out_with = tmp_path / "mit.pdf"
        AuditTrailPDF().render(engagement, events, out_without)
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
