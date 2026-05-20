# Sprint 19 – P-005 + F-007 + F-006 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drei Review-Findings in einem Branch: SQL-`DISTINCT` statt `get_all_rows` im Advanced-Sampling-Dialog (P-005), `repositories.py` in Einzelmodule splitten (F-007), `main_window.py` in Builder-Funktionen + State-Controller splitten (F-006).

**Architecture:** P-005 fügt `DatasetRepo.distinct_values` (SQL `json_extract` + `GROUP BY raw,jtype` + `MIN(row_index)`) hinzu und ersetzt den `rows`-Parameter des Sampling-Dialogs durch einen `distinct_values_provider`-Callback. F-007 zieht jede Repo-Klasse in ein eigenes Modul, `repositories.py` wird Re-Export-Fassade. F-006 extrahiert Menü-/Toolbar-/Layout-Aufbau in freie Builder-Funktionen und kapselt QSettings-/Panel-State in `WindowStateController`; `MainWindow` behält Backward-Compat-Shims.

**Tech Stack:** Python 3.13, PyQt6, SQLite (sqlite3 + orjson), pytest/pytest-qt, ruff, mypy strict.

**Branch:** `feat/sprint-19-distinct-and-splits` (existiert bereits, Design-Doc-Commit `4699fb5`).

**Verbindliche Regeln über alle Tasks:**
- TDD: erst der rote Test, dann Implementierung, dann grün, dann Commit.
- Nach jedem Task: `pytest -q`, `ruff check .`, `ruff format --check .`, `mypy src tests` müssen grün sein.
- Staging immer datei-explizit (`git add <pfad> ...`), **nie** `git add .` (Worktree hat untracked `SPRINT_19_PROMPT.md` + modifizierte `CLAUDE.md`, die nicht in die Task-Commits gehören).
- `core/sampling.py` / `core/rng.py` werden **nicht** angefasst.
- Commit-Trailer: `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.

---

## Phase 0 – Baseline

### Task 0: Grünen Ausgangszustand verifizieren

**Files:** keine.

- [ ] **Step 1: Voll-Suite laufen lassen**

Run: `pytest -q`
Expected: PASS, 681 Tests (alle grün). Falls rot: STOPP, Ursache klären, bevor irgendetwas geändert wird.

- [ ] **Step 2: Lint + Format + Typecheck**

Run: `ruff check . && ruff format --check . && mypy src tests`
Expected: alle drei ohne Fehler.

- [ ] **Step 3: kein Commit**

Phase 0 ändert nichts.

---

## Phase 1 – P-005: SQL-DISTINCT statt `get_all_rows`

### Task 1: `DatasetRepo.distinct_values` + Repro-Test

**Files:**
- Create: `tests/integration/test_distinct_values.py`
- Modify: `src/sampling_tool/persistence/repositories.py` (neue Methode in `DatasetRepo`, neue Modul-Funktion `_distinct_decode`)

- [ ] **Step 1: Failing-Test-Datei schreiben**

Create `tests/integration/test_distinct_values.py`:

```python
"""DatasetRepo.distinct_values – SQL-DISTINCT statt get_all_rows (Sprint 19 / P-005)."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

import pytest

from sampling_tool.core.models import Dataset, DatasetRow
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import DatasetRepo, EngagementRepo
from sampling_tool.core.models import Engagement

pytestmark = pytest.mark.integration


def _engagement_id(db: Database) -> int:
    eng = EngagementRepo(db.connect()).get_or_create(
        Engagement(
            auditor_name="A", client_name="C", auditor_position="S", audit_type="ISAE 3402"
        )
    )
    assert eng.id is not None
    return eng.id


def _persist(db: Database, eng_id: int, rows: list[DatasetRow], columns: tuple[str, ...]) -> int:
    repo = DatasetRepo(db.connect())
    ds = repo.create(
        Dataset(name="t", columns=columns, engagement_id=eng_id), tuple(rows)
    )
    assert ds.id is not None
    return ds.id


def _reference_distinct(rows: list[DatasetRow], field: str) -> list[Any]:
    """Oracle – repliziert die ursprüngliche _distinct_values-Semantik exakt."""
    seen: set[str] = set()
    result: list[Any] = []
    for row in rows:
        value = row.values.get(field)
        if value is None:
            continue
        key = repr(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    result.sort(key=lambda v: str(v))
    return result


class TestDistinctValues:
    def test_returns_distinct_strings_sorted(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = [
            DatasetRow(row_id=1, values={"Land": "DEU"}),
            DatasetRow(row_id=2, values={"Land": "AUT"}),
            DatasetRow(row_id=3, values={"Land": "DEU"}),
            DatasetRow(row_id=4, values={"Land": "CHE"}),
        ]
        ds_id = _persist(db, eng, rows, ("Land",))
        assert DatasetRepo(db.connect()).distinct_values(ds_id, "Land") == ["AUT", "CHE", "DEU"]

    def test_skips_none_values(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = [
            DatasetRow(row_id=1, values={"Land": "AUT"}),
            DatasetRow(row_id=2, values={"Land": None}),
            DatasetRow(row_id=3, values={"Land": "CHE"}),
        ]
        ds_id = _persist(db, eng, rows, ("Land",))
        assert DatasetRepo(db.connect()).distinct_values(ds_id, "Land") == ["AUT", "CHE"]

    def test_handles_datetime_column(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = [
            DatasetRow(row_id=1, values={"Ts": datetime(2026, 1, 2, 9, 0, 0)}),
            DatasetRow(row_id=2, values={"Ts": datetime(2026, 1, 1, 9, 0, 0)}),
            DatasetRow(row_id=3, values={"Ts": datetime(2026, 1, 2, 9, 0, 0)}),
        ]
        ds_id = _persist(db, eng, rows, ("Ts",))
        result = DatasetRepo(db.connect()).distinct_values(ds_id, "Ts")
        assert result == [datetime(2026, 1, 1, 9, 0, 0), datetime(2026, 1, 2, 9, 0, 0)]

    def test_handles_date_and_time_columns(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = [
            DatasetRow(row_id=1, values={"D": date(2026, 1, 2), "T": time(8, 30)}),
            DatasetRow(row_id=2, values={"D": date(2026, 1, 1), "T": time(8, 30)}),
        ]
        ds_id = _persist(db, eng, rows, ("D", "T"))
        repo = DatasetRepo(db.connect())
        assert repo.distinct_values(ds_id, "D") == [date(2026, 1, 1), date(2026, 1, 2)]
        assert repo.distinct_values(ds_id, "T") == [time(8, 30)]

    def test_distinguishes_int_from_float(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = [
            DatasetRow(row_id=1, values={"N": 5}),
            DatasetRow(row_id=2, values={"N": 5.0}),
        ]
        ds_id = _persist(db, eng, rows, ("N",))
        result = DatasetRepo(db.connect()).distinct_values(ds_id, "N")
        assert result == _reference_distinct(rows, "N")
        assert any(isinstance(v, int) for v in result)
        assert any(isinstance(v, float) for v in result)

    def test_handles_bool_column(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = [
            DatasetRow(row_id=1, values={"B": True}),
            DatasetRow(row_id=2, values={"B": False}),
            DatasetRow(row_id=3, values={"B": True}),
        ]
        ds_id = _persist(db, eng, rows, ("B",))
        result = DatasetRepo(db.connect()).distinct_values(ds_id, "B")
        assert result == _reference_distinct(rows, "B")
        assert all(isinstance(v, bool) for v in result)

    def test_column_name_with_spaces(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = [
            DatasetRow(row_id=1, values={"Mit Leerzeichen": "x"}),
            DatasetRow(row_id=2, values={"Mit Leerzeichen": "y"}),
        ]
        ds_id = _persist(db, eng, rows, ("Mit Leerzeichen",))
        assert DatasetRepo(db.connect()).distinct_values(ds_id, "Mit Leerzeichen") == ["x", "y"]

    def test_empty_dataset_returns_empty_list(self, db: Database) -> None:
        eng = _engagement_id(db)
        ds_id = _persist(db, eng, [], ("Land",))
        assert DatasetRepo(db.connect()).distinct_values(ds_id, "Land") == []

    def test_missing_column_returns_empty_list(self, db: Database) -> None:
        eng = _engagement_id(db)
        rows = [DatasetRow(row_id=1, values={"Land": "AUT"})]
        ds_id = _persist(db, eng, rows, ("Land",))
        assert DatasetRepo(db.connect()).distinct_values(ds_id, "GibtsNicht") == []


class TestDistinctValuesReproducibility:
    """KERN-Test: SQL-Pfad muss bit-identisch zum alten RAM-Pfad sein –
    inklusive str()-Gleichstand-Tie-Break über die Zeilen-Reihenfolge."""

    def test_sql_path_matches_ram_reference_all_types(self, db: Database) -> None:
        eng = _engagement_id(db)
        # `mixed` enthält bewusst: int 5 UND str "5" (gleicher str(),
        # anderer Wert), ein nicht-benachbartes Duplikat von "5" (row 2 und
        # row 7), float, bool, datetime, None. `none_haltig` testet das
        # None-Überspringen. Reine Ein-Typ-Spalten beweisen die
        # Bit-Gleichheit beim Tie-Break NICHT.
        rows = [
            DatasetRow(row_id=1, values={
                "mixed": 5, "none_haltig": "a", "txt": "delta",
                "zahl": 30, "fl": 1.5, "ts": datetime(2026, 3, 1, 8, 0)}),
            DatasetRow(row_id=2, values={
                "mixed": "5", "none_haltig": None, "txt": "alpha",
                "zahl": 10, "fl": 0.5, "ts": datetime(2026, 1, 1, 8, 0)}),
            DatasetRow(row_id=3, values={
                "mixed": 5.0, "none_haltig": "b", "txt": "delta",
                "zahl": 20, "fl": 1.5, "ts": datetime(2026, 2, 1, 8, 0)}),
            DatasetRow(row_id=4, values={
                "mixed": True, "none_haltig": None, "txt": "charlie",
                "zahl": 10, "fl": 2.5, "ts": datetime(2026, 1, 1, 8, 0)}),
            DatasetRow(row_id=5, values={
                "mixed": "apfel", "none_haltig": "a", "txt": "bravo",
                "zahl": 30, "fl": 0.5, "ts": datetime(2026, 3, 1, 8, 0)}),
            DatasetRow(row_id=6, values={
                "mixed": None, "none_haltig": "c", "txt": "alpha",
                "zahl": 40, "fl": 3.5, "ts": datetime(2026, 4, 1, 8, 0)}),
            DatasetRow(row_id=7, values={
                "mixed": "5", "none_haltig": None, "txt": "delta",
                "zahl": 20, "fl": 1.5, "ts": datetime(2026, 2, 1, 8, 0)}),
            DatasetRow(row_id=8, values={
                "mixed": 10, "none_haltig": "a", "txt": "echo",
                "zahl": 50, "fl": 2.5, "ts": datetime(2026, 5, 1, 8, 0)}),
        ]
        columns = ("mixed", "none_haltig", "txt", "zahl", "fl", "ts")
        ds_id = _persist(db, eng, rows, columns)
        repo = DatasetRepo(db.connect())
        for field in columns:
            assert repo.distinct_values(ds_id, field) == _reference_distinct(rows, field), field
```

- [ ] **Step 2: Test ausführen, Rot bestätigen**

Run: `pytest tests/integration/test_distinct_values.py -q --no-cov`
Expected: FAIL — `AttributeError: 'DatasetRepo' object has no attribute 'distinct_values'`.

- [ ] **Step 3: `distinct_values` + `_distinct_decode` implementieren**

In `src/sampling_tool/persistence/repositories.py`: am Ende der `DatasetRepo`-Klasse (nach `delete`, vor dem `SampleRepo`-Trennkommentar bei Zeile ~420) diese Methode einfügen:

```python
    def distinct_values(self, dataset_id: int, column: str) -> list[Any]:
        """Distinkte Nicht-None-Werte einer Dataset-Spalte – via SQL, ohne Row-Materialize.

        Ersetzt den `get_all_rows()`-Pfad des Advanced-Sampling-Dialogs (P-005).
        Bit-identisch zum bisherigen `_distinct_values(get_all_rows(...), column)`:
        None überspringen, Dedup über `repr(value)`, Sortierung über `str(value)`.
        RAM ~ Anzahl distinkter Werte (nicht Zeilenzahl).

        Tie-Break: bei `str()`-Gleichstand zweier verschiedener Werte
        (z. B. int 5 und str "5") entscheidet das früheste `row_index` –
        repliziert die Stable-Sort-First-Occurrence-Ordnung des alten
        RAM-Pfads.

        Limitierung: Spaltennamen mit eingebettetem `"` sind nicht abgedeckt
        (pathologisch bei Excel-Headern) – ein solcher Filter liefert eine
        leere Liste statt eines Crashs. Der JSON-Pfad wird als gebundener
        Parameter übergeben; SQL-Injection ist ausgeschlossen.
        """
        json_path = '$."' + column.replace('"', '""') + '"'
        cur = self.conn.execute(
            "SELECT json_extract(values_json, ?) AS raw, "
            "       json_type(values_json, ?) AS jtype, "
            "       MIN(row_index) AS first_idx "
            "FROM dataset_rows WHERE dataset_id = ? "
            "GROUP BY raw, jtype",
            (json_path, json_path, dataset_id),
        )
        decoded: list[tuple[Any, int]] = []
        seen: set[str] = set()
        for row in cur:
            jtype = row["jtype"]
            if jtype is None or jtype == "null":
                continue
            value = _distinct_decode(row["raw"], jtype)
            key = repr(value)
            if key in seen:
                continue
            seen.add(key)
            decoded.append((value, int(row["first_idx"])))
        decoded.sort(key=lambda item: (str(item[0]), item[1]))
        return [value for value, _ in decoded]
```

Und im JSON-Helfer-Block am Dateiende (nach `_values_from_json`) die Modul-Funktion ergänzen:

```python
def _distinct_decode(raw: Any, jtype: str) -> Any:
    """Rekonstruiert einen Python-Wert aus json_extract-Rohwert + json_type.

    Bool wird aus `jtype` rekonstruiert, NICHT aus `raw` – json_extract
    liefert für JSON-Booleans `1`/`0`, sonst ginge bool vs. int verloren.
    `object` ist ein tagged datetime/date/time (siehe `_encode_value`).
    """
    if jtype == "object":
        return _decode_value(_json_loads(raw))
    if jtype == "true":
        return True
    if jtype == "false":
        return False
    if jtype == "integer":
        return int(raw)
    if jtype == "real":
        return float(raw)
    if jtype == "text":
        return str(raw)
    return raw
```

- [ ] **Step 4: Test ausführen, Grün bestätigen**

Run: `pytest tests/integration/test_distinct_values.py -q --no-cov`
Expected: PASS — 11 Tests grün.

- [ ] **Step 5: Voll-Checks**

Run: `pytest -q && ruff check . && ruff format --check . && mypy src tests`
Expected: alles grün (692 Tests).

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_distinct_values.py src/sampling_tool/persistence/repositories.py
git commit -m "$(cat <<'EOF'
Sprint 19: DatasetRepo.distinct_values via SQL json_extract (P-005)

GROUP BY raw,jtype + MIN(row_index), Sort nach (str(value), first_idx) –
bit-identisch zum get_all_rows-RAM-Pfad inkl. Tie-Break.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `SamplingDialog` – `rows` → `distinct_values_provider`

**Files:**
- Modify: `src/sampling_tool/ui/dialogs/sampling_dialog.py`
- Modify: `tests/ui/test_sampling_dialog.py`

- [ ] **Step 1: Tests anpassen + neue Provider-Tests schreiben (Rot)**

In `tests/ui/test_sampling_dialog.py`:

(a) Import-Block (Zeilen 9–17) ersetzen — `DatasetRow` entfernen, `Any`/`Callable` ergänzen:

```python
from collections.abc import Callable
from typing import Any

from sampling_tool.core.models import (
    Dataset,
    SampleConfig,
    SampleResult,
    SamplingMethod,
    StratifyMode,
)
```

(b) `_make_dataset()` (Zeilen 22–38) komplett ersetzen — liefert künftig `(Dataset, provider)` statt `(Dataset, rows)`, damit alle `SamplingDialog(*_make_dataset(), ...)`-Aufrufer unverändert bleiben:

```python
def _make_dataset() -> tuple[Dataset, Callable[[str], list[Any]]]:
    """Sprint 19 / P-005: Dataset (Metadaten) + distinct-values-Provider."""
    distinct: dict[str, list[Any]] = {
        "Land": ["AUT", "CHE", "DEU"],
        "Konto": [f"K{i:03d}" for i in range(1, 13)],
        "Betrag": [i * 10 for i in range(1, 13)],
    }
    dataset = Dataset(name="t", columns=("Land", "Konto", "Betrag"), row_count=12)
    return dataset, lambda field: distinct.get(field, [])
```

(c) Zeile 106 (`test_validation_blocks_cluster_without_field`): `SamplingDialog(ds, (), advanced_mode=True)` → `SamplingDialog(ds, advanced_mode=True)`.

(d) In `test_resample_checkbox_updates_size_hint` (Z. 130–131) und `test_hint_updatet_bei_filter_toggle` (Z. 259–266) die lokale Variable `rows` zu `provider` umbenennen: `ds, provider = _make_dataset()` und `SamplingDialog(ds, provider, current_sample=..., advanced_mode=...)`.

(e) Am Dateiende neue Test-Klasse anhängen:

```python
class TestSamplingDialogDistinctProvider:
    """Sprint 19 / P-005: Filter-Werte kommen über den Provider-Callback."""

    def test_advanced_filter_values_use_provider(self, qtbot: QtBot) -> None:
        dialog = SamplingDialog(*_make_dataset(), advanced_mode=True)
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Land")
        items = {dialog._filter_value.itemText(i) for i in range(dialog._filter_value.count())}
        assert items == {"AUT", "CHE", "DEU"}

    def test_provider_called_with_selected_field(self, qtbot: QtBot) -> None:
        seen: list[str] = []
        dataset, _ = _make_dataset()

        def provider(field: str) -> list[Any]:
            seen.append(field)
            return ["x", "y"]

        dialog = SamplingDialog(dataset, provider, advanced_mode=True)
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Konto")
        assert "Konto" in seen

    def test_no_provider_yields_empty_value_combo(self, qtbot: QtBot) -> None:
        dataset, _ = _make_dataset()
        dialog = SamplingDialog(dataset, None, advanced_mode=True)
        qtbot.addWidget(dialog)
        dialog._filter_field.setCurrentText("Land")
        assert dialog._filter_value.count() == 0
```

- [ ] **Step 2: Tests ausführen, Rot bestätigen**

Run: `pytest tests/ui/test_sampling_dialog.py -q --no-cov`
Expected: FAIL — die neuen Tests + `test_filter_field_change_populates_values` scheitern, weil `SamplingDialog` noch den `rows`-Parameter hat (`_make_dataset` liefert jetzt einen Callable, kein Tuple).

- [ ] **Step 3: `sampling_dialog.py` umstellen**

(a) Imports (Zeilen 14–17): `from collections.abc import Sequence` → `from collections.abc import Callable, Sequence`.

(b) `core.models`-Import (Zeilen 45–52): `DatasetRow` entfernen:

```python
from sampling_tool.core.models import (
    Dataset,
    SampleConfig,
    SampleResult,
    SamplingMethod,
    StratifyMode,
)
```

(c) Konstruktor (Zeilen 73–104): den `rows`-Parameter durch `distinct_values_provider` ersetzen, `self._rows` durch `self._distinct_values_provider`, `_max_population` auf `dataset.row_count`:

```python
    def __init__(
        self,
        dataset: Dataset,
        distinct_values_provider: Callable[[str], Sequence[Any]] | None = None,
        current_sample: SampleResult | None = None,
        parent: QWidget | None = None,
        *,
        advanced_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Neue Stichprobe")
        self.setModal(True)
        self.setMinimumWidth(520)

        self._dataset = dataset
        # Sprint 19 / P-005: kein Row-Materialize mehr – der Controller
        # injiziert einen distinct-Werte-Provider (SQL-basiert). None im
        # Simple-Mode (dort gibt es kein Filter-Feld).
        self._distinct_values_provider = distinct_values_provider
        self._current_sample = current_sample
        self._result: SamplingDialogResult | None = None
        self._columns = list(dataset.columns)
        self._max_population = max(dataset.row_count, 1)
        self._advanced_mode = advanced_mode

        self._build_ui()
        self._wire_signals()
        if self._advanced_mode:
            self._refresh_filter_values()
            self._on_method_changed()
        self._validate()
```

(d) `_refresh_filter_values` (Zeilen 312–323) ersetzen:

```python
    def _refresh_filter_values(self) -> None:
        field = self._filter_field.currentText()
        self._filter_value.blockSignals(True)
        self._filter_value.clear()
        if field == NO_FILTER_LABEL or not field or self._distinct_values_provider is None:
            self._filter_value.setEnabled(False)
        else:
            self._filter_value.setEnabled(True)
            for value in self._distinct_values_provider(field):
                self._filter_value.addItem(_display(value), userData=value)
        self._filter_value.blockSignals(False)
        self._validate()
```

(e) Die Modul-Funktion `_distinct_values` (Zeilen 459–472) **ersatzlos löschen**.

- [ ] **Step 4: Tests ausführen, Grün bestätigen**

Run: `pytest tests/ui/test_sampling_dialog.py -q --no-cov`
Expected: PASS — alle (inkl. 3 neue) grün.

- [ ] **Step 5: Voll-Checks**

Run: `pytest -q && ruff check . && ruff format --check . && mypy src tests`
Expected: alles grün.

- [ ] **Step 6: Commit**

```bash
git add src/sampling_tool/ui/dialogs/sampling_dialog.py tests/ui/test_sampling_dialog.py
git commit -m "$(cat <<'EOF'
Sprint 19: SamplingDialog nutzt distinct_values_provider statt rows (P-005)

Dialog importiert kein persistence mehr; _max_population aus
dataset.row_count.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `_factories.py` + `workspace_controller.py` umverdrahten

**Files:**
- Modify: `src/sampling_tool/ui/controllers/_factories.py`
- Modify: `src/sampling_tool/ui/controllers/workspace_controller.py`
- Modify: `tests/ui/test_main_controller.py`

- [ ] **Step 1: Controller-Tests schreiben/anpassen (Rot)**

In `tests/ui/test_main_controller.py`:

(a) In `TestAdvancedModePropagation` (Z. 1830–1838 und Z. 1865–1873): in beiden `fake_factory`-Definitionen den Parameter `_rows: object` zu `_provider: object` umbenennen (rein kosmetisch – der Parameter bedeutet jetzt einen Provider-Callback).

(b) Direkt nach `TestAdvancedModePropagation` (vor dem `# Sprint 9.4`-Kommentarblock bei Zeile 1889) neue Klasse einfügen:

```python
class TestNewSamplingDistinctProvider:
    """Sprint 19 / P-005: Advanced-Mode reicht einen Provider-Callback durch,
    get_all_rows wird beim Dialog-Open NICHT mehr aufgerufen."""

    def test_advanced_mode_passes_provider_not_rows(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        from dataclasses import replace as dc_replace

        from sampling_tool.ui.settings_store import AppSettings

        captured: dict[str, object] = {}

        def fake_factory(
            _parent: MainWindow,
            _dataset: object,
            provider: object,
            _current: object,
            _advanced: bool,
        ) -> _StubSamplingDialog:
            captured["provider"] = provider
            return _StubSamplingDialog(None, accept=False)

        controller = MainController(
            window,
            recent_store=recent_store,
            sampling_dialog_factory=fake_factory,  # type: ignore[arg-type]
            settings=dc_replace(AppSettings.defaults(), advanced_mode=True),
        )
        try:
            _open_dataset(controller, window, populated_db)
            controller.handle_new_sampling()
            provider = captured["provider"]
            assert callable(provider)
            assert provider("Konto") == ["K1", "K2", "K3", "K4", "K5"]
        finally:
            controller.handle_close_engagement()

    def test_simple_mode_passes_none_provider(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
    ) -> None:
        from dataclasses import replace as dc_replace

        from sampling_tool.ui.settings_store import AppSettings

        captured: dict[str, object] = {}

        def fake_factory(
            _parent: MainWindow,
            _dataset: object,
            provider: object,
            _current: object,
            _advanced: bool,
        ) -> _StubSamplingDialog:
            captured["provider"] = provider
            return _StubSamplingDialog(None, accept=False)

        controller = MainController(
            window,
            recent_store=recent_store,
            sampling_dialog_factory=fake_factory,  # type: ignore[arg-type]
            settings=dc_replace(AppSettings.defaults(), advanced_mode=False),
        )
        try:
            _open_dataset(controller, window, populated_db)
            controller.handle_new_sampling()
            assert captured["provider"] is None
        finally:
            controller.handle_close_engagement()

    def test_get_all_rows_not_called_on_dialog_open(
        self,
        window: MainWindow,
        recent_store: RecentEngagementsStore,
        populated_db: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from dataclasses import replace as dc_replace

        from sampling_tool.persistence.repositories import DatasetRepo
        from sampling_tool.ui.settings_store import AppSettings

        def boom(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("get_all_rows darf im Advanced-Sampling-Pfad nicht aufgerufen werden")

        monkeypatch.setattr(DatasetRepo, "get_all_rows", boom)

        factory = lambda _p, _d, _r, _s, _am: _StubSamplingDialog(None, accept=False)  # noqa: E731
        controller = MainController(
            window,
            recent_store=recent_store,
            sampling_dialog_factory=factory,  # type: ignore[arg-type]
            settings=dc_replace(AppSettings.defaults(), advanced_mode=True),
        )
        try:
            _open_dataset(controller, window, populated_db)
            controller.handle_new_sampling()  # darf NICHT in boom() laufen
        finally:
            controller.handle_close_engagement()
```

- [ ] **Step 2: Tests ausführen, Rot bestätigen**

Run: `pytest tests/ui/test_main_controller.py::TestNewSamplingDistinctProvider -q --no-cov`
Expected: FAIL — `test_advanced_mode_passes_provider_not_rows` scheitert, weil der Controller noch ein Row-Tuple (kein Callable) übergibt; `test_get_all_rows_not_called_on_dialog_open` scheitert, weil `handle_new_sampling` noch `get_all_rows` aufruft.

- [ ] **Step 3: `_factories.py` umstellen**

(a) Imports: `from typing import TYPE_CHECKING` → `from typing import TYPE_CHECKING, Any`. `from sampling_tool.core.models import Dataset, DatasetRow, Engagement, SampleResult` → `from sampling_tool.core.models import Dataset, Engagement, SampleResult`.

(b) `SamplingDialogFactory` (Zeilen 43–46):

```python
SamplingDialogFactory = Callable[
    ["MainWindow", Dataset, Callable[[str], Sequence[Any]] | None, SampleResult | None, bool],
    SamplingDialog,
]
```

(c) `default_sampling_factory` (Zeilen 107–120):

```python
def default_sampling_factory(
    parent: MainWindow,
    dataset: Dataset,
    distinct_values_provider: Callable[[str], Sequence[Any]] | None,
    current_sample: SampleResult | None,
    advanced_mode: bool,
) -> SamplingDialog:
    return SamplingDialog(
        dataset,
        distinct_values_provider,
        current_sample=current_sample,
        parent=parent,
        advanced_mode=advanced_mode,
    )
```

- [ ] **Step 4: `workspace_controller.py` umstellen**

(a) Imports: `from collections.abc import Iterable` → `from collections.abc import Callable, Iterable`. Neue Zeile `from typing import Any` ergänzen (isort-korrekt einsortieren — nach `from pathlib import Path`). `DatasetRow` wird im `core.models`-Import noch von `_build_sampling_iterator` gebraucht → bleibt.

(b) In `handle_new_sampling` die Zeilen 196–206 (Kommentar + `repo`/`dialog_rows`/`dialog`) ersetzen:

```python
        # Sprint 19 / P-005: Advanced-Mode bekommt einen distinct-Werte-
        # Provider statt einem voll materialisierten Row-Tuple. Der Dialog
        # ruft den Callback lazy beim Filter-Spalten-Wechsel – RAM ~ Anzahl
        # distinkter Werte statt Zeilenzahl, kein get_all_rows mehr.
        repo = DatasetRepo(s.db.connect())
        dataset_id = s.dataset.id
        distinct_provider: Callable[[str], Sequence[Any]] | None = (
            (lambda col: repo.distinct_values(dataset_id, col))
            if s.settings.advanced_mode
            else None
        )
        dialog = self._factories.sampling(
            s.window, s.dataset, distinct_provider, s.sample, s.settings.advanced_mode
        )
```

Hinweis: `dataset_id` ist eine lokale `int`-Variable (nach `assert s.dataset.id is not None` in Zeile 193) — bewusst lokal gecaptured, damit mypy das Lambda-Closure ohne Attribut-Narrowing-Probleme akzeptiert. `Sequence` muss im `collections.abc`-Import von `workspace_controller.py` vorhanden sein → ergänzen falls nicht (`from collections.abc import Callable, Iterable, Sequence`).

- [ ] **Step 5: Tests ausführen, Grün bestätigen**

Run: `pytest tests/ui/test_main_controller.py -q --no-cov`
Expected: PASS — inkl. `TestNewSamplingDistinctProvider` (3 neu) und `TestAdvancedModePropagation`.

- [ ] **Step 6: Voll-Checks**

Run: `pytest -q && ruff check . && ruff format --check . && mypy src tests`
Expected: alles grün (~698 Tests). Phase 1 (P-005) komplett.

- [ ] **Step 7: Commit**

```bash
git add src/sampling_tool/ui/controllers/_factories.py src/sampling_tool/ui/controllers/workspace_controller.py tests/ui/test_main_controller.py
git commit -m "$(cat <<'EOF'
Sprint 19: handle_new_sampling injiziert distinct-Provider statt get_all_rows (P-005)

Advanced-Sampling-Dialog ohne 1-GB-RAM-Spike auf 1M-Datasets.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2 – F-007: `repositories.py` in Module splitten

> **Import-Disziplin (verbindlich):** Jedes neue Repo-Modul importiert `savepoint`
> aus `sampling_tool.persistence.database` und JSON-Helfer aus
> `sampling_tool.persistence._json` — **nie** über `sampling_tool.persistence.repositories`.
> Die Fassade importiert FROM den Modulen; eine Rück-Kante baut einen Zyklus.
>
> Jeder Move-Task hält `repositories.py` funktionsfähig: die verschobene Klasse
> wird dort sofort re-importiert, damit alle Konsumenten grün bleiben.

### Task 4: `persistence/_json.py` anlegen

**Files:**
- Create: `src/sampling_tool/persistence/_json.py`
- Modify: `src/sampling_tool/persistence/repositories.py`

- [ ] **Step 1: `_json.py` erstellen**

Create `src/sampling_tool/persistence/_json.py` mit folgendem Kopf, danach die JSON-Helfer **verbatim** aus `repositories.py` übernehmen: `_json_dumps`/`_json_loads` (aktuell Z. 37–44), `_json_or_none`/`_json_or_none_load` (Z. 896–908), `_TYPE_KEY`/`_VAL_KEY`/`_encode_value`/`_decode_value`/`_values_to_json`/`_values_from_json` (Z. 919–955):

```python
"""JSON-Helfer der Persistenz-Schicht (Sprint 19 / F-007).

orjson-Wrapper + tagged Encoder für datetime/date/time. Vorher in
repositories.py – herausgezogen, damit die Repo-Einzelmodule sie teilen.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Final

import orjson


# <hier: _json_dumps, _json_loads verbatim aus repositories.py:37-44>
# <hier: _json_or_none, _json_or_none_load verbatim aus repositories.py:896-908>
# <hier: _TYPE_KEY, _VAL_KEY, _encode_value, _decode_value, _values_to_json,
#        _values_from_json verbatim aus repositories.py:919-955>
```

- [ ] **Step 2: `repositories.py` auf `_json` umstellen**

In `repositories.py`: die acht Helfer-Definitionen (`_json_dumps`, `_json_loads`, `_json_or_none`, `_json_or_none_load`, `_TYPE_KEY`, `_VAL_KEY`, `_encode_value`, `_decode_value`, `_values_to_json`, `_values_from_json`) **löschen** und stattdessen oben importieren:

```python
from sampling_tool.persistence._json import (
    _decode_value,
    _encode_value,
    _json_dumps,
    _json_loads,
    _json_or_none,
    _json_or_none_load,
    _values_from_json,
    _values_to_json,
)
```

Jetzt nicht mehr gebrauchte Imports in `repositories.py` aufräumen (`orjson`, ggf. `date`/`time`/`Final` aus den `datetime`/`typing`-Importen) — `ruff check --fix src/sampling_tool/persistence/repositories.py` erledigt das deterministisch; danach Ergebnis sichten.

- [ ] **Step 3: Checks**

Run: `pytest -q && ruff check . && ruff format --check . && mypy src tests`
Expected: alles grün (unverändert ~698 Tests) — `repositories.py` re-exportiert die Helfer weiterhin transparent.

- [ ] **Step 4: Commit**

```bash
git add src/sampling_tool/persistence/_json.py src/sampling_tool/persistence/repositories.py
git commit -m "$(cat <<'EOF'
Sprint 19: JSON-Helfer nach persistence/_json.py extrahiert (F-007)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `engagement_repo.py` + `dataset_repo.py`

**Files:**
- Create: `src/sampling_tool/persistence/engagement_repo.py`
- Create: `src/sampling_tool/persistence/dataset_repo.py`
- Modify: `src/sampling_tool/persistence/repositories.py`

- [ ] **Step 1: `engagement_repo.py` erstellen**

Create `src/sampling_tool/persistence/engagement_repo.py`. Kopf wie folgt, danach die Klasse `EngagementRepo` **verbatim** aus `repositories.py` (aktuell Z. 52–147):

```python
"""EngagementRepo – 1 Zeile pro DB-Datei (Sprint 19 / F-007-Split)."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

from sampling_tool.core.models import Engagement
from sampling_tool.persistence.database import savepoint


# <hier: class EngagementRepo verbatim>
```

- [ ] **Step 2: `dataset_repo.py` erstellen**

Create `src/sampling_tool/persistence/dataset_repo.py`. Kopf wie folgt, danach die Klasse `DatasetRepo` (inkl. der in Task 1 ergänzten `distinct_values`-Methode) **verbatim** + die Modul-Funktion `_distinct_decode` **verbatim** aus `repositories.py`:

```python
"""DatasetRepo – Datasets + DatasetRows, inkl. distinct_values (Sprint 19 / F-007-Split)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import replace
from typing import Any, ClassVar

from sampling_tool.core.cancellation import CancellationToken
from sampling_tool.core.models import Dataset, DatasetRow
from sampling_tool.persistence._json import (
    _decode_value,
    _json_dumps,
    _json_loads,
    _values_from_json,
    _values_to_json,
)
from sampling_tool.persistence.database import savepoint


# <hier: class DatasetRepo verbatim>
# <hier: def _distinct_decode verbatim>
```

- [ ] **Step 3: `repositories.py` auf Re-Import umstellen**

`EngagementRepo`, `DatasetRepo` und `_distinct_decode` aus `repositories.py` **löschen**, stattdessen importieren:

```python
from sampling_tool.persistence.dataset_repo import DatasetRepo
from sampling_tool.persistence.engagement_repo import EngagementRepo
```

Danach `ruff check --fix src/sampling_tool/persistence/repositories.py` (entfernt jetzt überflüssige Imports).

- [ ] **Step 4: Checks**

Run: `pytest -q && ruff check . && ruff format --check . && mypy src tests`
Expected: alles grün.

- [ ] **Step 5: Commit**

```bash
git add src/sampling_tool/persistence/engagement_repo.py src/sampling_tool/persistence/dataset_repo.py src/sampling_tool/persistence/repositories.py
git commit -m "$(cat <<'EOF'
Sprint 19: EngagementRepo + DatasetRepo in Einzelmodule (F-007)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: `sample_repo.py` + `audit_repo.py`

**Files:**
- Create: `src/sampling_tool/persistence/sample_repo.py`
- Create: `src/sampling_tool/persistence/audit_repo.py`
- Modify: `src/sampling_tool/persistence/repositories.py`

- [ ] **Step 1: `sample_repo.py` erstellen**

Create `src/sampling_tool/persistence/sample_repo.py`. Kopf wie folgt, danach `SampleRepo` **verbatim** aus `repositories.py` (aktuell Z. 425–530):

```python
"""SampleRepo – SampleResults + selektierte row_ids (Sprint 19 / F-007-Split)."""

from __future__ import annotations

import sqlite3

from sampling_tool.core.models import (
    SampleConfig,
    SampleResult,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.persistence._json import _json_or_none, _json_or_none_load
from sampling_tool.persistence.database import savepoint


# <hier: class SampleRepo verbatim>
```

- [ ] **Step 2: `audit_repo.py` erstellen**

Create `src/sampling_tool/persistence/audit_repo.py`. Kopf wie folgt, danach `AuditRepo` **verbatim** aus `repositories.py` (aktuell Z. 538–615). `AuditRepo` nutzt keinen `savepoint` → nicht importieren:

```python
"""AuditRepo – append-only Audit-Log (Sprint 19 / F-007-Split)."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from typing import Any

from sampling_tool.core.models import AuditEvent
from sampling_tool.persistence._json import _json_dumps, _json_loads


# <hier: class AuditRepo verbatim>
```

- [ ] **Step 3: `repositories.py` auf Re-Import umstellen**

`SampleRepo` und `AuditRepo` aus `repositories.py` löschen, importieren:

```python
from sampling_tool.persistence.audit_repo import AuditRepo
from sampling_tool.persistence.sample_repo import SampleRepo
```

Danach `ruff check --fix src/sampling_tool/persistence/repositories.py`.

- [ ] **Step 4: Checks**

Run: `pytest -q && ruff check . && ruff format --check . && mypy src tests`
Expected: alles grün.

- [ ] **Step 5: Commit**

```bash
git add src/sampling_tool/persistence/sample_repo.py src/sampling_tool/persistence/audit_repo.py src/sampling_tool/persistence/repositories.py
git commit -m "$(cat <<'EOF'
Sprint 19: SampleRepo + AuditRepo in Einzelmodule (F-007)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: `engagement_state_repo.py` + `undo_repo.py`

**Files:**
- Create: `src/sampling_tool/persistence/engagement_state_repo.py`
- Create: `src/sampling_tool/persistence/undo_repo.py`
- Modify: `src/sampling_tool/persistence/repositories.py`

- [ ] **Step 1: `engagement_state_repo.py` erstellen**

Create `src/sampling_tool/persistence/engagement_state_repo.py`. Kopf wie folgt, danach `EngagementState` (dataclass) + `EngagementStateRepo` **verbatim** aus `repositories.py` (aktuell Z. 623–705):

```python
"""EngagementState + EngagementStateRepo – persistierter UI-State (Sprint 19 / F-007-Split)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from sampling_tool.persistence.database import savepoint


# <hier: @dataclass class EngagementState verbatim>
# <hier: class EngagementStateRepo verbatim>
```

- [ ] **Step 2: `undo_repo.py` erstellen**

Create `src/sampling_tool/persistence/undo_repo.py`. Kopf wie folgt, danach `UndoRepo` **verbatim** aus `repositories.py` (aktuell Z. 713–888):

```python
"""UndoRepo – SQL-Persistenz für Undo/Redo-Snapshots (Sprint 19 / F-007-Split)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from sampling_tool.core.models import Snapshot, UndoStack
from sampling_tool.persistence._json import _json_dumps, _json_loads
from sampling_tool.persistence.database import savepoint


# <hier: class UndoRepo verbatim>
```

- [ ] **Step 3: `repositories.py` zur reinen Fassade machen**

`EngagementState`, `EngagementStateRepo`, `UndoRepo` aus `repositories.py` löschen. Danach besteht `repositories.py` nur noch aus Modul-Docstring + Re-Exporten. Inhalt **komplett** durch dies ersetzen:

```python
"""Backward-Compat-Fassade: re-exportiert die Repos aus ihren Einzelmodulen (Sprint 19 / F-007)."""

from __future__ import annotations

from sampling_tool.persistence._json import (
    _decode_value,
    _encode_value,
    _json_dumps,
    _json_loads,
    _json_or_none,
    _json_or_none_load,
    _values_from_json,
    _values_to_json,
)
from sampling_tool.persistence.audit_repo import AuditRepo
from sampling_tool.persistence.dataset_repo import DatasetRepo
from sampling_tool.persistence.engagement_repo import EngagementRepo
from sampling_tool.persistence.engagement_state_repo import (
    EngagementState,
    EngagementStateRepo,
)
from sampling_tool.persistence.sample_repo import SampleRepo
from sampling_tool.persistence.undo_repo import UndoRepo

__all__ = [
    "AuditRepo",
    "DatasetRepo",
    "EngagementRepo",
    "EngagementState",
    "EngagementStateRepo",
    "SampleRepo",
    "UndoRepo",
    # JSON-Helfer für Tests/Tooling, die sie heute aus diesem Modul ziehen:
    "_decode_value",
    "_encode_value",
    "_json_dumps",
    "_json_loads",
    "_json_or_none",
    "_json_or_none_load",
    "_values_from_json",
    "_values_to_json",
]
```

- [ ] **Step 4: `persistence/__init__.py`-Docstring aktualisieren (F-011)**

`src/sampling_tool/persistence/__init__.py` — Zeile 1 ersetzen:

```python
"""Persistenz-Layer: SQLite-Wrapper, Migrations und stateless Repositories."""
```

- [ ] **Step 5: Checks**

Run: `pytest -q && ruff check . && ruff format --check . && mypy src tests`
Expected: alles grün. Insbesondere müssen die bestehenden `tests/integration/test_repositories.py`, `test_undo_manager.py`, `test_engagement_state_repo.py`, `test_db_performance_helpers.py` **unverändert** grün sein.

- [ ] **Step 6: Commit**

```bash
git add src/sampling_tool/persistence/engagement_state_repo.py src/sampling_tool/persistence/undo_repo.py src/sampling_tool/persistence/repositories.py src/sampling_tool/persistence/__init__.py
git commit -m "$(cat <<'EOF'
Sprint 19: EngagementStateRepo + UndoRepo extrahiert, repositories.py = Fassade (F-007)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: F-007-Layout-Test

**Files:**
- Create: `tests/integration/test_repositories_layout.py`

- [ ] **Step 1: Layout-Test schreiben (Grün erwartet — Fassade steht bereits)**

Create `tests/integration/test_repositories_layout.py`:

```python
"""F-007: repositories.py ist Re-Export-Fassade, jeder Repo lebt im eigenen Modul."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestRepositoriesBackwardCompat:
    def test_all_repos_importable_from_repositories_facade(self) -> None:
        from sampling_tool.persistence.repositories import (
            AuditRepo,
            DatasetRepo,
            EngagementRepo,
            EngagementState,
            EngagementStateRepo,
            SampleRepo,
            UndoRepo,
        )

        for cls in (
            AuditRepo,
            DatasetRepo,
            EngagementRepo,
            EngagementState,
            EngagementStateRepo,
            SampleRepo,
            UndoRepo,
        ):
            assert cls is not None

    def test_json_helpers_reexported_from_facade(self) -> None:
        from sampling_tool.persistence.repositories import (
            _decode_value,
            _encode_value,
            _json_dumps,
            _json_loads,
            _json_or_none,
            _json_or_none_load,
            _values_from_json,
            _values_to_json,
        )

        for fn in (
            _decode_value,
            _encode_value,
            _json_dumps,
            _json_loads,
            _json_or_none,
            _json_or_none_load,
            _values_from_json,
            _values_to_json,
        ):
            assert callable(fn)

    def test_each_repo_lives_in_own_module(self) -> None:
        from sampling_tool.persistence.audit_repo import AuditRepo
        from sampling_tool.persistence.dataset_repo import DatasetRepo
        from sampling_tool.persistence.engagement_repo import EngagementRepo
        from sampling_tool.persistence.engagement_state_repo import (
            EngagementState,
            EngagementStateRepo,
        )
        from sampling_tool.persistence.repositories import (
            AuditRepo as FacadeAudit,
        )
        from sampling_tool.persistence.sample_repo import SampleRepo
        from sampling_tool.persistence.undo_repo import UndoRepo

        # Fassaden-Symbol ist identisch mit dem Modul-Symbol.
        assert FacadeAudit is AuditRepo
        assert DatasetRepo.__module__ == "sampling_tool.persistence.dataset_repo"
        assert EngagementRepo.__module__ == "sampling_tool.persistence.engagement_repo"
        assert SampleRepo.__module__ == "sampling_tool.persistence.sample_repo"
        assert EngagementStateRepo.__module__ == "sampling_tool.persistence.engagement_state_repo"
        assert EngagementState.__module__ == "sampling_tool.persistence.engagement_state_repo"
        assert UndoRepo.__module__ == "sampling_tool.persistence.undo_repo"
```

- [ ] **Step 2: Test ausführen**

Run: `pytest tests/integration/test_repositories_layout.py -q --no-cov`
Expected: PASS — 3 Tests grün.

- [ ] **Step 3: Voll-Checks**

Run: `pytest -q && ruff check . && ruff format --check . && mypy src tests`
Expected: alles grün. Phase 2 (F-007) komplett.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_repositories_layout.py
git commit -m "$(cat <<'EOF'
Sprint 19: Layout-Test für die repositories.py-Fassade (F-007)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3 – F-006: `main_window.py` splitten

> Reihenfolge je Task: neues Modul anlegen → `MainWindow` umverdrahten → alte
> Methode löschen → `pytest -q` (bestehende `tests/ui/test_main_window.py` ist
> der Regressions-Test) → `ruff`/`mypy` → Commit.
> `# noqa`/`# type: ignore` nur übernehmen, wo im Original vorhanden.

### Task 9: Klassen-Level-Attribut-Annotationen auf `MainWindow`

**Files:**
- Modify: `src/sampling_tool/ui/main_window.py`

- [ ] **Step 1: Annotationen ergänzen**

In `src/sampling_tool/ui/main_window.py`, direkt nach den Signal-Deklarationen (nach Zeile 80 `dashboard_refresh_requested = pyqtSignal()`, vor `def __init__`) diesen Block einfügen. Er deklariert die Attribute, die ab Task 10–13 von freien Builder-Funktionen befüllt werden — sonst lehnt mypy-strict die externe Zuweisung ab:

```python
    # Von den _window_*-Buildern (Sprint 19 / F-006) befüllte Attribute –
    # hier deklariert, damit mypy-strict die externe Zuweisung akzeptiert.
    _file_menu: QMenu
    _recent_menu: QMenu
    _help_menu: QMenu
    _action_new: QAction
    _action_open: QAction
    _action_close: QAction
    _action_settings: QAction
    _action_import: QAction
    _action_export_sample: QAction
    _action_export_pdf: QAction
    _action_excel_report: QAction
    _action_html_report: QAction
    _action_new_sample: QAction
    _action_reset_sample: QAction
    _action_undo: QAction
    _action_redo: QAction
    _action_hotkeys: QAction
    _action_bug_report: QAction
    _action_about: QAction
    _action_switch_engagement: QAction
    _toolbar: QToolBar
    _sidebar: NavigationSidebar
    _workspace_splitter: QSplitter
    _data_table: DataTableView
    _lower_tabs: QTabWidget
    _audit_trail_view: AuditTrailView
    _dashboard_view: DashboardView
```

- [ ] **Step 2: Checks (reiner Additions-Schritt, keine Verhaltensänderung)**

Run: `pytest tests/ui/test_main_window.py -q --no-cov && ruff check src/sampling_tool/ui/main_window.py && mypy src tests`
Expected: alles grün — die Attribute werden weiterhin in `_build_menu`/`_build_toolbar`/`_build_workspace` zugewiesen, die Annotation ist nur eine Deklaration.

- [ ] **Step 3: Commit**

```bash
git add src/sampling_tool/ui/main_window.py
git commit -m "$(cat <<'EOF'
Sprint 19: Klassen-Level-Attribut-Annotationen auf MainWindow (F-006-Vorbereitung)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: `ui/_window_layout.py` – `build_workspace`

**Files:**
- Create: `src/sampling_tool/ui/_window_layout.py`
- Modify: `src/sampling_tool/ui/main_window.py`

- [ ] **Step 1: `_window_layout.py` erstellen**

Create `src/sampling_tool/ui/_window_layout.py`. Der Funktionsrumpf von `build_workspace` ist der **Body der bisherigen `MainWindow._build_workspace`-Methode** (aktuell Z. 296–339), mit `self.` → `window.` ersetzt (auch in den Signal-Forwards: `self._sidebar.dataset_selected.connect(self.dataset_selected.emit)` → `window._sidebar.dataset_selected.connect(window.dataset_selected.emit)`). Returnt den äußeren Splitter `outer`:

```python
"""Workspace-Layout-Builder für MainWindow (Sprint 19 / F-006)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSplitter, QTabWidget

from sampling_tool.ui.widgets.audit_trail_view import AuditTrailView
from sampling_tool.ui.widgets.dashboard_view import DashboardView
from sampling_tool.ui.widgets.data_table import DataTableView
from sampling_tool.ui.widgets.sidebar import NavigationSidebar

if TYPE_CHECKING:
    from sampling_tool.ui.main_window import MainWindow

# Tab-Titel im unteren QTabWidget (vorher in main_window.py).
_TAB_TITLE_AUDIT: str = "AuditTrail"
_TAB_TITLE_DASHBOARD: str = "Dashboard"


def build_workspace(window: MainWindow) -> QSplitter:
    """Baut den Workspace-Splitter und setzt window._sidebar /
    _workspace_splitter / _data_table / _lower_tabs / _audit_trail_view /
    _dashboard_view. Returnt den äußeren Splitter."""
    # <hier: Body von MainWindow._build_workspace verbatim, self -> window>
    # ... endet mit:  return outer
```

`QTabWidget` wird hier importiert, weil der Body `QTabWidget()` instanziiert. `AuditTrailView`/`DashboardView`/`DataTableView`/`NavigationSidebar` werden im Body instanziiert.

- [ ] **Step 2: `MainWindow` umverdrahten**

In `main_window.py`:
- Oben importieren: `from sampling_tool.ui._window_layout import build_workspace`.
- In `__init__` (Zeile 103) `self._workspace = self._build_workspace()` → `self._workspace = build_workspace(self)`.
- Die Methode `MainWindow._build_workspace` (Z. 295–339) **löschen**.
- Die Modul-Konstanten `_TAB_TITLE_AUDIT`/`_TAB_TITLE_DASHBOARD` (Z. 44–45) aus `main_window.py` **löschen** (leben jetzt in `_window_layout.py`).

- [ ] **Step 3: Import-Aufräumen**

Run: `ruff check --fix src/sampling_tool/ui/main_window.py`
Danach Ergebnis sichten — `ruff` entfernt nur jetzt-ungenutzte Imports. Falls `mypy` später eine im Klassen-Annotations-Block (Task 9) gebrauchte Klasse vermisst (z. B. `NavigationSidebar`), muss deren Import in `main_window.py` bleiben — die Annotationen zählen für `ruff` als Verwendung, also sollte `ruff --fix` sie nicht entfernen.

- [ ] **Step 4: Checks**

Run: `pytest tests/ui/test_main_window.py tests/ui/test_main_controller.py -q --no-cov && ruff check . && ruff format --check . && mypy src tests`
Expected: alles grün.

- [ ] **Step 5: Commit**

```bash
git add src/sampling_tool/ui/_window_layout.py src/sampling_tool/ui/main_window.py
git commit -m "$(cat <<'EOF'
Sprint 19: build_workspace nach ui/_window_layout.py extrahiert (F-006)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: `ui/_window_menu.py` – `build_menu` + `rebuild_recent_menu`

**Files:**
- Create: `src/sampling_tool/ui/_window_menu.py`
- Modify: `src/sampling_tool/ui/main_window.py`

- [ ] **Step 1: `_window_menu.py` erstellen**

Create `src/sampling_tool/ui/_window_menu.py`. `build_menu` = Body von `MainWindow._build_menu` (Z. 422–554), `rebuild_recent_menu` = Body von `MainWindow._rebuild_recent_menu` (Z. 643–655) — jeweils `self.` → `window.`. **Wichtig:** die Inline-Annotationen `self._file_menu: QMenu = file_menu` etc. werden zu schlichten Zuweisungen `window._file_menu = file_menu` (Typ kommt aus dem Klassen-Annotations-Block von Task 9). QAction-Parent: `QAction("…", self)` → `QAction("…", window)`.

```python
"""Menü-Builder für MainWindow (Sprint 19 / F-006)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QStyle

from sampling_tool.ui.recent import RecentEntry

if TYPE_CHECKING:
    from sampling_tool.ui.main_window import MainWindow

# Max. Recent-Einträge im Datei-Menü (vorher in main_window.py).
_MAX_RECENT_IN_MENU: int = 5


def build_menu(window: MainWindow) -> None:
    """Baut Menübar + alle QActions; setzt window._file_menu / _recent_menu /
    _help_menu / alle window._action_*."""
    # <hier: Body von MainWindow._build_menu verbatim, self -> window;
    #        Inline-Annotationen entfernen (window._file_menu = file_menu)>


def rebuild_recent_menu(window: MainWindow, entries: list[RecentEntry]) -> None:
    """Befüllt das File→Recent-Submenü neu."""
    # <hier: Body von MainWindow._rebuild_recent_menu verbatim, self -> window>
```

- [ ] **Step 2: `MainWindow` umverdrahten**

In `main_window.py`:
- Importieren: `from sampling_tool.ui._window_menu import _MAX_RECENT_IN_MENU, build_menu, rebuild_recent_menu`.
- In `__init__` (Zeile 123) `self._build_menu()` → `build_menu(self)`.
- In `set_recent_entries` (Z. 250–253) `self._rebuild_recent_menu(entries[:_MAX_RECENT_IN_MENU])` → `rebuild_recent_menu(self, entries[:_MAX_RECENT_IN_MENU])`. Der `_MAX_RECENT_IN_MENU`-Zugriff für `self._welcome.set_recent_entries(entries[:_MAX_RECENT_IN_MENU])` bleibt — die Konstante kommt jetzt aus dem Import.
- Methoden `MainWindow._build_menu` (Z. 421–554) und `MainWindow._rebuild_recent_menu` (Z. 642–655) **löschen**.
- Modul-Konstante `_MAX_RECENT_IN_MENU` (Z. 40) aus `main_window.py` **löschen**.

- [ ] **Step 3: Import-Aufräumen**

Run: `ruff check --fix src/sampling_tool/ui/main_window.py`

- [ ] **Step 4: Checks**

Run: `pytest tests/ui/test_main_window.py tests/ui/test_main_controller.py -q --no-cov && ruff check . && ruff format --check . && mypy src tests`
Expected: alles grün — insbesondere `TestSettingsAction`, `TestBugReportToolbarButton`, `test_set_recent_entries_builds_menu`.

- [ ] **Step 5: Commit**

```bash
git add src/sampling_tool/ui/_window_menu.py src/sampling_tool/ui/main_window.py
git commit -m "$(cat <<'EOF'
Sprint 19: build_menu/rebuild_recent_menu nach ui/_window_menu.py (F-006)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: `ui/_window_toolbar.py` – `build_toolbar`

**Files:**
- Create: `src/sampling_tool/ui/_window_toolbar.py`
- Modify: `src/sampling_tool/ui/main_window.py`

- [ ] **Step 1: `_window_toolbar.py` erstellen**

Create `src/sampling_tool/ui/_window_toolbar.py`. `build_toolbar` = Body von `MainWindow._build_toolbar` (Z. 557–617), `self.` → `window.`. Die Inline-Annotation `self._toolbar: QToolBar = toolbar` wird zu `window._toolbar = toolbar`. QAction-Parent `QAction("…", self)` → `QAction("…", window)`:

```python
"""Toolbar-Builder für MainWindow (Sprint 19 / F-006)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QSizePolicy, QStyle, QToolBar, QWidget

if TYPE_CHECKING:
    from sampling_tool.ui.main_window import MainWindow


def build_toolbar(window: MainWindow) -> None:
    """Baut die Haupt-Toolbar; setzt window._toolbar und
    window._action_switch_engagement. Muss NACH build_menu laufen
    (nutzt die dort erzeugten QActions)."""
    # <hier: Body von MainWindow._build_toolbar verbatim, self -> window>
```

- [ ] **Step 2: `MainWindow` umverdrahten**

In `main_window.py`:
- Importieren: `from sampling_tool.ui._window_toolbar import build_toolbar`.
- In `__init__` (Zeile 124) `self._build_toolbar()` → `build_toolbar(self)`.
- Methode `MainWindow._build_toolbar` (Z. 556–617) **löschen**.

- [ ] **Step 3: Import-Aufräumen**

Run: `ruff check --fix src/sampling_tool/ui/main_window.py`

- [ ] **Step 4: Checks**

Run: `pytest tests/ui/test_main_window.py tests/ui/test_main_controller.py -q --no-cov && ruff check . && ruff format --check . && mypy src tests`
Expected: alles grün — `TestSwitchEngagementToolbar`, `TestSettingsToolbarButton`, `TestBugReportToolbarButton`.

- [ ] **Step 5: Commit**

```bash
git add src/sampling_tool/ui/_window_toolbar.py src/sampling_tool/ui/main_window.py
git commit -m "$(cat <<'EOF'
Sprint 19: build_toolbar nach ui/_window_toolbar.py extrahiert (F-006)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: `ui/_window_state.py` – `WindowStateController` + Shims

**Files:**
- Create: `src/sampling_tool/ui/_window_state.py`
- Modify: `src/sampling_tool/ui/main_window.py`

- [ ] **Step 1: `_window_state.py` erstellen**

Create `src/sampling_tool/ui/_window_state.py`. Die Controller-Attribute heißen **bewusst identisch** zu den bisherigen `MainWindow`-Attributen (`_settings`, `_workspace_splitter`, `_lower_tabs`, `_audit_trail_view`, `_dashboard_view`, `_cached_splitter_sizes`) — dadurch sind die Methoden-Bodies **verbatim** übernehmbar: `restore` = Body von `_restore_workspace_state` (Z. 344–352), `save` = Body von `_save_workspace_state` (Z. 355–370), `apply_panel_visibility` = Body von Z. 379–382, `_rebuild_lower_tabs` = Body von Z. 385–396, `_update_splitter_for_visibility` = Body von Z. 399–412. Kein `self.X`→`window.X`-Rewrite nötig — `self` ist jetzt der Controller.

```python
"""WindowStateController – QSettings-Restore/Save + Panel-Visibility (Sprint 19 / F-006)."""

from __future__ import annotations

from PyQt6.QtCore import QByteArray, QSettings
from PyQt6.QtWidgets import QSplitter, QTabWidget

from sampling_tool.ui._window_layout import _TAB_TITLE_AUDIT, _TAB_TITLE_DASHBOARD
from sampling_tool.ui.widgets.audit_trail_view import AuditTrailView
from sampling_tool.ui.widgets.dashboard_view import DashboardView


class WindowStateController:
    """QSettings-Restore/Save + Panel-Visibility + Splitter-Sizes-Cache."""

    def __init__(
        self,
        *,
        settings: QSettings,
        workspace_splitter: QSplitter,
        lower_tabs: QTabWidget,
        audit_trail_view: AuditTrailView,
        dashboard_view: DashboardView,
    ) -> None:
        self._settings = settings
        self._workspace_splitter = workspace_splitter
        self._lower_tabs = lower_tabs
        self._audit_trail_view = audit_trail_view
        self._dashboard_view = dashboard_view
        self._cached_splitter_sizes: list[int] | None = None

    def restore(self) -> None:
        """Stellt Splitter-Größen + aktiven Tab aus QSettings wieder her."""
        # <hier: Body von MainWindow._restore_workspace_state verbatim>

    def save(self) -> None:
        """Persistiert Splitter-Größen + aktiven Tab."""
        # <hier: Body von MainWindow._save_workspace_state verbatim>

    def apply_panel_visibility(self, *, show_dashboard: bool, show_audit_trail: bool) -> None:
        """Schaltet Dashboard-/AuditTrail-Tab im unteren Panel ein/aus."""
        # <hier: Body von MainWindow.apply_panel_visibility verbatim (Z. 379-382)>

    def _rebuild_lower_tabs(self, *, show_dashboard: bool, show_audit_trail: bool) -> None:
        # <hier: Body von MainWindow._rebuild_lower_tabs verbatim>

    def _update_splitter_for_visibility(self, *, both_off: bool) -> None:
        # <hier: Body von MainWindow._update_splitter_for_visibility verbatim>
```

- [ ] **Step 2: `MainWindow` umverdrahten + Shims**

In `main_window.py`:
- Importieren: `from sampling_tool.ui._window_state import WindowStateController`.
- In `__init__`: die Zeile `self._cached_splitter_sizes: list[int] | None = None` (Z. 92) **löschen**. Nach `self._workspace = build_workspace(self)` + `self._stack.addWidget(self._workspace)` den Controller bauen und `self._restore_workspace_state()` (Z. 105) ersetzen:

```python
        self._window_state = WindowStateController(
            settings=self._settings,
            workspace_splitter=self._workspace_splitter,
            lower_tabs=self._lower_tabs,
            audit_trail_view=self._audit_trail_view,
            dashboard_view=self._dashboard_view,
        )
        self._window_state.restore()
```

- `closeEvent` (Z. 414–419): `self._save_workspace_state()` → `self._window_state.save()`.
- `apply_panel_visibility` (Z. 372–382): den Body durch einen Delegate ersetzen:

```python
    def apply_panel_visibility(self, *, show_dashboard: bool, show_audit_trail: bool) -> None:
        """Schaltet Dashboard-/AuditTrail-Tab (Delegate an WindowStateController)."""
        self._window_state.apply_panel_visibility(
            show_dashboard=show_dashboard, show_audit_trail=show_audit_trail
        )
```

- Die Methoden `_restore_workspace_state` (Z. 343–352), `_rebuild_lower_tabs` (Z. 384–396), `_update_splitter_for_visibility` (Z. 398–412) **löschen**.
- `_save_workspace_state` (Z. 354–370) durch einen Backward-Compat-Shim ersetzen, und einen `_cached_splitter_sizes`-Property-Shim ergänzen (beide werden direkt von `tests/ui/test_main_window.py` benutzt):

```python
    @property
    def _cached_splitter_sizes(self) -> list[int] | None:
        """Backward-Compat-Shim → WindowStateController (Sprint 19 / F-006)."""
        return self._window_state._cached_splitter_sizes

    @_cached_splitter_sizes.setter
    def _cached_splitter_sizes(self, value: list[int] | None) -> None:
        self._window_state._cached_splitter_sizes = value

    def _save_workspace_state(self) -> None:
        """Backward-Compat-Shim → WindowStateController.save()."""
        self._window_state.save()
```

Platzierung: die `apply_panel_visibility`-Methode und die beiden Shims im Block „Settings-Persistenz" bzw. nahe `closeEvent` lassen (Reihenfolge unkritisch, solange in der Klasse).

- [ ] **Step 3: Import-Aufräumen**

Run: `ruff check --fix src/sampling_tool/ui/main_window.py`
Danach `mypy` (siehe Step 4) — falls `QByteArray` o. ä. als ungenutzt entfernt wurde und doch noch gebraucht wird, korrigieren. Erwartet: `QByteArray` ist in `main_window.py` jetzt ungenutzt (war nur in `_restore_workspace_state`) → wird entfernt. `QSettings` bleibt (`__init__` baut `QSettings`).

- [ ] **Step 4: Checks**

Run: `pytest tests/ui/test_main_window.py tests/ui/test_main_controller.py -q --no-cov && ruff check . && ruff format --check . && mypy src tests`
Expected: alles grün — insbesondere `TestPanelVisibility` (nutzt `win._cached_splitter_sizes` + `win._save_workspace_state()` über die Shims).

- [ ] **Step 5: Voll-Suite**

Run: `pytest -q`
Expected: alles grün.

- [ ] **Step 6: Commit**

```bash
git add src/sampling_tool/ui/_window_state.py src/sampling_tool/ui/main_window.py
git commit -m "$(cat <<'EOF'
Sprint 19: WindowStateController nach ui/_window_state.py, MainWindow mit Shims (F-006)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: F-006-Tests

**Files:**
- Modify: `tests/ui/test_main_window.py`

- [ ] **Step 1: Neue Test-Klassen schreiben**

Am Ende von `tests/ui/test_main_window.py` anhängen:

```python
class TestWindowStateController:
    """Sprint 19 / F-006: QSettings-/Panel-State im WindowStateController."""

    def test_apply_panel_visibility_hides_both_panels(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        win._window_state.apply_panel_visibility(show_dashboard=False, show_audit_trail=False)
        assert win._lower_tabs.isVisible() is False
        assert win._lower_tabs.count() == 0

    def test_splitter_sizes_cached_and_restored_on_collapse(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        before = win._workspace_splitter.sizes()
        win._window_state.apply_panel_visibility(show_dashboard=False, show_audit_trail=False)
        assert win._window_state._cached_splitter_sizes == before
        win._window_state.apply_panel_visibility(show_dashboard=True, show_audit_trail=True)
        assert win._window_state._cached_splitter_sizes is None
        assert win._workspace_splitter.sizes() == before

    def test_restore_falls_back_to_default_tab_on_garbage(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win._settings.setValue("workspace/lower_tab", "kein-int")
        win._window_state.restore()
        assert win._lower_tabs.currentIndex() == 0


class TestMainWindowComposition:
    """Sprint 19 / F-006: MainWindow bleibt dünner Compositor, API unverändert."""

    def test_public_api_attributes_present(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        for name in (
            "_file_menu",
            "_help_menu",
            "_recent_menu",
            "_toolbar",
            "_action_new",
            "_action_settings",
            "_action_bug_report",
            "_action_switch_engagement",
        ):
            assert hasattr(win, name), name
        assert win.data_table() is not None
        assert win.workspace_splitter() is not None
        assert win.lower_tabs() is not None

    def test_helper_modules_qt_importable(self) -> None:
        from sampling_tool.ui import (
            _window_layout,
            _window_menu,
            _window_state,
            _window_toolbar,
        )

        assert callable(_window_layout.build_workspace)
        assert callable(_window_menu.build_menu)
        assert callable(_window_menu.rebuild_recent_menu)
        assert callable(_window_toolbar.build_toolbar)
        assert _window_state.WindowStateController is not None
```

- [ ] **Step 2: Tests ausführen**

Run: `pytest tests/ui/test_main_window.py -q --no-cov`
Expected: PASS — alle (inkl. 5 neue) grün.

- [ ] **Step 3: Voll-Checks**

Run: `pytest -q && ruff check . && ruff format --check . && mypy src tests`
Expected: alles grün. Phase 3 (F-006) komplett.

- [ ] **Step 4: Commit**

```bash
git add tests/ui/test_main_window.py
git commit -m "$(cat <<'EOF'
Sprint 19: Tests für WindowStateController + MainWindow-Komposition (F-006)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4 – Abschluss

### Task 15: Voll-Verifikation + Demo-Smoke + PR + Merge

**Files:** keine Code-Änderung.

- [ ] **Step 1: Komplette Verifikation**

Run: `pytest && ruff check . && ruff format --check . && mypy src tests`
Expected: alle grün — ~706 Tests (681 + ~25 neu). Coverage core ≥90 % / rest ≥80 % (Report sichten).

- [ ] **Step 2: End-to-End-Smoke**

Run: `python scripts/demo_full_workflow.py`
Expected: läuft ohne Exception durch (Artefakte in `./demo_output/`). Verifiziert, dass der F-007-Fassaden-Split die Layer-übergreifenden Pfade nicht gebrochen hat.

- [ ] **Step 3: Branch-Diff prüfen**

Run: `git status --short && git log --oneline main..HEAD`
Expected: working tree zeigt nur `M CLAUDE.md` + `?? SPRINT_19_PROMPT.md` (beide NICHT committen); die Commit-Liste enthält Design-Doc + die Task-Commits aus Phase 1–3.

- [ ] **Step 4: Push + PR**

```bash
git push -u origin feat/sprint-19-distinct-and-splits
gh pr create --title "Sprint 19: P-005 + F-007 + F-006" --body "$(cat <<'EOF'
## Summary
- **P-005**: `DatasetRepo.distinct_values` via SQL `json_extract` + `GROUP BY raw,jtype` + `MIN(row_index)`; Advanced-Sampling-Dialog ohne `get_all_rows` (RAM ~ Anzahl distinkter Werte statt Zeilen), Provider-Callback statt `rows`-Parameter. Bit-identisch zum alten RAM-Pfad inkl. `str()`-Tie-Break.
- **F-007**: `repositories.py` (956 LoC) in `_json.py` + 6 Repo-Einzelmodule gesplittet; `repositories.py` ist Re-Export-Fassade — alle Import-Sites unverändert.
- **F-006**: `main_window.py` (691 LoC) in `_window_menu`/`_window_toolbar`/`_window_layout` + `WindowStateController` gesplittet; `MainWindow` als dünner Compositor mit Backward-Compat-Shims.

## Manueller Smoke-Test (GUI – bitte durchklicken)
1. App starten, Engagement öffnen/anlegen, Excel importieren (Multi-Sheet → Import-Dialog).
2. Einstellungen → Advanced-Mode an.
3. Neue Stichprobe → Methode Cluster bzw. Geschichtet → Filter-Spalte wählen, inkl. einer datetime-Spalte → Distinct-Werte korrekt, kein mehrsekündiger Freeze beim Spaltenwechsel, kein RAM-Spike.
4. Stichprobe ziehen, exportieren (Sample-xlsx).
5. Menü UND Toolbar durchklicken: Undo/Redo, Reset, Excel-/HTML-Report, AuditTrail-PDF, Einstellungen, Bug-Report.
6. Panel-Visibility toggeln (Dashboard/AuditTrail aus → beide aus → wieder an), App neu starten → Splitter-Aufteilung + aktiver Tab wiederhergestellt.
7. Reproduzierbarkeit: gleiche Stichprobe mit gleichem Seed zweimal ziehen → identische Auswahl.

## Test plan
- [x] `pytest` grün (~706 Tests)
- [x] `ruff check .` / `ruff format --check .` / `mypy src tests` grün
- [x] `scripts/demo_full_workflow.py` läuft durch
- [ ] Manueller GUI-Smoke-Test (siehe oben)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: Merge**

```bash
gh pr merge --squash --delete-branch
git checkout main
git pull --ff-only
```

Falls `gh pr merge` auf CI-Checks wartet/fehlschlägt: STOPP und Status berichten — nicht erzwingen.

---

### Task 16: Sprint-Status-Tabelle nachziehen (Commit auf `main`)

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: `CLAUDE.md` Sprint-Tabelle ergänzen**

In `CLAUDE.md`, in der `## Sprint-Status`-Tabelle nach der Sprint-18-Zeile anhängen:

```
| 19     | P-005 SQL-DISTINCT + F-007 repositories-Split + F-006 main_window-Split | done |
```

(Hinweis: `CLAUDE.md` hat bereits eine vor-bestehende, uncommittete Doc-Section-Änderung — die fließt mit diesem Commit ein, das ist beabsichtigt.)

- [ ] **Step 2: `README.md` Sprint-Tabelle ergänzen**

In `README.md` die Sprint-Status-Tabelle analog um die Sprint-19-Zeile erweitern (gleiche Spalten-Struktur wie dort vorhanden — Datei vorher lesen und Format übernehmen).

- [ ] **Step 3: Checks + Commit**

```bash
git add CLAUDE.md README.md
git commit -m "$(cat <<'EOF'
Sprint 19: Sprint-Status-Tabelle in CLAUDE.md + README.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

(Kleiner `chore`-artiger Doc-Commit direkt auf `main` — laut Sprint-Protokoll erlaubt.)

---

## Self-Review (vom Plan-Autor durchgeführt)

**Spec-Coverage:** P-005 → Tasks 1–3. F-007 → Tasks 4–8. F-006 → Tasks 9–14. Worktree-Handling → bereits vor Plan-Ausführung erledigt + Task 15/16-Hinweise. Repro-Oracle mit Tie-Break-Shapes → Task 1 `test_sql_path_matches_ram_reference_all_types`. Import-Disziplin F-007 → Phase-2-Vorspann + explizite Modul-Header. mypy-Annotations-Mechanismus → Task 9. Backward-Compat-Shims → Task 13. Alle Hard Constraints des Specs adressiert.

**Platzhalter-Scan:** `# <hier: ... verbatim>`-Marker sind **bewusste Verbatim-Move-Anweisungen** mit exakter Quell-Zeilenangabe — kein Hand-Waving (das Re-Transkribieren von 100+-Zeilen-Bodies wäre fehleranfälliger als ein präziser Move-Befehl). Alle NEUEN Logik-Teile (`distinct_values`, `_distinct_decode`, alle neuen Tests, `WindowStateController`-Gerüst, Shims) stehen als vollständiger Code im Plan.

**Typ-Konsistenz:** `distinct_values_provider: Callable[[str], Sequence[Any]] | None` einheitlich in Dialog, Factory-Typ und Controller-Variable. `WindowStateController`-Attributnamen identisch zu `MainWindow` (`_audit_trail_view` etc.) → Verbatim-Move ohne Rename. `_window_state.py` importiert `_TAB_TITLE_*` aus `_window_layout.py` (Einweg-Kante, kein Zyklus).
