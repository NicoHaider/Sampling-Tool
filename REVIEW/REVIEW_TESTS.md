# Pass 4: Tests Review

**Datum:** 2026-05-18
**Reviewer:** Claude Code via superpowers/requesting-code-review (kein dedizierter Test-Coverage- / Mutation-Skill im Plugin v5.1.0; nächster genereller Review-Skill als Konventions-Anker, Analyse rein toolbasiert).
**Scope:** `tests/` (38 Dateien, 502 Test-Funktionen) + Coverage-Audit gegen `src/sampling_tool/`
**Methodik:** `pytest --cov --cov-report=term-missing`, `pytest --durations=15`, AST-Analyse, grep-Pattern, gezieltes Lesen einzelner Test- und Source-Stellen.
**Verknüpfung:** Pass 1 ([REVIEW_STRUCTURE.md](REVIEW_STRUCTURE.md)), Pass 2 ([REVIEW_QUALITY.md](REVIEW_QUALITY.md)), Pass 3 v2 ([REVIEW_PERFORMANCE.md](REVIEW_PERFORMANCE.md)), Sprint 12.1 (PR #34, P-001/P-002/P-007).

## Methodik-Limitierungen

- **`mutmut` / `cosmic-ray` nicht installiert** – keine Mutation-Testing-Analyse. Damit nicht abgedeckt: schwache Assertions, die zwar Coverage-Zeilen treffen aber Mutationen überleben. Insbesondere für die ISAE-3402-Reproducibility-Tests wäre das interessant; Pass 4 stützt sich stattdessen auf manuelle Inspektion der Assertions.
- **`hypothesis` (Property-Based) nicht im Test-Setup** – Edge-Cases für `_largest_remainder`, `_coerce_value`, `_sort_key` werden nicht zufallsgetestet. Findings nur über manuelle Lücken-Identifikation.
- **Branch-Coverage** ist über `branch = true` in `pyproject.toml` aktiv, aber `BrPart`-Spalte zeigt nur das Verhältnis. Welche konkreten Branches genau fehlen, wäre erst über `coverage report --show-missing` mit Branch-Diff vollständig sichtbar.
- **Branch-Stand:** `main` zeigt auf `47f7820` (Pass 3 v2). Sprint 12.1 (PR #34, `a721be8`) ist noch nicht gemerged. Damit Pass 4 die Sprint-12.1-Tests bewerten kann, basiert dieser Review-Branch auf `origin/feat/sprint-12.1-perf-quick-wins`. Wenn Sprint 12.1 doch nicht gemerged wird, sind die Aussagen zu `TestSimpleSamplerIdsPath` und zum Controller-Spezialpfad ohne Wirkung.

## Ausgangslage

Aktueller Stand laut `pytest --cov`:
- **506 Tests grün**, +32 in Sprint 12.1 (TestSimpleSamplerIdsPath + paar weitere).
- **Gesamt-Coverage 89 %** (5 439 Stmts, 437 Miss, 1 198 Branches, 235 BrPart).
- **502 Test-Funktionen** in 38 Dateien. Verteilung: `tests/unit/` 2 Dateien, `tests/integration/` 14 Dateien, `tests/ui/` 22 Dateien. `tests/fixtures/` ist leer – Fixtures werden alle programmatisch in `tests/conftest.py` (248 LoC, 14 Fixtures) erzeugt.
- **CLAUDE.md-Ziele:** `core/ ≥90 %`, `Rest ≥80 %`.
- **Verfehlungen auf Datei-Ebene:**
  - `core/rng.py` 89 % (Ziel 90 %, -1 %) – ein Miss bei `raise ValueError` für negativen Seed
  - `ui/dialogs/progress_dialog.py` **0 %** (Ziel 80 %, -80 %) – komplettes Modul ungenutzt + ungetestet, korreliert direkt mit Pass-2-Q-008 / Pass-3 P-008
  - `ui/widgets/audit_trail_view.py` 72 % (Ziel 80 %, -8 %)
  - `ui/dialogs/new_engagement_dialog.py` 74 % (Ziel 80 %, -6 %)
- **Test-Performance:** schnell (~9 s ohne Coverage, ~15 s mit Coverage). Top-Test 1.04 s (`test_perf_probe_kleine_groesse_laeuft_durch`, Subprocess-Aufruf des Probe-Scripts).

**Headline:** Die Test-Suite ist überwiegend gesund. Reproducibility-Schutz für alle drei Sampler-Methoden ist solide, der Sprint-12.1-`sample_ids`-Pfad bekommt 7 dedizierte Tests inkl. 5-Seed-Parametrisierung. Die echten Lücken sind (1) Regression-Schutz für die neuen Performance-Fixes Sprint 12.1 P-001/P-007 fehlt komplett, (2) ein paar ungetestete Edge-Cases im Sampler (n=1, n=N, leerer Pool ohne Filter), und (3) drei Stolperfallen aus CLAUDE.md haben keinen Regressionsschutz. **Insgesamt 0 SEV-0, 2 SEV-1, 5 SEV-2, 4 SEV-3.**

## Severity-Skala

- **SEV-0** — Reproducibility-Test fehlt für produktiv genutzten Sampler ODER fragiler Test der CI rot/grün flackern lässt
- **SEV-1** — core/ <90 % mit nicht-trivialen Missings ODER kritischer Edge-Case ungetestet ODER 0 %-Coverage-Datei
- **SEV-2** — Datei <80 % (außerhalb core) ODER Test-Helper-Drift gegenüber Sprint-11/12-API ODER Stolperfalle ohne Regressionsschutz
- **SEV-3** — Lange Test-Funktion, ungenutzter Helper, fehlender Kommentar bei @skip, Magic-Number-Konstante ohne Test

## Findings

### SEV-0

Keine SEV-0-Findings.

Belegt durch:
- `grep -rn "random\.\|np\.random\." tests/ --include="*.py" | grep -v "default_rng\|seed\|_rng\|TestRng"` → **leer**. Keine ungeseedete Randomness in Tests.
- Alle drei Sampler (`SimpleSampler`, `ClusterSampler`, `StratifiedSampler`) haben jeweils einen `test_reproducible_with_same_seed`-Test mit Bit-Gleichheit-Assertion (`first == second`).
- Der Sprint-12.1-Spezialpfad `sample_ids` hat einen 5-Seed-parametrisierten Reproducibility-Test gegen den klassischen Pfad ([test_sampling.py:142–155](tests/unit/test_sampling.py#L142-L155)).

### SEV-1

#### T-001: `ui/dialogs/progress_dialog.py` mit 0 % Coverage – komplettes Modul ungetestet
- **Datei(en):** [tests/](tests/) (kein Test existiert), [src/sampling_tool/ui/dialogs/progress_dialog.py](src/sampling_tool/ui/dialogs/progress_dialog.py)
- **Zeilen:** Source 8–37 (alle 19 Stmts uncovered)
- **Befund:** `TaskProgressDialog` (37 LoC) hat keinen einzigen Test. Coverage-Report: `19 19 2 0 0 % 8-37`. Pass-2-Q-008 und Pass-3-P-008 haben bereits diagnostiziert, dass das Modul existiert, aber NIE im Controller verbraucht wird – es ist Infrastruktur ohne Caller. Symptom des Pass-1/2/3-Befunds: ungenutzter Code wird auch nicht getestet, Lücke wird kaschiert. Sobald der Controller P-001/P-002-Sprint Worker-Wrap nachzieht und `TaskProgressDialog` aktiviert, gibt es keinen Regression-Schutz.
- **Belegt durch:** `pytest --cov`-Output Zeile `progress_dialog.py 19 19 2 0 0%`; `grep -rn "TaskProgressDialog" tests/` → leer.
- **linked_to:** Q-008 (Pass 2), P-008 (Pass 3 v2)
- **Empfehlung:** Mindestens einen Smoke-Test, der `TaskProgressDialog(label, parent)` instanziiert und einen Progress-Callback-Tick durchschickt (Maximum-Auto-Adjust, Value-Setzen). Wird beim Worker-Wrap-Sprint sowieso Pflicht.

#### T-002: Coverage-Verfehlung `ui/widgets/audit_trail_view.py` 72 % – Filter-Proxy-Lücken
- **Datei(en):** [src/sampling_tool/ui/widgets/audit_trail_view.py](src/sampling_tool/ui/widgets/audit_trail_view.py), Test in [tests/ui/test_audit_trail_view.py](tests/ui/test_audit_trail_view.py)
- **Zeilen:** Source Missings 107, 112, 125, 133, 140, 142, 144, 146, 149-151, 187, 190, 222, 228-232, 299->302, 334, 363, 377-379, 392-409, 416, 421, 437-444, 449-454
- **Befund:** 72 % ist 8 Prozentpunkte unter dem 80-%-Ziel. Die Missings sind überwiegend Filter-Proxy-Logik (`filterAcceptsRow`-Branches für leere/null-Filter, Range-Filter Wochen-/Monats-Logik in Zeilen 437–444), Helper-Funktionen `_format_file`/`_format_timestamp`/`_in_range` und `_to_int`-Edge-Cases. Pass-3-P-010 hat zusätzlich auf den Performance-Aspekt hingewiesen (Haystack pro Tastenanschlag), aber die Funktionalität selbst ist unzureichend getestet.
- **Belegt durch:** Coverage-Output + manuelles Lesen der Missing-Zeilen.
- **linked_to:** P-010 (Pass 3 v2 zur Haystack-Performance)
- **Empfehlung:** Tests für `AuditTrailFilterProxy` ausbauen: Filter „Heute"/"Diese Woche"/"Dieser Monat"-Boundary-Cases, kombinierte Action+User+Range-Filter, leere Volltextsuche, Sortierung durch `lessThan` für Columns 0/4. Aufwand: ~10–15 Tests, ein halber Tag.

### SEV-2

#### T-003: Kein Regression-Schutz für Sprint-12.1-P-001 (`setResizeContentsPrecision(100)`)
- **Datei(en):** [tests/ui/test_data_table.py](tests/ui/test_data_table.py) (Lücke), Source [src/sampling_tool/ui/widgets/data_table.py:305](src/sampling_tool/ui/widgets/data_table.py#L305)
- **Befund:** Sprint 12.1 hat im `DataTableView.__init__` `h_header.setResizeContentsPrecision(100)` ergänzt – das ist der 1-LoC-Fix, der die Tabelle-Anzeige von 34 s auf <1 s bringt (P-001 in Pass 3 v2). Es gibt keinen Test, der `header.resizeContentsPrecision() == 100` assertiert. Würde jemand die Zeile in einem Refactor entfernen, würde die Test-Suite weiterhin grün bleiben – der Performance-Bug käme klammheimlich zurück.
- **Belegt durch:** `grep -rn "ResizeContentsPrecision\|setResizeContentsPrecision" tests/` → leer.
- **linked_to:** P-001 (Pass 3 v2, Sprint 12.1)
- **Empfehlung:** 1-Zeilen-Test in `tests/ui/test_data_table.py::TestDataTableView`: `assert view.horizontalHeader().resizeContentsPrecision() == 100`. Etabliert die Performance-Invariante als Regression-Schutz.

#### T-004: Kein Regression-Schutz für Sprint-12.1-P-007 (Pipeline-Total-Soft-Target)
- **Datei(en):** [tests/integration/test_perf_probe_runs.py](tests/integration/test_perf_probe_runs.py) (Lücke), Source [scripts/perf_probe.py:89–113, 560–597](scripts/perf_probe.py#L89-L113)
- **Befund:** Sprint 12.1 hat `PIPELINE_TOTAL_LABEL` + `PIPELINE_TOTAL_PHASES` + `LEGACY_PRE_STREAMING_TARGETS_1M_SECONDS` eingeführt und `detect_violations` so umgebaut, dass Einzelphasen Import/DB nicht mehr eigenständig bewertet werden, sondern als Pipeline-Total aggregiert. Es gibt keinen Test, der diese Aggregation-Logik verifiziert. Der existierende Smoke-Test ruft das Script subprozess und prüft nur "läuft durch" + "Bericht-Datei enthält Phase-Labels". Wenn die Aggregations-Logik kaputtgeht, schlägt der Smoke-Test nicht aus.
- **Belegt durch:** `grep -rn "detect_violations\|PIPELINE_TOTAL" tests/` → leer.
- **linked_to:** P-007 (Pass 3 v2, Sprint 12.1)
- **Empfehlung:** Unit-Test für `detect_violations` mit gefälschten `SizeResult`-Objekten: (a) Pipeline-Total knapp drunter → keine Verfehlung, Einzelphasen über altem Target werden ignoriert; (b) Pipeline-Total drüber → eine Verfehlung mit dem `PIPELINE_TOTAL_LABEL`; (c) Verschiedene Phasen-Sets (nur Import gemessen, nicht DB) → keine Pipeline-Aggregation. ~3 Tests, 30 LoC.

#### T-005: Sampler-Edge-Cases n=1, n=N, einzelner Distinct-Cluster ungetestet
- **Datei(en):** [tests/unit/test_sampling.py](tests/unit/test_sampling.py) (Lücke)
- **Befund:** Bestehende Tests decken `n=normal`, `n>N` (oversample raises) und `size=0` (invalid). Es fehlen:
  - **n=1** (Grenze nach unten – der "ein-Element-Sample"-Fall, der häufig Off-by-One offenlegt) für alle drei Sampler.
  - **n=N** ("ziehe alles") für SimpleSampler – Reproducibility ist hier degeneriert (alle Rows immer drin), aber RNG-Verbrauch sollte trotzdem deterministisch sein.
  - **Pool mit nur einem Distinct-Wert** für Cluster/Stratified – degenerierte Cluster-Anzahl = 1.
  - **Leerer Pool im klassischen `sample()`-Pfad ohne Filter** – Zeile [sampling.py:81](src/sampling_tool/core/sampling.py#L81) (`raise SamplingError("Nach Anwendung des Filters … keine Datensätze")`) ist uncovered, weil bei ungefiltertem Pool ein leerer Iterator unüblich ist – aber im Streaming-Modus durchaus möglich (Dataset mit row_count=0). `TestSimpleSamplerIdsPath.test_empty_pool_raises` deckt es nur für den Spezialpfad.
- **Belegt durch:** `pytest --cov` zeigt Zeile 81, 132, 294, 351, 365 uncovered; manuelle Inspektion der `TestSimpleSampler`/`TestClusterSampler`/`TestStratifiedSampler`-Klassen in [test_sampling.py:67–349](tests/unit/test_sampling.py#L67-L349).
- **linked_to:** —
- **Empfehlung:** Pro Sampler eine `TestEdgeCases`-Klasse mit `test_n_equals_one`, `test_n_equals_pool_size`, `test_empty_pool_raises_unfiltered`, plus für Cluster/Stratified `test_single_distinct_value`. ~10 Tests, 100 LoC. Hebt core/sampling.py-Coverage über 95 %.

#### T-006: Stolperfallen ohne Regressionsschutz (CLAUDE.md "Bekannte Stolperfallen")
- **Datei(en):** Lücken in `tests/integration/test_importer.py`, kein Test für pywin32-Schutz
- **Befund:** CLAUDE.md listet 7 Stolperfallen. Status:
  - ✅ **orjson bytes vs str:** [test_db_performance_helpers.py:53](tests/integration/test_db_performance_helpers.py#L53) `test_returns_str_not_bytes`
  - ✅ **orjson Umlaute (strict-utf8):** [test_db_performance_helpers.py:47](tests/integration/test_db_performance_helpers.py#L47) `test_roundtrip_umlaute`
  - ✅ **PRAGMA fetchall + bulk_insert_pragmas:** dedizierte `TestBulkInsertPragmas`-Klasse in [test_db_performance_helpers.py:79](tests/integration/test_db_performance_helpers.py#L79)
  - ⚠️ **calamine `iter_rows()`-Panic bei `sheet.start is None`** (leeres Sheet): nur indirekt via `empty_xlsx`-Fixture, die ein Workbook mit Default-Sheet aber ohne Header speichert. Der `_excel_header_pass`-Defensive-Branch [importer.py:325–327](src/sampling_tool/io/importer.py#L325-L327) ist uncovered laut Pass-1-vereinbarter Heuristik. Keine explizite Assertion gegen den Calamine-Panic-Trigger.
  - ⚠️ **Calamine Float für ganzzahlige Werte** (Excel-Zahlen kommen als `float`, Importer normalisiert via `value.is_integer()` → `int`): erwähnt im Kommentar [test_importer.py:206](tests/integration/test_importer.py#L206), aber unklar ob dort eine harte Assertion `assert type(x) is int` existiert. Lass mich nicht spekulieren ohne genaues Lesen.
  - ⚠️ **Calamine Empty-String statt None** (leere Zellen kommen als `""`, Importer normalisiert auf `None`): kein direkter Unit-Test für `_coerce_value("")` → muss `None` liefern.
  - ❌ **pywin32 Windows-only / macOS-Schutz:** kein Test der verifiziert, dass auf macOS kein Modul-Level `import pywin32` passiert. `grep -rn "pywin32\|sys_platform\|win32" tests/` ist leer. Risiko: jemand fügt versehentlich Top-Level-Import hinzu → CI grün, App auf macOS crasht beim Start.
  - n/a **journal_mode-Deadlock bei WAL + parallel Connections:** Pass 1 / Sprint 10.3 hat dokumentiert, dass das schwer reproduzierbar testbar ist. Akzeptiert.
- **Belegt durch:** `grep`-Auswertung gegen die 7 Stolperfallen.
- **linked_to:** —
- **Empfehlung:** Drei kleine Tests in `tests/unit/test_imports.py` (neu): (a) `assert _coerce_value("") is None`; (b) `assert isinstance(_coerce_value(42.0), int)`; (c) `assert "pywin32" not in sys.modules` (nach Modul-Import). Aufwand: 15 Min.

#### T-007: Kein Test verifiziert, dass Controller P-002 tatsächlich den `sample_ids`-Pfad nimmt
- **Datei(en):** [tests/ui/test_main_controller.py](tests/ui/test_main_controller.py) (Lücke), Source [main_controller.py:549–569](src/sampling_tool/ui/controllers/main_controller.py#L549-L569)
- **Befund:** Der Sprint-12.1-Controller-Switch (`isinstance(sampler, SimpleSampler) and not from_sample_only and config.filter_field is None` → `sampler.sample_ids(repo.iter_row_ids(...))`) ist über den bestehenden `test_new_sampling_creates_sample_and_highlights` ([test_main_controller.py:471](tests/ui/test_main_controller.py#L471)) **implizit** ausgeführt – das Test-Setup nutzt SimpleSampler + `from_sample_only=False` ohne Filter. Aber: das `selected_row_ids`-Resultat wäre auch über den klassischen `sample()`-Pfad bit-genau identisch (siehe `TestSimpleSamplerIdsPath`). Der Test verifiziert NICHT, dass der Spezialpfad tatsächlich genommen wird. Würde jemand `isinstance(sampler, SimpleSampler)` aus dem Controller entfernen, würde alles grün bleiben, aber der RAM-Fix wäre weg.
- **Belegt durch:** `grep -c "sample_ids" tests/ui/test_main_controller.py` → `0`.
- **linked_to:** P-002 (Pass 3 v2, Sprint 12.1)
- **Empfehlung:** Spy/Mock auf `SimpleSampler.sample_ids` und `SimpleSampler.sample`: bei SimpleSampler+ohne Filter erwarte `sample_ids` aufgerufen, `sample` nicht; bei SimpleSampler+mit Filter erwarte `sample` aufgerufen, `sample_ids` nicht; bei ClusterSampler erwarte `sample` aufgerufen. ~3 Tests, 40 LoC.

### SEV-3

#### T-008: Sammel-Finding "Trivial-Lücken in core/"
- **Datei(en):** [src/sampling_tool/core/rng.py:28](src/sampling_tool/core/rng.py#L28), [sampling.py:132, 365](src/sampling_tool/core/sampling.py#L132)
- **Befund:** Drei defensive `raise`-Branches uncovered: (a) `make_rng(-1)` → ValueError; (b) `BaseSampler._validate_config` mit seed=-1 → SamplingError; (c) `_largest_remainder([], 0)` → SamplingError "Gewichts-Summe 0". Alle dokumentiert als "defensive – sollte durch upstream-Validation nicht erreichbar sein". CLAUDE.md fordert ≥90 % für core, `rng.py` 89 % und `sampling.py` 94 % liegen knapp daran. Drei Mini-Tests heben beide Module über 95 %.
- **Belegt durch:** Coverage-Output + Source-Read der Missing-Zeilen.
- **linked_to:** —
- **Empfehlung:** Drei `pytest.raises`-Tests, je 4 LoC.

#### T-009: Lange Tests >40 LoC (8 Stück) — Fixture-Refactor-Kandidaten
- **Datei(en):** [tests/ui/test_main_controller.py](tests/ui/test_main_controller.py) (5 Tests), [tests/integration/test_database.py](tests/integration/test_database.py), [tests/integration/test_exporter.py](tests/integration/test_exporter.py), [tests/integration/test_db_performance_helpers.py](tests/integration/test_db_performance_helpers.py), [tests/integration/test_perf_probe_runs.py](tests/integration/test_perf_probe_runs.py)
- **Zeilen:** Längste 59 LoC (`test_audit_pdf_dialog_receives_settings_defaults`), kein Test >100 LoC – Schwellwert sauber eingehalten.
- **Befund:** Kein wirklich langer Test, aber 5 Tests in `test_main_controller.py` zwischen 40 und 59 LoC. Das ist linked-zu F-001 (MainController-Refactor): wenn der Controller in Sub-Controller zerlegt wird, werden die Setup-Schritte pro Test natürlich kürzer.
- **Belegt durch:** AST-Analyse via `ast.walk` über `tests/`.
- **linked_to:** F-001 (Pass 1)
- **Empfehlung:** Nach F-001 mit-bereinigen, eigenständig nicht prioritär. Reduzierte Severity wegen linked_to.

#### T-010: `tests/unit/` enthält nur 2 Dateien (sampling, resources)
- **Datei(en):** [tests/unit/](tests/unit/)
- **Befund:** Nur zwei Unit-Test-Module: `test_sampling.py` (422 LoC) und `test_resources.py`. CLAUDE.md sagt "tests/unit/ – schnell, deterministisch, keine I/O." Tatsächlich liegen viele Module, die Unit-Tests verdient hätten, im `integration/`-Ordner und ziehen dort eine SQLite-DB hoch (`test_database.py`, `test_repositories.py`, `test_audit_logger.py`). Beispiele für echte Unit-Test-Kandidaten, die fehlplatziert sind: `_coerce_value`-Tests (würden in `tests/unit/test_importer_coerce.py` gehören), `_largest_remainder`-Tests (in `test_sampling.py` versteckt, könnten als Stand-alone Unit-Tests laufen). Niedrige Priorität, aber Konvention-Drift.
- **Belegt durch:** `ls tests/unit/` zeigt nur 2 Dateien; `grep -l "from sampling_tool" tests/integration/` zeigt 14 Dateien, davon viele die kein echtes Integration-Setup brauchen.
- **linked_to:** —
- **Empfehlung:** Niedrige Priorität, eher Backlog. Bei nächstem Anfassen eines Integration-Tests prüfen, ob er ohne DB-Setup auskommt → umziehen.

#### T-011: `restore_from_snapshot` in `version_manager.py` ungetestet (Production-unused)
- **Datei(en):** [src/sampling_tool/persistence/version_manager.py:105–115](src/sampling_tool/persistence/version_manager.py#L105-L115)
- **Befund:** Die Methode `restore_from_snapshot` ist im Source als "Aktuell nicht aus der UI heraus aufgerufen – wird in einer späteren Sprint-Version freigeschaltet" dokumentiert. Konsequenz: 11 Zeilen tote-aber-existierende API, kein Test. Risiko klein, aber wenn die Methode in einem späteren Sprint live geht, wäre der Erst-Lauf ohne Sicherheitsnetz.
- **Belegt durch:** Coverage-Output `version_manager.py 69 8 16 3 85 % 81, 85, 105-115, 139` + Lesen Source.
- **linked_to:** —
- **Empfehlung:** Mini-Test der die Roundtrip-Eigenschaft prüft (`snapshot` → `restore_from_snapshot` → DB-Inhalt identisch). 15 LoC.

## Coverage-Audit

### Verfehlungen ggü. CLAUDE.md-Zielen

| Datei | Coverage | BrPart | Ziel | Verfehlung | Missings sind ... | Finding-ID |
|-------|---------:|-------:|-----:|-----------:|-------------------|------------|
| core/rng.py | 89 % | 1 | ≥90 % | −1 % | defensiver `raise ValueError` für seed<0 | T-008 |
| core/sampling.py | 94 % | 7 | ≥90 % | ok, aber 7 Branches partial | defensive Raises + Edge-Cases (n=N, leerer unfiltered Pool, single-distinct-cluster) | T-005, T-008 |
| core/undo.py | 96 % | 1 | ≥90 % | ok | Zeile 97, 123 (Branches in `_move_top`) | — (knapp drüber) |
| ui/dialogs/progress_dialog.py | **0 %** | 0 | ≥80 % | **−80 %** | komplettes Modul, kein Test, kein Caller | **T-001** |
| ui/widgets/audit_trail_view.py | 72 % | 20 | ≥80 % | −8 % | Filter-Proxy, Helper-Funktionen, Sort-Branches | **T-002** |
| ui/dialogs/new_engagement_dialog.py | 74 % | 4 | ≥80 % | −6 % | Validierung, `audit_type`-Branch für unbekannten Typ, `_on_choose_path` | T-002-verwandt |
| ui/controllers/main_controller.py | 81 % | 61 | ≥80 % | ok, aber 61 partial Branches | Error-Handler in `handle_open_engagement` / `handle_export_*`, defensiver `return` | linked F-001 |
| ui/widgets/data_table.py | 82 % | 22 | ≥80 % | ok | defensive `return None` in `_actual_row_id` / `view_row_for_row_id` + paintEvent | — |
| ui/dialogs/settings_dialog.py | 84 % | 5 | ≥80 % | ok | Briefpapier-Browse-Dialog, Reset-Branch | — |
| io/importer.py | 85 % | 26 | ≥80 % | ok, aber 26 partial Branches | viele Edge-Cases in `_coerce_value`, `_excel_header_pass`-Defensiv, CSV-Encoding-Fallback | T-006 |
| persistence/version_manager.py | 85 % | 3 | ≥80 % | ok | `restore_from_snapshot` + `list_snapshots`-Branches | T-011 |
| ui/settings_store.py | 86 % | 4 | ≥80 % | ok | `_int`-Edge-Cases, `LOG_LEVELS`-Fallback | — |

Alle anderen Module: ≥89 %. **Bestkandidaten ohne Mangel:** `core/models.py` 100 %, `audit/logger.py` 100 %, `core/__init__.py` 100 %, `config.py` 100 %, `resources.py` 100 %.

### Reproducibility-Test-Matrix

| Sampler | same-seed | diff-seed | n=0 (invalid) | n=1 | n=N | n>N | leerer Pool unfiltered | leerer Pool filtered | single distinct | Bemerkung |
|---------|:---------:|:---------:|:-------------:|:---:|:---:|:---:|:----------------------:|:--------------------:|:---------------:|-----------|
| SimpleSampler (klassisch) | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ (Zeile 81 uncov.) | ✅ (filter_reduces_pool) | n/a | T-005 |
| SimpleSampler.sample_ids (Sprint 12.1) | ✅ (5 Seeds) | implizit ✅ | ✅ | ❌ | ❌ | ✅ | ✅ (empty_pool_raises) | n/a (rejects) | n/a | Vorbildlich abgedeckt |
| ClusterSampler | ✅ | ✅ | n/a (size=Cluster-Count) | ❌ | ❌ | ✅ (too_many) | ❌ | ❌ | ❌ | T-005 |
| StratifiedSampler | ✅ | ❌ (fehlt diff-seed) | n/a | ❌ | ❌ | implizit | ❌ | ❌ | ❌ | T-005, fehlender diff-seed-Test |

### Stolperfallen-Test-Status (aus CLAUDE.md "Bekannte Stolperfallen")

| Stolperfalle | Regressionsschutz vorhanden? | Finding-ID |
|--------------|------------------------------|------------|
| pywin32 Windows-only, Modul-Level-Import auf macOS verboten | ❌ | T-006 |
| python-calamine `iter_rows()` Panic bei `sheet.start is None` | ⚠️ indirekt via empty_xlsx | T-006 |
| python-calamine `""` statt `None` für leere Zellen | ⚠️ indirekt | T-006 |
| python-calamine Float für ganzzahlige Excel-Werte | ⚠️ Kommentar in test_importer.py, Assertion unklar | T-006 |
| orjson Bytes vs Str für SQLite-TEXT | ✅ test_returns_str_not_bytes | — |
| journal_mode-Deadlock bei WAL + parallel Connections | n/a (nicht reproduzierbar testbar, akzeptiert) | — |
| `PRAGMA <name>=<value>` braucht `.fetchall()` | ✅ TestBulkInsertPragmas | — |

### Test-Performance (Top 5 langsamste)

| Dauer | Test | Verbesserungspotenzial |
|------:|------|------------------------|
| 1.04 s | `tests/integration/test_perf_probe_runs.py::test_perf_probe_kleine_groesse_laeuft_durch` | Subprocess-Lauf des Probe-Scripts (intendiert, kein Smell) |
| 0.75 s | `tests/ui/test_chart_renderer.py::test_repeated_render_does_not_leak_figures` | Matplotlib-Render-Loop, intendiert |
| 0.27 s | `tests/ui/test_main_controller.py::TestSamplingFlow::test_undo_redo_round_trip` | Round-trip durch DB+UI, akzeptabel |
| 0.19 s | `tests/ui/test_main_controller.py::TestSettingsIntegration::test_reset_keeps_filter_when_setting_enabled` | UI+DB+Settings-Combo, akzeptabel |
| 0.16 s | `tests/ui/test_main_controller.py::TestSamplingFlow::test_reset_clears_highlight_with_confirmation` | dito |

Suite läuft komplett in **9.20 s ohne Coverage**, **15 s mit Coverage**. Kein Test über 2 s, kein `sleep()`, kein ungeseededer Random – Suite-Hygiene gut.

## Test-Qualitäts-Smells

### Fragile Tests (ungeseedete Randomness, Sleep-basiert)

Keine Treffer. `grep -rn "random\.\|np\.random\." tests/` ohne `seed`/`default_rng`-Kontext: leer. `grep -rn "sleep(" tests/`: leer. **Hygiene vorbildlich.**

### Time-Dependent ohne Mocking

| Test | Datei:Zeile | Pattern |
|------|-------------|---------|
| `_FilenameTemplate.test_replaces_date_token` | [test_export_sample_dialog.py:60](tests/ui/test_export_sample_dialog.py#L60) | `today = datetime.now().strftime("%Y%m%d")` ohne Mock |
| `TestExportTargetWidget.test_date_token_resolves_to_today` | [test_export_target_widget.py:23](tests/ui/test_export_target_widget.py#L23) | dito |

Beide vergleichen den Token gegen den live-`datetime.now()` – wenn der Test um Mitternacht läuft und der Code unter Test die nächste Sekunde abruft, kann Date-String-Mismatch auftreten. Theoretisch flaky, praktisch <<1×/Jahr. SEV-3, **kein eigenständiges Finding**, hier nur erwähnt.

### Veraltete Test-Helper / API-Drift

Keine veralteten API-Nutzungen gefunden. Sprint-11.5-Cleanup hat die `ImportResult.skipped_rows`/`.warnings`-Compat-Properties entfernt; Tests nutzen konsistent `result.stats.skipped_rows`/`result.stats.warnings` ([test_importer.py:34, 76, 285, 291](tests/integration/test_importer.py#L34)). `dataset.rows` nirgends in Tests verwendet.

### Skipped Tests

| Test | Grund | Issue-Ref? |
|------|-------|------------|
| `test_resources.py:79` | `pytest.skip("running unter PyInstaller, sys._MEIPASS bereits gesetzt")` | ja, intendiert |

Nur ein einziger Skip, mit klarem Grund. **Vorbildlich.**

### TODO/FIXME in Tests

Keine Treffer. `grep -rn "TODO\|FIXME\|XXX" tests/` → leer.

## Healthy Tests

Module / Test-Bereiche, die besonders gut abgedeckt sind:

- **`core/models.py` 100 %** – jede frozen Dataclass über Roundtrip-Tests verifiziert.
- **`audit/logger.py` 100 %** – jeder `log_*`-Helper hat einen dedizierten Integration-Test ([test_audit_logger.py](tests/integration/test_audit_logger.py)).
- **`TestSimpleSamplerIdsPath`** (Sprint 12.1, [test_sampling.py:124–206](tests/unit/test_sampling.py#L124-L206)) – 7 Tests, davon 1 parametrisiert über 5 Seeds inkl. Edge-Cases (0, 2³¹−1). Deckt den neuen sample_ids-Pfad konstruktiv ab und verifiziert Bit-Gleichheit zum klassischen Pfad. **Vorbildlich.**
- **`TestValuesJsonRoundtrip`** ([test_db_performance_helpers.py:28–58](tests/integration/test_db_performance_helpers.py#L28-L58)) – 4 Tests decken alle Pass-2-Q-007-Gefahrenzonen ab (Datetime-Roundtrip, Umlaute, bytes-vs-str).
- **`TestBulkInsertPragmas`** ([test_db_performance_helpers.py:79+](tests/integration/test_db_performance_helpers.py#L79)) – dokumentiert + testet die Sprint-10.3-Stolperfalle (journal_mode-Pragma-Deadlock-Verhalten).
- **`tests/conftest.py`** – 248 LoC, 14 session-scoped Fixtures, klare Trennung: DB-Setup, programmatisch erzeugte Excel/CSV-Fixtures mit deutschen Umlauten + BOM + cp1252-Variante. Keine Binärblobs im Repo. **Konventionell vorbildlich.**
- **Importer-Tests** ([test_importer.py](tests/integration/test_importer.py)) – decken Multi-Sheet, leere Workbook, leading-blank, duplicate columns, UTF-8/BOM/cp1252-CSV.
- **Engagement-State-Restore-Tests** in [test_main_controller.py](tests/ui/test_main_controller.py) – decken Sprint-8.2-Restore-Flow und stale-ID-Stillschweigen.
- **Test-Suite-Hygiene insgesamt:** 0 fragile randomness, 0 sleep, 0 TODO/FIXME, 1 begründeter skip. Test-Suite läuft in <15 s mit Coverage.

## Beifang

Bugs/Smells im Produktivcode, die beim Test-Lesen aufgefallen sind und NICHT durch Pass 1/2/3 abgedeckt sind:

1. **Sprint-12.1-Doc-String-Verweis ungenau:** [data_table.py:374–381](src/sampling_tool/ui/widgets/data_table.py#L374-L381) `_autosize_columns`-Docstring sagt korrekt "Sprint 12.1: `setResizeContentsPrecision(100)` im Konstruktor", aber der Kommentar im Konstruktor ([data_table.py:300–305](src/sampling_tool/ui/widgets/data_table.py#L300-L305)) sagt "Pass 3 v2 P-001" — beides legitim, aber Verweis-Stil ist inkonsistent (mal Sprint-Nr., mal Finding-ID). Doku-Nit, kein Bug.
2. **Keine.** Sonst keine neuen Bugs aufgefallen.

## Eigenständige Refactor-/Test-Kandidaten

Sortiert nach Aufwand-/Nutzen:

1. **T-003 (SEV-2)** – 1-Zeilen-Test für `setResizeContentsPrecision(100)` als Regression-Schutz für P-001. **Quickest Win.** Sollte VOR dem nächsten DataTableView-Refactor passieren.
2. **T-008 (SEV-3)** – 3 Mini-Tests für defensive Raises in core/. ~15 Min Arbeit, bringt core/rng.py und core/sampling.py über 95 %.
3. **T-006 (SEV-2)** – 3 Tests für CLAUDE.md-Stolperfallen (pywin32-Schutz, Empty-String-Coerce, Float-Integer-Coerce). ~30 Min.
4. **T-004 (SEV-2)** – Unit-Test für `detect_violations`-Aggregation. ~30 LoC, behebt fehlenden P-007-Regressionsschutz.
5. **T-007 (SEV-2)** – Spy/Mock-Test im Controller für P-002-Spezialpfad. ~3 Tests, 40 LoC.
6. **T-005 (SEV-2)** – Edge-Case-Tests für Sampler (n=1, n=N, leerer Pool unfiltered, single-distinct). ~10 Tests, hebt core-Coverage und schließt latente Off-by-One-Risiken aus.
7. **T-002 (SEV-1)** – AuditTrailFilterProxy-Filter-Boundary-Tests. ~10–15 Tests, hebt audit_trail_view.py von 72 % auf >85 %.
8. **T-001 (SEV-1)** – Smoke-Test für `TaskProgressDialog`. Wird bei Worker-Refactor (P-001/P-002-Folgesprint) sowieso Pflicht.

## Empfehlung Reihenfolge

**Vor dem nächsten Feature-Sprint:** T-003 und T-008 sofort als 30-Minuten-Mini-Sprint mit-bereinigen – beide sind 1-Zeilen-Fixes, schließen Regressionslücken im frisch-gemergten Sprint 12.1, und heben core-Coverage über die CLAUDE.md-Zielmarke. T-006 (Stolperfallen-Tests) ist konzeptionell ähnlich klein und gehört in denselben Mini-Sprint.

**Eigener Test-Sprint sinnvoll:** T-001, T-002, T-004, T-005, T-007 zusammen ~50 Tests, ~600 LoC, halber bis ein Tag Arbeit. Lohnt sich vor dem F-001-MainController-Split (Pass 1), weil ein größerer Test-Sicherheitsgürtel den Refactor stützt. Wenn F-001 zuerst kommt, werden T-007 und T-009 natürlich mit-bereinigt – das nicht zweimal machen.

**Backlog:** T-010 (Unit/Integration-Konvention-Drift), T-011 (`restore_from_snapshot`-Test), beide niedrige Priorität.

**Abhängigkeiten zu Pass-1/2/3:** T-001 löst sich teilweise auf, sobald der Pass-3-Folgesprint `TaskProgressDialog` aktiviert. T-007 wird durch F-001-MainController-Split natürlich umgestaltet. T-002 sollte gemeinsam mit P-010 (Pass-3-Haystack-Cache) angegangen werden – beide adressieren denselben Filter-Proxy-Code-Pfad.

## Offene Fragen

1. **Sprint-12.1-Merge-Status:** Pass 4 läuft auf `feat/sprint-12.1-perf-quick-wins`-Branch-Stand. Wenn der PR doch nicht gemerged wird, gelten T-003 (P-001-Regression-Schutz), T-004 (P-007), T-007 (P-002-Spy) automatisch nicht. Vor dem Pass-4-Merge auf main: Status von PR #34 prüfen.
2. **Mutation-Testing:** Reproducibility-Tests bestehen die Coverage, aber mutation-testing würde zeigen, wie robust die Assertions wirklich sind. Wäre `mutmut` oder `cosmic-ray` als Dev-Dependency tolerierbar? Nicht in diesem Pass installiert (Konvention).
3. **Property-Based-Tests:** `_largest_remainder` und `_coerce_value` sind Kernel-Funktionen mit vielen Input-Klassen. `hypothesis` würde Edge-Cases finden, die manuelle Tests übersehen. Frage: passt es in den Sampling-Tool-Scope oder ist es overkill?
4. **`tests/fixtures/` leer:** alle Fixtures werden programmatisch erzeugt – das ist konsequent und repo-freundlich. Aber der Ordner ohne `__init__.py` und ohne README ist eine Stolperfalle für neue Contributor. Vorschlag: README mit "Fixtures werden in `tests/conftest.py` session-scoped erzeugt" oder Ordner entfernen.
5. **Coverage-Threshold im Pre-Push:** der Pre-Push-Hook prüft Coverage NICHT als Hard-Threshold (sonst wäre `progress_dialog.py 0 %` rot). Soll der Hook auf `coverage report --fail-under=85` (oder `--skip-covered`) erweitert werden? Wäre Pass-4-Folgesprint-Thema.
