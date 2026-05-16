"""Integration: ExcelExporter – Sample → .xlsx mit Metadaten-Sheet."""

from __future__ import annotations

from collections.abc import Iterator
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
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import (
    DatasetRepo,
    EngagementRepo,
)


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
def db() -> Iterator[Database]:
    database = Database(Path(":memory:"))
    database.migrate()
    yield database
    database.close()


@pytest.fixture
def dataset_with_repo(db: Database, rows: tuple[DatasetRow, ...]) -> tuple[Dataset, DatasetRepo]:
    """Persistiert das Test-Dataset in einer In-Memory-DB und liefert
    (Dataset, DatasetRepo) – die neue Sprint-11.4-API."""
    eng = EngagementRepo(db.connect()).get_or_create(
        Engagement(
            auditor_name="Anna Auditorin",
            client_name="ACME GmbH",
            auditor_position="Senior Auditor",
            audit_type="ISAE 3402 Typ II",
        )
    )
    assert eng.id is not None
    repo = DatasetRepo(db.connect())
    stored = repo.create(
        Dataset(
            name="TestData",
            columns=("Name", "Betrag", "Land", "Datum"),
            row_count=len(rows),
            source_file="/tmp/source.xlsx",
            engagement_id=eng.id,
        ),
        rows,
    )
    return stored, repo


@pytest.fixture
def dataset(dataset_with_repo: tuple[Dataset, DatasetRepo]) -> Dataset:
    return dataset_with_repo[0]


@pytest.fixture
def dataset_repo(dataset_with_repo: tuple[Dataset, DatasetRepo]) -> DatasetRepo:
    return dataset_with_repo[1]


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
        dataset_repo: DatasetRepo,
        tmp_path: Path,
    ) -> None:
        out = exporter.export_sample(
            sample=sample,
            dataset=dataset,
            dataset_repo=dataset_repo,
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
        dataset_repo: DatasetRepo,
        tmp_path: Path,
    ) -> None:
        out = exporter.export_sample(
            sample=sample,
            dataset=dataset,
            dataset_repo=dataset_repo,
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
        dataset_repo: DatasetRepo,
        engagement: Engagement,
        tmp_path: Path,
    ) -> None:
        out = exporter.export_sample(
            sample=sample,
            dataset=dataset,
            dataset_repo=dataset_repo,
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
        dataset_repo: DatasetRepo,
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
                dataset_repo=dataset_repo,
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
        dataset_repo: DatasetRepo,
        tmp_path: Path,
    ) -> None:
        out = exporter.export_sample(
            sample=sample,
            dataset=dataset,
            dataset_repo=dataset_repo,
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
        dataset_repo: DatasetRepo,
        tmp_path: Path,
    ) -> None:
        out = exporter.export_sample(
            sample=sample,
            dataset=dataset,
            dataset_repo=dataset_repo,
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
        dataset_repo: DatasetRepo,
        tmp_path: Path,
    ) -> None:
        umlaut_dir = tmp_path / "Prüfung_Müller_2026"
        out = exporter.export_sample(
            sample=sample,
            dataset=dataset,
            dataset_repo=dataset_repo,
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
        dataset_repo: DatasetRepo,
        tmp_path: Path,
    ) -> None:
        events: list[tuple[int, int]] = []
        exp = ExcelExporter(progress=lambda c, t: events.append((c, t)))
        exp.export_sample(
            sample=sample,
            dataset=dataset,
            dataset_repo=dataset_repo,
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
        dataset_repo: DatasetRepo,
        tmp_path: Path,
    ) -> None:
        with pytest.raises(ExportError, match="existieren nicht"):
            exporter.export_sample(
                sample=sample,
                dataset=dataset,
                dataset_repo=dataset_repo,
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
        dataset_repo: DatasetRepo,
        tmp_path: Path,
    ) -> None:
        with pytest.raises(ExportError, match="Mindestens eine"):
            exporter.export_sample(
                sample=sample,
                dataset=dataset,
                dataset_repo=dataset_repo,
                columns=[],
                output_dir=tmp_path,
                custom_name="X",
                custom_id="1",
            )

    def test_streaming_loads_only_sample_rows_not_all(
        self,
        exporter: ExcelExporter,
        dataset: Dataset,
        dataset_repo: DatasetRepo,
        tmp_path: Path,
    ) -> None:
        """Sprint 11.4: Exporter darf NUR get_rows_by_ids aufrufen,
        nicht get_all_rows (= keinen voll-materialisierten Load)."""
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=2, seed=1)
        sample = SampleResult(
            config=cfg,
            selected_row_ids=(2, 4),
            population_size=10,
        )

        get_all_calls: list[int] = []
        get_by_ids_calls: list[list[int]] = []
        original_get_all = dataset_repo.get_all_rows
        original_get_by_ids = dataset_repo.get_rows_by_ids

        def track_get_all(ds_id: int) -> tuple[DatasetRow, ...]:
            get_all_calls.append(ds_id)
            return original_get_all(ds_id)

        def track_get_by_ids(ds_id: int, ids: list[int]) -> list[DatasetRow]:
            get_by_ids_calls.append(list(ids))
            return original_get_by_ids(ds_id, ids)

        dataset_repo.get_all_rows = track_get_all  # type: ignore[assignment]
        dataset_repo.get_rows_by_ids = track_get_by_ids  # type: ignore[assignment]

        exporter.export_sample(
            sample=sample,
            dataset=dataset,
            dataset_repo=dataset_repo,
            columns=["Name"],
            output_dir=tmp_path,
            custom_name="X",
            custom_id="1",
        )

        assert get_all_calls == [], "Exporter sollte NICHT get_all_rows aufrufen"
        assert get_by_ids_calls == [[2, 4]], (
            "Exporter sollte get_rows_by_ids genau mit den Sample-IDs aufrufen"
        )
