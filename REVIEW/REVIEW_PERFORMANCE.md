# Pass 3: Performance Review

**Datum:** 2026-05-18
**Reviewer:** Claude Code via superpowers/requesting-code-review (kein dedizierter Performance-/Profiling-Skill im Plugin verfügbar; wieder der generische Code-Review-Skill als Konventions-Anker).
**Scope:** `src/sampling_tool/` + `PERFORMANCE.md` + `scripts/perf_probe.py` (Read-only)
**Methodik:** statische Analyse + Audit der bestehenden Mess-Daten. **Keine** neuen Probe-Läufe in diesem Pass.
**Verknüpfung:** [REVIEW/REVIEW_STRUCTURE.md](REVIEW/REVIEW_STRUCTURE.md) (PR #30), [REVIEW/REVIEW_QUALITY.md](REVIEW/REVIEW_QUALITY.md) (PR #31).

## Methodik-Limitierungen

- Keine neuen `perf_probe.py`-Läufe. Mess-Empfehlungen am Ende, der User entscheidet ob/wann er sie ausführt.
- Cyclomatic-Komplexität und Hotspot-Profiling wurden statisch geschätzt (Code-Lesen), nicht via cProfile/snakeviz/py-spy.
- Keine Headless-Verifikation, ob z. B. der Excel-Import-Pfad ohne PyQt6 funktioniert (siehe Pass 1 F-003/F-004 zur Indirekt-Abhängigkeit).
- Pre-Push-Hook + `pytest`-Coverage decken Funktionalität ab, nicht Performance.

## Ausgangslage (Sprint 10.x)

Sprint 10 hat die drei großen Bottlenecks adressiert:

- **Sprint 10.2** (calamine-Migration): Excel-Import 1M Zeilen 4.83 min → 55 s (5.3×). Soft-Target 60 s erreicht.
- **Sprint 10.3** (orjson + executemany-Generator): DB-Speicherung 100k 3.74 s → 0.75 s (5.0×); 1M-Projektion 37.5 s → ~7.5 s. RAM 100k 55 MB → 0.2 MB.
- **Sprint 10.4** (PDF-Chunking): AuditTrail-PDF 5k Events 13.43 s → 0.40 s (34×). 20k Events 1.64 s, weit unter Soft-Target 30 s.

Die jüngste Vollmessung in [PERFORMANCE.md](../PERFORMANCE.md) ist auf `Toolversion: 2b54753` getaggt (das ist der **Sprint-10.1-Commit**, also vor 10.2/10.3/10.4). Die Sprint-10.2/3/4-Updates wurden als Δ-Tabellen ergänzt, aber **der 1M-Lauf wurde nach 10.3 nicht erneut durchgeführt** – die DB-Speicherungs-Zahl für 1M (~7.5 s) ist eine Projektion, keine Messung.

**Wichtiger Hinweis zum Aufgaben-Briefing:** Das Briefing zu Pass 3 nennt einen "Sprint 11.x mit Streaming-Architektur" (Dataset ohne rows, LRU-Cache, on-demand Sampler). Beim Lesen des Codes und der git-Historie zeigt sich: **dieser Sprint 11 existiert NICHT im Code-Stand**. Letzter Commit ist `267e4c5 Sprint 10.4: AuditTrail-PDF Performance`. `core/models.py` hat weiterhin `Dataset.rows: tuple[DatasetRow, ...]` (full materialization), und `io/importer.py:151,172` materialisiert via `tuple(rows)`. Pass 3 bewertet den **tatsächlichen** Stand Sprint 10.4. Das, was im Briefing als „durch Sprint 11 bereits gelöst" markiert war, ist im Code noch offen – insbesondere der 1.4-GB-RAM-Peak beim 1M-Import.

## Zusammenfassung

Sprint 10.x hat die Pipeline auf 1M-Zeilen-Datasets **funktional ausreichend schnell** gemacht: Import < 60 s, DB-Speicherung projiziert < 8 s, PDF < 2 s bei 20k Events, alle Soft-Targets erreicht oder massiv unterschritten. **Die echten verbleibenden Performance-Risiken liegen NICHT in den von `perf_probe.py` gemessenen Phasen, sondern in den Pfaden, die `perf_probe.py` nicht abdeckt** – allen voran das synchrone Ausführen langer Operationen im UI-Thread (kein einziger `QThread` / `QRunnable` / `moveToThread` in der Codebasis, `TaskProgressDialog` existiert aber wird nie aufgerufen), das voll materialisierende `DatasetRepo.get_by_id` beim Engagement-Restore, der voll materialisierende `_distinct_values`-Scan im Sampling-Dialog und der `shutil.copy2`-DB-Snapshot beim Engagement-Open. **Keine SEV-0** (keine Reproducibility-Risiken durch Caching – die Codebasis enthält 0 `@lru_cache` / `@cached_property`), **5 SEV-1**, **3 SEV-2**, **4 SEV-3** Findings. 6 von 12 Findings sind `linked_to` einem Pass-1- oder Pass-2-Ticket und werden mit-bereinigt.

## Severity-Skala

- **SEV-0** — Reproducibility-Risiko durch Caching ODER Soft-Target um >100% verfehlt auf produktiver Größe (1M Zeilen).
- **SEV-1** — Soft-Target verfehlt 20–100% ODER potenzielles OOM-Risiko auf Zielgröße ODER UI-Freeze >1 s ohne Worker.
- **SEV-2** — Subjektiv langsam aber nutzbar ODER vermeidbare Voll-Materialisierung in seltenen Pfaden ODER schwer messbarer Lag.
- **SEV-3** — Mikro-Optimierung ODER veraltete Mess-/Doku-Daten ODER hardcoded Tuning-Werte ohne Begründung.

## Findings

### SEV-0

Keine SEV-0-Findings.

Belegt durch:
- `grep -rn "@cache\|@lru_cache\|@cached_property\|functools\.cache\|functools\.lru" src/sampling_tool/` → **leer** (0 Treffer).
- Keine Soft-Target-Verfehlung um >100% in [PERFORMANCE.md](../PERFORMANCE.md) (alle 4 dokumentierten Verfehlungen sind Sprint-10.2/3/4-Vorgängerstand, inzwischen behoben; die AuditTrail-PDF-Verfehlungen waren Heuristik-Fehler – die Phase hängt an Event-Anzahl, nicht an Rows).

### SEV-1

#### P-001: Excel-Import läuft 55 s synchron im UI-Thread ohne Worker und ohne Progress-Dialog
- **Datei(en):** [src/sampling_tool/ui/controllers/main_controller.py:340–385](src/sampling_tool/ui/controllers/main_controller.py#L340-L385), [src/sampling_tool/io/importer.py:82–88](src/sampling_tool/io/importer.py#L82-L88)
- **Zeilen:** Controller-Aufruf in [main_controller.py:357](src/sampling_tool/ui/controllers/main_controller.py#L357) (`result = ExcelImporter().import_file(path)` – **kein** `progress=`-Callback)
- **Befund:** `handle_import_excel` ruft den Importer synchron, ohne `progress`-Callback, ohne `QThread`-Worker, ohne `TaskProgressDialog`. Bei 1M Zeilen sind das laut [PERFORMANCE.md](../PERFORMANCE.md) **55 s UI-Freeze**. macOS und Windows zeigen ab ~3 s einen "App reagiert nicht"-Beachball/Wartecursor – der Anwender denkt, die App ist abgestürzt. `TaskProgressDialog` existiert in [ui/dialogs/progress_dialog.py](src/sampling_tool/ui/dialogs/progress_dialog.py), wird aber laut `grep -rn "TaskProgressDialog" src/sampling_tool/ui/controllers/` **nirgends im Controller** verbraucht. Auch der `ExcelImporter`-Konstruktor hat einen `progress: ProgressCallback | None`-Parameter, der nie gesetzt wird.
- **Belegt durch:** `grep -rn "QThread\|QRunnable\|moveToThread\|QThreadPool" src/sampling_tool/` → leer; `grep -rn "TaskProgressDialog\|ProgressCallback" src/sampling_tool/` zeigt nur Definitionen, keine Controller-Nutzung.
- **linked_to:** F-001 (MainController-Split macht Worker-Wrap pro Sub-Controller einfacher) — Performance-Wirkung bleibt aber bestehen, daher Severity NICHT reduziert.
- **Vermutete Wirkung:** Bei 100k-Zeilen-Datasets bereits ~5 s Freeze, bei 1M ~55 s. Auf langsameren Windows-Disks vermutlich noch deutlich länger.
- **Empfehlung:** Importer in `QThread` wrappen (oder `QtConcurrent.run`), `TaskProgressDialog` als Callback-Empfänger einbinden. Mindestens kurzfristig den existierenden `progress`-Callback aktivieren – dann sieht der User wenigstens "X von Y Zeilen verarbeitet".

#### P-002: `EngagementVersionManager.create_snapshot` macht synchron `shutil.copy2` der gesamten `.db` beim Engagement-Open
- **Datei(en):** [src/sampling_tool/persistence/version_manager.py:51–75](src/sampling_tool/persistence/version_manager.py#L51-L75), Aufruf in [main_controller.py:280](src/sampling_tool/ui/controllers/main_controller.py#L280)
- **Zeilen:** [version_manager.py:72](src/sampling_tool/persistence/version_manager.py#L72) (`shutil.copy2(self.engagement_db_path, target)`)
- **Befund:** Bei jedem `handle_open_engagement` wird vor dem eigentlichen Öffnen ein voller Datei-Klon der `.db` ins `archiv/`-Verzeichnis geschrieben. Bei einem 1M-Zeilen-Engagement (laut DB-Schema mit JSON-Values pro Row schätzungsweise 300–600 MB DB-Größe) sind das auf einer typischen SSD **3–6 s** synchron im UI-Thread, auf einer Windows-HDD oder einem Netz-Share Größenordnungen mehr. Die App wirkt beim Doppelklick auf ein großes Engagement "eingefroren". Der Snapshot ist ISAE-3402-Pflicht (Compliance), das Pattern ist also korrekt – nur die Synchronität ist das Problem.
- **Belegt durch:** Lesen [version_manager.py:51–75](src/sampling_tool/persistence/version_manager.py#L51-L75) + `grep -n "create_snapshot" src/sampling_tool/`.
- **linked_to:** F-001 (Sub-Controller-Split → `EngagementService` natürlicher Ort für Async-Wrap)
- **Vermutete Wirkung:** Auf 1M-Zeilen-Engagements 3–10 s Freeze beim Open, abhängig von Disk.
- **Empfehlung:** Snapshot in `QThread`-Worker oder zumindest hinter `TaskProgressDialog` mit "Snapshot wird angelegt…"-Anzeige. Alternative: Snapshot via `os.link`/Hardlink statt `copy2` wenn das Dateisystem es erlaubt – funktioniert auf APFS/NTFS/ext4, fällt auf FAT32 zurück.

#### P-003: `DatasetRepo.get_by_id` lädt alle Rows in einen `tuple` beim Engagement-Restore
- **Datei(en):** [src/sampling_tool/persistence/repositories.py:194–218](src/sampling_tool/persistence/repositories.py#L194-L218), Aufruf-Kette via [main_controller.py:401](src/sampling_tool/ui/controllers/main_controller.py#L401) und [main_controller.py:965](src/sampling_tool/ui/controllers/main_controller.py#L965)
- **Zeilen:** [repositories.py:205–209](src/sampling_tool/persistence/repositories.py#L205-L209) (`rows = tuple(DatasetRow(...) for r in row_cursor)`)
- **Befund:** `DatasetRepo.get_by_id` materialisiert die komplette Row-Liste in ein `tuple` von `DatasetRow`-Objekten (jeweils mit values-dict). Bei 1M Rows mit 15 Spalten sind das ~15M dict-Einträge zuzüglich Python-Object-Overhead – grobe Schätzung 800 MB–1.4 GB RAM-Peak. Wird beim `_restore_state` (Engagement-Open, wenn dort ein `active_dataset_id` persistiert war) und bei jedem `handle_dataset_selected` (Sidebar-Klick) aufgerufen. Das verschärft den bereits in [PERFORMANCE.md "Offen für spätere Sprints" #1](../PERFORMANCE.md) dokumentierten 1.4-GB-Import-Peak: nach dem Import ist der RAM-Peak vorbei (calamine-Streaming + executemany-Generator), beim erneuten Öffnen kommt er aber wieder.
- **Belegt durch:** Lesen [repositories.py:194–218](src/sampling_tool/persistence/repositories.py#L194-L218); Aufrufer-Suche `grep -n "get_by_id" src/sampling_tool/ui/controllers/main_controller.py`.
- **linked_to:** F-007 (Repositories-Split würde streaming-fähige Variante wie `iter_by_id` natürlich integrierbar machen)
- **Vermutete Wirkung:** OOM-Risiko auf 2-GB-RAM-Geräten bei 1M-Zeilen-Engagements; spürbarer Lag beim Sidebar-Dataset-Wechsel.
- **Empfehlung:** `iter_by_id(dataset_id) -> Iterator[DatasetRow]` als Pendant ergänzen. `DatasetTableModel` (siehe [ui/widgets/data_table.py:35–172](src/sampling_tool/ui/widgets/data_table.py#L35-L172)) ist bereits virtuell – es braucht das volle Row-Tuple gar nicht in einem Schritt.

#### P-004: `_distinct_values` im Sampling-Dialog scannt 1M Rows synchron bei jedem ComboBox-Wechsel
- **Datei(en):** [src/sampling_tool/ui/dialogs/sampling_dialog.py:451–464](src/sampling_tool/ui/dialogs/sampling_dialog.py#L451-L464), Aufruf in [sampling_dialog.py:304–315](src/sampling_tool/ui/dialogs/sampling_dialog.py#L304-L315)
- **Zeilen:** [sampling_dialog.py:454](src/sampling_tool/ui/dialogs/sampling_dialog.py#L454) (`for row in dataset.rows:`)
- **Befund:** Wenn der User im Advanced-Modus das Filter-Feld in der ComboBox ändert, läuft `_refresh_filter_values` → `_distinct_values(self._dataset, field)`. Die Funktion iteriert **synchron über alle Rows des Datasets**, baut `seen`-Set + `result`-Liste, sortiert das Ergebnis. Bei 1M Rows sind das vermutlich 2–5 s pro ComboBox-Klick im UI-Thread. Ohne Cache: jedes erneute Anklicken desselben Feldes triggert den Scan erneut.
- **Belegt durch:** `grep -rn "get_all_rows\|fetchall()\|list(.*iter_" src/sampling_tool/ui/` → leer (keine streaming-API), aber Lesen zeigt direkten `for row in dataset.rows`-Pass.
- **linked_to:** F-010 (Sampling-Dialog Concern-Split bietet natürlichen Ort für Distinct-Values-Worker)
- **Vermutete Wirkung:** 2–5 s UI-Freeze pro Filter-Feld-Klick auf 1M-Datasets; bei mehrfachem Klicken multipliziert sich der Freeze.
- **Empfehlung:** Pro-Field-`@lru_cache(maxsize=8)`-Wrapper auf `_distinct_values` (Reproducibility unkritisch – Cache-Hit oder -Miss verändert das Sample nicht, sondern nur den UI-Vorschlag). Mittelfristig auf SQL-`SELECT DISTINCT field FROM dataset_rows WHERE dataset_id = ?` umstellen, sobald die JSON-Values indexierbar sind – das ist eine eigene DB-Migration.

#### P-005: 1.4-GB-RAM-Peak beim 1M-Excel-Import bleibt offen, Architektur-Refactor noch nicht durchgeführt
- **Datei(en):** [src/sampling_tool/io/importer.py:183–201](src/sampling_tool/io/importer.py#L183-L201), [src/sampling_tool/core/models.py:81–95](src/sampling_tool/core/models.py#L81-L95) (`DatasetRow.values: dict[str, Any]`), [PERFORMANCE.md → "Offen für spätere Sprints" #1](../PERFORMANCE.md)
- **Zeilen:** [importer.py:194–195](src/sampling_tool/io/importer.py#L194-L195) (`values = {col: _coerce_value(...) for ...}; rows.append(DatasetRow(row_id=idx, values=values))`), [importer.py:201](src/sampling_tool/io/importer.py#L201) (`return tuple(rows)`)
- **Befund:** Der Importer hält während des Imports **alle 1M `DatasetRow`-Objekte gleichzeitig im RAM** (in der `rows: list[DatasetRow]`, am Ende `tuple(rows)`). Pro Row eine dict mit 15 Einträgen → ~15M dict-Slots + Object-Overhead. PERFORMANCE.md misst den Peak auf 1.4 GB bei 1M Zeilen. Das ist in der Datei explizit als "Offen für spätere Sprints" gelistet, mit dem Hinweis "Spalten-orientierte Dataset-Struktur (Arrow/Numpy) wäre die Lösung, ist aber ein Architektur-Refactor mit Ripple-Effekt". Pass-3-Befund: dieser Refactor ist **nicht** passiert (entgegen der Briefing-Annahme).
- **Belegt durch:** Lesen [importer.py:183–201](src/sampling_tool/io/importer.py#L183-L201), Lesen [PERFORMANCE.md](../PERFORMANCE.md) Auffälligkeiten-Block.
- **linked_to:** —
- **Vermutete Wirkung:** OOM-Risiko auf 2-GB-RAM-Devices, in der Praxis aber Auditoren-Workstations mit 16+ GB – Risiko gedämpft. Bei 5M Zeilen würde der Peak proportional auf ~7 GB steigen → ab 5M wird das ein hartes Problem.
- **Empfehlung:** Sprint-12-Kandidat: Streaming-Importer mit `yield DatasetRow` statt `tuple(rows)`, plus Dataset als Lazy-Header (`rows_iter: Callable[[], Iterator[DatasetRow]]`) statt voller Materialisierung. Parallel: Streaming-Pfad in `DatasetRepo.create` (das bereits via Generator inserted) konsumiert den Iterator direkt, ohne dass der Importer alles erst sammeln muss.

### SEV-2

#### P-006: `_refresh_views` triggert AuditTrail-Reload + 3 matplotlib-Charts nach jeder mutierenden Aktion
- **Datei(en):** [src/sampling_tool/ui/controllers/main_controller.py:1019–1041](src/sampling_tool/ui/controllers/main_controller.py#L1019-L1041), 8× Aufruf-Stellen
- **Zeilen:** Aufrufe in [main_controller.py:335, 377, 570, 609, 629, 648, 699, 925](src/sampling_tool/ui/controllers/main_controller.py#L335)
- **Befund:** Nach Engagement-Close, Import, Sampling, Reset, Undo, Redo, Export, Engagement-Open läuft `_refresh_views` → `_refresh_audit_trail` (lädt bis zu 10 000 Events neu) + `_refresh_dashboard` (lädt Datasets, Samples, Events neu + rendert 3 matplotlib-Charts). Bei einem Engagement mit 10k Events ist das pro Aktion 200–500 ms zusätzlicher Sync-Aufwand im UI-Thread; bei einem Auditor, der schnell zwischen 5 Samples wechselt, summiert sich das spürbar. Plus: AuditTrail wird auch dann neu geladen, wenn die Aktion nichts mit Audit-Events zu tun hatte (z. B. reines `handle_dataset_selected`-Klick).
- **Belegt durch:** `grep -n "_refresh_views" src/sampling_tool/ui/controllers/main_controller.py`; Lesen [main_controller.py:999–1041](src/sampling_tool/ui/controllers/main_controller.py#L999-L1041).
- **linked_to:** F-001 (im Sub-Controller-Split würde Refresh-Strategie pro Service natürlich überarbeitet)
- **Vermutete Wirkung:** Spürbarer Lag bei rapiden UI-Interaktionen auf großen Audit-Trails; in einer Klick-Heavy-Sitzung 5–10 unnötige Reloads/Min.
- **Empfehlung:** `_refresh_views` durch zielgerichtete `invalidate_*`-Methoden ersetzen (`invalidate_audit_trail()`, `invalidate_dashboard_samples()`). Optional via `QTimer.singleShot(0, ...)` deferren, damit mehrere Folge-Aktionen gebatcht werden.

#### P-007: `AuditTrailFilterProxy.filterAcceptsRow` baut Haystack pro Row pro Tastenanschlag (kein Cache)
- **Datei(en):** [src/sampling_tool/ui/widgets/audit_trail_view.py:180–212](src/sampling_tool/ui/widgets/audit_trail_view.py#L180-L212)
- **Zeilen:** [audit_trail_view.py:199–210](src/sampling_tool/ui/widgets/audit_trail_view.py#L199-L210)
- **Befund:** Bei aktiver Volltextsuche baut der Proxy pro Row 4 String-Konkatenationen + `.lower()` zusammen (`_format_timestamp`, `event_type`, `user_name`, `_format_file(evt)`). Bei jedem Tastenanschlag im Such-Input wird `setFilterFixedString(text)` → `invalidateFilter()` aufgerufen → der Proxy iteriert alle Rows neu. Bei 10k Events × ~5 keystrokes/Sek = 50k Haystack-Builds/Sek. Auf einem 20k-Engagement bereits spürbar (>100 ms UI-Lag pro Keystroke).
- **Belegt durch:** Lesen [audit_trail_view.py:154–212](src/sampling_tool/ui/widgets/audit_trail_view.py#L154-L212); `grep -n "haystack\|setFilterFixedString" src/sampling_tool/ui/widgets/audit_trail_view.py`.
- **linked_to:** —
- **Vermutete Wirkung:** Spürbares Lag bei Volltextsuche in Engagements mit >10k Audit-Events; bei 50k Events Eingabe-Verzögerung.
- **Empfehlung:** Haystack-String einmalig bei `set_events()` pro Event vorberechnen und in einem `_haystacks: list[str]`-Cache parallel zur Event-Liste halten. Filter-Proxy greift dann via `model._haystacks[source_row]`. Alternativ: Debounce auf `_on_search_changed` via `QTimer.singleShot(200, ...)`.

#### P-008: `TaskProgressDialog` existiert, wird aber NIE im Controller verbraucht (Dead Feature)
- **Datei(en):** [src/sampling_tool/ui/dialogs/progress_dialog.py](src/sampling_tool/ui/dialogs/progress_dialog.py), [src/sampling_tool/io/importer.py:82](src/sampling_tool/io/importer.py#L82), [src/sampling_tool/io/exporter.py:46](src/sampling_tool/io/exporter.py#L46)
- **Zeilen:** Gesamtes [progress_dialog.py](src/sampling_tool/ui/dialogs/progress_dialog.py) (37 LoC, 0% Test-Coverage laut Pre-Push-Output)
- **Befund:** Die Infrastruktur für Progress-Feedback existiert end-to-end: `TaskProgressDialog` wrappt `QProgressDialog`, `ExcelImporter.__init__(progress: ProgressCallback | None)`, `ExcelExporter.__init__(progress: ProgressCallback | None)`. Aber kein einziger Controller-Pfad verbindet die Stücke. `grep -rn "TaskProgressDialog\|ProgressCallback" src/sampling_tool/ui/controllers/` → leer. Konsequenz: alle SEV-1-Findings oben (P-001, P-002) hätten ein einsatzfähiges Tool zur Hand, aber niemand ruft es.
- **Belegt durch:** `grep -rn "TaskProgressDialog" src/sampling_tool/` (nur Definitions-Treffer, keine Verbraucher); Pre-Push-Coverage-Report: `progress_dialog.py 19 19 2 0 0% 8-37`.
- **linked_to:** Q-009-verwandt (Pass 2 hat das 0%-Coverage-Symptom dokumentiert, P-008 erklärt die Ursache)
- **Vermutete Wirkung:** UX-Schaden, keine direkte Performance-Wirkung – die Operationen wären gleich langsam, der User würde aber wenigstens einen Progress-Bar sehen.
- **Empfehlung:** Mindestens für Import + Export einbinden (3–5 LoC im Controller). Wenn Worker-Refactor (P-001) kommt, sowieso Pflicht.

### SEV-3

#### P-009: `PERFORMANCE.md` ist auf Toolversion `2b54753` (= Sprint 10.1) getaggt, nie aktualisiert
- **Datei(en):** [PERFORMANCE.md](../PERFORMANCE.md) Zeile 5
- **Befund:** Die Datei sagt im Header "Toolversion: 2b54753". Das ist der Commit "Sprint 10.1: Performance-Probe (Discovery)" – Sprint 10.2/10.3/10.4 haben jeweils Delta-Tabellen ergänzt, aber den Haupt-Header und den 1M-Lauf nicht. Insbesondere die 1M-DB-Speicherung-Zahl von 37.5 s ist seit Sprint 10.3 obsolet (Projektion: ~7.5 s), aber die Tabelle ist nicht aktualisiert. Ein Re-Lauf `python scripts/perf_probe.py --sizes 1000000` würde die Lücke schließen.
- **Belegt durch:** `head -10 PERFORMANCE.md`; `git log --oneline -- PERFORMANCE.md | head`.
- **linked_to:** —
- **Empfehlung:** Vor dem nächsten Refactor (z. B. Pass-1-Sprint) einmal `perf_probe.py --sizes 100000 1000000` laufen lassen + Header-Tag auf aktuellen HEAD updaten. Wird sonst zur Doku-Lüge.

#### P-010: 5M-Lauf nie ausgeführt, in PERFORMANCE.md explizit als Out-of-Scope markiert
- **Datei(en):** [PERFORMANCE.md → "Out of Scope"](../PERFORMANCE.md)
- **Befund:** Der Lauf für 5M Zeilen wurde mit Begründung "Setup würde ~40 min dauern" übersprungen. Nach calamine-Migration wäre der eigentliche Import in ~5 min projiziert. Für den 1.4-GB-RAM-Befund (P-005) wäre eine 5M-Messung interessant (linear → ~7 GB Peak, jenseits typischer 16-GB-Workstations).
- **Belegt durch:** Lesen [PERFORMANCE.md "Out of Scope"](../PERFORMANCE.md).
- **linked_to:** P-005-Verwandt
- **Empfehlung:** Optional vor Sprint-12 (Streaming-Refactor): Einmaliger 5M-Lauf mit pre-generiertem .xlsx (statt jedes Mal Setup), um die RAM-Skalierung zu verifizieren.

#### P-011: `core/undo.py` benutzt stdlib-`json` statt `orjson` (Sprint-10.3-Inkonsistenz)
- **Datei(en):** [src/sampling_tool/core/undo.py:15, 58–59, 126–127, 168–169](src/sampling_tool/core/undo.py#L15)
- **Befund:** Bereits in Pass-2-Q-007 dokumentiert, hier nochmal aus Performance-Sicht: Undo-Snapshots typischerweise <100 row-ids, stdlib-`json` da völlig ausreichend. Performance-Auswirkung praktisch null – aber Inkonsistenz mit dem orjson-Migrationspfad aus Sprint 10.3.
- **Belegt durch:** `grep -rn "import json\b\|json\.dumps\|json\.loads" src/sampling_tool/core/ src/sampling_tool/persistence/`.
- **linked_to:** F-002 (Undo aus core nach persistence — dort sowieso orjson)
- **Empfehlung:** Mit F-002 zusammen migrieren. Eigenständig nicht prioritär.

#### P-012: Sprint-11-Streaming-Spec nicht im Code umgesetzt (Doku-Drift)
- **Datei(en):** Briefing zu Pass 3 vs. tatsächlicher Code-Stand (siehe Sektion "Ausgangslage" oben)
- **Befund:** Das Pass-3-Briefing setzt voraus, dass Sprint 11.1–11.5 (Streaming, `Dataset` ohne `rows`, on-demand Sampler, LRU-Cache) bereits umgesetzt ist. Code-Stand ist Sprint 10.4: `Dataset.rows: tuple[DatasetRow, ...]` (Volle Materialisierung), `tuple(rows)` im Importer, keine `@lru_cache` im Sampling-Pfad. **Das ist keine Code-Lücke, sondern eine Doku-/Spec-Lücke** – eine inzwischen offenbar fallen gelassene oder verschobene Streaming-Roadmap aus dem Briefing-Kontext. Pass-1-Offene-Frage #5 hat das bereits angemerkt.
- **Belegt durch:** `git log --oneline | head -5` zeigt 10.4 als Top; `grep -rn "yield" src/sampling_tool/io/importer.py` zeigt nur Generator im DB-Insert, nicht im Importer-Output; `grep -rn "@lru_cache\|@cache" src/sampling_tool/` leer.
- **linked_to:** Verwandt mit Pass-1-Offene-Frage #5
- **Empfehlung:** Entscheidung im Team: Streaming-Sprint als Sprint 11 / 12 priorisieren ODER `core/models.py` umbenennen so dass klar ist, dass `Dataset.rows` ein materialisiertes Snapshot ist. Dokumentations-/Roadmap-Thema, nicht Code-Fix.

## Audit der bestehenden Mess-Daten (PERFORMANCE.md)

| Phase                       | Letzte Messung | Sprint-Stand | Soft-Target  | Aktuell verfehlt?  | Daten-Aktualität                       |
|-----------------------------|----------------|--------------|--------------|--------------------|----------------------------------------|
| Excel-Import 1M             | 55.00 s        | 10.2         | < 60 s       | nein               | aktuell                                |
| DB-Speicherung 1M           | 37.50 s (10.2) | 10.3 projiziert ~7.5 s | < 30 s | nein              | **veraltet** – Re-Lauf für 1M fehlt    |
| Tabelle-Anzeige 1M          | 0.51 s         | 10.2         | < 5 s        | nein               | aktuell                                |
| Sampling Simple 1M          | 3.59 s         | 10.2         | < 10 s       | nein               | aktuell                                |
| Sampling Cluster 1M         | 0.19 s         | 10.2         | < 15 s       | nein               | aktuell                                |
| Sampling Stratified 1M      | 3.64 s         | 10.2         | < 15 s       | nein               | aktuell                                |
| Filter-Toggle (an/aus) 1M   | 0.21 / 0.15 s  | 10.2         | < 2 s        | nein               | aktuell                                |
| Highlight 1M                | 3.1 ms         | 10.2         | < 2 s        | nein               | aktuell                                |
| Excel-Export Sample 1M      | 0.16 s         | 10.2         | < 60 s       | nein               | aktuell                                |
| Excel-Report Multi 1M       | 0.09 s         | 10.2         | < 60 s       | nein               | aktuell                                |
| HTML-Report 1M              | 0.25 s         | 10.2         | < 30 s       | nein               | aktuell                                |
| AuditTrail-PDF (5k Events)  | 0.40 s         | 10.4         | < 30 s       | nein, massiv drunter | aktuell                              |
| AuditTrail-PDF (20k Events) | 1.64 s         | 10.4         | (extrapoliert) | nein              | aktuell                                |
| **RAM Import 1M**           | **1.4 GB**     | 10.2         | **kein Target** | unbekannt        | aktuell, aber **Architektur-offen (P-005)** |
| **5M Vollmessung**          | —              | —            | nicht spezifiziert | unbekannt      | **nie gemessen (P-010)**               |
| **Engagement-Open + Snapshot** | —          | —            | nicht spezifiziert | unbekannt      | **nie gemessen (P-002)**               |
| **Dataset-Restore via `get_by_id`** | —     | —            | nicht spezifiziert | unbekannt      | **nie gemessen (P-003)**               |
| **Advanced-Dialog distinct-Load** | —       | —            | nicht spezifiziert | unbekannt      | **nie gemessen (P-004)**               |
| **AuditTrail-Filter @ 50k Events** | —      | —            | nicht spezifiziert | unbekannt      | **nie gemessen (P-007)**               |
| **Dashboard-Refresh-Frequenz** | —          | —            | nicht spezifiziert | unbekannt      | **nie gemessen (P-006)**               |

## Static-Analysis-Smells (Übersicht)

### Synchrone Long-Operations im UI-Thread (kein einziger Worker in der Codebasis)

| Methode                                                | Datei:Zeile                                                                 | Potenzielle Dauer auf 1M-Engagement | Worker? | Finding-ID |
|--------------------------------------------------------|-----------------------------------------------------------------------------|--------------------------------------|---------|------------|
| `handle_import_excel`                                  | [main_controller.py:340](src/sampling_tool/ui/controllers/main_controller.py#L340) | ~55 s                              | nein    | P-001      |
| `handle_open_engagement` → `create_snapshot`           | [main_controller.py:269](src/sampling_tool/ui/controllers/main_controller.py#L269) → [version_manager.py:51](src/sampling_tool/persistence/version_manager.py#L51) | ~3–10 s                          | nein    | P-002      |
| `handle_dataset_selected` → `DatasetRepo.get_by_id`    | [main_controller.py:387](src/sampling_tool/ui/controllers/main_controller.py#L387) → [repositories.py:194](src/sampling_tool/persistence/repositories.py#L194) | 2–5 s                          | nein    | P-003      |
| `handle_new_sampling` → `_build_sampling_dataset`+sample | [main_controller.py:510](src/sampling_tool/ui/controllers/main_controller.py#L510) | ~3.6 s (Simple/Stratified)         | nein    | F-001/linked |
| `_refresh_views` (nach jeder Mutation)                 | [main_controller.py:1037](src/sampling_tool/ui/controllers/main_controller.py#L1037) | 0.2–0.5 s                        | nein    | P-006      |
| `_distinct_values` (ComboBox-Wechsel im Sampling-Dialog) | [sampling_dialog.py:451](src/sampling_tool/ui/dialogs/sampling_dialog.py#L451) | 2–5 s                             | nein    | P-004      |
| `_refresh_audit_trail` (Volltextsuche-Keystroke)       | [audit_trail_view.py:180](src/sampling_tool/ui/widgets/audit_trail_view.py#L180) | >100 ms pro Keystroke @ 20k Events | nein    | P-007      |

### Vermeidbare List-Materialisierungen

| Stelle                                          | Datei:Zeile                                                                  | Größe (1M-Worst-Case)        | Finding-ID |
|-------------------------------------------------|------------------------------------------------------------------------------|------------------------------|------------|
| `tuple(rows)` im Importer                       | [importer.py:201](src/sampling_tool/io/importer.py#L201)                     | 1M `DatasetRow`-Objekte      | P-005      |
| `tuple(DatasetRow(...) for r in row_cursor)` im Repo | [repositories.py:205](src/sampling_tool/persistence/repositories.py#L205) | 1M `DatasetRow`-Objekte      | P-003      |
| `for row in dataset.rows:` in `_distinct_values` | [sampling_dialog.py:454](src/sampling_tool/ui/dialogs/sampling_dialog.py#L454) | 1M Rows linear            | P-004      |

### matplotlib fig-Handling

| Stelle                                       | `plt.close(fig)` vorhanden?       | Finding-ID |
|----------------------------------------------|-----------------------------------|------------|
| `_figure_to_bytes` in `chart_renderer.py:200` | ✅ Zeile 203, im `finally`-Block  | —          |
| `_figure_to_pixmap` in `chart_renderer.py:208` | ✅ via `_figure_to_bytes`-Wrapper | —          |

Belegt durch `grep -rn "savefig\|Figure(" src/sampling_tool/ui/widgets/chart_renderer.py src/sampling_tool/io/` + `grep -rn "plt\.close" src/sampling_tool/ui/widgets/chart_renderer.py`. **Kein matplotlib-Memory-Leak in der Codebasis.**

### Hardcoded Tuning-Werte

| Konstante                       | Datei:Zeile                                                                  | Begründung im Docstring?                | Finding-ID |
|---------------------------------|------------------------------------------------------------------------------|------------------------------------------|------------|
| `CHUNK_SIZE = 500`              | [pdf_report.py:46](src/sampling_tool/io/pdf_report.py#L46)                  | ✅ ausführlich (Sprint 10.4)            | —          |
| `_CELL_STRING_THRESHOLD = 60`   | [pdf_report.py:51](src/sampling_tool/io/pdf_report.py#L51)                  | ✅ ausführlich (Paragraph-vs-str)        | —          |
| `_HEADER_STRING_RATIO = 0.5`    | [importer.py:42](src/sampling_tool/io/importer.py#L42)                      | ⚠️ nur Kommentar "≥50 % String-Anteil"  | —          |
| `MAX_DEPTH = 20` (UndoManager)  | [undo.py:26](src/sampling_tool/core/undo.py#L26)                            | ✅ Modul-Docstring                       | —          |
| `_RECENT_SAMPLE_LIMIT = 5`      | [dashboard_view.py:44](src/sampling_tool/ui/widgets/dashboard_view.py#L44)  | ⚠️ nur Konstante, keine Begründung      | —          |
| `_HISTORY_DAYS = 30`            | [dashboard_view.py:45](src/sampling_tool/ui/widgets/dashboard_view.py#L45)  | ⚠️ Tile-Titel "30 Tage" — implizit     | —          |
| `_MAX_COLUMN_WIDTH = 50`        | [exporter.py:35](src/sampling_tool/io/exporter.py#L35) + Duplikat in `multi_report_exporter.py:42` | ⚠️ ohne Begründung                   | Q-003/Pass 2 |
| `limit=10_000` Audit-Reads      | 4× in `main_controller.py` (siehe Q-008/Pass 2)                              | ❌ inline magic                          | Q-008/Pass 2 |

## Verifikation der Sprint-11-Effekte

**Nicht zutreffend.** Sprint 11 existiert nicht im aktuellen Code-Stand (siehe Sektion "Ausgangslage" oben). Der im Briefing angenommene Streaming-Refactor ist nicht passiert. Konsequenz:

- Der 1.4-GB-RAM-Peak beim 1M-Import ist **nicht gefixt**, sondern weiterhin offen (P-005).
- `Dataset.rows` ist weiterhin voll materialisiertes `tuple[DatasetRow, ...]`.
- Es gibt keinen LRU-Cache irgendwo (`grep` ist eindeutig).
- `DatasetRepo.get_by_id` hat keine streaming-Variante (P-003).

Wenn das Briefing aus einer alternativen Branch oder einem Plan-Doc stammt: dort gleichen, ob die Roadmap noch aktuell ist.

## Mess-Empfehlung

Konkrete Aufrufe, die offene Fragen klären würden – der User entscheidet ob/wann er sie ausführt. **Pass 3 startet keinen davon.**

```bash
# 1. Aktualisierung der 1M-Daten nach Sprint 10.3/10.4 (öffnet PERFORMANCE.md-Lücke P-009)
python scripts/perf_probe.py --sizes 1000000
# Was wir lernen: aktuelle DB-Speicherung-Zahl für 1M (Projektion vs. Realität),
# RAM-Peak Import 1M nach calamine (= 1.4 GB-Bestätigung oder -Korrektur).

# 2. 5M-Verifikation für P-005/P-010
python scripts/perf_probe.py --sizes 5000000
# Was wir lernen: ob der lineare RAM-Skalierungs-Verdacht (~7 GB Peak) hält.
# Achtung: Setup dauert ~40 min, gesamter Lauf ~1 h, ~15 GB Disk temporär.

# 3. Engagement-Wechsel-Profiling (nicht in perf_probe abgedeckt)
# Manuell: Engagement mit 1M Rows öffnen, Sekunden-Stoppuhr vom Doppelklick bis Workspace-Sichtbar.
# Alternative: dedizierten Mess-Block in perf_probe.py ergänzen, der nach DB-Speicherung
#   einmal db.close() + Database(...).migrate() + EngagementRepo.get() misst.

# 4. Dataset-Restore-Profiling (P-003)
# Manuell mit Profiler:
python -m cProfile -o /tmp/restore.prof -m sampling_tool  # GUI-Lauf
# Engagement mit 1M Rows öffnen, dann Dataset in Sidebar wechseln.
# snakeviz /tmp/restore.prof  (nur lokal, kein Repo-Tool)

# 5. AuditTrail-Filter-Skalierung (P-007)
# Smoke: Engagement mit 20k synthetischen Audit-Events erzeugen (perf_probe --audit-events 20000),
#   dann manuell Volltextsuche → subjektive Eingabe-Latenz beobachten.

# 6. Advanced-Sampling-Dialog distinct-Load (P-004)
# Manuell: 1M-Engagement öffnen, Advanced-Mode in Settings aktivieren,
#   Sampling-Dialog öffnen, Filter-Feld-ComboBox durchklicken, Stoppuhr.
```

## Healthy Pfade

Code-Pfade, die laut Static Analysis keine Performance-Issues haben:

- **`core/sampling.py`** – numpy-RNG, Fisher-Yates, deterministische Sortierung. Sampling Simple/Cluster/Stratified bleibt auf 1M unter Soft-Target.
- **`io/exporter.py`** (Excel-Sample-Export) – atomarer Write, 0.16 s bei 1M-Sample. Keine Optimierung nötig.
- **`io/pdf_report.py`** – Sprint-10.4-Chunking, plt.close-clean, _format_cell-String-Pfad. Soft-Target massiv unterschritten.
- **`io/multi_report_exporter.py`** – 0.09 s bei 1M. Atomarer Write, Sheet-Komposition unkritisch.
- **`io/html_report.py`** – 0.25 s bei 1M, 2 Base64-Charts (nicht skalierend mit Dataset-Größe).
- **`persistence/database.py`** – WAL + executemany via Generator + orjson + sqlite3-Adapter. Keine Smell-Treffer.
- **`persistence/repositories.py::DatasetRepo.create`** – Generator-basierter `executemany`, RAM-Peak 0.2 MB bei 100k. Sprint-10.3-Ergebnis sauber umgesetzt.
- **`ui/widgets/data_table.py`** – `DatasetTableModel` ist virtuell (`QAbstractTableModel`), `_visible_indices`-Mapping statt Proxy-Filter. 0.5 s Anzeige bei 1M.
- **`ui/widgets/chart_renderer.py`** – matplotlib-Agg-Backend, `plt.close` im finally. Kein Leak.
- **`ui/recent.py`** – `prune_missing` iteriert max. 50 Einträge (`MAX_ENTRIES`). Unkritisch.

## Eigenständige Refactor-Kandidaten (nicht durch Pass-1/2-Refactor mit-gefixt)

Sortiert nach Aufwand-/Nutzen-Verhältnis:

1. **P-008 (SEV-2)** – `TaskProgressDialog` aktivieren für Import + Export. 5–10 LoC, sofortige UX-Wirkung, Voraussetzung für P-001-Worker-Wrap. Schnellster Quick-Win.
2. **P-007 (SEV-2)** – Haystack-Cache im `AuditTrailFilterProxy`. ~15 LoC, behebt die Volltextsuche-Latenz bei großen Audit-Trails.
3. **P-001 (SEV-1)** – Excel-Import in `QThread` wrappen. Mittlere Komplexität (richtige Signal-Slot-Koordination), aber hoher Nutzen (kein UI-Freeze mehr).
4. **P-002 (SEV-1)** – Snapshot-Worker beim Engagement-Open. Ähnliche Komplexität wie P-001, kombinierbar.
5. **P-005 (SEV-1)** – Streaming-Importer. Architektur-Refactor mit Ripple-Effekt auf `Dataset.rows`, `DatasetRepo.get_by_id`, Sampler, Exporter. **Eigener Sprint.** Klärt gleichzeitig P-003 und P-004.
6. **P-009 (SEV-3)** – Re-Lauf `perf_probe.py --sizes 1000000`. 5 Min Arbeit, schließt die Doku-Lücke.

## Offene Fragen

1. **Briefing-Drift Sprint 11**: Die im Pass-3-Briefing genannte Streaming-Architektur (Sprint 11.1–11.5) existiert nicht im Code-Stand. Aus welcher Quelle stammt die Annahme? Falls aus einem Plan-Doc oder einer alternativen Branch: bitte verifizieren, ob diese Roadmap noch aktuell ist oder formal verworfen wurde.
2. **`_HEADER_STRING_RATIO = 0.5`**: empirisch gewählt oder aus VBA-Tool übernommen? Für mehrsprachige Headers (z. B. tschechische Mandanten mit Sonderzeichen) könnte der String-Anteil sinken.
3. **DB-Größen-Skalierung**: gibt es eine Messung, wie groß die `.db`-Datei (inkl. WAL) bei 1M Rows wird? Wenn nahe 1 GB, wird P-002 (Snapshot-copy) bedrohlich auf Windows-Netz-Shares.
4. **Disk-Profil der Auditoren**: zielt das Tool primär auf SSD-Workstations oder werden HDD-Geräte/Netz-Shares unterstützt? Die SEV-1-Findings zu Synchron-IO sind auf HDD signifikant problematischer.
5. **Sprint-10.x-Re-Validation**: PERFORMANCE.md ist auf 10.1-Toolversion getaggt. Wäre vor dem Refactor-Sprint (Pass-1 F-001) ein erneuter Voll-Lauf sinnvoll, um die Baseline für post-Refactor-Vergleiche zu fixieren?
