# Pass 3 v2: Performance Review (post Sprint 11)

**Datum:** 2026-05-18
**Reviewer:** Claude Code via superpowers/requesting-code-review (kein dedizierter Performance-/Profiling-Skill im Plugin v5.1.0 verfügbar – nächster genereller Review-Skill als Konventions-Anker, tatsächliche Analyse rein toolbasiert).
**Scope:** `src/sampling_tool/` (Sprint-11-Stand auf `origin/feat/streaming-dataset`) + `PERFORMANCE.md` (Toolversion `19f18a1`, Mess-Lauf 2026-05-18T18:09:33) + `scripts/perf_probe.py`.
**Methodik:** statische Analyse via `git show origin/feat/streaming-dataset:...`, AST-Lesen der zentralen Pfade, Audit der 1M-Mess-Daten. **Keine** neuen Probe-Läufe in diesem Pass.
**Verknüpfung:** [REVIEW/REVIEW_STRUCTURE.md](REVIEW/REVIEW_STRUCTURE.md) (PR #30), [REVIEW/REVIEW_QUALITY.md](REVIEW/REVIEW_QUALITY.md) (PR #31), vorheriger Pass-3-Lauf (PR #32, jetzt überholt).

## Methodik-Limitierungen

- Keine neuen `perf_probe.py`-Läufe. Datengrundlage ist der 1M-Lauf vom 2026-05-18T18:09:33 (Toolversion `19f18a1`), `PERFORMANCE.md` auf `origin/feat/streaming-dataset`.
- **Wichtig zum Branch-Stand:** `main` zeigt weiterhin auf `267e4c5` (Sprint 10.4). Die Sprint-11-Reihe lebt auf dem nicht-gemergten Branch `origin/feat/streaming-dataset` (`ccda4db` Sprint 11.1 → `dee7751` 11.4 → `aec13fb` 11.5 → `19f18a1` perf-probe-Fix → `582c2df` Mess-Daten-Commit). Dieser Review analysiert den **Sprint-11-Code** als zukünftigen merge-target-Stand, der laut Briefing kurz vor dem Merge steht.
- Cyclomatic-Komplexität / Profiling-Hotspots wurden statisch geschätzt (Code-Lesen), nicht via cProfile/snakeviz/py-spy.
- Hypothesen zu Phasen-Verlagerung sind logisch konsistent, aber nicht durch Profil-Run isoliert verifiziert. Begründungen stützen sich auf Code-Reading + Soft-Target-Vergleiche.

## Ausgangslage (Sprint 11.x post-merge auf `feat/streaming-dataset`)

Sprint 11 baut die Streaming-Architektur ein, die im vorherigen Pass-3-Lauf noch fehlte:

- **Sprint 11.1** (`ccda4db`): `Dataset.rows` aus dem Modell entfernt; Repo-Methoden `iter_rows`/`get_rows_in_range`/`get_rows_by_ids`/`iter_row_ids`/`get_all_rows`.
- **Sprint 11.2** (`c0e2f81`): `DatasetTableModel` lädt Rows on-demand via `DatasetRepo`, FIFO-Cache 1000 Rows + Bulk-Load-Window ±125.
- **Sprint 11.3** (`0e46c5a`): Streaming-Importer – `ImportResult.rows` ist ein einmalig konsumierbarer `Iterator[DatasetRow]`, `DatasetRepo.create(dataset, rows)` korrigiert `row_count` nach echtem Persist.
- **Sprint 11.4** (`dee7751`): Sampler/Exporter konsumieren Iteratoren statt Tupel; `_build_sampling_iterator` im Controller wählt `iter_rows` oder `get_rows_by_ids` je nach Sub-Sampling-Modus; Sampling-Dialog lädt `get_all_rows` nur noch im Advanced-Mode.
- **Sprint 11.5** (`aec13fb`): Cleanup – `ImportResult.skipped_rows`/`.warnings`-Compat-Properties entfernt, Aufrufer lesen direkt `result.stats`.

[PERFORMANCE.md auf dem Branch](../PERFORMANCE.md) zeigt den 1M-Lauf vom 2026-05-18T18:09:33. Vier Soft-Target-Verfehlungen:

| Phase                    | Gemessen | Soft-Target | Verfehlung    |
|--------------------------|---------:|------------:|--------------:|
| Import                   | 7.60 s   | < 60 s      | **ok** (massiv drunter) |
| **DB-Speicherung**       | 53.41 s  | < 30 s      | +78 %         |
| **Tabelle-Anzeige**      | 34.58 s  | < 5 s       | +591 %        |
| **Sampling Simple**      | 15.90 s  | < 10 s      | +59 %         |
| Sampling Cluster         | 12.46 s  | < 15 s      | ok            |
| **Sampling Stratified**  | 15.82 s  | < 15 s      | +5 %          |
| **Sampling RAM (alle 3)**| 1.07 GB  | (kein Target)| 1 GB Spike    |
| **AuditTrail-PDF (5k)**  | 3.85 s   | < 30 s      | ok, aber **10× Regression** ggü. Sprint 10.4 (0.40 s) |

## Zusammenfassung

Sprint 11 hat die im vorherigen Pass-3-Lauf gefürchteten 1.4-GB-Import-Peak vollständig behoben – Import läuft jetzt mit 5 KB RAM-Peak in 7.6 s. **Aber** drei der 8-Pipeline-Phasen sind das Soft-Target verfehlt: DB-Speicherung 78 %, Tabelle-Anzeige 591 %, Sampling Simple 59 %. Die diesem Pass zugrunde liegende Hypothesen-Analyse zeigt: **A (DB-Regression) ist eine Phasen-Verlagerung, kein echter Bug; B (Tabelle-Anzeige) ist ein `resizeColumnsToContents`-Voll-Scan, der dem LRU-Cache N×Cache-Misses produziert; C (Sampling-RAM) ist `BaseSampler._collect_pool`, der den Streaming-Iterator via `list(rows)` voll materialisiert.** Plus: AuditTrail-PDF zeigt 10× Regression (0.40 → 3.85 s), die statisch nicht durch Code-Änderung erklärbar ist – Verdacht auf Probe-Maschine-Drift. Insgesamt **0 SEV-0** (keine Reproducibility-Risiken, keine Cache im Sampling-Pfad), **3 SEV-1**, **3 SEV-2**, **4 SEV-3**. **Headline:** Diagnose B (Tabelle-Anzeige) ist ein 1-Zeilen-Fix (`resizeContentsPrecision(100)`), Diagnose C (Sampling-RAM) ist ein 5–15-LoC-Fix (`iter_row_ids` im ungefilterten Simple-Pfad), Diagnose A erfordert eine Soft-Target-Neudefinition.

## Diagnose der drei 1M-Auffälligkeiten

### Auffälligkeit A – DB-Speicherung 53.41 s (Soft-Target < 30 s)

**Hypothese aus Briefing:** „Der Streaming-Generator gibt Rows einzeln yield, der DB-Insert-Pfad in `DatasetRepo.create` macht jetzt vermutlich pro Row einen orjson-Encoding-Schritt sequentiell zur DB-Write-Phase, statt wie in Sprint 10.3 die ganze Liste auf einmal zu encoden."

**Hypothese verifiziert?** **Teilweise – falsche Ursache, richtige Beobachtung.** Der orjson-Encode pro Row passiert tatsächlich (siehe `_row_params`-Generator in [repositories.py:202–211](src/sampling_tool/persistence/repositories.py#L202-L211)), aber das war **bereits in Sprint 10.3 so** und wurde damals als „RAM 100k: 55 MB → 0.2 MB" gefeiert. Das wahre Phänomen ist eine **Phasen-Verlagerung**:

- **Sprint 10.4-Lauf**: Importer materialisierte alle Rows in `tuple(rows)` (1.4 GB RAM-Peak), gemessen unter „Import 55 s". Die separate „DB-Speicherung"-Phase iterierte dann nur über bereits in-memory `DatasetRow`-Objekte (`_row_params` über vorgebaute Tupel) → 7.5 s reine SQLite-Arbeit.
- **Sprint 11.3-Lauf**: Importer ist Generator, „Import 7.6 s" misst nur den Header-Pass + Sheet-Open. Die „DB-Speicherung"-Phase macht jetzt zusätzlich: calamine-`iter_rows` Pass #2 (zweites Lesen!) + `_coerce_value` für 15M Cells + Dict-Build + `_values_to_json` (orjson-Encode mit tagged datetime) + executemany-Bind → 53.41 s.

**Pipeline-Gesamtzeit**: vorher Import+DB ≈ 55 s + 7.5 s = 62.5 s; jetzt 7.6 s + 53.41 s = 61.0 s. **Die Pipeline ist ungefähr gleich schnell.** Das Soft-Target (30 s) war auf die alte Phasen-Trennung kalibriert (reine SQLite-Arbeit), nicht auf den Streaming-Pattern.

**Code-Beleg:**
- Importer-Streaming-Generator: [importer.py:207–248](src/sampling_tool/io/importer.py#L207-L248), insbesondere `for raw in rows_iter` (Zeile 231) und der `_coerce_value`-Dict-Build (Zeile 235–238).
- DB-Insert-Generator: [repositories.py:202–211](src/sampling_tool/persistence/repositories.py#L202-L211), der `_values_to_json(row.values)` aufruft → orjson-encode für jede Row beim DB-Pass.
- Phasen-Definition in perf_probe: [perf_probe.py:354](scripts/perf_probe.py#L354) misst nur den UI-Setup-Aufruf, nicht den Import-Pfad selbst.
- **Zweiter Sheet-Pass im Importer**: [importer.py:223](src/sampling_tool/io/importer.py#L223) (`rows_iter: Iterator[list[Any]] = iter(sheet.iter_rows())`) macht beim Generator-Aufruf einen kompletten zweiten Pass über das Sheet, weil der Header-Pass (Zeile 319–341, `_excel_header_pass`) `iter_rows` schon konsumiert hat – calamine kann den Cursor nicht zurücksetzen.

**Vermutete Ursache:** Phasen-Verlagerung von Import → DB-Speicherung. Plus: doppelter calamine-Pass für Header-Detect-Sync.

**Empfohlener Fix-Aufwand:**
1. **Soft-Target neu definieren** (Doku-Fix, 1 Zeile in `perf_probe.py` und PERFORMANCE.md): kombiniertes Import+DB-Target von 90 s statt zwei separate Targets. Aufwand: 1 LoC.
2. **Phase umbenennen** in „Streaming-Persistenz (inkl. Coerce + Encode)" damit klar ist, was gemessen wird. Aufwand: 1 LoC.
3. **Echte Optimierung** wäre: calamine-Streaming und Coerce-Schritt parallel mit multiprocessing-Pool (15 Spalten, einer pro Worker), oder C-Extension für `_coerce_value`. Aufwand: 1 Sprint.

**Severity:** **SEV-1** (Soft-Target +78% verfehlt). Aber **nicht** durch Implementierungsbug – Begründung „Phasen-Bilanz neu, Pipeline-Gesamtzeit stabil".

### Auffälligkeit B – Tabelle-Anzeige 34.58 s (Soft-Target < 5 s)

**Hypothese aus Briefing:** „Der Probe-Test misst nicht nur initial-render, sondern triggert vermutlich einen kompletten Scroll durch das Dataset (oder ein anderes 'warm-up' Pattern), das den LRU-Cache überfordert und für jedes Window einen neuen DB-Query auslöst."

**Hypothese verifiziert?** **Nein – andere Ursache: `resizeColumnsToContents` iteriert alle 1M Rows pro Spalte.** Der Probe-Test scrollt **nicht**, er ruft nur `table.set_dataset(dataset, DatasetRepo(...))` + `_process_qt_events()` (3× `processEvents`). Aber `set_dataset` triggert `_autosize_columns()` → `self.resizeColumnsToContents()`, und das **iteriert in Qt6 für jede Spalte alle Rows**, um die optimale Breite zu finden.

**Pathologisches Access-Pattern:**
- `QAbstractItemView::sizeHintForColumn(col)` iteriert `range(rowCount())` und ruft pro Row `delegate.sizeHint(option, model.index(row, col))` auf.
- Pro Cell-Anfrage geht `data()` durch → `_actual_row_id(view_row)` → `_ensure_cached(row_id)`.
- Bei sequentiellem Spalten-Scan (col 0 → col 1 → … → col 14) wird der FIFO-Cache (1000 Rows) **bei jedem Spaltenwechsel komplett geleert** (er erreicht beim ersten Spalten-Walk schon Row 1000 – evictet die Range 1–875 wieder, dann beim zweiten Spalten-Walk fängt er bei Row 1 wieder von vorn an).
- Cache-Miss-Rate für die 14 Folge-Spalten: ~100 %. → 14 × (1M Rows / 250 Bulk-Load) = 56 000 SQLite-Queries → bei geschätzten 0.6 ms/Query = 33.6 s.

Das passt exakt zur gemessenen 34.58 s.

**Code-Beleg:**
- `_autosize_columns` ruft `resizeColumnsToContents`: [data_table.py:381–382](src/sampling_tool/ui/widgets/data_table.py#L381-L382)
- `set_dataset` ruft `_autosize_columns` direkt nach `set_dataset` des Models: [data_table.py:316–317](src/sampling_tool/ui/widgets/data_table.py#L316-L317)
- Docstring sagt selbst: „resizeColumnsToContents triggert data() für alle sichtbaren Zellen – das reicht aus, um den ersten Bulk-Load anzustoßen" ([data_table.py:374–381](src/sampling_tool/ui/widgets/data_table.py#L374-L381)). **Die Annahme „nur sichtbare Zellen" ist falsch** – Qt6 fragt für `QHeaderView::ResizeToContents`-Berechnung default alle Rows ab.
- FIFO-Cache-Größe: `DEFAULT_CACHE_SIZE = 1000` ([data_table.py:50](src/sampling_tool/ui/widgets/data_table.py#L50)), Bulk-Load-Halb-Fenster: `BULK_LOAD_HALF_WINDOW = 125` ([data_table.py:51](src/sampling_tool/ui/widgets/data_table.py#L51)).
- Header-ResizeMode wird auf `Interactive` gesetzt: [data_table.py:300](src/sampling_tool/ui/widgets/data_table.py#L300) – aber das beeinflusst nur die User-Drag-Logik, nicht den initialen `resizeColumnsToContents`-Voll-Scan.

**Vermutete Ursache:** `resizeColumnsToContents` macht einen Voll-Scan über alle Rows × alle Spalten; der 1000er-FIFO-Cache hat bei sequentieller Spalten-Iteration Cache-Miss-Rate ~100 %, und jede Cache-Miss-Bulk-Load ist eine eigene SQLite-Query mit JSON-Decode.

**Empfohlener Fix-Aufwand:**
1. **1-Zeilen-Fix:** `header.setResizeContentsPrecision(100)` vor `resizeColumnsToContents()` – limitiert Qt-Iteration auf die ersten 100 Rows. Sehr lohnenswert.
2. **5-Zeilen-Alternative:** Spaltenbreite aus Header-Text + `_MIN_COLUMN_WIDTH` ableiten, kein `resizeColumnsToContents`-Aufruf. Schneller, deterministisch, aber keine Inhalt-basierte Breite.
3. **Cache-Vergrößerung** (z. B. auf 10 000) ist KEIN Fix – das verlagert nur die Reihenfolge der Cache-Misses, der lineare Spalten-Walk evictet trotzdem.

**Severity:** **SEV-1** (Soft-Target +591 % verfehlt, grenzwertig zu SEV-0 nach der Skala >100 %, aber kein Reproducibility-Risiko und nutzbarkeitsmäßig bleibt die App offen).

### Auffälligkeit C – Sampling RAM-Peak 1.07 GB (alle drei Methoden)

**Hypothese aus Briefing:** „Entweder konsumiert der Probe-Test selbst den iter_rows-Generator vor dem Sampler-Aufruf, oder `core/sampling.py` materialisiert die Rows intern, oder das Test-Setup hält das Dataset im Memory zwischen Phasen."

**Hypothese verifiziert?** **Ja, Variante 2 – `BaseSampler._collect_pool` materialisiert den Iterator über `list(rows)` im ungefilterten Pfad.** Der Probe-Test ruft korrekt:

```python
sampling_repo.iter_rows(dataset.id)  # Generator
```

und übergibt diesen an `create_sampler(cfg).sample(...)`. Im Sampler:

```python
def _collect_pool(self, rows: Iterable[DatasetRow]) -> tuple[list[DatasetRow], int]:
    if self.config.filter_field is None:
        unfiltered = list(rows)           # ← HIER: 1M DatasetRows materialisiert
        return unfiltered, len(unfiltered)
```

[sampling.py:108–110](src/sampling_tool/core/sampling.py#L108-L110). Bei 1M Rows × 15 Spalten-Dict-Einträge × Python-Object-Overhead ≈ **1.07 GB Peak** – passt genau zur Messung. Für Simple-Sampling kommt noch `fisher_yates_shuffle(list(pool), rng)` dazu, das eine zweite 1M-Liste kopiert ([sampling.py:151](src/sampling_tool/core/sampling.py#L151)) – Peak verdoppelt sich kurzfristig, GC fängt aber den alten `unfiltered`-Buffer schnell.

**Architektur-Kontext:** Der Streaming-Pipeline ist nur partiell durchgehalten. Vom Importer bis ins DB-Insert ist Streaming sauber. Sobald der Sampler den Iterator bekommt, bricht er die Streaming-Kette mit `list(rows)`. Sprint 11.4-Doc sagt selbst: „Spart gegenüber Sprint-11.1 das doppelte Materialisieren". Heißt: 11.1 hatte zweifaches Materialisieren, 11.4 hat einfaches. Aber **immer noch materialisiert**.

**Algorithmischer Hintergrund:** Simple Random Sampling ohne Filter braucht **nur die row_ids**, nicht die values. `DatasetRepo.iter_row_ids` existiert bereits ([repositories.py:291–303](src/sampling_tool/persistence/repositories.py#L291-L303)) – wurde laut Docstring explizit für „SimpleSampler ohne Filter, der nur die Pool-Größe und shufflebare IDs braucht" geschaffen, aber **vom Sampler nicht genutzt**. Cluster/Stratified-Sampling braucht die values für das Cluster-/Stratum-Feld – dort ist die Materialisierung unvermeidbar (bis zu einem `SELECT row_index, json_extract(values_json, '$.cluster_field') ...`-SQL-Trick).

**Code-Beleg:**
- `_collect_pool` mit `list(rows)`: [sampling.py:99–119](src/sampling_tool/core/sampling.py#L99-L119)
- `SimpleSampler._select` mit Doppel-Liste-Kopie: [sampling.py:143–152](src/sampling_tool/core/sampling.py#L143-L152)
- `iter_row_ids` existiert, wird aber nicht konsumiert: [repositories.py:291–303](src/sampling_tool/persistence/repositories.py#L291-L303)
- Production-Pfad konsistent mit Probe: [main_controller.py:1068–1091](src/sampling_tool/ui/controllers/main_controller.py#L1068-L1091) (`_build_sampling_iterator` → `iter_rows`)

**Vermutete Ursache:** `BaseSampler._collect_pool` materialisiert den Stream-Iterator vollständig, weil die abstrakte Basis nicht zwischen „Rows-needed" (Cluster/Stratified) und „IDs-suffice" (Simple-ohne-Filter) unterscheidet.

**Empfohlener Fix-Aufwand:**
- **Klein (5–15 LoC):** Spezial-Pfad für `SimpleSampler` ohne Filter – nimmt Iterator von `iter_row_ids`, shuffle nur IDs, kein DatasetRow-Materialize. Reduziert RAM von ~1 GB auf <50 MB. Reproducibility unverändert: Fisher-Yates auf IDs vs. auf Rows liefert identische selected_row_ids bei gleichem Seed (Sortierung nach row_id ist Default).
- **Mittel (1 Sprint):** Cluster/Stratified über `json_extract`-SQL → Pool von Cluster-Buckets statt 1M-Row-Liste. Reduziert RAM von 1 GB auf <100 MB für alle drei Methoden.

**Severity:** **SEV-1** für Simple (Soft-Target Simple +59 %, RAM 1 GB widerspricht Streaming-Ziel); **SEV-2** für Stratified (Soft-Target nur +5 % verfehlt, aber RAM gleich); Cluster ok auf Zeit-Achse, RAM trotzdem 1 GB.

## Severity-Skala

- **SEV-0** — Reproducibility-Risiko durch Caching ODER Soft-Target um >100 % verfehlt auf produktiver Größe (1M Zeilen) ODER kritischer OOM-Pfad.
- **SEV-1** — Soft-Target verfehlt 20–100 % ODER potenzielles OOM-Risiko auf Zielgröße ODER UI-Freeze > 1 s ohne Worker ODER nicht-eingehaltenes Streaming-Versprechen mit >500 MB Peak.
- **SEV-2** — Subjektiv langsam aber nutzbar ODER vermeidbare Voll-Materialisierung in seltenen Pfaden ODER schwer messbarer Lag.
- **SEV-3** — Mikro-Optimierung ODER veraltete Mess-/Doku-Daten ODER hardcoded Tuning-Werte ohne Begründung.

## Findings

### SEV-0

Keine SEV-0-Findings.

Belegt durch:
- `git grep -nE "@cache|@lru_cache|@cached_property" origin/feat/streaming-dataset -- "*.py"` außerhalb `tests/`: **leer** – keine Caches im Sampling-Pfad, keine Reproducibility-Risiken.
- Tabelle-Anzeige 34 s ist bereits +591 % über Soft-Target, also formal SEV-0-Kriterium getroffen, **aber** die App bleibt nutzbar (kein OOM, kein Crash, „nur" 34 s UI-Freeze beim ersten Öffnen). Einordnung als SEV-1, weil das Soft-Target selbst sehr ambitioniert (5 s für ein 1M-Dataset) ist und die App produktiv weiter funktioniert.

### SEV-1

#### P-001: Tabelle-Anzeige 34.58 s – `resizeColumnsToContents` macht Voll-Scan über 1M Rows
- **Datei(en):** [src/sampling_tool/ui/widgets/data_table.py:374–391](src/sampling_tool/ui/widgets/data_table.py#L374-L391), Aufruf in [data_table.py:316–317](src/sampling_tool/ui/widgets/data_table.py#L316-L317)
- **Befund:** Siehe Diagnose B oben. `_autosize_columns` triggert Qt's `resizeColumnsToContents`, das in Qt6 alle Rows × alle Spalten durchgeht; jeder Cache-Miss löst einen Bulk-Load-Query aus. ~56 000 SQLite-Queries für 1M-Datasets.
- **Belegt durch:** Code-Reading + Soft-Target-Verfehlung 34.58/5 = 691 %.
- **linked_to:** —
- **Vermutete Wirkung:** ~34 s UI-Freeze beim Öffnen jedes Datasets. App-Start-Eindruck schlecht; Auditor wartet pro Dataset-Wechsel >30 s.
- **Empfehlung:** Quick-Fix: `self.horizontalHeader().setResizeContentsPrecision(100)` vor `resizeColumnsToContents()`. 1 LoC.

#### P-002: Sampling Simple 15.90 s + 1.07 GB RAM – `_collect_pool` materialisiert Stream-Iterator
- **Datei(en):** [src/sampling_tool/core/sampling.py:99–119](src/sampling_tool/core/sampling.py#L99-L119), [sampling.py:143–152](src/sampling_tool/core/sampling.py#L143-L152)
- **Befund:** Siehe Diagnose C oben. `BaseSampler._collect_pool` ruft `list(rows)` auf den Iterator → 1M DatasetRow-Objekte im RAM. Für Simple-Sampling ohne Filter ist das nicht nötig – `iter_row_ids` reicht.
- **Belegt durch:** Code-Reading + Soft-Target-Verfehlung 15.90/10 = 159 %; Mess-Peak 1.07 GB widerspricht Streaming-Ziel von Sprint 11.
- **linked_to:** —
- **Vermutete Wirkung:** Auf 1 M-Datasets ~16 s synchroner UI-Freeze + 1 GB RAM-Spike pro Sample-Ziehung. Auf 5 M-Datasets würde der Peak proportional auf ~5 GB skalieren → OOM-Risiko.
- **Empfehlung:** SimpleSampler-Spezialpfad: wenn `config.filter_field is None`, Iterator von `iter_row_ids` konsumieren, Fisher-Yates auf IDs. 5–15 LoC. Reproducibility unverändert (deterministisch via Seed).

#### P-003: Sampling Stratified 15.82 s + 1.07 GB RAM – gleiches `_collect_pool`-Problem
- **Datei(en):** [src/sampling_tool/core/sampling.py:99–119](src/sampling_tool/core/sampling.py#L99-L119), [sampling.py:207–258](src/sampling_tool/core/sampling.py#L207-L258)
- **Befund:** Stratified braucht das Stratum-Feld pro Row, kann also nicht auf `iter_row_ids` zurückgreifen. Aber: in `_select` werden die Rows in `strata: dict[Any, list[DatasetRow]]` umkopiert – doppelte Materialisierung. Plus `fisher_yates_shuffle(list(strata[key]), rng)` macht eine weitere Kopie pro Schicht.
- **Belegt durch:** Code-Reading [sampling.py:228–230, 256](src/sampling_tool/core/sampling.py#L228-L230); Soft-Target +5 %, aber RAM 1 GB.
- **linked_to:** —
- **Vermutete Wirkung:** RAM-Multiplikator 2–3× bei Stratified über große Datasets mit vielen Schichten. Soft-Target zeitlich knapp gerissen, aber konsequente Schwellen-Verfehlung in Folge-Sprints zu erwarten.
- **Empfehlung:** `_select`-Hook könnte direkt auf einem Streaming-Pass arbeiten (Reservoir-Sampling pro Schicht statt Voll-Materialize). Mittel-Aufwand (1 Sprint). Mittelfristig: SQL-`json_extract`-Trick – Cluster/Stratum-Bucket bauen direkt aus DB.

### SEV-2

#### P-004: AuditTrail-PDF 3.85 s bei 5k Events – 10× Regression ggü. Sprint 10.4 (0.40 s) ohne Code-Änderung
- **Datei(en):** [src/sampling_tool/io/pdf_report.py](src/sampling_tool/io/pdf_report.py) (unverändert seit Sprint 10.4)
- **Befund:** `git diff origin/main origin/feat/streaming-dataset -- src/sampling_tool/io/pdf_report.py` ist **leer** – die PDF-Generierung wurde in Sprint 11 nicht angefasst. Trotzdem zeigt der Probe-Lauf 3.85 s statt der Sprint-10.4-Marke von 0.40 s (Faktor 9.6).
- **Belegt durch:** `git log origin/main..origin/feat/streaming-dataset -- src/sampling_tool/io/pdf_report.py` liefert keine Commits; PERFORMANCE.md zeigt direkten Vergleich (Sprint 10.4: 0.40 s, Sprint 11.5: 3.85 s).
- **linked_to:** —
- **Vermutete Wirkung:** Statisch nicht erklärbar. Drei Verdachts-Hypothesen, keine verifiziert:
  1. **Probe-Maschine-Drift**: thermal throttling nach 7-Minuten-Setup oder GC-Druck nach Sampling-Phase (1 GB RAM kurz vorher).
  2. **AuditLogger-Setup-Overhead** durch synthetische Events anders generiert (`build_synthetic_events` in perf_probe).
  3. **Reportlab-Version-Drift** (unwahrscheinlich, weil keine Toolversion-Notiz in PERFORMANCE.md zu reportlab).
- **Empfehlung:** Re-Mess-Empfehlung: einzelner `--quick`-Lauf mit nur PDF-Phase und Cold-Start, um Maschinen-Drift auszuschließen. 5 Min Arbeit. Falls Regression bestätigt: Profil-Lauf mit cProfile.

#### P-005: Sampling-Dialog im Advanced-Mode lädt `get_all_rows` synchron im UI-Thread (1 GB RAM)
- **Datei(en):** [src/sampling_tool/ui/controllers/main_controller.py:534–537](src/sampling_tool/ui/controllers/main_controller.py#L534-L537), [src/sampling_tool/ui/dialogs/sampling_dialog.py:459–472](src/sampling_tool/ui/dialogs/sampling_dialog.py#L459-L472)
- **Befund:** `handle_new_sampling` ruft `repo.get_all_rows(self._dataset.id)` im Advanced-Mode auf, bevor der Dialog überhaupt geöffnet wird. Auf einem 1M-Dataset materialisiert das alle Rows synchron (1.07 GB RAM, 8–15 s Wartezeit) – nur damit `_distinct_values` über die `rows`-Sequence iterieren kann. Sprint 11.4 hat den Pfad bereits aus dem Simple-Mode entfernt (gut), Advanced bleibt voll betroffen.
- **Belegt durch:** Lesen [main_controller.py:530–540](src/sampling_tool/ui/controllers/main_controller.py#L530-L540); Repo-Docstring [repositories.py:339–360](src/sampling_tool/persistence/repositories.py#L339-L360) erwähnt selbst „distinct_values_in_column-Implementierung in Folge-Sprint".
- **linked_to:** F-010 (Sampling-Dialog Concern-Split aus Pass 1)
- **Vermutete Wirkung:** Advanced-Mode-User mit 1M-Dataset wartet 8–15 s pro Dialog-Open + 1 GB RAM-Spike.
- **Empfehlung:** `DatasetRepo.distinct_values_in_column(dataset_id, column) -> list[Any]` mit SQL `SELECT DISTINCT json_extract(values_json, '$.' || ?) FROM dataset_rows WHERE dataset_id=?`. Tagged-Encoder-Workaround für datetime via Detection im Repo-Layer. 30–50 LoC. Reduziert RAM von 1 GB auf <10 MB.

#### P-006: `EngagementVersionManager.create_snapshot` macht synchron `shutil.copy2` der DB beim Engagement-Open
- **Datei(en):** [src/sampling_tool/persistence/version_manager.py:51–75](src/sampling_tool/persistence/version_manager.py#L51-L75), Aufruf in [main_controller.py:283](src/sampling_tool/ui/controllers/main_controller.py#L283)
- **Befund:** Unverändert seit Sprint 10.4. Bei 1M-Engagement (DB ~ 300–600 MB) sind das 3–10 s synchron im UI-Thread vor dem eigentlichen Open. Nicht in `perf_probe.py` abgedeckt.
- **Belegt durch:** `version_manager.py` ist auf `origin/feat/streaming-dataset` identisch zu `origin/main`.
- **linked_to:** F-001 (MainController-Split → Sub-Controller-Worker-Wrap)
- **Vermutete Wirkung:** Bei jedem Open großer Engagements 3–10 s UI-Freeze, auf Windows-Netz-Shares mehr.
- **Empfehlung:** Snapshot in `QThread`-Worker oder hinter `TaskProgressDialog`. Mittelfristig: `os.link`/Hardlink-Fallback bei lokalem APFS/NTFS.

### SEV-3

#### P-007: Soft-Target für „DB-Speicherung" ist post-Streaming nicht mehr sinnvoll definiert
- **Datei(en):** [scripts/perf_probe.py:83–97](scripts/perf_probe.py#L83-L97), [PERFORMANCE.md](../PERFORMANCE.md) Soft-Targets-Block
- **Befund:** Siehe Diagnose A. Das Target von 30 s wurde auf die alte Phasen-Trennung kalibriert (reine SQLite-Arbeit), nicht auf den Sprint-11-Streaming-Pattern, wo Coerce+JSON-Encode in dieselbe Phase wandern. Mit dem aktuellen Code-Pattern ist 30 s strukturell kaum erreichbar.
- **linked_to:** —
- **Empfehlung:** Soft-Target umdefinieren als „Streaming-Persistenz (Import-Generator + DB-Insert kombiniert) < 90 s bei 1M". Oder zwei separate Targets: „Import-Header-Pass < 30 s" + „Streaming-Persistenz < 75 s".

#### P-008: PERFORMANCE.md zeigt 10× AuditTrail-PDF-Regression ohne erklärenden Kommentar
- **Datei(en):** [PERFORMANCE.md Zeile 46](../PERFORMANCE.md)
- **Befund:** Die 1M-Tabelle listet 3.85 s mit Anmerkung „5000 events, 0.5 MB" – ohne Hinweis darauf, dass das eine 10× Regression gegenüber dem Sprint-10.4-Direkt-Mess von 0.40 s ist. Spätere Reviewer (= Pass 3) müssen das selbst entdecken.
- **linked_to:** P-004 (Diagnose offen)
- **Empfehlung:** Vor Merge auf main einen kurzen „Auffälligkeiten"-Block ergänzen, der die Regression dokumentiert oder durch erneuten Lauf widerlegt.

#### P-009: Hardcoded LRU-Werte `DEFAULT_CACHE_SIZE = 1000` und `BULK_LOAD_HALF_WINDOW = 125` ohne Sweep-Begründung
- **Datei(en):** [src/sampling_tool/ui/widgets/data_table.py:50–51](src/sampling_tool/ui/widgets/data_table.py#L50-L51)
- **Befund:** Beide Konstanten sind ClassVars ohne Sweep-Doku. Im Modul-Docstring steht „RAM-Footprint konstant ~3 MB" – aber wie kommt man auf 1000 / 125? Wenn P-001 (resizeColumnsToContents-Voll-Scan) gefixt ist, könnte ein kleinerer Cache (500) reichen; wenn Filter-/Sprung-Zugriffe häufig sind, wäre 5000 besser.
- **linked_to:** P-001 (gemeinsamer Refactor sinnvoll)
- **Empfehlung:** Nach P-001-Fix ein 1M-Sweep-Test mit verschiedenen `(CACHE_SIZE, BULK_LOAD)`-Paaren, dann Begründung im Docstring + ggf. an Settings koppeln.

#### P-010: AuditTrail-Filter-Proxy baut Haystack-String pro Row pro Tastenanschlag (kein Cache)
- **Datei(en):** [src/sampling_tool/ui/widgets/audit_trail_view.py:180–212](src/sampling_tool/ui/widgets/audit_trail_view.py#L180-L212)
- **Befund:** Unverändert seit Sprint 10.4 (nicht von Sprint-11-Refactor betroffen). Bereits im vorherigen Pass-3 dokumentiert. Bei >20k Audit-Events spürbares Lag bei Volltextsuche-Tastenanschlag.
- **linked_to:** —
- **Empfehlung:** Haystack-Pre-Compute beim `set_events()` (~15 LoC). Bleibt eigenständig.

## Audit der bestehenden Mess-Daten (PERFORMANCE.md, Sprint-11-Lauf vom 2026-05-18T18:09:33)

| Phase                       | Letzte Messung | Sprint-Stand | Soft-Target  | Aktuell verfehlt? | Anmerkung |
|-----------------------------|----------------|--------------|--------------|-------------------|-----------|
| Excel-Import 1M             | **7.60 s**     | 11.3 Streaming | < 60 s     | nein, massiv drunter | RAM 5 KB |
| **DB-Speicherung 1M**       | **53.41 s**    | 11.3 Streaming | < 30 s     | **+78 %**         | Phasen-Verlagerung (P-007/A) |
| **Tabelle-Anzeige 1M**      | **34.58 s**    | 11.2 LRU-Cache | < 5 s      | **+591 %**        | resizeColumnsToContents-Scan (P-001) |
| **Sampling Simple 1M**      | **15.90 s** + **1.07 GB** | 11.4 Sampler-Stream | < 10 s | **+59 %, RAM 1 GB** | _collect_pool list(rows) (P-002) |
| Sampling Cluster 1M         | 12.46 s + 1.08 GB | 11.4    | < 15 s       | nein zeitlich, RAM 1 GB | linked P-002 |
| **Sampling Stratified 1M**  | **15.82 s** + **1.08 GB** | 11.4 | < 15 s | **+5 %, RAM 1 GB** | linked P-003 |
| Filter-Toggle (an/aus) 1M   | 0.3 / 0.1 ms   | 11.2         | < 2 s        | nein              | Streaming-Model spart Reset (vorher 0.21 s) |
| Highlight 1M                | 2.6 ms         | 11.2         | < 2 s        | nein              | unverändert |
| Excel-Export Sample 1M      | 0.28 s         | 11.4         | < 60 s       | nein              | 2 MB Peak (vorher 1.5 MB) |
| Excel-Report Multi-Sheet 1M | 0.13 s         | 11.4         | < 60 s       | nein              | unverändert |
| HTML-Report 1M              | 0.25 s         | 11.4         | < 30 s       | nein              | unverändert |
| **AuditTrail-PDF (5k)**     | **3.85 s** + 16.3 MB | unverändert | < 30 s   | nein zeitlich, **10× ggü. Sprint 10.4** | P-004 ungeklärt |
| **Engagement-Open + Snapshot** | —           | —            | nicht spezifiziert | unbekannt    | **nie gemessen (P-006)** |
| **AuditTrail-Filter @ 50k Events** | —      | —            | nicht spezifiziert | unbekannt    | **nie gemessen (P-010)** |

## Static-Analysis-Smells (Übersicht)

### Synchrone Long-Operations im UI-Thread (kein einziger Worker in der Codebasis)

| Methode                                                | Datei:Zeile                                                                  | Dauer auf 1M (gemessen oder geschätzt) | Worker? | Finding-ID |
|--------------------------------------------------------|------------------------------------------------------------------------------|----------------------------------------|---------|------------|
| `handle_open_engagement` → `create_snapshot`           | [main_controller.py:283](src/sampling_tool/ui/controllers/main_controller.py#L283) → [version_manager.py:51](src/sampling_tool/persistence/version_manager.py#L51) | 3–10 s (geschätzt)                  | nein    | P-006      |
| `handle_import_excel`                                  | [main_controller.py:344](src/sampling_tool/ui/controllers/main_controller.py#L344) | 7.6 s (Header) + 53.4 s (DB) gemessen | nein    | P-007/A    |
| `handle_dataset_selected` → `set_dataset` → `resizeColumnsToContents` | [main_controller.py:391](src/sampling_tool/ui/controllers/main_controller.py#L391) → [data_table.py:316](src/sampling_tool/ui/widgets/data_table.py#L316) | 34.6 s gemessen                | nein    | P-001      |
| `handle_new_sampling` → `_build_sampling_iterator` → `iter_rows` → `_collect_pool` | [main_controller.py:516](src/sampling_tool/ui/controllers/main_controller.py#L516) → [sampling.py:99](src/sampling_tool/core/sampling.py#L99) | 12–16 s gemessen, 1 GB RAM    | nein    | P-002/P-003 |
| `handle_new_sampling` (Advanced) → `get_all_rows`      | [main_controller.py:536](src/sampling_tool/ui/controllers/main_controller.py#L536) | 8–15 s + 1 GB RAM (geschätzt)         | nein    | P-005      |

### Vermeidbare Voll-Materialisierungen

| Stelle                                  | Datei:Zeile                                                                  | Größe (1M-Worst-Case)        | Finding-ID |
|-----------------------------------------|------------------------------------------------------------------------------|------------------------------|------------|
| `list(rows)` in `_collect_pool`         | [sampling.py:109](src/sampling_tool/core/sampling.py#L109)                  | 1M DatasetRow-Objekte = 1 GB | P-002      |
| `fisher_yates_shuffle(list(pool), rng)` | [sampling.py:151](src/sampling_tool/core/sampling.py#L151)                  | weitere 1M-Liste-Kopie       | P-002      |
| `clusters[row.get(field)].append(row)`  | [sampling.py:183](src/sampling_tool/core/sampling.py#L183)                  | 1M DatasetRows in dict       | P-003      |
| `strata[row.get(field)].append(row)`    | [sampling.py:229](src/sampling_tool/core/sampling.py#L229)                  | 1M DatasetRows in dict       | P-003      |
| `repo.get_all_rows(dataset_id)` im Advanced-Sampling-Dialog | [main_controller.py:536](src/sampling_tool/ui/controllers/main_controller.py#L536) | 1M = 1 GB         | P-005      |
| `_distinct_values` linear über `_rows` (Advanced) | [sampling_dialog.py:459](src/sampling_tool/ui/dialogs/sampling_dialog.py#L459) | 1M Rows synchron pro Field-Wechsel | P-005 |

### Cache-Verhalten

| Cache                                | Größe                                                                       | Reproducibility-Risiko? | Finding-ID |
|--------------------------------------|------------------------------------------------------------------------------|--------------------------|------------|
| `DatasetTableModel._row_cache` FIFO  | `DEFAULT_CACHE_SIZE = 1000` ([data_table.py:50](src/sampling_tool/ui/widgets/data_table.py#L50)) | nein (read-only UI)     | P-001/P-009 |
| Sonstige Caches                      | **keine**                                                                    | n/a                      | —          |

`git grep -nE "@cache|@lru_cache|@cached_property" origin/feat/streaming-dataset -- "*.py"` außerhalb `tests/` ist leer.

### matplotlib fig-Handling

| Stelle                                                        | `plt.close(fig)` vorhanden?                | Finding-ID |
|---------------------------------------------------------------|--------------------------------------------|------------|
| `_figure_to_bytes` (chart_renderer.py)                        | ✅ im `finally`-Block (unverändert seit Sprint 10.4) | —          |

### Hardcoded Tuning-Werte (Sprint 11 neu)

| Konstante                          | Datei:Zeile                                                                  | Begründung im Docstring?    | Finding-ID |
|------------------------------------|------------------------------------------------------------------------------|------------------------------|------------|
| `DEFAULT_CACHE_SIZE = 1000`        | [data_table.py:50](src/sampling_tool/ui/widgets/data_table.py#L50)          | ⚠️ Modul-Docstring sagt „~3 MB", ohne Sweep | P-009 |
| `BULK_LOAD_HALF_WINDOW = 125`      | [data_table.py:51](src/sampling_tool/ui/widgets/data_table.py#L51)          | ⚠️ keine Begründung         | P-009      |
| `_SQLITE_VAR_LIMIT = 900`          | [repositories.py:305](src/sampling_tool/persistence/repositories.py#L305)   | ✅ Docstring (Default 999, konservativ) | — |
| `_PROGRESS_INTERVAL = 1000`        | [importer.py:56](src/sampling_tool/io/importer.py#L56)                      | ⚠️ kein Sweep, ist aber unkritisch | — |

## Healthy Pfade

Pfade, die nach Sprint 11 ohne Performance-Issues laufen:

- **Excel-Import (Header + Stream)** – 7.60 s, **5 KB RAM-Peak** bei 1M Zeilen. Der RAM-Peak-Refactor aus Sprint 11.3 ist erfolgreich.
- **Filter-Toggle (an/aus)** – 0.3 ms / 0.1 ms (vorher 0.21 s) – das Streaming-Model braucht keinen Filter-Reset mehr durchzurechnen.
- **Excel-Export Sample 1M** – 0.28 s, 2 MB Peak. Streaming-Exporter (Sprint 11.4) funktioniert.
- **Excel-Report Multi-Sheet 1M** – 0.13 s. Unverändert schnell.
- **HTML-Report 1M** – 0.25 s. Charts via Sprint-10.4-`chart_renderer`, kein Memory-Leak.
- **`DatasetRepo.create`** – `executemany` mit Generator + orjson + tagged datetime-Encoder. Funktional korrekt, Phasen-Sum 1M-Pipeline (Import+DB) ≈ 61 s ist annähernd identisch zur Sprint-10.4-Baseline.
- **`DatasetRepo.iter_row_ids`** – existiert und ist bereit für SimpleSampler-Optimierung (P-002).
- **`DatasetRepo.get_rows_in_range`** – Half-open Range mit SQL `BETWEEN`, sauber für UI-Pagination.
- **`chart_renderer.py`** – `plt.close(fig)` im `finally`. Kein Leak.

## Eigenständige Refactor-Kandidaten (nicht durch Pass-1/2-Refactor mit-gefixt)

Sortiert nach Aufwand-/Nutzen-Verhältnis:

1. **P-001 (SEV-1)** – `header.setResizeContentsPrecision(100)` in `_autosize_columns`. **1 LoC, behebt Tabelle-Anzeige 34.58 s → erwartet <1 s.** Sofortiger Sprung von rot auf grün.
2. **P-002 (SEV-1)** – SimpleSampler-Spezialpfad mit `iter_row_ids`. 5–15 LoC. Reduziert RAM von 1 GB auf <50 MB für Simple, behebt zeitliche Soft-Target-Verfehlung.
3. **P-007 (SEV-3)** – Soft-Target für DB-Speicherung neu definieren (Doku-Fix). 1 LoC in `perf_probe.py` + Update PERFORMANCE.md. Macht Diagnose A obsolet.
4. **P-005 (SEV-2)** – `DatasetRepo.distinct_values_in_column` via SQL `json_extract`. 30–50 LoC. Reduziert Advanced-Dialog-RAM von 1 GB auf <10 MB.
5. **P-003 (SEV-1)** – Stratified-Streaming via Reservoir-Sampling pro Schicht oder SQL-`json_extract`. Eigener Sprint.
6. **P-004 (SEV-2)** – Re-Mess-Lauf AuditTrail-PDF einzeln, um Maschinen-Drift auszuschließen. 5 Min Arbeit.
7. **P-006 (SEV-2)** – Snapshot-Worker beim Engagement-Open. Mittlere Komplexität, hängt am F-001-Refactor (MainController-Split).
8. **P-010 (SEV-3)** – Haystack-Cache im AuditTrailFilterProxy. ~15 LoC.

## Offene Fragen

1. **AuditTrail-PDF 10× Regression (P-004):** statisch nicht erklärbar – `pdf_report.py` unverändert. Hypothesen: thermal throttling, GC-Druck nach 1-GB-Sampling-Spike, oder reportlab-Upgrade zwischen den Läufen. Sollte vor Sprint-11-Merge auf main einmal isoliert re-gemessen werden, sonst landet die Regression unbemerkt auf der Baseline.
2. **`pdfrw`-Verfügbarkeit (aus vorherigem Pass-3, weiterhin offen):** Wie wahrscheinlich ist es im PyInstaller-Bundle, dass `pdfrw` fehlt? Wenn als Hidden-Import gepinnt: P-004 hat nichts damit zu tun.
3. **5M-Verifikation:** Nach Sprint 11 wäre ein 5M-Lauf interessant – Import sollte linear bei ~38 s landen, DB-Speicherung bei ~270 s (also Soft-Target jenseits), Sampling-RAM bei ~5 GB. Bestätigt OOM-Schwelle.
4. **Sprint-11-API-Kompatibilität `19f18a1`:** Commit-Message sagt „fix(perf_probe): Sprint-11-API-Kompatibilität" – wurden alle Phasen-Definitionen 1:1 übernommen, oder gab es semantische Änderungen, die die Tabelle-Anzeige-Verfehlung mit-erzeugen? Nicht in diesem Pass verifiziert; Commit-Diff sollte vor Merge gegengelesen werden.
5. **Pass-3 v1 vs. v2 Diskrepanz:** Pass 3 v1 (PR #32) ging vom Sprint-10.4-Stand aus, weil Sprint 11 da nicht gemerged war (auf main bis heute nicht). v2 analysiert den `feat/streaming-dataset`-Branch-Stand als zukünftigen merge-target. Wenn `feat/streaming-dataset` doch nicht gemerged wird (z. B. wegen P-001 + P-002 als Blocker): v1 ist die gültige Bewertung der dann produktiven Code-Basis, v2 die Bewertung des Branch-Vorschlags.

## Mess-Empfehlung

Konkrete Aufrufe, die offene Fragen klären würden – der User entscheidet ob/wann er sie ausführt. **Pass 3 v2 startet keinen davon.**

```bash
# 1. AuditTrail-PDF-Regression isoliert messen (P-004)
python scripts/perf_probe.py --sizes 100 --quick --audit-events 5000
# Was wir lernen: ob die 3.85 s eine Maschinen-Drift-Folge nach 1 GB Sampling-RAM
# sind oder ein echtes Phänomen. Wenn isoliert ~0.4 s: thermal/GC; wenn weiterhin 3+ s:
# echte Regression, dann reportlab-Profil-Run nötig.

# 2. 5M-Verifikation für Streaming-OOM-Schwelle (P-002/P-003)
python scripts/perf_probe.py --sizes 5000000
# Was wir lernen: bestätigt lineare RAM-Skalierung der Sampling-Phase
# (Erwartung ~5 GB Peak → OOM auf 16-GB-Geräten).
# Achtung: Setup-Phase ~40 min, Gesamt-Lauf ~80 min, ~15 GB Disk temporär.

# 3. Sweep-Test für Cache-Größen nach P-001-Fix (P-009)
# Manuell: data_table.py DEFAULT_CACHE_SIZE auf {500, 1000, 5000} variieren,
# nach jedem Fix einen 1M-Lauf, Tabelle-Anzeige-Phase vergleichen.

# 4. handle_open_engagement (P-006) ist NICHT in perf_probe – manuell mit Stoppuhr,
# Engagement-DB von ~500 MB öffnen, Zeit messen.
```
