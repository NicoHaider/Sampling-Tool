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

Follow-up-Kandidaten (Sprint 24; Stand nach Sprint 25):
- **Offen:** Debounce/Delay für die Volltextsuche (z. B. 150 ms QTimer) würde
  die verbleibende Keystroke-Latenz bei sehr großen Event-Listen kaschieren.
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

**Hinweis zur Mess-Tabelle unten:** Der 1M-Lauf stammt vom Sprint-11-Stand
(Toolversion `19f18a1`) und liegt damit VOR den Sprint-12.1-Fixes für P-001
(`setResizeContentsPrecision(100)` → Tabelle-Anzeige) und P-002
(`SimpleSampler.sample_ids` via `iter_row_ids` → Sampling-Simple-RAM).
Die Zeilen „Tabelle-Anzeige 34.58 s" und „Sampling Simple 15.90 s / 1.07 GB"
beschreiben den Zustand VOR diesen Fixes (inzwischen behoben); Regression-Guards:
`tests/ui/test_data_table.py` (Precision + Bulk-Load-Zähler) und
`tests/unit/test_sampling.py::TestSimpleSamplerIdsPath` (Bit-Repro alt vs. neu).

## Messung 1,000,000 Zeilen

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

## Soft-Target-Verfehlungen (Sprint-10.2-Kandidaten)

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

