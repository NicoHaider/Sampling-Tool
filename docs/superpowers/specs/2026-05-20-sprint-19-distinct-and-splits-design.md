# Sprint 19 – Design: P-005 + F-007 + F-006

**Datum:** 2026-05-20
**Branch:** `feat/sprint-19-distinct-and-splits`
**Status:** freigegeben

Drei Review-Findings in einem Sprint, in dieser Reihenfolge umgesetzt:

1. **P-005** (REVIEW_PERFORMANCE, SEV-2) – Advanced-Sampling-Dialog lädt distinct-Werte
   über `DatasetRepo.get_all_rows()` → 1 GB RAM-Spike auf 1M-Datasets.
2. **F-007** (REVIEW_STRUCTURE, SEV-2) – `persistence/repositories.py` (956 LoC) bündelt
   6 Repo-Klassen + JSON-Encoder in einer Datei.
3. **F-006** (REVIEW_STRUCTURE, SEV-2) – `ui/main_window.py` (691 LoC) mischt 5 Concerns.

TDD pro Phase: Tests zuerst (rot), dann Implementierung (grün). Reproduzierbarkeit
(`core/sampling.py`, `core/rng.py`) bleibt unverändert.

---

## Phase 1 – P-005: SQL-DISTINCT statt `get_all_rows`

### Ziel

Der Advanced-Sampling-Dialog braucht distinct-Werte einer Spalte für das Filter-Wert-
Dropdown. Bisher: `get_all_rows()` materialisiert das ganze Dataset im RAM
(~1 GB bei 1M Zeilen), dann iteriert `_distinct_values` linear darüber. Neu: on-the-fly
SQL, RAM ∝ Anzahl distinkter Werte (nicht Zeilen).

**Keine Schema-Migration, keine Schema-Änderung.** Dataset-Spalten sind dynamisch
(beliebige Excel-Header in `values_json`) – statische Generated Columns / Indizes
scheiden aus.

### `DatasetRepo.distinct_values(dataset_id, column) -> list[Any]`

Neue Methode (lebt nach dem F-007-Split in `persistence/dataset_repo.py`). Muss
**bit-identisch** zum bisherigen `_distinct_values(get_all_rows(...), column)` sein:
`None` überspringen, Dedup über `repr(value)`, Sortierung über `str(value)`.

**Tie-Break-Korrektheit (verbindlich):** Der bisherige RAM-Pfad sortiert mit
Python-`list.sort` (stabil) – bei `str()`-Gleichstand zweier verschiedener Werte
(z. B. int `5` und str `"5"`) bleibt die Reihenfolge der **ersten Vorkommen** in
Zeilen-Reihenfolge erhalten. Ein reines `SELECT DISTINCT` ohne `ORDER BY` hat
keine definierte Vor-Sort-Reihenfolge → der Gleichstand würde nicht-deterministisch
brechen. Lösung:

```sql
SELECT json_extract(values_json, ?) AS raw,
       json_type(values_json, ?)    AS jtype,
       MIN(row_index)               AS first_idx
FROM dataset_rows
WHERE dataset_id = ?
GROUP BY raw, jtype
```

In Python: pro `(raw, jtype)` dekodieren, dann
`result.sort(key=lambda item: (str(item.value), item.first_idx))`.
`first_idx` repliziert die Stable-Sort-First-Occurrence-Ordnung exakt → beweisbar
bit-identisch für **jede** Spalten-Form, nicht nur reine Ein-Typ-Spalten.

**Decode pro `(raw, jtype)`:**

- `jtype is None` oder `'null'` → überspringen (entspricht `value is None`).
- `jtype == 'object'` → tagged datetime/date/time: `_decode_value(_json_loads(raw))`.
- `jtype == 'true'` → `True`; `jtype == 'false'` → `False`
  (Bool aus `jtype`, **nicht** aus `raw` – json_extract liefert für Booleans `1`/`0`).
- `jtype == 'integer'` → `int(raw)`; `'real'` → `float(raw)`; `'text'` → `str(raw)`.

**JSON-Pfad:** als gebundener Parameter (`?`), nie f-string. In Python gebaut:
`'$."' + column.replace('"', '""') + '"'`. SQL-Injection ist ausgeschlossen, weil der
Pfad ein Bind-Parameter ist. Spaltennamen mit eingebettetem `"` sind pathologisch
(unüblich bei Audit-Daten) und im Docstring als nicht-abgedeckt dokumentiert – sie
degradieren zu einem leeren Dropdown, crashen aber nicht.

`distinct_values` läuft **synchron**: lazy (nur bei Filter-Spalten-Wechsel im
Advanced-Modus), reiner SQL-Read, modaler Dialog. Falls ein 1M-Messlauf >2 s zeigt →
als Follow-up dokumentieren, nicht spekulativ in einen Worker wrappen.

### Dialog / Controller / Factory

- **`ui/dialogs/sampling_dialog.py`**: Konstruktor-Parameter `rows` entfernen, ersetzen
  durch `distinct_values_provider: Callable[[str], Sequence[Any]] | None = None`.
  `self._rows` und die Modul-Funktion `_distinct_values` entfernen.
  `_max_population` → `max(dataset.row_count, 1)`. `_refresh_filter_values` ruft
  `self._distinct_values_provider(field)`. Der Dialog importiert **kein** `persistence`/
  `DatasetRepo` – Layer-Sauberkeit. `DatasetRow`-Import wird unused → entfernen.
- **`ui/controllers/workspace_controller.py`** (`handle_new_sampling`): `get_all_rows`-
  Aufruf entfernen. Provider bauen, dabei eine **lokale `dataset_id`-Variable**
  capturen (mypy-sauber im Lambda-Scope):
  `dataset_id = s.dataset.id` (nach Assert), dann
  `distinct_provider = (lambda col: repo.distinct_values(dataset_id, col)) if s.settings.advanced_mode else None`.
  An die Factory durchreichen statt `dialog_rows`. `repo` bleibt (wird für
  `iter_row_ids` / `_build_sampling_iterator` weiter gebraucht).
- **`ui/controllers/_factories.py`**: `SamplingDialogFactory`-Protocol +
  `default_sampling_factory` von `Sequence[DatasetRow] | None` auf
  `Callable[[str], Sequence[Any]] | None` umstellen. `DatasetRow`-Import wird unused.

---

## Phase 2 – F-007: `repositories.py` in Module splitten

`persistence/repositories.py` (956 LoC, 6 Repos + JSON-Encoder) → Einzelmodule.
`repositories.py` wird **reine Re-Export-Fassade** – alle ~29 bestehenden Import-Sites
(`from sampling_tool.persistence.repositories import X`) laufen unverändert.

| Neues Modul                              | Inhalt (1:1 verschoben)                                              |
|------------------------------------------|----------------------------------------------------------------------|
| `persistence/_json.py`                   | `_json_dumps/_loads/_or_none/_or_none_load`, `_encode/_decode_value`, `_values_to/from_json`, `_TYPE_KEY`, `_VAL_KEY` |
| `persistence/engagement_repo.py`         | `EngagementRepo`                                                    |
| `persistence/dataset_repo.py`            | `DatasetRepo` (inkl. neuer `distinct_values`)                        |
| `persistence/sample_repo.py`             | `SampleRepo`                                                        |
| `persistence/audit_repo.py`              | `AuditRepo`                                                         |
| `persistence/engagement_state_repo.py`   | `EngagementState` + `EngagementStateRepo`                           |
| `persistence/undo_repo.py`               | `UndoRepo`                                                          |
| `persistence/repositories.py`            | nur Re-Exporte + `__all__`                                          |

**Import-Disziplin (verbindlich, verhindert Zyklen):** Die neuen Repo-Module importieren
`savepoint` direkt aus `sampling_tool.persistence.database` und die JSON-Helfer aus
`sampling_tool.persistence._json` – **niemals** zurück über die `repositories.py`-Fassade.
Die Fassade importiert FROM den Repo-Modulen; eine Rück-Kante würde einen Zyklus bauen.
`_json.py` hat keine internen Deps (nur `orjson`, `datetime`, `typing`).

Die Fassade `__all__` re-exportiert auch die 8 unterstrichenen JSON-Helfer
(`_decode_value`, `_encode_value`, `_json_dumps`, `_json_loads`, `_json_or_none`,
`_json_or_none_load`, `_values_from_json`, `_values_to_json`) – Pflicht, weil
`tests/integration/test_db_performance_helpers.py` `_values_to_json`/`_values_from_json`
heute aus `repositories` zieht. Namen in `__all__` zählen für Ruff als "verwendet".

Nebenbei (F-011): veralteten Stub-Docstring in `persistence/__init__.py`
("Implementierung folgt in Sprint 2.") durch eine aktuelle 1-Zeilen-Beschreibung ersetzen.

---

## Phase 3 – F-006: `main_window.py` splitten (Sprint-13-Muster)

Freie Builder-Funktionen + eine State-Klasse. **Keine Mixins** (mypy-strict-Reibung).
`MainWindow` bleibt dünner Compositor.

| Neues Modul              | Inhalt                                                                          |
|--------------------------|---------------------------------------------------------------------------------|
| `ui/_window_menu.py`     | `build_menu(window)`, `rebuild_recent_menu(window, entries)`, `_MAX_RECENT_IN_MENU` |
| `ui/_window_toolbar.py`  | `build_toolbar(window)`                                                         |
| `ui/_window_layout.py`   | `build_workspace(window) -> QSplitter`, `_TAB_TITLE_AUDIT/_DASHBOARD`            |
| `ui/_window_state.py`    | Klasse `WindowStateController`                                                  |
| `ui/main_window.py`      | Signals, `__init__`, State-Maschine, Public-Setter, Accessors, Statusbar, Shims |

`MainWindow.__init__`-Reihenfolge (Abhängigkeiten): `build_workspace(self)` →
`WindowStateController` bauen + `.restore()` → Statusbar → `build_menu(self)` →
`build_toolbar(self)` (Toolbar nutzt Menü-Actions, muss danach laufen) → `show_welcome()`.

### mypy-strict-Mechanismus: Klassen-Attribut-Annotationen

Freie Builder-Funktionen weisen `window._action_*` etc. von außerhalb der Klasse zu.
mypy-strict akzeptiert das nur, wenn die Attribute auf der Klasse deklariert sind.
Lösung: Block von **Klassen-Level-Annotationen** (ohne Wert) auf `MainWindow`:

```python
class MainWindow(QMainWindow):
    # Von den _window_*-Buildern befüllt:
    _file_menu: QMenu
    _recent_menu: QMenu
    _help_menu: QMenu
    _action_new: QAction
    # ... alle _action_* ...
    _toolbar: QToolBar
    _action_switch_engagement: QAction
    _sidebar: NavigationSidebar
    _workspace_splitter: QSplitter
    _data_table: DataTableView
    _lower_tabs: QTabWidget
    _audit_trail_view: AuditTrailView
    _dashboard_view: DashboardView
```

### `WindowStateController`

```python
class WindowStateController:
    def __init__(self, *, settings, workspace_splitter, lower_tabs,
                 audit_view, dashboard_view) -> None: ...
    def restore(self) -> None: ...              # Body von _restore_workspace_state
    def save(self) -> None: ...                 # Body von _save_workspace_state
    def apply_panel_visibility(self, *, show_dashboard, show_audit_trail) -> None: ...
    # privat: _rebuild_lower_tabs, _update_splitter_for_visibility
    # hält: self._cached_splitter_sizes
```

`_window_state.py` importiert `_TAB_TITLE_AUDIT/_DASHBOARD` aus `_window_layout.py`
(Einweg-Kante, kein Zyklus).

### Backward-Compat-Shims auf `MainWindow` (verifiziert nötig)

`test_main_window.py` greift direkt auf zwei Member zu, die in den Controller wandern.
Damit der Test **unverändert** grün bleibt (Sprint-13-Backward-Compat-Property-Pattern):

- `_cached_splitter_sizes` – **Property mit Getter UND durchschreibendem Setter**.
  Getter: `return self._window_state._cached_splitter_sizes`.
  Setter: `self._window_state._cached_splitter_sizes = value`.
  (Verifiziert: `test_main_window.py:358/372/383` sind reine Reads; ein Setter ist
  trotzdem da, damit der Shim ein vollwertiger Ersatz für das frühere Plain-Attribut
  ist.)
- `_save_workspace_state()` – **Methoden-Shim**, delegiert an `self._window_state.save()`.
  (Genutzt von `closeEvent` + `test_main_window.py:394`.)

`apply_panel_visibility` bleibt Public-API auf `MainWindow` als Thin-Delegate.
`set_recent_entries` ruft `rebuild_recent_menu(self, ...)` und importiert
`_MAX_RECENT_IN_MENU` aus `_window_menu`.

**MainWindow Public-API unverändert:** alle Signals, alle `set_*`/`show_*`-Methoden,
Accessors, sowie `_action_*`, `_file_menu`, `_help_menu`, `_recent_menu`, `_toolbar`.

---

## Test-Plan (~25–35 neue Tests, 681 bestehende bleiben grün)

### P-005 – `tests/integration/test_distinct_values.py`

`TestDistinctValues`: strings sortiert, None überspringen, datetime/date/time,
int-vs-float, bool, Spaltenname mit Leerzeichen, leeres Dataset, fehlende Spalte.

`TestDistinctValuesReproducibility::test_sql_path_matches_ram_reference_all_types`:
KERN-Test. Eigene Oracle-Funktion `_reference_distinct` (repliziert die ursprüngliche
`_distinct_values`-Semantik). Vergleich **inkl. Reihenfolge** (`==`, nicht set).
Das Test-Dataset muss die Tie-Break-Shapes wirklich enthalten – reine Ein-Typ-Spalten
beweisen die Bit-Gleichheit **nicht**:

- eine Spalte mit str `"5"` UND int `5` (gleiches `str()`, anderer Wert, anderes `repr`),
- Duplikate über **nicht-benachbarte** Zeilen (z. B. Wert in Zeile 1 und Zeile 50),
- eine echt gemischt-typige Spalte,
- zusätzlich None-haltige Spalte + reine str/int/float/datetime/date/time/bool-Spalten.

### P-005 – Dialog / Controller

`TestSamplingDialogDistinctProvider` (in `test_sampling_dialog.py`): Advanced-Filter-
Werte kommen über den Provider; Provider wird mit dem gewählten Feld aufgerufen.
`TestNewSamplingDistinctProvider` (im Controller-Test): Advanced-Mode reicht Provider
statt rows durch; `get_all_rows` wird beim Dialog-Open NICHT aufgerufen.
Aufrufer/Tests, die heute `rows` an die Sampling-Factory geben, mit-anpassen.

### F-007 – `tests/integration/test_repositories_layout.py`

`TestRepositoriesBackwardCompat`: alle Repos aus der Fassade importierbar; JSON-Helfer
re-exportiert; jeder Repo lebt im eigenen Modul (Direkt-Import aus den neuen Modulen).
Bestehende `test_repositories.py` etc. bleiben unverändert grün.

### F-006 – in `tests/ui/test_main_window.py`

`TestWindowStateController`: Panel-Visibility versteckt beide Panels; Splitter-Sizes
gecacht + bei Collapse wiederhergestellt; Restore fällt bei Garbage auf Default-Tab.
`TestMainWindowComposition`: Public-API-Attribute vorhanden; Helper-Module Qt-importierbar.

---

## Hard Constraints

- `core/sampling.py`, `core/rng.py` unverändert. `distinct_values` speist nur das
  Filter-Wert-Dropdown, nie den RNG.
- Keine Schema-Migration, kein `migrations/NNN_*.sql`, kein `EngagementVersionManager`-Eingriff.
- `distinct_values` bit-identisch zum alten `get_all_rows`-Pfad (Repro-Test Pflicht).
- Alle ~29 Import-Sites von `persistence.repositories` laufen unverändert (Fassade).
- MainWindow Public-API + test-genutzte Attribute unverändert.
- Kein `get_all_rows` mehr im Advanced-Sampling-Pfad.
- `sampling_dialog.py` importiert kein `persistence`/`DatasetRepo`.
- 681 bestehende Tests bleiben grün; Coverage core ≥90 % / rest ≥80 %.

## Worktree / Git

Vorab erledigt: 4 untracked `" 2"`-Cruft-Dateien gelöscht (byte-identische Duplikate /
stale Coverage-Daten – `test_formatting 2.py` wurde von pytest mitgesammelt, Löschen
ist Korrektheits-Fix). `SPRINT_19_PROMPT.md` bleibt untracked. Modifiziertes `CLAUDE.md`
(Doc-Section, vor-bestehend) fließt in den Post-Merge-Sprint-Tabellen-Commit.
Staging immer datei-explizit, nie `git add .`.
