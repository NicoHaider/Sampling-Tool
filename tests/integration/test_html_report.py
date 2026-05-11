"""Tests für `HtmlReportGenerator` – Jinja-Render, Base64-Charts, Inhalt."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sampling_tool.core.models import (
    AuditEvent,
    Engagement,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.io.html_report import HtmlReportGenerator

pytestmark = pytest.mark.integration


@pytest.fixture
def engagement() -> Engagement:
    return Engagement(
        auditor_name="Anna Auditorin",
        client_name="ACME GmbH",
        auditor_position="Senior",
        audit_type="ISAE 3402",
        id=1,
    )


@pytest.fixture
def samples() -> list[SampleResult]:
    cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=5, seed=42)
    return [
        SampleResult(
            config=cfg,
            selected_row_ids=(1, 2, 3, 4, 5),
            population_size=10,
            drawn_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
            id=1,
        )
    ]


@pytest.fixture
def events() -> list[AuditEvent]:
    return [
        AuditEvent(
            event_type="sampling",
            engagement_id=1,
            user_name="anna",
            sample_id=1,
            sample_size=5,
            sample_percent=50.0,
            seed=42,
            timestamp=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
            id=1,
        )
    ]


class TestHtmlReportGenerator:
    def test_render_creates_file(
        self,
        tmp_path: Path,
        engagement: Engagement,
        samples: list[SampleResult],
        events: list[AuditEvent],
    ) -> None:
        out = tmp_path / "report.html"
        result = HtmlReportGenerator().render(engagement, [], samples, events, out)
        assert result.exists()
        content = result.read_text(encoding="utf-8")
        assert "<!doctype html>" in content.lower()

    def test_html_contains_engagement_info(
        self,
        tmp_path: Path,
        engagement: Engagement,
        samples: list[SampleResult],
        events: list[AuditEvent],
    ) -> None:
        out = tmp_path / "report.html"
        HtmlReportGenerator().render(engagement, [], samples, events, out)
        html = out.read_text(encoding="utf-8")
        assert "ACME GmbH" in html
        assert "ISAE 3402" in html
        assert "Anna Auditorin" in html

    def test_html_embeds_base64_chart(
        self,
        tmp_path: Path,
        engagement: Engagement,
        samples: list[SampleResult],
        events: list[AuditEvent],
    ) -> None:
        out = tmp_path / "report.html"
        HtmlReportGenerator().render(engagement, [], samples, events, out)
        html = out.read_text(encoding="utf-8")
        match = re.search(r'data:image/png;base64,([A-Za-z0-9+/=]+)"', html)
        assert match is not None, "Erwartet mind. eine Base64-eingebettete PNG-Grafik"
        # Base64 sollte sich dekodieren lassen und PNG-Header tragen.
        import base64

        decoded = base64.b64decode(match.group(1))
        assert decoded[:8] == b"\x89PNG\r\n\x1a\n"

    def test_html_renders_without_samples(
        self,
        tmp_path: Path,
        engagement: Engagement,
        events: list[AuditEvent],
    ) -> None:
        out = tmp_path / "report.html"
        HtmlReportGenerator().render(engagement, [], [], events, out)
        html = out.read_text(encoding="utf-8")
        # Leerer Stichproben-Block muss noch enthalten sein, aber ohne Tabelle.
        assert "Noch keine Stichproben" in html

    def test_custom_template_path(
        self,
        tmp_path: Path,
        engagement: Engagement,
        samples: list[SampleResult],
        events: list[AuditEvent],
    ) -> None:
        custom = tmp_path / "tpl.html"
        custom.write_text(
            "<html><body><h1>{{ engagement.client_name }}</h1></body></html>",
            encoding="utf-8",
        )
        out = tmp_path / "out.html"
        HtmlReportGenerator(template_path=custom).render(engagement, [], samples, events, out)
        html = out.read_text(encoding="utf-8")
        assert "<h1>ACME GmbH</h1>" in html

    def test_missing_template_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            HtmlReportGenerator(template_path=tmp_path / "ghost.html")
