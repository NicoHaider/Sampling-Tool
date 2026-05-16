"""Integration: ExcelExporter – Sample → .xlsx mit Metadaten-Sheet."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from openpyxl import load_workbook

from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    Engagement,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.io.exporter import ExcelExporter, ExportError


@pytest.fixture
def rows() -> tuple[DatasetRow, ...]:
    return tuple(
        DatasetRow(
            row_id=i,
            values={
                "Name": f"Posten {i}",
                "Betrag": 100 + i,
                "Land": "AUT" if i % 2 == 0 else "DEU",
                "Datum": datetime(2026, 1, i, 9, 0, 0),
            },
        )
        for i in range(1, 11)
    )


@pytest.fixture
def dataset(rows: tuple[DatasetRow, ...]) -> Dataset:
    return Dataset(
        name="TestData",
        columns=("Name", "Betrag", "Land", "Datum"),
        row_count=len(rows),
        source_file="/tmp/source.xlsx",
        engagement_id=1,
        id=42,
    )


@pytest.fixture
def sample(dataset: Dataset) -> SampleResult:
    cfg = SampleConfig(
        method=SamplingMethod.SIMPLE,
        size=4,
        seed=42,
        description="Test-Stichprobe",
    )
    return SampleResult(
        config=cfg,
        selected_row_ids=(1, 3, 5, 7),
        population_size=len(dataset),
    )


@pytest.fixture
def engagement() -> Engagement:
    return Engagement(
        auditor_name="Anna Auditorin",
        client_name="ACME GmbH",
        auditor_position="Senior Auditor",
        audit_type="ISAE 3402 Typ II",
        id=1,
    )


@pytest.fixture
def exporter() -> ExcelExporter:
    return ExcelExporter()


class TestExportSample:
    def test_dateiname_folgt_vba_schema(
        self,
        exporter: ExcelExporter,
        sample: SampleResult,
        dataset: Dataset,
        rows: tuple[DatasetRow, ...],
        tmp_path: Path,
    ) -> None:
        out = exporter.export_sample(
            sample=sample,
            dataset=dataset,
            rows=rows,
            columns=["Name", "Betrag"],
            output_dir=tmp_path,
            custom_name="NewHires_Q2_2026",
            custom_id="001",
        )
        assert out.exists()
        assert out.name.startswith("NewHires_Q2_2026_ID001_BDO_sampling_")
        assert out.name.endswith(".xlsx")
        # Datum im Namen plausibel (8 Ziffern)
        date_token = out.name.split("_BDO_sampling_")[1].replace(".xlsx", "")
        assert len(date_token) == 8
        assert date_token.isdigit()

    def test_sample_sheet_enthaelt_genau_die_gewaehlten_spalten(
        self,
        exporter: ExcelExporter,
        sample: SampleResult,
        dataset: Dataset,
        rows: tuple[DatasetRow, ...],
        tmp_path: Path,
    ) -> None:
        out = exporter.export_sample(
            sample=sample,
            dataset=dataset,
            rows=rows,
            columns=["Land", "Name"],  # bewusst andere Reihenfolge
            output_dir=tmp_path,
            custom_name="X",
            custom_id="1",
        )
        wb = load_workbook(out)
        ws = wb["Sample"]
        header = [c.value for c in ws[1]]
        assert header == ["Land", "Name"]
        # Zeilenanzahl = sample.actual_size (4) + 1 Header
        assert ws.max_row == 5
        # Werte aus row_id=1: Land="DEU", Name="Posten 1"
        first_data = [c.value for c in ws[2]]
        assert first_data == ["DEU", "Posten 1"]

    def test_metadaten_sheet_enthaelt_seed_und_engagement(
        self,
        exporter: ExcelExporter,
        sample: SampleResult,
        dataset: Dataset,
        rows: tuple[DatasetRow, ...],
        engagement: Engagement,
        tmp_path: Path,
    ) -> None:
        out = exporter.export_sample(
            sample=sample,
            dataset=dataset,
            rows=rows,
            columns=["Name"],
            output_dir=tmp_path,
            custom_name="X",
            custom_id="1",
            engagement=engagement,
        )
        wb = load_workbook(out)
        ws = wb["Metadaten"]
        meta = {row[0].value: row[1].value for row in ws.iter_rows(min_row=2)}
        assert meta["Seed"] == 42
        assert meta["Stichprobengröße"] == 4
        assert meta["Population (Zeilen)"] == 10
        assert meta["Sampling-Methode"] == "simple"
        assert meta["Auditor"] == "Anna Auditorin"
        assert meta["Mandant"] == "ACME GmbH"
        assert meta["Beschreibung"] == "Test-Stichprobe"

    def test_atomic_write_kein_halbes_file_bei_exception(
        self,
        exporter: ExcelExporter,
        sample: SampleResult,
        dataset: Dataset,
        rows: tuple[DatasetRow, ...],
        tmp_path: Path,
    ) -> None:
        # openpyxl-Save soll fehlschlagen → die Tmp-Datei muss verschwinden,
        # die Ziel-Datei darf gar nicht erst entstehen.
        with (
            patch("sampling_tool.io.exporter.Workbook.save", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            exporter.export_sample(
                sample=sample,
                dataset=dataset,
                rows=rows,
                columns=["Name"],
                output_dir=tmp_path,
                custom_name="X",
                custom_id="1",
            )
        leftover = list(tmp_path.iterdir())
        assert leftover == [], f"Es sollten keine Dateien übrig bleiben, gefunden: {leftover}"

    def test_spaltenbreiten_sind_gesetzt(
        self,
        exporter: ExcelExporter,
        sample: SampleResult,
        dataset: Dataset,
        rows: tuple[DatasetRow, ...],
        tmp_path: Path,
    ) -> None:
        out = exporter.export_sample(
            sample=sample,
            dataset=dataset,
            rows=rows,
            columns=["Name", "Betrag"],
            output_dir=tmp_path,
            custom_name="X",
            custom_id="1",
        )
        wb = load_workbook(out)
        ws = wb["Sample"]
        assert ws.column_dimensions["A"].width is not None
        assert ws.column_dimensions["A"].width >= 8
        # Spalte mit "Posten 10" (9 Zeichen) → mindestens 9 + 2
        assert ws.column_dimensions["A"].width >= 9

    def test_header_ist_gefettet_und_gefaerbt(
        self,
        exporter: ExcelExporter,
        sample: SampleResult,
        dataset: Dataset,
        rows: tuple[DatasetRow, ...],
        tmp_path: Path,
    ) -> None:
        out = exporter.export_sample(
            sample=sample,
            dataset=dataset,
            rows=rows,
            columns=["Name"],
            output_dir=tmp_path,
            custom_name="X",
            custom_id="1",
        )
        wb = load_workbook(out)
        ws = wb["Sample"]
        cell = ws["A1"]
        assert cell.font.bold is True
        # BDO_RED = #E81A3B → ARGB FFE81A3B
        assert cell.fill.start_color.rgb == "FFE81A3B"
        # Weiße Schrift
        assert cell.font.color.rgb == "FFFFFFFF"

    def test_umlaute_im_pfad_funktionieren(
        self,
        exporter: ExcelExporter,
        sample: SampleResult,
        dataset: Dataset,
        rows: tuple[DatasetRow, ...],
        tmp_path: Path,
    ) -> None:
        umlaut_dir = tmp_path / "Prüfung_Müller_2026"
        out = exporter.export_sample(
            sample=sample,
            dataset=dataset,
            rows=rows,
            columns=["Name"],
            output_dir=umlaut_dir,
            custom_name="Stichprobe_März",
            custom_id="042",
        )
        assert out.exists()
        assert "Prüfung_Müller_2026" in str(out)
        assert "Stichprobe_März" in out.name

    def test_progress_callback(
        self,
        sample: SampleResult,
        dataset: Dataset,
        rows: tuple[DatasetRow, ...],
        tmp_path: Path,
    ) -> None:
        events: list[tuple[int, int]] = []
        exp = ExcelExporter(progress=lambda c, t: events.append((c, t)))
        exp.export_sample(
            sample=sample,
            dataset=dataset,
            rows=rows,
            columns=["Name"],
            output_dir=tmp_path,
            custom_name="X",
            custom_id="1",
        )
        # 4 Zeilen → 4 Ticks
        assert len(events) == 4
        assert events[-1] == (4, 4)

    def test_unbekannte_spalte_wirft_export_error(
        self,
        exporter: ExcelExporter,
        sample: SampleResult,
        dataset: Dataset,
        rows: tuple[DatasetRow, ...],
        tmp_path: Path,
    ) -> None:
        with pytest.raises(ExportError, match="existieren nicht"):
            exporter.export_sample(
                sample=sample,
                dataset=dataset,
                rows=rows,
                columns=["GibtsNicht"],
                output_dir=tmp_path,
                custom_name="X",
                custom_id="1",
            )

    def test_leere_spaltenliste_wirft_export_error(
        self,
        exporter: ExcelExporter,
        sample: SampleResult,
        dataset: Dataset,
        rows: tuple[DatasetRow, ...],
        tmp_path: Path,
    ) -> None:
        with pytest.raises(ExportError, match="Mindestens eine"):
            exporter.export_sample(
                sample=sample,
                dataset=dataset,
                rows=rows,
                columns=[],
                output_dir=tmp_path,
                custom_name="X",
                custom_id="1",
            )
