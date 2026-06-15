"""Sprint 26 – Korrektheits-/Repro-Guard für die Import-Performance-Arbeit.

Die rote Linie des Sprints: die importierten Werte/Typen und die
Tagged-Encoding-Semantik müssen **byte-für-byte identisch** zum Verhalten
vor Sprint 26 bleiben. Diese Tests pinnen das Verhalten gegen eine
eingefrorene Referenz-Implementierung des Encoders (das Pre-Sprint-26-
Muster: Dict-Comp + isinstance-basiertes `_encode_value`, serialisiert via
orjson). Jede Optimierung von `_values_to_json` muss byte-identisch dazu
bleiben – analog zu den Oracle-Tests in `test_audit_trail_view.py` und
`test_distinct_values.py`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from pathlib import Path
from typing import Any

import orjson
import pytest
from openpyxl import Workbook

from sampling_tool.core.cancellation import CancellationToken, OperationCancelled
from sampling_tool.core.models import Dataset, DatasetRow, Engagement
from sampling_tool.io.importer import ExcelImporter
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import (
    DatasetRepo,
    EngagementRepo,
    _values_from_json,
    _values_to_json,
)

# ---------------------------------------------------------------------------
# Eingefrorene Referenz: das Tagged-Encoding-Verhalten VOR Sprint 26.
# Produktionscode (`_values_to_json`) muss byte-identisch dazu bleiben.
# ---------------------------------------------------------------------------

_TYPE_KEY = "__type__"
_VAL_KEY = "v"


def _reference_encode_value(value: object) -> object:
    """Pre-Sprint-26 `_encode_value` – datetime VOR date prüfen (Subclass!)."""
    if isinstance(value, datetime):
        return {_TYPE_KEY: "datetime", _VAL_KEY: value.isoformat()}
    if isinstance(value, date):
        return {_TYPE_KEY: "date", _VAL_KEY: value.isoformat()}
    if isinstance(value, dt_time):
        return {_TYPE_KEY: "time", _VAL_KEY: value.isoformat()}
    return value


def _reference_values_to_json(values: dict[str, object]) -> str:
    """Pre-Sprint-26 `_values_to_json` (Dict-Comp + orjson)."""
    return orjson.dumps({k: _reference_encode_value(v) for k, v in values.items()}).decode("utf-8")


# Werte-Batterie inkl. Edge-Cases: None, gemischte Spalten, Nicht-ASCII,
# große Zahlen (innerhalb int64), datetime/date/time, naiv + tz-aware.
_VALUE_BATTERY: tuple[dict[str, object], ...] = (
    {},
    {"a": 1, "b": 2.5, "c": "hallo", "d": None, "e": True, "f": False},
    {"text": "Müller", "land": "Österreich", "preis": "€42,50", "nr": "№7", "str": "Straße"},
    {"big": 9_000_000_000_000_000_000, "neg": -123456789, "zero": 0, "flt": 1.7976931348623157e308},
    {"dt": datetime(2024, 1, 1, 12, 30, 45), "d": date(2024, 6, 15), "t": dt_time(23, 59, 59)},
    {
        "dt_tz": datetime(2024, 1, 1, 12, 30, tzinfo=UTC),
        "micro": datetime(2024, 1, 1, 0, 0, 0, 123456),
    },
    {"gemischt": None, "wann": datetime(2026, 12, 31, 8, 0), "wer": "Anna", "wieviel": 42},
)


class TestImportResultUnchanged:
    """Importergebnisse bleiben byte-für-byte identisch zum Pre-Sprint-26-Stand."""

    @pytest.mark.parametrize("values", _VALUE_BATTERY)
    def test_tagged_encoding_roundtrip_unchanged(self, values: dict[str, object]) -> None:
        # Byte-Identität gegen die eingefrorene Referenz.
        assert _values_to_json(values) == _reference_values_to_json(values)
        # Round-Trip: zurückgelesene Werte sind wertgleich + typgleich.
        restored = _values_from_json(_values_to_json(values))
        assert restored == values
        for key, original in values.items():
            assert type(restored[key]) is type(original), f"Typ-Drift bei '{key}'"

    def test_xlsx_import_identical_to_baseline(self, tmp_path: Path) -> None:
        path = _make_rich_xlsx(tmp_path)
        rows = list(ExcelImporter().import_file(path).rows)

        # 1) Encodierte Bytes pro Zeile identisch zur Referenz.
        for row in rows:
            assert _values_to_json(row.values) == _reference_values_to_json(row.values)

        # 2) Voller Datei→DB→Readback-Pfad: Zeilenzahl, Werte, Typen identisch.
        readback = _persist_and_read_back(tmp_path / "xlsx.db", rows)
        _assert_rows_identical(readback, rows)

    def test_csv_import_identical_to_baseline(self, tmp_path: Path) -> None:
        # CSV erzeugt nie datetime/date/time (Strings bleiben Strings) – testet
        # explizit den Nicht-Temporal-Pfad des Encoders.
        path = tmp_path / "rich.csv"
        path.write_text(
            "name,betrag,menge,leer,wann\n"
            "Müller,1234.5,7,,2024-01-01T08:00:00\n"
            "Köck,-0.5,0,,2024-06-15\n"
            "Straße €,1000,42,,\n",
            encoding="utf-8",
        )
        rows = list(ExcelImporter().import_file(path).rows)

        for row in rows:
            assert _values_to_json(row.values) == _reference_values_to_json(row.values)

        readback = _persist_and_read_back(tmp_path / "csv.db", rows)
        _assert_rows_identical(readback, rows)

    def test_cancellation_still_works(self, tmp_path: Path) -> None:
        path = _make_rich_xlsx(tmp_path, n_rows=3000)

        # Vorab gesetztes Token: Konsum bricht sofort ab.
        token = CancellationToken()
        token.set()
        importer = ExcelImporter(cancellation=token)
        with pytest.raises(OperationCancelled):
            list(importer.import_file(path).rows)

        # Mitten in der Iteration: nach 500 Zeilen gesetzt → Abbruch beim
        # nächsten Intervall-Check (1000), nicht alle Zeilen konsumiert.
        token2 = CancellationToken()
        importer2 = ExcelImporter(cancellation=token2)
        consumed: list[DatasetRow] = []
        with pytest.raises(OperationCancelled):
            _drain_setting_token_at(importer2.import_file(path).rows, consumed, token2, 500)
        assert 500 <= len(consumed) < 3000

    def test_pragmas_restored_after_import(self, tmp_path: Path) -> None:
        """Sprint 26 lockert keine PRAGMAs – synchronous/journal_mode bleiben sicher.

        Guard gegen eine versehentlich am Live-Handle hängende
        Bulk-Load-Lockerung (`synchronous=OFF` darf NICHT bestehen bleiben).
        """
        db = Database(tmp_path / "pragmas.db")
        db.migrate()
        conn = db.connect()
        eng = EngagementRepo(conn).get_or_create(
            Engagement(
                auditor_name="P",
                auditor_position="S",
                client_name="C",
                audit_type="ISAE 3402",
            )
        )
        rows = [
            DatasetRow(row_id=i, values={"a": i, "t": datetime(2024, 1, 1, 0, 0)})
            for i in range(1, 51)
        ]
        dataset = Dataset(name="ds", columns=("a", "t"), engagement_id=eng.id)
        with db.session() as session_conn:
            DatasetRepo(session_conn).create(dataset, iter(rows))

        # synchronous=NORMAL(1), journal_mode=wal – wie in `Database.connect`.
        assert int(conn.execute("PRAGMA synchronous").fetchone()[0]) == 1
        assert str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
        db.close()

    def test_bulk_load_count_guard_holds(self, tmp_path: Path) -> None:
        """Write-Pfad bleibt ein einziger `executemany`-Bulk-Insert (kein Per-Row).

        Spiegelt den Sprint-24-Geist (≤10 Bulk-Loads) auf der Insert-Seite:
        eine Encoder-Optimierung darf das Streaming-`executemany` nicht in
        viele Einzel-Inserts zerlegen.
        """
        db = Database(tmp_path / "bulk.db")
        db.migrate()
        conn = db.connect()
        eng = EngagementRepo(conn).get_or_create(
            Engagement(
                auditor_name="P",
                auditor_position="S",
                client_name="C",
                audit_type="ISAE 3402",
            )
        )
        rows = [DatasetRow(row_id=i, values={"a": i}) for i in range(1, 1001)]
        dataset = Dataset(name="ds", columns=("a",), engagement_id=eng.id)

        # sqlite3.Connection-Methoden sind read-only (C-Typ) → Zähl-Proxy.
        proxy = _CountingConn(conn)
        DatasetRepo(proxy).create(dataset, iter(rows))  # type: ignore[arg-type]

        assert proxy.dataset_rows_executemany == 1
        db.close()


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------


def _make_rich_xlsx(tmp_path: Path, n_rows: int = 12) -> Path:
    """xlsx mit gemischten Typen: Text (Nicht-ASCII), int, float, datetime,
    date, time, Nullwerte."""
    path = tmp_path / f"rich_{n_rows}.xlsx"
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Daten"
    ws.append(["name", "betrag", "menge", "wann", "tag", "uhr", "notiz"])
    for i in range(1, n_rows + 1):
        ws.append(
            [
                f"Straße {i} – Zürich €",
                round(0.1 * i, 4),
                100 + i,
                datetime(2024, 1, 1, 8, 0, 0) + timedelta(minutes=i),
                date(2024, 6, (i % 28) + 1),
                dt_time(i % 24, 30, 0),
                None if i % 5 == 0 else f"Beleg №{i}",
            ]
        )
    wb.save(path)
    return path


def _drain_setting_token_at(
    rows: object, consumed: list[DatasetRow], token: CancellationToken, n: int
) -> None:
    """Konsumiert den Row-Iterator und setzt das Token nach ``n`` Zeilen."""
    for row in rows:  # type: ignore[attr-defined]
        consumed.append(row)
        if len(consumed) == n:
            token.set()


class _CountingConn:
    """Dünner Proxy um eine sqlite3.Connection, der `executemany` in die
    `dataset_rows`-Tabelle zählt (Instanz-Attribute des C-Typs sind read-only)."""

    def __init__(self, real: sqlite3.Connection) -> None:
        self._real = real
        self.dataset_rows_executemany = 0

    def executemany(self, sql: str, params: Iterable[Any]) -> sqlite3.Cursor:
        if "dataset_rows" in sql:
            self.dataset_rows_executemany += 1
        return self._real.executemany(sql, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


def _persist_and_read_back(db_path: Path, rows: list[DatasetRow]) -> list[DatasetRow]:
    """Persistiert die Rows (Worker-Muster) und liest sie zurück."""
    db = Database(db_path)
    db.migrate()
    conn = db.connect()
    eng = EngagementRepo(conn).get_or_create(
        Engagement(
            auditor_name="Anna",
            auditor_position="Senior",
            client_name="ACME",
            audit_type="ISAE 3402",
        )
    )
    columns = tuple(rows[0].values.keys()) if rows else ()
    dataset = Dataset(name="ds", columns=columns, engagement_id=eng.id)
    with db.session() as session_conn:
        stored = DatasetRepo(session_conn).create(dataset, iter(rows))
    assert stored.id is not None
    repo = DatasetRepo(conn)
    readback = repo.get_rows_in_range(stored.id, 1, len(rows) + 1)
    db.close()
    return readback


def _assert_rows_identical(readback: list[DatasetRow], original: list[DatasetRow]) -> None:
    assert len(readback) == len(original)
    for got, want in zip(readback, original, strict=True):
        assert got.row_id == want.row_id
        assert got.values == want.values
        for col, want_val in want.values.items():
            assert type(got.values[col]) is type(want_val), (
                f"Typ-Drift bei Spalte '{col}': {type(got.values[col])} != {type(want_val)}"
            )
