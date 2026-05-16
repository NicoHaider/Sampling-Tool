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
        assert isinstance(result, ImportResult)
        ds = result.dataset
        assert ds.columns == ("Name", "Betrag", "Quote", "Buchungsdatum")
        assert len(result.rows) == 10
        assert result.rows[0].row_id == 1
        assert result.rows[0].values["Name"] == "Posten 1"
        assert result.rows[0].values["Betrag"] == 101
        assert isinstance(result.rows[0].values["Buchungsdatum"], datetime)
        assert ds.source_file == str(simple_xlsx)
        assert result.skipped_rows == 0

    def test_importiert_xlsm_und_ignoriert_makros(
        self, importer: ExcelImporter, xlsm_macro: Path
    ) -> None:
        result = importer.import_file(xlsm_macro)
        assert result.dataset.columns == ("A", "B")
        assert len(result.rows) == 2
        assert result.rows[0].values == {"A": 1, "B": 2}

    def test_sheet_auswahl_bei_multi_sheet(
        self, importer: ExcelImporter, multi_sheet_xlsx: Path
    ) -> None:
        result = importer.import_file(multi_sheet_xlsx, sheet_name="Stammdaten")
        assert result.dataset.columns == ("KundenID", "Land")
        assert len(result.rows) == 3
        assert result.rows[0].values["Land"] == "AUT"

    def test_default_sheet_ohne_argument(
        self, importer: ExcelImporter, multi_sheet_xlsx: Path
    ) -> None:
        result = importer.import_file(multi_sheet_xlsx)
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
        assert result.dataset.columns == ("Konto", "Bezeichnung", "Saldo")
        assert len(result.rows) == 2
        # 3 leere Vorzeilen wurden geskipped
        assert result.skipped_rows == 3
        assert result.rows[0].values["Saldo"] == 500.50

    def test_duplikat_spaltennamen_bekommen_suffix(
        self, importer: ExcelImporter, duplicate_columns_xlsx: Path
    ) -> None:
        result = importer.import_file(duplicate_columns_xlsx)
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
        first = result.rows[0].values
        assert isinstance(first["Name"], str)
        assert isinstance(first["Betrag"], int)
        assert isinstance(first["Quote"], float)
        assert isinstance(first["Buchungsdatum"], datetime)


class TestImportCsv:
    def test_csv_utf8(self, importer: ExcelImporter, utf8_csv: Path) -> None:
        result = importer.import_file(utf8_csv)
        assert result.dataset.columns == ("Name", "Stadt")
        assert result.rows[0].values == {"Name": "Müller", "Stadt": "Wien"}
        # utf-8 ohne BOM erzeugt keine Encoding-Warnung
        assert not any("Encoding" in w for w in result.warnings)

    def test_csv_utf8_bom(self, importer: ExcelImporter, utf8_bom_csv: Path) -> None:
        result = importer.import_file(utf8_bom_csv)
        assert result.dataset.columns == ("Name", "Stadt")
        # utf-8-sig wurde gewählt → Warnung
        assert any("utf-8-sig" in w for w in result.warnings)

    def test_csv_cp1252(self, importer: ExcelImporter, cp1252_csv: Path) -> None:
        # latin-1 nimmt jedes Byte und liest in dem Zeichensatz – das ist für
        # die hier verwendeten Umlaute kompatibel mit cp1252.
        result = importer.import_file(cp1252_csv)
        assert result.dataset.columns == ("Name", "Stadt")
        assert result.rows[0].values["Name"] == "Müller"
        assert any("Encoding" in w for w in result.warnings)

    def test_csv_mit_semikolon_separator(self, importer: ExcelImporter, tmp_path: Path) -> None:
        path = tmp_path / "semi.csv"
        path.write_text("a;b;c\n1;2;3\n4;5;6\n", encoding="utf-8")
        result = importer.import_file(path)
        assert result.dataset.columns == ("a", "b", "c")
        assert result.rows[0].values == {"a": 1, "b": 2, "c": 3}

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
        first = result.rows[0].values
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
        first = result.rows[0].values
        second = result.rows[1].values
        assert first["A"] == "x"
        assert first["B"] is None
        assert first["C"] is None
        assert second["A"] is None
        assert second["B"] == 5


class TestProgressCallback:
    def test_callback_wird_aufgerufen(self, simple_xlsx: Path) -> None:
        events: list[tuple[int, int]] = []
        importer = ExcelImporter(progress=lambda c, t: events.append((c, t)))
        importer.import_file(simple_xlsx)
        assert len(events) == 10
        assert events[-1] == (10, 10)
        assert events[0] == (1, 10)

    def test_callback_bei_leeren_daten(self, tmp_path: Path) -> None:
        # Datei mit Header aber ohne Datenzeilen
        path = tmp_path / "header_only.xlsx"
        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.append(["A", "B"])
        wb.save(path)

        events: list[tuple[int, int]] = []
        ExcelImporter(progress=lambda c, t: events.append((c, t))).import_file(path)
        assert events == [(0, 0)]
