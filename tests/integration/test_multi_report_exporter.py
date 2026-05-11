"""Tests für `MultiSheetReportExporter` – alle 4 Sheets + Chart-Bild."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from openpyxl import load_workbook

from sampling_tool.core.models import (
    AuditEvent,
    Dataset,
    DatasetRow,
    Engagement,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.io.multi_report_exporter import MultiSheetReportExporter

pytestmark = pytest.mark.integration


@pytest.fixture
def engagement() -> Engagement:
    return Engagement(
        auditor_name="Anna",
        client_name="ACME GmbH",
        auditor_position="Senior",
        audit_type="ISAE 3402",
        id=1,
    )


@pytest.fixture
def datasets() -> list[Dataset]:
    return [
        Dataset(
            name="Buchungen",
            columns=("Konto", "Betrag"),
            rows=(DatasetRow(row_id=1, values={"Konto": "K1", "Betrag": 10}),),
            engagement_id=1,
            id=1,
        ),
    ]


@pytest.fixture
def samples() -> list[SampleResult]:
    cfg1 = SampleConfig(method=SamplingMethod.SIMPLE, size=5, seed=42)
    cfg2 = SampleConfig(method=SamplingMethod.STRATIFIED, size=3, seed=7, stratum_field="Land")
    return [
        SampleResult(
            config=cfg1,
            selected_row_ids=(1, 2, 3, 4, 5),
            population_size=10,
            drawn_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
            created_by="anna",
            id=1,
        ),
        SampleResult(
            config=cfg2,
            selected_row_ids=(7, 8, 9),
            population_size=10,
            drawn_at=datetime(2026, 5, 2, 11, 0, tzinfo=UTC),
            created_by="bob",
            id=2,
        ),
    ]


@pytest.fixture
def audit_events() -> list[AuditEvent]:
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
        ),
        AuditEvent(
            event_type="export",
            engagement_id=1,
            user_name="anna",
            sample_id=1,
            export_file="/exports/sample.xlsx",
            timestamp=datetime(2026, 5, 1, 11, 0, tzinfo=UTC),
            id=2,
        ),
    ]


class TestMultiSheetReportExporter:
    def test_creates_all_four_sheets(
        self,
        tmp_path: Path,
        engagement: Engagement,
        datasets: list[Dataset],
        samples: list[SampleResult],
        audit_events: list[AuditEvent],
    ) -> None:
        out = tmp_path / "bericht.xlsx"
        result = MultiSheetReportExporter().export(engagement, datasets, samples, audit_events, out)
        assert result.exists()
        wb = load_workbook(result)
        names = wb.sheetnames
        assert any("Übersicht" in n for n in names)
        assert any("AuditTrail" in n for n in names)
        assert any("Samples" in n for n in names)
        assert any("Statistiken" in n for n in names)

    def test_uebersicht_contains_engagement_info(
        self,
        tmp_path: Path,
        engagement: Engagement,
        datasets: list[Dataset],
        samples: list[SampleResult],
        audit_events: list[AuditEvent],
    ) -> None:
        out = tmp_path / "bericht.xlsx"
        MultiSheetReportExporter().export(engagement, datasets, samples, audit_events, out)
        wb = load_workbook(out)
        ws = wb["1. Übersicht"]
        flat = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
        assert "ACME GmbH" in flat
        assert "Anna" in flat
        assert any(v == "2" for v in flat)  # samples-count

    def test_samples_sheet_has_method_rows(
        self,
        tmp_path: Path,
        engagement: Engagement,
        datasets: list[Dataset],
        samples: list[SampleResult],
        audit_events: list[AuditEvent],
    ) -> None:
        out = tmp_path / "bericht.xlsx"
        MultiSheetReportExporter().export(engagement, datasets, samples, audit_events, out)
        wb = load_workbook(out)
        ws = wb["3. Samples"]
        rows = list(ws.iter_rows(values_only=True))
        assert rows[0][0] == "ID"
        methods = {row[1] for row in rows[1:] if row[1] is not None}
        assert "simple" in methods
        assert "stratified" in methods

    def test_audit_trail_in_chronological_order(
        self,
        tmp_path: Path,
        engagement: Engagement,
        datasets: list[Dataset],
        samples: list[SampleResult],
        audit_events: list[AuditEvent],
    ) -> None:
        out = tmp_path / "bericht.xlsx"
        MultiSheetReportExporter().export(engagement, datasets, samples, audit_events, out)
        wb = load_workbook(out)
        ws = wb["2. AuditTrail"]
        rows = list(ws.iter_rows(values_only=True))
        # Header + 2 events
        assert len(rows) == 3
        first_ts = str(rows[1][0])
        second_ts = str(rows[2][0])
        assert first_ts < second_ts

    def test_statistik_sheet_includes_chart_image(
        self,
        tmp_path: Path,
        engagement: Engagement,
        datasets: list[Dataset],
        samples: list[SampleResult],
        audit_events: list[AuditEvent],
    ) -> None:
        out = tmp_path / "bericht.xlsx"
        MultiSheetReportExporter().export(engagement, datasets, samples, audit_events, out)
        wb = load_workbook(out)
        ws = wb["4. Statistiken"]
        # Mindestens ein eingebettetes Bild im Sheet.
        assert len(ws._images) >= 1

    def test_atomic_write_no_tmp_left(
        self,
        tmp_path: Path,
        engagement: Engagement,
        datasets: list[Dataset],
        samples: list[SampleResult],
        audit_events: list[AuditEvent],
    ) -> None:
        out = tmp_path / "bericht.xlsx"
        MultiSheetReportExporter().export(engagement, datasets, samples, audit_events, out)
        # Kein .tmp-Rest, nur die finale .xlsx.
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == []
        assert out.exists()
