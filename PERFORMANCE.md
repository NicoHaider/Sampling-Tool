# Performance-Probe

Datum: 2026-05-18T18:09:33
Maschine: Darwin 25.3.0 (arm64), Python 3.13.13
Toolversion: 19f18a1
psutil RSS-Cross-Check: aus

## Soft-Targets (1M Zeilen)

| Phase | Target |
|-------|-------:|
| Import + DB-Speicherung (Pipeline-Total) | < 90 s |
| Tabelle-Anzeige | < 5 s |
| Sampling Simple | < 10 s |
| Sampling Cluster | < 15 s |
| Sampling Stratified | < 15 s |
| Filter-Toggle (an) | < 2 s |
| Filter-Toggle (aus) | < 2 s |
| Highlight | < 2 s |
| Excel-Export (Sample) | < 60 s |
| Excel-Report (Multi-Sheet) | < 60 s |
| HTML-Report | < 30 s |
| AuditTrail-PDF | < 30 s |

Bei kleineren Größen werden Targets linear skaliert (z. B. 30 s/M → 3 s/100k); reine Heuristik.

**Sprint 12.1 / P-007 – Phasen-Verlagerung:** seit Sprint 11.3 (Streaming-Import)
gehört die Cell-Coercion + JSON-Encode-Arbeit zum DB-Insert-Generator, nicht mehr
zur Import-Phase. Die historischen Einzeltargets (`Import < 60 s`,
`DB-Speicherung < 30 s`) wurden deshalb zu einem Pipeline-Total `< 90 s`
konsolidiert. Die Einzelphasen-Zeiten bleiben in den Mess-Tabellen sichtbar,
werden aber NICHT mehr in der Verfehlungsübersicht bewertet.

Historische Pre-Streaming-Targets (nur Sprint-10.x-Vergleichbarkeit):

| Phase | Legacy-Target |
|-------|--------------:|
| Import | < 60 s |
| DB-Speicherung | < 30 s |

**Sprint 24 / P-010 – AuditTrail-Volltextsuche (Haystack-Cache):**
`AuditTrailFilterProxy` baute den Such-Haystack (Timestamp-Formatierung inkl.
TZ-Konversion + Join) pro Row und pro Tastenanschlag neu (Pass 3 v2, P-010).
Seit Sprint 24 wird er pro Event genau einmal beim Event-Load vorberechnet
(`_haystack_cache`, Rebuild via `modelReset`-Signal); `filterAcceptsRow` macht
nur noch einen Substring-Check. Micro-Benchmark (20k Events, offscreen,
Darwin arm64, 2026-06-11): **194.7 ms → 129.8 ms pro Tastenanschlag** (−33 %).
Die verbleibenden ~130 ms sind struktureller Qt-Overhead (20k Python-
`filterAcceptsRow`-Aufrufe pro Anschlag im `QSortFilterProxyModel`), nicht
String-Bau. Treffer-Semantik bit-identisch zum alten Inline-Aufbau
(Oracle-Test `tests/ui/test_audit_trail_view.py::
TestAuditTrailFilterHaystackCache`). Kein neuer 1M-Probe-Lauf – `perf_probe.py`
misst die AuditTrail-Filter-Phase nicht (siehe „nie gemessen (P-010)" unten).

Follow-up-Kandidaten (Sprint 24; Stand nach Sprint 34):
- ~~Debounce/Delay für die Volltextsuche~~ → **Sprint 34 / WP1: umgesetzt** –
  150-ms-QTimer im Widget (`AuditTrailView.AUDIT_SEARCH_DEBOUNCE_MS`, singleShot,
  Restart pro `textChanged`); `AuditTrailFilterProxy.set_search_text` bleibt
  synchron und API-unverändert, Treffer-Semantik identisch (Sprint-25-Invariante).
  Zähler-Beleg statt Timing-Benchmark (deterministisch): Spy auf
  `set_search_text` in `tests/ui/test_audit_trail_view.py::TestAuditSearchDebounce::
  test_typing_coalesces_filter_runs` – 10 schnelle Keystrokes („a" → „anna export")
  ⇒ **genau 1** Filterlauf mit dem finalen Text (vorher: 10 Läufe à ~120 ms bei
  20k Events = ~1,2 s verdeckte Arbeit pro getipptem Suchwort).
- ~~Needle-Lowercase-Cache~~ → **Sprint 25: umgesetzt** – `set_search_text`
  lowercased die Nadel einmal pro Filter-Änderung, nicht mehr pro Row.
- ~~Escape-Bug der Volltextsuche~~ → **Sprint 25: gefixt** (siehe Block unten).

**Sprint 25 – Audit-Suche matcht Nicht-Wort-Zeichen literal (Bugfix):**
Die Volltextsuche lief über `setFilterFixedString`; `filterAcceptsRow` nutzte
das escapte `filterRegularExpression().pattern()` als Substring-Nadel. Qt
escapet dabei JEDES Nicht-Wort-Zeichen („.csv" → „\.csv", „ö" → „\ö",
„Größe" → „Gr\ö\ße", auch Leerzeichen: „anna export" → „anna\ export") –
Suchen mit Umlauten, Punkten, Regex-Metazeichen oder Mehrwort-Phrasen trafen
deshalb seit Sprint 6 nie (empirisch verifiziert). Fix:
`AuditTrailFilterProxy.set_search_text(raw)` führt die **rohe** Nadel;
`setFilterFixedString` ist aus dem Suchpfad entfernt. Invariante: literales,
case-insensitives Substring-Matching. Plain-Text-Treffer bleiben bit-identisch
(Oracle-Test `test_plain_text_search_unchanged`), P-010-Haystack-Cache
unverändert (kein Per-Row-Stringbau, Keystroke-Spy-Test weiter grün).
Micro-Benchmark (20k Events, offscreen, 2026-06-12):
**129,8 → 120,7 ms pro Tastenanschlag** – kein Regress, leicht besser.

**Sprint 26 – Import-Geschwindigkeit (Profiling-first):**

Reproduzierbarer 1-Mio-Zeilen-Benchmark für **beide** Formate, aufgeschlüsselt
in Parse / Encode / Write (Median aus 3 Läufen, Apple Silicon, Python 3.13.13,
gemischte Spalten: Text inkl. Nicht-ASCII, int, Dezimal, datetime/date/time,
Nullwerte). Skript: `scripts/bench_import.py` (bleibt im Repo). Aufruf:

```bash
python scripts/bench_import.py                       # 1M Zeilen, beide Formate, 3 Läufe
python scripts/bench_import.py --rows 1000000 --runs 5 --profile   # + cProfile-Gegenprobe
python scripts/bench_import.py --quick               # 1000 Zeilen, 1 Lauf (Smoke)
```

**Messlage (Baseline `e31ef72`, 1M Zeilen):**

| Phase | xlsx | csv |
|-------|-----:|----:|
| Parse | 5276 ms | 2531 ms |
| **Encode** | **5512 ms (43 %)** | **6957 ms (64 %)** |
| – davon Coercion (`_coerce_value`) | 3261 ms | 5756 ms |
| – davon Tagged-JSON (`_values_to_json`) | 2118 ms | 1226 ms |
| Write (`executemany` + Commit) | 1924 ms | 1432 ms |
| End-to-End (Streaming-Pipeline) | 12941 ms | 13640 ms |

**Entscheidungs-Gate:** Dominanter Posten je Format ist **Encode/Transform**.
Er zerfällt in (a) **Coercion** – der größere Teil, der aber die importierten
**Werte/Typen definiert** (float→int, deutsche Komma-Dezimalzahl, date→datetime)
und damit die „byte-für-byte identisch"-Rote-Linie ist (Hard Constraint §9,
bewusst NICHT angefasst, keine neue Dependency – der Parse-Pfad ist nicht
dominant) – und (b) **Tagged-JSON-Encoding**, der vom Sprint freigegebene,
risikoarme Hebel. cProfile bestätigt: zwei Per-Zellen-Pässe über dieselben
Daten (`_coerce_value` + `_encode_value` je 8 Mio. Aufrufe bei 8 Spalten).

**Fix (nur der dominante, sichere Hebel):** `_values_to_json` nutzt jetzt
`orjson.dumps(values, default=_encode_value, option=OPT_PASSTHROUGH_DATETIME)`.
orjson serialisiert das Werte-Dict direkt in C und ruft `_encode_value` NUR
noch für tatsächliche datetime/date/time-Werte zurück – der frühere
Per-Zellen-Dict-Comp + isinstance-Pass über die (ganz überwiegend
nicht-temporalen) Massendaten entfällt. Die erzeugten JSON-Bytes sind
**byte-identisch** (gleiche Tag-Shape `{"__type__":…,"v":…}`, gleiche
Key-Reihenfolge), der Read-Pfad (`_decode_value`/`_values_from_json`,
`distinct_values` via `json_extract`) bleibt unberührt.

**Vorher/Nachher (1M Zeilen):**

| Phase | xlsx vorher | xlsx nachher | csv vorher | csv nachher |
|-------|-----------:|------------:|-----------:|-----------:|
| Tagged-JSON (dominanter Hebel) | 2118 ms | **1476 ms** | 1226 ms | **404 ms** |
| Encode gesamt | 5512 ms | 4783 ms | 6957 ms | 6240 ms |
| End-to-End | 12941 ms | 12629 ms | 13640 ms | 11740 ms |

Cross-Prozess-Läufe haben Mess-Rauschen (Parse/Coercion/Write ~unverändert
innerhalb ±2 %). Der saubere, prozess-interne Alt-gegen-Neu-Vergleich des
Encoders (1M Zeilen, Median aus 5, Byte-Identität auf 5000 Zeilen asserted):
**xlsx 2070 → 1438 ms (−30,5 %)**, **csv 1163 → 312 ms (−73,1 %)** – der
dominante Hebel wird auf beiden Formaten ≥30 % schneller, der Gesamt-Import
messbar schneller (csv-E2E −14 %).

**Keine Korrektheits-Regression:** Byte-Identität + Tag-Round-Trip + Coercion-
Typen + Cancellation + PRAGMA-Unverändertheit + Single-`executemany`-Bulk-Insert
sind gepinnt in `tests/integration/test_import_result_unchanged.py::
TestImportResultUnchanged` (Oracle gegen die eingefrorene Pre-Sprint-26-
Referenz). Der Benchmark hat einen Smoke-Guard
(`tests/integration/test_bench_import_runs.py`).

**Sprint 34 – Startup-Import-Budget (M1):**

Gemessen via `python -X importtime -c "import sampling_tool.ui.main_window,
sampling_tool.ui.controllers.main_controller"` (3 Läufe, Darwin arm64,
Python 3.13.13, 2026-07-02). Wall-Clock-Median (warm): **0,303 s**; Cold-Lauf
(kumulativ `sampling_tool`): 0,746 s. Kumulative Anteile je Lib:

| Lib | cold (ms) | warm (ms, Median) | in Startup-Kette? | WP2-Gate ≥ 300 ms? |
|-----|----------:|------------------:|-------------------|--------------------|
| matplotlib | 96,5 | 78,1 | ja (main_window → dashboard_view → chart_renderer → io.charts) | nein |
| openpyxl | 118,5 | 39,4 | ja (io-Exporter) | nein |
| numpy | 82,5 | 24,1 | ja (core/rng) | nein |
| reportlab | 38,4 | 23,0 | ja (io.pdf_report via tasks.py) | nein |
| PyQt6 | 60,8 | 13,5 | ja | nein |
| jinja2 | 17,6 | 7,6 | ja (io.html_report, erst via Controller) | nein |
| pandas | – | – | nicht installiert | – |

**Entscheidung (WP2): bewusst nicht gefixt.** Der statische Verdacht stimmt
(schwere Libs laden transitiv beim App-Start – schon `main_window` zieht
matplotlib/reportlab/openpyxl), aber der Hebel ist zu klein: keine Lib erreicht
das 300-ms-Gate, der gesamte Startup-Import liegt bei ~0,3 s (warm) bzw.
~0,75 s (cold). Lazy-Imports + PyInstaller-`hiddenimports`-Pflege würden
Komplexität ohne spürbaren Gewinn einkaufen.

**Sprint 34 – Snapshot beim Projekt-Öffnen/Überschreiben (M3):**

`EngagementVersionManager.create_snapshot` (reines `shutil.copy2`) isoliert
gemessen mit synthetischen DB-Dateien (Zufallsbytes, Median aus 3, lokale SSD):

| DB-Größe | Median | Läufe |
|---------:|-------:|-------|
| 50 MB | 0,009 s | 0,009 / 0,009 / 0,009 |
| 200 MB | 0,035 s | 0,035 / 0,035 / 0,079 |
| 500 MB | 0,259 s | 0,108 / 0,282 / 0,259 |

**Entscheidung (WP3): bleibt synchron.** Gate war > 2 s bei realistischer
Größe (≤ 200 MB); gemessen sind 0,035 s – selbst 500 MB bleiben unter 0,3 s.
Ein Worker-Umbau (SnapshotTask + Progress-Dialog + Reihenfolge-Garantien in
beiden Pfaden Öffnen/Überschreiben) stünde in keinem Verhältnis. Vorbehalt:
Auf Windows-Netz-Shares kann das langsamer sein – falls das real auftritt,
ist `ui/workers/tasks.py` (Worker-Muster, Sprint 17) der vorbereitete Ansatz.

**Sprint 34 – WP5-Mikro-Pass (3 Items, je Zähler-Beleg, keine Verhaltensänderung):**

1. **`refresh_views` lud die Audit-Events doppelt** – `refresh_audit_trail` +
   `refresh_dashboard` machten je einen identischen
   `AuditRepo.list_for_engagement`-Fetch (2× bis zu 10.000 Events dekodiert)
   pro mutierender User-Aktion (9 Controller-Call-Sites: Import, Sampling,
   Reset, Sampling-Reset, Undo, Redo, Export, Open, Close). Jetzt versorgt EIN
   `collect_report_data`-Aufruf beide Views. Beleg:
   `TestRefreshViewsSingleEventLoad` – 2 → 1 Event-Fetch (**−50 %**),
   identische Events an beiden Views (Oracle).
2. **Sampling-Dialog: Full-Table-Scan pro Filter-Feld-Wechsel** – der
   P-005-Provider (`distinct_values`, SQL-`json_extract` über alle Rows) lief
   bei jedem `currentTextChanged` erneut, auch beim Zurückwechseln auf eine
   schon geladene Spalte (Pfeiltasten im Combo = ein Scan pro Tastendruck;
   bei 1M Zeilen hunderte ms). Jetzt Memo pro modaler Dialog-Instanz (Dataset
   währenddessen unveränderlich). Beleg: `TestFilterDistinctValuesCache` –
   5 Wechsel über 2 Spalten: 5 → 2 Provider-Calls (Wiederholbesuch:
   **Full-Scan → Dict-Lookup, −100 % Queries**), Combo-Inhalt bit-identisch.
3. **Export-Dialog „Alle auswählen/abwählen" war O(N²)** – `itemChanged`
   feuerte pro Spalten-Item → `_update_state` lief N-mal mit je O(N)-Scan +
   Preview-Rebuild (300 Spalten ≈ 90.000 checkState-Reads pro Klick). Jetzt
   Guard-Flag + genau ein Update am Ende, Endzustand identisch. Beleg:
   `TestBulkCheckSingleUpdate` – 40 Spalten: 40 → 1 Update-Lauf (**−97,5 %**).

Geprüft und bewusst NICHT umgesetzt (Kandidaten aus dem Fan-out-Scan):
`AuditRepo.get_by_id` für den AuditTrail-Doppelklick (dokumentierter
Semantik-Randfall bei Events außerhalb der 10k-Anzeige → verletzt „keine
Verhaltensänderung"), Timestamp-Float-/DisplayRole-Caches in der
AuditTrail-View und `data()`-Konstanten-Hoisting in der Datentabelle
(schwächeres Aufwand/Hebel-Verhältnis, WP5-Limit von 3 Items erreicht) –
Follow-up-Kandidaten für einen späteren Pass. QSettings-Reads in heißen
Pfaden: Scan fand **keine** (data()/paint sind sauber).

**Sprint 35 – Advanced-Sampling-Streaming (P-003, Cluster/Stratified):**

Der letzte große Streaming-Bruch ist geschlossen: `_collect_pool`
materialisierte für Cluster/Stratified den vollen `DatasetRow`-Pool
(~1,12 GB bei 1M Zeilen; bei 5M wäre das ~5,5 GB → OOM-Risiko auf
16-GB-Geräten). Beide Sampler brauchen pro Row aber nur `(row_id, feldwert)`
– der Shuffle hängt nur an Listenlängen und RNG, das Ergebnis wird ohnehin
sortiert. Neu (P-002-Muster, alles additiv – `sample`/`_select`/
`_collect_pool` wörtlich unverändert):

- `DatasetRepo.iter_row_field_pairs(dataset_id, column)` – `(row_index,
  Wert)`-Stream via `json_extract` + der P-005-erprobten
  `_distinct_decode`-Mechanik (Decode-Oracle gegen `iter_rows` über alle
  Import-Typen inkl. bool/int/float-Grenzfällen).
- `ClusterSampler.sample_pairs` / `StratifiedSampler.sample_pairs` –
  spiegeln `_select` exakt (gleiche Gruppierung in row_id-Reihenfolge,
  gleiche `_sort_key`-Sortierung, gleiche Largest-Remainder-Gewichte,
  gleiche RNG-Konsumreihenfolge). Nur für `filter_field is None`.
- Controller-Weiche + perf_probe-Spiegel: ungefiltert + ohne Resampling →
  pairs; Filter/Resampling → klassischer `sample(iter_rows)`-Pfad.

**Vorher/Nachher (identische 1M-DB, 15 Spalten, Median aus 3 ohne
tracemalloc; Peak aus separatem tracemalloc-Lauf; Endstand inkl. der
Review-Fixes unten):**

| Methode | vorher (rows) | nachher (pairs) | Δ Zeit | Δ RAM |
|---------|--------------:|----------------:|-------:|------:|
| Cluster (size=5, seed=43) | 4,74 s / 1124,8 MB | **1,52 s / 154,5 MB** | **−68 %** | **−86 %** |
| Stratified (size=500, seed=44) | 5,35 s / 1123,6 MB | **2,30 s / 151,8 MB** | **−57 %** | **−86 %** |

**Reproduzierbarkeit (rote Linie):** `selected_row_ids` beider Pfade sind
auf der vollen 1M-DB **identisch** (Benchmark-Assert) und per Oracle-Tests
gepinnt: `TestClusterSamplerPairsPath`/`TestStratifiedSamplerPairsPath`
(58 Fälle: 5 Seeds × Größen × Modi, Misch-Typ-Keys inkl. 5/5.0/True-
Hash-Kollision, None-Keys, unsortierter Input, identische Fehlermeldungen)
+ E2E-Repro-Oracle über den echten Controller
(`TestSamplingPathDispatch::test_pairs_path_result_matches_classic_reference`).

**Zwei Review-Findings (adversariales Code-Review) wurden vor dem Merge
gefixt – beide waren real erreichbare Bit-Repro-Gegenbeispiele:**

1. **u64-Integer:** SQLites `json_extract` approximiert JSON-Integer
   > 2^63 als REAL (`json_type` meldet weiter `'integer'`) – zwei
   distinkte 19-stellige IDs wären im Pairs-Pfad zu einem Cluster
   kollabiert. Fix: `exact_json`-Fallback-Spalte (CASE WHEN
   `typeof='real'` bei `json_type='integer'` → exakter Voll-Decode nur
   für diese Rows). Kostet ~0,2 s auf 1M (in der Tabelle enthalten).
   Oracle: `test_u64_integers_decode_exactly` (2^63±1, 2^64−1, 1e20).
2. **Spaltennamen mit `"`/`\`:** brechen das JSON-Path-Label →
   `json_extract` liefert NULL für jede Row (alles wäre still in einer
   None-Gruppe gelandet). Fix: `DatasetRepo.supports_field_pairs`-Guard –
   Controller + perf_probe schicken solche Spalten auf den klassischen
   Pfad; `iter_row_field_pairs` selbst wirft laut statt still falsch.
   Tests: `test_unsupported_column_name_raises` +
   `test_cluster_field_with_quote_falls_back_to_classic_path`.

Follow-up-Notiz: `distinct_values` (P-005) hat dieselbe u64-Schwäche seit
Sprint 19 – dort nur Dropdown-Anzeige, ein falsch decodierter Filter-Wert
führt zu `SamplingError` statt stiller Falschziehung (deshalb kein
Blocker); beim nächsten Persistence-Pass mitziehen.

**Mess-Methodik-Hinweis:** Die perf_probe-Phasenzeiten laufen unter
aktivem `tracemalloc` und sind dadurch ~2,5–3× überhöht (Cluster 12,9 s
probe vs. 4,6 s real; Stratified 16,4 s vs. 5,3 s). Für Vorher/Nachher-
Vergleiche innerhalb EINES Laufs ist das ok, als Absolutwerte nicht –
deshalb misst dieser Sprint mit separaten Timing-/RAM-Läufen
(`tmp/perf/s35_bench_sampling.py`-Methodik). Die Stratified-Soft-Target-
„Verfehlung" aus Sprint 34 (16,43 s > 15 s) war demnach ein
Instrumentierungs-Artefakt; real lag die Phase bei ~5 s.

**Sprint 35 – Import-Pipeline (profiling-first): gemessen, bewusst nicht gefixt.**

Baseline (`scripts/bench_import.py`, 1M Zeilen, Median aus 3, Rev `abac095`):

| Phase | xlsx | csv |
|-------|-----:|----:|
| Parse | **5149 ms (45 %)** | 2572 ms |
| Encode | 4742 ms | **6276 ms (61 %)** |
| – davon Coercion | 3217 ms | 5875 ms |
| – davon Tagged-JSON | 1464 ms | 398 ms |
| Write | 1648 ms | 1366 ms |
| End-to-End | 12232 ms | 11257 ms |

Dominanten: xlsx → Parse (calamine-Rust→Python-Konversion, ohne Engine-Wechsel
kein Hebel), csv → Encode, davon 94 % Coercion. Zwei Coercion-Hebel wurden
implementiert, gemessen und nach dem Gate **wieder revertiert**:

1. **Digit-Guard** (nicht-numerische Texte ohne int()/float()-Exception-
   Versuche): csv-Coercion 5875 → 5614 ms (**−4 %**). cProfile zeigt warum:
   2,34 von 2,4 Mio. String-Zellen der realistischen Fixture enthalten
   Ziffern (Datums-Strings, Belegnummern, Mischtexte) – der Guard greift
   fast nie, kostet aber selbst einen Regex-Scan pro Zelle.
2. **isinstance-Ketten-Umordnung** (str/float zuerst): xlsx-Coercion −1 %.
   `isinstance` ist mit ~15 ns pro Check kein relevanter Posten (cProfile:
   0,11 s tottime bei 2,7 Mio. Aufrufen, profiliert).

Der verbleibende Hebel (Exception-freies Parsen über exakte int()/float()-
Grammatik-Regexes inkl. Underscore-/Unicode-Ziffern-/inf-nan-Regeln) wurde
per Profil auf ~15–18 % der Encode-Phase geschätzt – **unter dem 20 %-Gate**
und mit erhöhtem Risiko direkt an der Byte-Identitäts-Rote-Linie (die
Coercion DEFINIERT die importierten Werte). Entscheidung: nicht umgesetzt.
Bleibender Ertrag des Passes:

- **`TestCoerceStringEquivalenceOracle`** (tests/unit/test_importer_coerce.py):
  eingefrorene Referenz-Implementierung + Nasty-Corpus + 5000er-Seeded-Fuzz
  pinnt die Coercion-Semantik (Wert UND Typ, NaN-sicher via repr) für jede
  zukünftige Optimierung.
- **Doppel-Pass-Hypothese aus Pass 3 v2 widerlegt:** `_excel_header_pass`
  konsumiert nur Zeilen bis zum Header (Größe kommt aus
  `sheet.total_height`-Metadaten) – es gibt EINEN vollen Daten-Pass, kein
  verstecktes Zweitparsen.
- **Einordnung der „DB-Speicherung 53,7 s":** real läuft der komplette
  1M-Import (8 Spalten, End-to-End inkl. Write) in ~12 s; die
  perf_probe-Phasenwerte laufen unter `tracemalloc` und messen 15 Spalten –
  als Absolutwerte nicht mit Alltags-Performance zu verwechseln (siehe
  Mess-Methodik-Hinweis im Sprint-35-Sampling-Block).

**Hinweis zur Mess-Tabelle unten:** Der 1M-Lauf stammt vom Sprint-11-Stand
(Toolversion `19f18a1`) und liegt damit VOR den Sprint-12.1-Fixes für P-001
(`setResizeContentsPrecision(100)` → Tabelle-Anzeige) und P-002
(`SimpleSampler.sample_ids` via `iter_row_ids` → Sampling-Simple-RAM).
Die Zeilen „Tabelle-Anzeige 34.58 s" und „Sampling Simple 15.90 s / 1.07 GB"
beschreiben den Zustand VOR diesen Fixes (inzwischen behoben); Regression-Guards:
`tests/ui/test_data_table.py` (Precision + Bulk-Load-Zähler) und
`tests/unit/test_sampling.py::TestSimpleSamplerIdsPath` (Bit-Repro alt vs. neu).

## Messung 1M – Sprint 34 (2026-07-02, Toolversion `6c4691e`)

Re-Baseline via `scripts/perf_probe.py --sizes 1000000` (Darwin arm64,
Python 3.13.13). Die Sprint-11-Tabelle unten war als Referenz wertlos
geworden (VOR den P-001/P-002-Fixes gemessen) – dies ist der neue
Vergleichsstand. Vergleichsspalte = historischer Sprint-11-Lauf (`19f18a1`).

| Phase | Sprint 34 | Peak (tracemalloc) | Sprint 11 (hist.) | Δ |
|-------|----------:|-------------------:|------------------:|---|
| Setup (xlsx generieren) | 7.66 min | 141.2 MB | 7.71 min | = |
| Import | 7.62 s | 5 KB | 7.60 s | = |
| DB-Speicherung | 53.71 s | 41 KB | 53.41 s | = (Pipeline-Total 61.3 s < 90 s ✓) |
| Tabelle-Anzeige | **0.27 s** | 371 KB | 34.58 s | **−99 % – P-001-Fix bestätigt** |
| Sampling Simple | **4.50 s** | **46.2 MB** | 15.90 s / 1074.6 MB | **−72 % Zeit, −96 % RAM – P-002-Fix bestätigt** |
| Sampling Cluster | 12.89 s | 1078.9 MB | 12.46 s | = (RAM-Materialisierung bekannt, P-003 deferred) |
| Sampling Stratified | 16.43 s | 1077.7 MB | 15.82 s | +4 % (einzige Target-Verfehlung, s. u.) |
| Filter-Toggle (an/aus) | 0.3 / 0.1 ms | 4 KB | 0.3 / 0.1 ms | = |
| Highlight / Clear | 4.1 / 0.1 ms | 40 KB | 2.6 / 0.1 ms | = (ms-Rauschen) |
| Excel-Export (Sample) | 0.28 s | 2.0 MB | 0.28 s | = |
| Excel-Report (Multi-Sheet) | 0.15 s | 1.4 MB | 0.13 s | = |
| HTML-Report | 0.25 s | 2.0 MB | 0.25 s | = |
| AuditTrail-PDF (5k Events) | 4.45 s (0.7 MB PDF) | 16.4 MB | 3.85 s (0.5 MB PDF) | +16 % (Querformat; P-004-Verdikt s. u.) |

Einzige Soft-Target-Verfehlung: **Sampling Stratified 16.43 s** vs. Target
15 s (+9,5 %). Ursache bekannt (P-003: `_collect_pool`-/Strata-Materialisierung
in `core/sampling.py`) und per Hard Constraint bewusst deferred – kein
Sprint-34-Gegenstand, kein neues Finding.

**P-004-Verdikt (AuditTrail-PDF 0,40 s → 3,85 s → 4,45 s):** Das Rätsel aus
Pass 3 v2 ist geklärt: Die Zahl ist **reproduzierbar und KEIN Maschinen-Drift**.
Isolierter Kontrolllauf (frischer Prozess, `--sizes 100 --quick
--audit-events 5000`, also ohne 1-GB-Sampling-Kontext davor): **4,44 s** –
identisch zu den 4,45 s im vollen 1M-Lauf. Damit sind die Drift-/GC-Hypothesen
aus dem Review widerlegt; ~4,4 s ist der echte Renderaufwand für 5k
synthetische Events auf dem aktuellen Stand. Der Anstieg 3,85 → 4,45 s (+16 %)
gegenüber Sprint 11 geht plausibel aufs Sprint-33-Querformat (breitere
„Datei"-Spalte → mehr Paragraph-Zellen, PDF 0,5 → 0,7 MB). Die historische
Sprint-10.4-Marke von 0,40 s ist als Vergleichspunkt nicht belastbar
(anderes Layout/Setup). Mit 4,45 s bei 5k Events liegt die Phase weit unter
dem Soft-Target (< 30 s) – **kein Handlungsbedarf**.

## Messung 1,000,000 Zeilen – historisch (Sprint 11, `19f18a1`, VOR P-001/P-002-Fixes)

| Phase | Zeit | Peak (tracemalloc) | RSS-Delta | Anmerkung |
|-------|-----:|-------------------:|----------:|-----------|
| Setup (xlsx generieren) | 7.71 min | 141.2 MB | — | 81.4 MB |
| Import | 7.60 s | 5 KB | — | Streaming – Zeilen-Anzahl steht nach Phase 2 fest |
| DB-Speicherung | 53.41 s | 41 KB | — | 1,000,000 rows, 0 skipped |
| Tabelle-Anzeige | 34.58 s | 1.7 MB | — |  |
| Sampling Simple | 15.90 s | 1074.6 MB | — | 500 rows |
| Sampling Cluster | 12.46 s | 1078.9 MB | — | 499827 rows |
| Sampling Stratified | 15.82 s | 1077.7 MB | — | 500 rows |
| Filter-Toggle (an) | 0.3 ms | 4 KB | — |  |
| Filter-Toggle (aus) | 0.1 ms | 0 KB | — |  |
| Highlight | 2.6 ms | 40 KB | — |  |
| Clear-Highlight | 0.1 ms | 1 KB | — |  |
| Excel-Export (Sample) | 0.28 s | 2.0 MB | — |  |
| Excel-Report (Multi-Sheet) | 0.13 s | 1.4 MB | — |  |
| HTML-Report | 0.25 s | 2.0 MB | — |  |
| AuditTrail-PDF | 3.85 s | 16.3 MB | — | 5000 events, 0.5 MB |

## Soft-Target-Verfehlungen – historisch (Sprint-11-Lauf)

| Größe | Phase | Gemessen | Skaliertes Target | Überschreitung |
|------:|-------|---------:|------------------:|---------------:|
| 1,000,000 | DB-Speicherung | 53.41 s | 30.00 s | +23.41 s |
| 1,000,000 | Tabelle-Anzeige | 34.58 s | 5.00 s | +29.58 s |
| 1,000,000 | Sampling Simple | 15.90 s | 10.00 s | +5.90 s |
| 1,000,000 | Sampling Stratified | 15.82 s | 15.00 s | +0.82 s |

## Auffälligkeiten

Werden manuell ergänzt, nachdem die Tabellen oben gelesen wurden. Erwartete Bottleneck-Hypothesen (siehe Sprint-10.1-Brief):

- DatasetRepo.create – `executemany`-Bulk-Insert, sollte skalieren
- values_json-Encoding pro Row – ein json.dumps-Aufruf je Zeile, potenziell sichtbar bei 1M+
- DataTableView.highlight_rows – Set-Lookup im BackgroundRole
- AuditTrail-PDF – reportlab.platypus mit vielen Flowables
- Stratified mit vielen Strata – largest-remainder-Schleifen

