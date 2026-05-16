"""Integration: ExcelImporter – Excel/CSV → Dataset, Header-Detection, Encoding."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from sampling_tool.io.importer import DataImportError, ExcelImporter, ImportResult


@pytest.fixture
def importer() -> ExcelImporter:
    return ExcelImporter()


class TestImportXlsx:
    def test_importiert_einfache_xlsx_mit_header(
        self, importer: ExcelImporter, simple_xlsx: Path
    ) -> None:
        result = importer.import_file(simple_xlsx)
        rows = list(result.rows)
        assert isinstance(result, ImportResult)
        ds = result.dataset
        assert ds.columns == ("Name", "Betrag", "Quote", "Buchungsdatum")
        assert len(rows) == 10
        assert rows[0].row_id == 1
        assert rows[0].values["Name"] == "Posten 1"
        assert rows[0].values["Betrag"] == 101
        assert isinstance(rows[0].values["Buchungsdatum"], datetime)
        assert ds.source_file == str(simple_xlsx)
        assert result.skipped_rows == 0

    def test_importiert_xlsm_und_ignoriert_makros(
        self, importer: ExcelImporter, xlsm_macro: Path
    ) -> None:
        result = importer.import_file(xlsm_macro)
        rows = list(result.rows)
        assert result.dataset.columns == ("A", "B")
        assert len(rows) == 2
        assert rows[0].values == {"A": 1, "B": 2}

    def test_sheet_auswahl_bei_multi_sheet(
        self, importer: ExcelImporter, multi_sheet_xlsx: Path
    ) -> None:
        result = importer.import_file(multi_sheet_xlsx, sheet_name="Stammdaten")
        rows = list(result.rows)
        assert result.dataset.columns == ("KundenID", "Land")
        assert len(rows) == 3
        assert rows[0].values["Land"] == "AUT"

    def test_default_sheet_ohne_argument(
        self, importer: ExcelImporter, multi_sheet_xlsx: Path
    ) -> None:
        result = importer.import_file(multi_sheet_xlsx)
        list(result.rows)
        # Erstes/aktives Sheet ist "Buchungen"
        assert result.dataset.columns == ("BuchungsID", "Betrag")

    def test_unbekanntes_sheet_wirft_klare_meldung(
        self, importer: ExcelImporter, multi_sheet_xlsx: Path
    ) -> None:
        with pytest.raises(DataImportError, match="existiert nicht"):
            importer.import_file(multi_sheet_xlsx, sheet_name="GibtEsNicht")

    def test_header_detection_mit_leerzeilen(
        self, importer: ExcelImporter, leading_blank_xlsx: Path
    ) -> None:
        result = importer.import_file(leading_blank_xlsx)
        rows = list(result.rows)
        assert result.dataset.columns == ("Konto", "Bezeichnung", "Saldo")
        assert len(rows) == 2
        # 3 leere Vorzeilen wurden geskipped
        assert result.skipped_rows == 3
        assert rows[0].values["Saldo"] == 500.50

    def test_duplikat_spaltennamen_bekommen_suffix(
        self, importer: ExcelImporter, duplicate_columns_xlsx: Path
    ) -> None:
        result = importer.import_file(duplicate_columns_xlsx)
        list(result.rows)
        assert result.dataset.columns == ("Betrag", "Betrag_2", "Betrag_3")
        assert any("Doppelter Spaltenname" in w for w in result.warnings)

    def test_leere_xlsx_wirft_fachlichen_fehler(
        self, importer: ExcelImporter, empty_xlsx: Path
    ) -> None:
        with pytest.raises(DataImportError, match="Keine Spaltenüberschriften"):
            importer.import_file(empty_xlsx)

    def test_unbekannter_dateityp(self, importer: ExcelImporter, tmp_path: Path) -> None:
        bogus = tmp_path / "data.xyz"
        bogus.write_text("nope")
        with pytest.raises(DataImportError, match="wird nicht unterstützt"):
            importer.import_file(bogus)

    def test_nicht_existente_datei(self, importer: ExcelImporter, tmp_path: Path) -> None:
        with pytest.raises(DataImportError, match="nicht gefunden"):
            importer.import_file(tmp_path / "fehlt.xlsx")

    def test_datentyp_konvertierung_zahl_string_datum(
        self, importer: ExcelImporter, simple_xlsx: Path
    ) -> None:
        result = importer.import_file(simple_xlsx)
        rows = list(result.rows)
        first = rows[0].values
        assert isinstance(first["Name"], str)
        assert isinstance(first["Betrag"], int)
        assert isinstance(first["Quote"], float)
        assert isinstance(first["Buchungsdatum"], datetime)


class TestImportCsv:
    def test_csv_utf8(self, importer: ExcelImporter, utf8_csv: Path) -> None:
        result = importer.import_file(utf8_csv)
        rows = list(result.rows)
        assert result.dataset.columns == ("Name", "Stadt")
        assert rows[0].values == {"Name": "Müller", "Stadt": "Wien"}
        # utf-8 ohne BOM erzeugt keine Encoding-Warnung
        assert not any("Encoding" in w for w in result.warnings)

    def test_csv_utf8_bom(self, importer: ExcelImporter, utf8_bom_csv: Path) -> None:
        result = importer.import_file(utf8_bom_csv)
        list(result.rows)
        assert result.dataset.columns == ("Name", "Stadt")
        # utf-8-sig wurde gewählt → Warnung
        assert any("utf-8-sig" in w for w in result.warnings)

    def test_csv_cp1252(self, importer: ExcelImporter, cp1252_csv: Path) -> None:
        # latin-1 nimmt jedes Byte und liest in dem Zeichensatz – das ist für
        # die hier verwendeten Umlaute kompatibel mit cp1252.
        result = importer.import_file(cp1252_csv)
        rows = list(result.rows)
        assert result.dataset.columns == ("Name", "Stadt")
        assert rows[0].values["Name"] == "Müller"
        assert any("Encoding" in w for w in result.warnings)

    def test_csv_mit_semikolon_separator(self, importer: ExcelImporter, tmp_path: Path) -> None:
        path = tmp_path / "semi.csv"
        path.write_text("a;b;c\n1;2;3\n4;5;6\n", encoding="utf-8")
        result = importer.import_file(path)
        rows = list(result.rows)
        assert result.dataset.columns == ("a", "b", "c")
        assert rows[0].values == {"a": 1, "b": 2, "c": 3}

    def test_leere_csv(self, importer: ExcelImporter, tmp_path: Path) -> None:
        path = tmp_path / "empty.csv"
        path.write_text("", encoding="utf-8")
        with pytest.raises(DataImportError, match="keine Daten"):
            importer.import_file(path)


class TestPreviewUndDetectSheets:
    def test_detect_sheets_listet_alle(
        self, importer: ExcelImporter, multi_sheet_xlsx: Path
    ) -> None:
        sheets = importer.detect_sheets(multi_sheet_xlsx)
        assert sheets == ["Buchungen", "Stammdaten"]

    def test_detect_sheets_nur_excel(self, importer: ExcelImporter, utf8_csv: Path) -> None:
        with pytest.raises(DataImportError, match="nur für Excel"):
            importer.detect_sheets(utf8_csv)

    def test_preview_liefert_n_rows_xlsx(self, importer: ExcelImporter, simple_xlsx: Path) -> None:
        cols, rows = importer.preview(simple_xlsx, n_rows=3)
        assert cols == ["Name", "Betrag", "Quote", "Buchungsdatum"]
        assert len(rows) == 3
        assert rows[0]["Name"] == "Posten 1"

    def test_preview_n_rows_groesser_als_datei(
        self, importer: ExcelImporter, simple_xlsx: Path
    ) -> None:
        _cols, rows = importer.preview(simple_xlsx, n_rows=999)
        assert len(rows) == 10

    def test_preview_csv(self, importer: ExcelImporter, utf8_csv: Path) -> None:
        cols, rows = importer.preview(utf8_csv, n_rows=1)
        assert cols == ["Name", "Stadt"]
        assert len(rows) == 1
        assert rows[0] == {"Name": "Müller", "Stadt": "Wien"}


class TestCalamineIntegration:
    """Sprint 10.2: ExcelImporter nutzt python-calamine als Excel-Engine."""

    def test_importer_quelle_referenziert_calamine_nicht_openpyxl(self) -> None:
        """openpyxl darf im Excel-Import-Pfad nicht mehr auftauchen."""
        import inspect

        from sampling_tool.io import importer

        src = inspect.getsource(importer)
        # Calamine ist da
        assert "CalamineWorkbook" in src
        # openpyxl darf nicht mehr importiert werden (Module-Level)
        assert "from openpyxl" not in src
        assert "import openpyxl" not in src

    def test_native_python_types_aus_excel(self, simple_xlsx: Path) -> None:
        """Zahlen, Datums-Werte und Strings kommen als Python-Native-Typen."""
        result = ExcelImporter().import_file(simple_xlsx)
        rows = list(result.rows)
        first = rows[0].values
        # Ganzzahliger Excel-Wert → int (auch wenn Calamine intern float liefert)
        assert isinstance(first["Betrag"], int)
        assert first["Betrag"] == 101
        # Echter Float bleibt float
        assert isinstance(first["Quote"], float)
        # datetime statt date (Calamine liefert date für 00:00:00-Werte)
        assert isinstance(first["Buchungsdatum"], datetime)

    def test_leere_zellen_als_none(self, tmp_path: Path) -> None:
        """Calamine liefert leere Zellen als ``""`` – muss zu None normalisiert werden."""
        path = tmp_path / "with_blanks.xlsx"
        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.append(["A", "B", "C"])
        ws.append(["x", None, None])
        ws.append([None, 5, None])
        wb.save(path)

        result = ExcelImporter().import_file(path)
        rows = list(result.rows)
        first = rows[0].values
        second = rows[1].values
        assert first["A"] == "x"
        assert first["B"] is None
        assert first["C"] is None
        assert second["A"] is None
        assert second["B"] == 5


class TestProgressCallback:
    """Sprint 11.3 – Streaming: Progress feuert erst beim Generator-Verbrauch."""

    def test_callback_finaler_tick_nach_voller_iteration(self, simple_xlsx: Path) -> None:
        events: list[tuple[int, int]] = []
        importer = ExcelImporter(progress=lambda c, t: events.append((c, t)))
        result = importer.import_file(simple_xlsx)
        # Vor dem Konsumieren ist der Generator nicht gelaufen → keine Events.
        assert events == []
        list(result.rows)
        # Nach voller Iteration mindestens der finale Tick.
        assert events[-1] == (10, 10)

    def test_callback_bei_leeren_daten(self, tmp_path: Path) -> None:
        # Datei mit Header aber ohne Datenzeilen → 0 Events vor Konsum,
        # ein finaler (0, 0)-Tick nach Konsum.
        path = tmp_path / "header_only.xlsx"
        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.append(["A", "B"])
        wb.save(path)

        events: list[tuple[int, int]] = []
        result = ExcelImporter(progress=lambda c, t: events.append((c, t))).import_file(path)
        list(result.rows)
        assert events == [(0, 0)]


class TestStreamingImport:
    """Sprint 11.3: ImportResult.rows ist ein einmalig konsumierbarer Iterator."""

    def test_rows_ist_kein_tuple_oder_list(self, simple_xlsx: Path) -> None:
        result = ExcelImporter().import_file(simple_xlsx)
        # Kein materialisierter Container.
        assert not isinstance(result.rows, list | tuple)
        # Aber iterierbar – Generator hat __next__.
        assert hasattr(result.rows, "__next__")

    def test_rows_nur_einmal_konsumierbar(self, simple_xlsx: Path) -> None:
        result = ExcelImporter().import_file(simple_xlsx)
        first_pass = list(result.rows)
        assert len(first_pass) == 10
        second_pass = list(result.rows)
        assert second_pass == []

    def test_stats_vor_iteration_leer(self, simple_xlsx: Path) -> None:
        result = ExcelImporter().import_file(simple_xlsx)
        assert result.stats.processed_count == 0
        assert result.stats.skipped_rows == 0

    def test_stats_nach_iteration_gefuellt(self, leading_blank_xlsx: Path) -> None:
        result = ExcelImporter().import_file(leading_blank_xlsx)
        list(result.rows)
        # 3 Leerzeilen vorm Header werden beim Header-Pass schon erkannt.
        assert result.stats.skipped_rows == 3
        assert result.stats.processed_count == 2

    def test_stats_property_compat(self, leading_blank_xlsx: Path) -> None:
        # Backwards-Compat-Properties (ImportResult.skipped_rows / .warnings).
        result = ExcelImporter().import_file(leading_blank_xlsx)
        list(result.rows)
        assert result.skipped_rows == 3
        assert isinstance(result.warnings, tuple)


class TestRepoStreamingRowCount:
    """Sprint 11.3: DatasetRepo.create korrigiert row_count basierend auf
    der echten Anzahl persistierter Rows (wichtig bei Skipped-Rows im
    Streaming-Import)."""

    def test_repo_create_uebernimmt_actual_count(self, simple_xlsx: Path, tmp_path: Path) -> None:
        from dataclasses import replace as dc_replace

        from sampling_tool.core.models import Engagement
        from sampling_tool.persistence.database import Database
        from sampling_tool.persistence.repositories import DatasetRepo, EngagementRepo

        db = Database(tmp_path / "streaming.db")
        db.migrate()
        eng = EngagementRepo(db.connect()).get_or_create(
            Engagement(
                auditor_name="A", client_name="C", auditor_position="S", audit_type="ISAE 3402"
            )
        )
        assert eng.id is not None

        result = ExcelImporter().import_file(simple_xlsx)
        dataset = dc_replace(result.dataset, engagement_id=eng.id)
        stored = DatasetRepo(db.connect()).create(dataset, result.rows)

        assert stored.row_count == 10
        assert stored.id is not None
        # Echte Persistenz prüfen.
        all_rows = DatasetRepo(db.connect()).get_all_rows(stored.id)
        assert len(all_rows) == 10
        db.close()

    def test_repo_create_korrigiert_bei_skipped(
        self, leading_blank_xlsx: Path, tmp_path: Path
    ) -> None:
        # leading_blank_xlsx hat 3 Leerzeilen vor dem Header, 2 Daten-Rows.
        # `sheet.total_height` enthält die Leerzeilen, der Importer
        # schätzt also evtl. zu hoch – Repo korrigiert auf 2.
        from dataclasses import replace as dc_replace

        from sampling_tool.core.models import Engagement
        from sampling_tool.persistence.database import Database
        from sampling_tool.persistence.repositories import DatasetRepo, EngagementRepo

        db = Database(tmp_path / "skipped.db")
        db.migrate()
        eng = EngagementRepo(db.connect()).get_or_create(
            Engagement(
                auditor_name="A", client_name="C", auditor_position="S", audit_type="ISAE 3402"
            )
        )
        assert eng.id is not None

        result = ExcelImporter().import_file(leading_blank_xlsx)
        dataset = dc_replace(result.dataset, engagement_id=eng.id)
        stored = DatasetRepo(db.connect()).create(dataset, result.rows)

        assert stored.row_count == 2
        db.close()
