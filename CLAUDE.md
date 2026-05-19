# CLAUDE.md

Projektkontext für zukünftige Claude-Code-Sessions. Diese Datei wird automatisch geladen.

## Was ist das?

Migration eines BDO-internen, VBA-basierten Excel-Audit-Sampling-Tools (ISAE 3402) zu einem
sauberen Python-Projekt. Auditoren ziehen damit reproduzierbare Stichproben aus Massendaten
(Buchungssätze, Verträge, etc.) für Prüfungshandlungen.

- **Plattform-Strategie:** Entwicklung auf macOS, Zielsystem Windows. Cross-Platform Pflicht.
- **Python-Version:** 3.13+
- **UI:** PyQt6 (kein Web, kein TUI)
- **Persistenz:** SQLite (lokale Datei pro Engagement)
- **Reproduzierbarkeit:** Pflicht – jede Stichprobe muss bei gleichem Seed bit-genau
  rekonstruierbar sein (Audit-Trail, ISAE-3402-Anforderung).

## Sprint-Status

| Sprint | Inhalt                                              | Status      |
|-------:|-----------------------------------------------------|-------------|
| 1      | Projekt-Skelett, Config, Sampling-Core + Tests      | done        |
| 2      | SQLite-Persistenz, Audit-Trail, Undo, Migrations    | done        |
| 3      | I/O: Excel-/CSV-Import, Excel-Export, AuditTrail-PDF| done        |
| 4      | PyQt6-UI: Hauptfenster, Datentabelle, Sidebar       | done        |
| 5      | UI: Sampling-Dialog, Export, Undo/Redo, Bug/About   | done        |
| 5.5    | UX-Bugfixes + Engagement-Auto-Versionierung         | done        |
| 5.6    | Sample-Filter-Default, grüne Markierung, Engagement-Wechsel | done |
| 6      | Dashboard, AuditTrail-View, Multi-Sheet-/HTML-Report | done       |
| 6.1    | Einheitliche Export-Dialoge für alle Reports         | done        |
| 7      | Settings, Platzhalter-Briefpapier, CI, Windows-Compat | done        |
| 8      | PyInstaller-Build (Mac `.app` + Windows `.exe`), Release-Workflow | done |
| 9.1    | Duplikat-Check beim Anlegen neuer Engagements        | done        |
| 9.2    | Bug-Report als Toolbar-Button                        | done        |
| 9.3    | Advanced-Mode-Toggle (Simple/Advanced Sampling)      | done        |
| 9.4    | Dashboard/AuditTrail ein-/ausblendbar               | done        |
| 9.5    | First-Run-Wizard (Standard-Ordner + Auditor-Name)   | done        |
| 9.6    | Settings im Menü + Sample-Größe-Hint + Seed in Simple-Mode | done |
| 9.7    | Einstellungen-Button in Toolbar                     | done        |
| 10.1   | Performance-Probe (Discovery-Lauf, 10k–1M Zeilen)   | done        |
| 10.2   | Excel-Import via python-calamine (Performance-Fix)  | done        |
| 10.3   | DB-Performance: orjson + executemany-Generator      | done        |
| 10.4   | AuditTrail-PDF Performance (reportlab-Chunking)     | done        |
| 11.1   | Dataset-API-Cut (rows raus, Repo-Methoden rein)     | done        |
| 11.2   | Streaming Teil 2: UI-LRU-Cache für TableModel       | done        |
| 11.3   | Streaming Teil 3: Excel-Import streamt direkt in DB | done        |
| 11.4   | Streaming Teil 4: Sampler/Exporter auf iter_rows    | done        |
| 11.5   | Streaming Cleanup + Konsolidierung                  | done        |
| 12.1   | Perf-Quick-Wins (P-001/P-002/P-007)                 | done        |
| 12.2   | F-002 Undo-Refactor (core/undo.py SQL-frei) + T-003/T-004/T-006 | done |
| 13     | F-001 MainController-Split (God-Object zerlegen)    | done        |
| 14     | Test-Catchup (T-001/T-002/T-005/T-007)              | done        |
| 15     | F-003/F-004/F-005 IO-Layer-Reinigung (charts.py)    | done        |
| 16     | VBA-Backlog: Multi-Sheet + Header-Detection-Dialog beim Import | done |

**Sprint 11.x abgeschlossen** – Streaming-Architektur komplett (siehe
nächster Abschnitt). Dataset lebt in SQLite, Code-Pfade arbeiten mit
Generatoren / Range-Queries / Bulk-ID-Lookups. RAM-Footprint ist nicht
mehr proportional zur Dataset-Größe.

Bei Sprint-Wechsel: diese Tabelle hier UND im README.md aktualisieren.

## Streaming-Architektur (Sprint 11.x)

Zentraler Designgrundsatz nach Sprint 11.x: **das Tool hält Dataset-Rows
nicht im RAM**, sondern in SQLite. Alle Code-Pfade arbeiten mit
Generatoren / Range-Queries / Bulk-ID-Lookups, nicht mit
voll-materialisierten Listen.

**Was lebt wo:**
- `Dataset` (frozen Dataclass): Metadaten + `row_count`, KEINE rows.
- Rows: in `dataset_rows`-Tabelle, abgerufen via `DatasetRepo`.
- `DatasetTableModel` (UI): FIFO-Cache mit 1000 Rows, Bulk-Load 250
  pro Cache-Miss (Window davor + dahinter). RAM konstant ~3 MB.
- `ExcelImporter`: liefert `ImportResult.rows` als einmal-konsumierbaren
  `Iterator[DatasetRow]`; `DatasetRepo.create` zieht ihn einmal durch
  und korrigiert `row_count` auf die tatsächliche Anzahl.
- `BaseSampler.sample(rows, population_size)`: Single-Pass-Filter über
  Iterator, `population_size` dokumentiert die Universumsgröße (auch
  bei Sub-Sampling).
- `ExcelExporter.export_sample(sample, dataset, dataset_repo, ...)`:
  holt nur die Sample-Rows on-demand via `get_rows_by_ids`.

**Repo-API für Row-Zugriffe:**
- `create(dataset, rows: Iterable[DatasetRow])` – Generator akzeptiert,
  `row_count` wird nach echter Persistierung korrigiert.
- `get_by_id(dataset_id)` – nur Metadaten, keine Rows.
- `get_row(dataset_id, row_id)` – einzelne Row.
- `get_rows_in_range(dataset_id, start, end)` – half-open Range, für
  UI-Pagination / TableModel-Cache.
- `iter_rows(dataset_id)` – Streaming-Generator (sortiert).
- `iter_row_ids(dataset_id)` – Light-Streaming nur über `row_index`,
  ohne JSON-Parsing.
- `get_rows_by_ids(dataset_id, row_ids)` – Bulk-Lookup, behält
  Eingabe-Reihenfolge, ignoriert stale IDs, chunkt bei >900 Parametern
  (SQLite-Bind-Limit 999).
- `get_all_rows(dataset_id)` – Tests-Convenience. **In Production
  nur** im SamplingDialog-Advanced-Mode für distinct-Werte-Sammlung
  (siehe Docstring im Repo). Streaming-Alternative via SQLite
  `json_extract` wurde geprüft, am tagged-Encoder für datetime-Spalten
  gescheitert; tolerabler RAM-Footprint bei realistischen Audit-Datasets.

**Was nicht streamt (legitime Ausnahmen):**
- Advanced-SamplingDialog: distinct-Werte für Cluster/Stratum-ComboBoxen.
  Controller lädt `get_all_rows` nur wenn `advanced_mode=True`.
- ImportResult.dataset (Metadaten) – klein, keine Rows.

**Reproduzierbarkeit bleibt gewahrt**: `row_id` ist die stabile
Sortier-Ordnung, `iter_rows` sortiert per `ORDER BY row_index`,
Sampler nutzen row_id-basierte Indices. Generator-Konsum ist
deterministisch.

## Architektur

Strikte Layer-Trennung. Keine zyklischen Importe. UI darf Core/Persistence/IO nutzen,
umgekehrt nie.

```
ui ──▶ controllers ──▶ core ◀── io
                         ▲ ▲
                         │ │
                  persistence audit
```

- **`core/`** – reine Domain-Logik. Keine I/O, kein Qt, keine SQL. Alles deterministisch
  und unit-test-bar ohne Mocks.
  - `models.py` – frozen Dataclasses (Engagement, Dataset, SampleConfig, …).
    `Dataset` ist seit Sprint 11.1 nur Metadaten (`columns`, `row_count`,
    `source_file`, Engagement-FK) – Rows leben im Repo (siehe Block
    "Streaming-Architektur" oben).
  - `rng.py` – `make_rng(seed)` + `fisher_yates_shuffle` über `numpy.random.default_rng`
  - `sampling.py` – `BaseSampler` + Simple/Cluster/Stratified + `create_sampler`-Factory.
    `sample(rows, population_size=None)` akzeptiert einen einmalig-
    konsumierbaren Iterator, `_collect_pool` ist Single-Pass-Filter
    (zählt parallel den Pre-Filter-Total für den `population_size`-
    Default). Production-Caller setzen `population_size=dataset.row_count`
    explizit, damit auch bei Sub-Sampling die Original-Population
    dokumentiert bleibt. Details siehe Streaming-Architektur-Block.
- **`io/`** – Excel-/CSV-Import, Excel-Export, PDF-Report.
  - `importer.py` – `ExcelImporter` nutzt seit Sprint 10.2 die Rust-
    basierte `python-calamine`-Library für Excel-Reads (10–30× schneller
    als openpyxl, deutlich niedrigerer RAM-Footprint, Streaming via
    `CalamineSheet.iter_rows`). CSV-Pfad bleibt stdlib-`csv` mit
    Encoding-Fallback. Header-Detection (≥50 % String-Anteil) +
    Progress-Callback unverändert. Native Python-Typen (kein
    numpy/pandas-Output). openpyxl wird im Import-Pfad NICHT mehr
    verwendet – bleibt nur für die Exporter.
    Calamine-Eigenheiten, die der Importer normalisiert:
    leere Zellen kommen als `""` (→ `None`), Excel-Zahlen kommen
    immer als `float` (ganzzahlige → `int`), Datums-Zellen ohne
    Uhrzeit kommen als `date` (→ `datetime`).
    **Streaming-Import**: `ImportResult.rows` ist ein einmalig
    konsumierbarer `Iterator[DatasetRow]`, `ImportResult.stats`
    (`ImportStats`-Container) füllt sich während der Iteration
    (`skipped_rows`, `warnings`, `processed_count` – erst nach voller
    Konsumierung aussagekräftig). Typischer Pfad: `dataset_repo.create(
    dataset, result.rows)` zieht den Generator einmal durch und
    korrigiert `row_count` auf die tatsächlich persistierte Anzahl
    (Initial-Estimate aus `sheet.total_height` ist oft zu hoch).
    Sprint 11.5 – die Compat-Properties `result.skipped_rows` /
    `result.warnings` sind weg, Caller lesen `result.stats.*` direkt.
    **Sprint 16 – Sheet-/Header-Dialog-API**: zusätzlich zu `import_file`
    drei neue Methoden für den `ImportOptionsDialog`-Flow:
    - `list_sheets(path) → list[SheetInfo]` – Sheet-Namen + Zeile-/Spalten-
      anzahl ohne die Daten zu laden.
    - `preview_sheet(path, sheet, max_rows=20) → SheetPreview` – rohe 2D-
      Zellen + heuristisch erkannte Header-Zeile + `confidence`
      (`high`/`low`/`ambiguous`). Header-Zeile ist NICHT interpretiert,
      sie steht in den Zeilen drin.
    - `import_file_configured(path, sheet, header_row) → ImportResult` –
      Excel-Import mit explizit gewählten Sheet + Header-Zeile (0-basiert).
      Skipt die Auto-Detection, ist der Override-Pfad für den Dialog.
    Bestehender `import_file()`-Pfad UNVERÄNDERT – lautloser Auto-Import
    funktioniert weiter wie zuvor.
  - `exporter.py` – `ExcelExporter`. Atomare Writes (`.tmp` → `os.replace`),
    Sheet "Sample" (BDO-rote Header) + Sheet "Metadaten" (Engagement, Seed,
    Methode). Dateiname-Schema:
    `{name}_ID{id}_BDO_sampling_{YYYYMMDD}.xlsx`.
    `export_sample(sample, dataset, dataset_repo, ...)` nimmt das
    `DatasetRepo` und holt nur `sample.selected_row_ids` via
    `get_rows_by_ids` – siehe Streaming-Architektur-Block.
  - `pdf_report.py` – `AuditTrailPDF` via `reportlab.platypus`.
    A4 Portrait, Engagement-Block oben, Event-Tabelle mit
    Korrektur-Highlight, Footer mit Seitenzahl + Zeitstempel. Optionales
    Briefpapier (PNG/JPG) wird via `onPage`-Hook hinter den Content gelegt.
    Falls kein Briefpapier explizit übergeben wird, lädt
    `get_default_briefpapier()` automatisch ein Default (s. unten).
    Sprint 10.4 – die Event-Tabelle wird in Sub-Tables zu je
    `CHUNK_SIZE=500` Rows gerendert (`_build_event_flowables`); kurze
    Zellen bleiben rohe `str` statt `Paragraph` (`_format_cell`,
    Threshold 60 Zeichen / kein Markup). Reduziert die Render-Zeit
    massiv – 5 000 Events ~13 s → 0.4 s, 20 000 Events 1.6 s.
  - `multi_report_exporter.py` – `MultiSheetReportExporter` schreibt einen
    Komplett-Bericht als Multi-Sheet-xlsx (Übersicht, AuditTrail, Samples,
    Statistiken inkl. eingebettetem Chart-Bild via `io.charts`).
    Atomare Writes wie der `ExcelExporter`.
  - `html_report.py` – `HtmlReportGenerator` rendert einen selbstständigen
    HTML-Report via Jinja2. CSS inline, Charts als Base64-PNG eingebettet
    (geliefert von `io.charts`), Template-Default unter
    `resources/templates/audit_report.html`.
  - `charts.py` – Bytes-Renderer für die Mini-Charts (Bar/Line/Pie) als
    PNG-Bytes. Matplotlib mit `Agg`-Backend, BDO-Farbschema aus
    `config.py`, transparenter Hintergrund, `plt.close(fig)` nach jeder
    Render-Operation gegen Memory-Leaks. Wird von
    `multi_report_exporter.py` (Excel-Image) und `html_report.py`
    (Base64-Embed) konsumiert. **Bewusst Qt-frei** – der Pixmap-Wrapper
    für die UI sitzt in `ui/widgets/chart_renderer.py` und ruft seinerseits
    `render_*_chart_bytes` hier auf. Sprint 15 / F-003+F-004+F-005:
    vorher lebte die ganze Logik in `ui/widgets/chart_renderer.py`,
    was IO transitiv an PyQt6 gebunden hat (Layer-Verletzung). Der
    grep-Schutz dafür sitzt in `tests/unit/test_io_charts.py::
    TestQtFreeImport`.
  - `briefpapier.py` – `BriefpapierConfig` (frozen) + `get_default_briefpapier()`.
    Resolution-Order: zuerst User-Override unter `BRIEFPAPIER_DIR`
    (`~/Documents/BDO Audit Sampling/briefpapier/bdo_letterhead.{png,jpg,jpeg,pdf}`),
    danach das Paket-Default `config.DEFAULT_BRIEFPAPIER`
    (Platzhalter-PDF unter `<package>/resources/briefpapier/bdo_placeholder.pdf`).
    Wenn beides fehlt, läuft der Report ohne Briefpapier-Layer.
    Der Controller hängt zusätzlich `settings.custom_briefpapier_path`
    (aus dem Settings-Dialog) als höchste Priorität vor (siehe
    `MainController._resolve_briefpapier`). PDF-Briefpapier wird via
    `pdfrw` (`pagexobj` + `makerl`) auf den Reportlab-Canvas gelegt;
    PNG/JPG direkt mit `canvas.drawImage`.
- **`persistence/`** – SQLite über sqlite3 (kein ORM-Overhead).
  - `database.py` – `Database`-Wrapper mit WAL+FK-PRAGMAs, `session()`-Transaktionen,
    `savepoint()`-Helper für nestbare Repo-Transaktionen, automatische Migrations.
  - `repositories.py` – `EngagementRepo`, `DatasetRepo`, `SampleRepo`, `AuditRepo`.
    Stateless, nehmen `sqlite3.Connection` im Konstruktor, geben Domain-Modelle zurück.
  - `migrations/NNN_*.sql` – nummerierte SQL-Files; `001_initial.sql` ist das
    komplette Sprint-2-Schema. Migrations-Runner liest `schema_version` und führt
    nur ausstehende Versionen aus.
  - `version_manager.py` – `EngagementVersionManager` legt bei jedem
    `handle_open_engagement` einen Snapshot der `.db` unter `<mandant>/archiv/`
    ab (Dateiname `{stem}_{YYYY-MM-DD}_{HH-MM-SS}_{Auditor}.db`).
    `.db-wal`/`.db-shm` werden NICHT mitkopiert. Compliance-Pfad für
    ISAE-3402-Versionsnachweis.
- **`audit/`** – Append-only Event-Log via Trigger.
  - `logger.py` – `AuditLogger` ist der High-Level-Eingang: `log_sampling`,
    `log_import`, `log_export`, `log_undo`, `log_redo`, `log_reset`, `log_correction`.
  - Korrekturen werden als neue Events mit `event_type='correction'` und
    `corrects_event_id`-FK auf den Original-Event gespeichert (kein UPDATE/DELETE).
- **`ui/`** – PyQt6. Strikt MVC: Widgets dumm, Controllers in
  `ui/controllers/`. Stylesheet (BDO-CI) unter `ui/styles/*.qss`.
  - `main_window.py` – `MainWindow` mit `QStackedWidget`-State-Maschine
    Welcome ↔ Workspace. Menü, Toolbar, Splitter-Layout (Sidebar links;
    rechts vertikaler Splitter: Datentabelle oben, `QTabWidget` mit
    AuditTrail-/Dashboard-View unten). Splitter-Größen + aktiver
    Tab werden in `QSettings` (BDO / Audit Sampling Tool) persistiert.
    Die Toolbar enthält rechtsbündig (Expanding-Spacer) einen Bug-
    Report-Button, der dieselbe `QAction`-Instanz wie der Hilfe-Menü-
    Eintrag teilt – keine Duplikation des Triggers.
    `self._action_settings` ist eine geteilte QAction, die an drei
    Stellen sichtbar ist (alle teilen dieselbe Instanz, keine
    Duplikation): Datei-Menü, Mac-App-Menü via `setMenuRole(
    PreferencesRole)` und – seit Sprint 9.7 – Toolbar rechts vor dem
    Bug-Report-Button (nach dem Expanding-Spacer). Cmd+,-Shortcut via
    `QKeySequence.StandardKey.Preferences`; Toolbar-Tooltip enthält
    den plattformnativen Shortcut-Text (`toString(NativeText)`).
    Icon kommt aus `SP_FileDialogContentsView` – nicht
    `SP_FileDialogDetailedView`, das ist für den Excel-Report belegt.
    `self._file_menu` ist als Attribut exponiert, damit Tests die
    Menü-Zugehörigkeit prüfen können.
    Sendet typisierte Signals; *kein* DB-Zugriff hier.
  - `controllers/main_controller.py` – **Sprint 13 / F-001**: dünner
    Coordinator (~343 LoC) statt vorherigem 1304-LoC-God-Object. Hält
    die `WorkspaceSession` (gemeinsamer State) und fünf Sub-Controller,
    verdrahtet `MainWindow`-Signals an den jeweils zuständigen
    Sub-Controller. Externe API (Konstruktor + alle public `handle_*`-
    Methoden) **unverändert** – Backward-Compat-Fassade leitet `handle_*`-
    Aufrufe an die Sub-Controller weiter, Backward-Compat-Properties
    (`_db`, `_engagement`, `_dataset`, `_sample`, `_active_sample_id`,
    `_filter_active_sample_id`, `_state_repo`, `_undo_manager`,
    `_settings`, `_datasets`, `_restoring_state`) delegieren transparent
    an die `session`. Damit laufen bestehende Tests
    (`controller.handle_new_sampling()`, `controller._sample`, etc.)
    unverändert.
  - `controllers/workspace_session.py` – **Sprint 13 / F-001**: zentraler
    Session-State + Glue-Helper. Hält DB-Connection, Engagement,
    Dataset, Sample, Filter-State, UndoManager, EngagementStateRepo,
    Settings, Window-Ref. Helpers: `has_engagement()` / `has_active_
    dataset()` / `has_active_sample()` (Convenience-Guards), `persist_
    state()` / `restore_state()`-Lebenszyklus, `refresh_audit_trail()` /
    `refresh_dashboard()` / `refresh_views()`, `select_dataset(id)`
    (geteilt von Selection- und WorkspaceController), `resolve_brief
    papier()`, `default_export_dir()`, `error(message)`, `reset_to_
    welcome()`, `apply_new_settings()`. `AUDIT_EVENT_DISPLAY_LIMIT =
    10_000` als zentrale Konstante (vorher 4× hardgecodet, Pass-2 Q-008).
  - `controllers/engagement_controller.py` – Engagement-Lifecycle:
    `handle_new_engagement` (inkl. DuplicateEngagementDialog-Loop),
    `handle_open_engagement` (inkl. Compliance-Snapshot via
    `EngagementVersionManager`), `handle_close_engagement_requested`
    (Bestätigungs-Dialog), `handle_close_engagement`, `refresh_recent`,
    `_adopt_database` (UndoManager + EngagementStateRepo aufsetzen,
    Recent-Store updaten, `_restore_state` triggern). Undo-Konvention:
    nach jeder mutierenden Aktion wird der NEUE State auf den
    Undo-Stack gelegt; bei `handle_undo` wird der Top entfernt und der
    `peek_undo`-State angewandt (leerer State, wenn der Stack nach dem
    Pop leer ist).
  - `controllers/workspace_controller.py` – mutierende Workspace-
    Operationen: `handle_import_excel` (ruft `s.select_dataset(stored.
    id)` für Auto-Select nach Import), `handle_new_sampling`,
    `handle_reset`, `handle_undo`, `handle_redo`. **Sprint 11.4 –
    Sampling-Streaming**: `_build_sampling_iterator(repo, dataset,
    from_sample_only)` liefert `(Iterable[DatasetRow], int)`: bei
    `from_sample_only` → `get_rows_by_ids` mit den IDs des aktiven
    Samples + Sample-Größe; sonst → `iter_rows`-Generator + `dataset.
    row_count`. **Sprint 12.1 / P-002**: für `SimpleSampler` ohne
    Filter + ohne Sub-Sampling Spezialpfad via `sampler.sample_ids(
    repo.iter_row_ids(...))` – kein DatasetRow-Materialize, RAM-Peak
    1 GB → <50 MB bei 1M-Datasets.
  - `controllers/selection_controller.py` – Dataset-/Sample-/Filter-
    Auswahl: `handle_dataset_selected` (delegiert an `session.select_
    dataset`), `handle_sample_selected`, `handle_sample_filter_toggled`
    (Doppelklick), `handle_filter_only_sample_toggled` (Checkbox),
    `handle_audit_event_double_clicked` (sucht Sample-Event und
    markiert via `handle_sample_selected`).
  - `controllers/export_controller.py` – 4 Export-Handler:
    `handle_export_sample` (Excel via `ExcelExporter` mit `DatasetRepo`
    – der Exporter holt die Sample-Rows selbst), `handle_export_audit_
    pdf` (AuditTrail-PDF mit Briefpapier-Resolution + Zeitraum-/Type-
    Filter), `handle_export_excel_report` (Multi-Sheet via
    `MultiSheetReportExporter`), `handle_export_html_report` (Jinja2-
    HTML via `HtmlReportGenerator`). Plus interner `_next_sample_id_
    for_export` für die ID-Spalte im Dateiname-Token.
  - `controllers/help_controller.py` – Bug-Report, About, Settings,
    Hotkeys-Info. `handle_settings` ruft nach OK `save_settings(...)`
    und `session.apply_new_settings(...)` (legt Engagement-Dir an +
    setzt Panel-Visibility live).
  - `controllers/_factories.py` – `ControllerFactories`-Dataclass
    (frozen, slots) bündelt alle Dialog-Factory-Refs + Default-
    Implementierungen. Jeder Sub-Controller nimmt sich nur die
    Factories, die er braucht.
  - `widgets/data_table.py` – `DatasetTableModel(QAbstractTableModel)` +
    `DataTableView`. Virtuelles Model (kein QStandardItemModel) –
    100k+ Zeilen scrollen flüssig. Sample-Highlighting per
    `BackgroundRole`, Filter ohne Proxy via `_visible_indices`.
    Bei leerem Model zeichnet `paintEvent` einen zentrierten
    "Keine Datensätze – Datei importieren"-Hinweis.
    **Sprint 11.2 – Streaming-UI**: Das Model hält keine In-Memory-
    Liste mehr, sondern liest Rows on-demand via
    `DatasetRepo.get_rows_in_range`. FIFO-Cache mit
    `DEFAULT_CACHE_SIZE = 1000` Rows; bei Cache-Miss lädt
    `_ensure_cached` einen ganzen Block (Window
    `BULK_LOAD_HALF_WINDOW = 125` davor + dahinter). RAM-Footprint
    konstant ~3 MB, unabhängig von Dataset-Größe. `set_dataset(dataset,
    repo)` (statt `dataset, rows`) – Caller (MainController) übergibt
    ein frisches `DatasetRepo`. FIFO statt echtes LRU: bei sequentiellem
    Qt-Scroll reicht das aus.
  - `widgets/audit_trail_view.py` – `AuditTrailModel` +
    `AuditTrailFilterProxy` + `AuditTrailView`. Filter-Zeile mit
    Volltextsuche und ComboBoxen (Aktion / User / Zeitraum), sortierbar.
    Doppelklick emittiert `event_double_clicked(int)` – der Controller
    sucht den passenden Sample-Event und markiert das Sample.
  - `widgets/dashboard_view.py` – `DashboardView` mit Kachel-Grid
    (Datasets, Samples, Audit-Events, Letzte Aktivität, Letzte
    Stichproben, Sampling-Historie). Charts werden via `chart_renderer`
    als `QPixmap` in `QLabel`s gerendert. Klicks auf einzelne Samples
    emittieren `sample_clicked(int)`.
  - `widgets/chart_renderer.py` – Dünner Pixmap-Wrapper (~35 LoC).
    `render_bar/line/pie_chart` rufen die `_bytes`-Funktionen aus
    `sampling_tool.io.charts` auf und wandeln das PNG via
    `QImage.fromData` → `QPixmap`. Heavy-Lifting (matplotlib, BDO-
    Farbschema, Styling) liegt seit Sprint 15 in `io/charts.py` –
    damit bleibt der `io`-Layer Qt-frei (siehe dortigen Block).
  - `widgets/sidebar.py` – `NavigationSidebar` mit drei Sektionen
    (Engagement-Block, Datasets-Liste, Samples-Liste).
  - `widgets/welcome.py` – `WelcomeScreen` (Recent-Engagement-Karten +
    Buttons) wird angezeigt, wenn keine `.db` geladen ist.
  - `dialogs/first_run_wizard.py` – Vierseitiger `QWizard` für die
    Erst-Einrichtung beim allerersten App-Start (Begrüßung →
    Ordner-Auswahl → Auditor-Name → Zusammenfassung). Wird in
    `__main__.run_first_run_wizard` aufgerufen, wenn
    `AppSettings.first_run_completed=False`. Die Folder-Page legt das
    Verzeichnis bei `validatePage` an; bei Cancel/Close werden Defaults
    beibehalten und das Flag trotzdem auf `True` gesetzt.
  - `dialogs/new_engagement_dialog.py` – Modal-Dialog für die
    Pflichtfelder Auditor/Position/Mandant/Prüfungstyp +
    Save-Path-Auswahl. Optionaler `initial_engagement`-Konstruktor-
    Parameter füllt die Felder vor (RENAME-Flow nach Duplikat-Konflikt).
  - `dialogs/duplicate_engagement_dialog.py` – `DuplicateEngagementDialog`
    wird vom `MainController` gezeigt, wenn der gewählte Ziel-DB-Pfad
    schon existiert. Drei Buttons (Bestehendes öffnen / Anderen Namen
    wählen / Abbrechen) liefern ein `DuplicateEngagementChoice`-Enum
    statt eines stumpfen Überschreiben-Ja/Nein.
  - `dialogs/sampling_dialog.py` – Sampling-Konfigurator (Simple/Cluster/
    Stratified, Filter, Seed mit Würfel, Resample-Checkbox). Liefert
    `SamplingDialogResult` mit `SampleConfig` + `from_sample_only`-Flag.
    Das Flag ist **nicht** persistiert – der Controller filtert das
    Dataset zur Laufzeit auf die Vorsample-Auswahl.
    Konstruktor-Parameter `advanced_mode: bool`: im Default-Modus
    (False) werden ausschließlich Methodenauswahl, Cluster-/Schicht-
    Felder und der Spalten-Filter ausgeblendet. Methode ist fix
    `SIMPLE`. Footer zeigt links einen diskreten „Einfach-Modus"-Hinweis
    mit Tooltip.
    Sprint 9.6 – Common-Block in beiden Modi:
    - `_resample_checkbox` (= from_sample_only-Filter).
    - **Seed-Widget** (`_seed_spin` + `_seed_dice`-Würfel): beim Öffnen
      mit Zufalls-Seed via `_generate_random_seed()` vorbefüllt; User
      kann manuell ändern oder per Würfel neu generieren. Korrektur zur
      Sprint-9.3-Spec: das Widget wandert aus dem Advanced-Block in den
      Common-Block, weil Reproduzierbarkeits-Transparenz auch im
      Default-Modus essentiell ist (ISAE-3402).
    - **Größe (`_size_spin`)** ohne hartes Cap (`setMaximum(_SPINBOX_MAX)`,
      = int32-max). Direkt unter dem SpinBox sitzt `_lbl_size_hint`
      ("max. N verfügbar"), das via `_update_size_hint()` live bei
      Resample-Toggle aktualisiert wird. Validierung passiert in der
      überschriebenen `accept()`-Methode: Größe < `MIN_SAMPLE_SIZE`
      oder > `_effective_max_sample_size()` zeigt eine
      `QMessageBox.warning` und blockiert das Dialog-Close. Vorher hat
      `_on_resample_toggled` stilles QSpinBox-Capping gemacht – das ist
      raus.
    Verbleibender Unterschied Simple/Advanced: nur noch Methodenwahl +
    method-spezifische Felder (Cluster-/Schicht-Feld, Stratify-Mode,
    Spalten-Filter).
    **Sprint 11.4**: Konstruktor-Parameter `rows: Sequence[DatasetRow] |
    None`. Im Simple-Mode wird `None` übergeben – kein voller
    Row-Materialize nur für die Größen-Validierung; stattdessen zieht
    `_max_population` `dataset.row_count`. Nur im Advanced-Mode (wenn
    das Filter-Dropdown distinct-Werte braucht) lädt der Controller
    weiterhin `get_all_rows` und reicht sie an den Dialog durch.
    `MainController.handle_new_sampling` orchestriert das.
  - `dialogs/export_sample_dialog.py` – Spaltenauswahl (Checkboxen) +
    Filename/ID + Zielordner. Vorschau-Label live mit
    `{name}_ID{id}_BDO_sampling_{YYYYMMDD}.xlsx`.
  - `dialogs/_export_base.py` – `ExportTargetWidget` als wiederverwendbare
    rechte Spalte für alle Export-Dialoge (Dateiname, ID, Zielordner,
    Vorschau-Label). Pattern-basiert über `{name}/{id}/{type}/{date}`-Tokens
    + frei wählbare Extension. Emittiert `changed`-Signal für Live-
    Validierung der OK-Buttons.
  - `dialogs/export_audit_pdf_dialog.py` – `ExportAuditPdfDialog` mit
    Zeitraum-Filter (zwei optional aktivierbare `QDateEdit`),
    Aktionstyp-Selektion (Checkbox-Liste je verfügbarem Event-Typ),
    Briefpapier-Toggle (disabled wenn nicht konfiguriert) und
    Statistik-Seite-Toggle. Liefert `ExportAuditPdfDialogResult`.
  - `dialogs/export_excel_report_dialog.py` – `ExportExcelReportDialog`
    mit Sheet-Selektion (Übersicht/AuditTrail/Samples/Statistiken,
    Default alle ein). Liefert `ExportExcelReportDialogResult` inkl.
    `sheets: set[str]` für den `MultiSheetReportExporter`.
  - `dialogs/export_html_report_dialog.py` – `ExportHtmlReportDialog`
    mit Toggles für Charts (Base64-eingebettet), AuditTrail-Tabelle und
    Samples-Übersicht. Liefert `ExportHtmlReportDialogResult` mit den
    drei `include_*`-Flags für `HtmlReportGenerator.render`.
  - `dialogs/bug_report_dialog.py` – 3 Freitextfelder + System-Info-
    Checkbox. Konstruiert `mailto:`-URL und öffnet sie via
    `QDesktopServices`. Auf Windows wird das in Sprint 7 von
    `pywin32`/Outlook abgelöst.
  - `dialogs/about_dialog.py` – statischer About-Dialog (Version,
    Beschreibung, Repo-Link).
  - `dialogs/progress_dialog.py` – `TaskProgressDialog` wrapt
    `QProgressDialog` mit Callback-Adapter im
    `ExcelImporter`-Signatur-Format.
  - `dialogs/import_options_dialog.py` – `ImportOptionsDialog` (Sprint 16,
    VBA-Backlog). Kombinierter Sheet-Dropdown + Preview-Tabelle + Header-
    Zeile-Spinbox. Wird vom `WorkspaceController.handle_import_excel`
    aufgerufen, wenn die Datei mehr als ein Sheet hat ODER die Header-
    Confidence nicht `high` ist (Multi-Sheet → immer Dialog; Single-Sheet
    + high → lautloser Auto-Import). Liefert `ImportOptionsResult`
    (`sheet_name`, `header_row` 0-basiert), der Controller reicht das
    an `ExcelImporter.import_file_configured` durch. Confidence-Label
    unter dem SpinBox: grau bei `high`/`low`, BDO-Rot bei `ambiguous`.
    Importieren-Button ist disabled, wenn die gewählte Header-Zeile
    ≥ Sheet-Höhe − 1 ist (sonst gäbe es keine Datenzeilen).
  - `recent.py` – `RecentEngagementsStore` mit JSON-Persistenz unter
    `platformdirs.user_data_dir('AuditSamplingTool', 'BDO')`.
    Defekte Pfade werden beim `list()` gefiltert; `prune_missing()`
    räumt sie persistent weg.
  - `settings_store.py` – `AppSettings` (frozen dataclass) plus
    `load_settings()` / `save_settings(...)`. Persistenz via
    `QSettings(APP_ORG, APP_NAME)`; fehlende Keys fallen auf
    `AppSettings.defaults()` zurück. Wird vom `MainController` beim
    Start gelesen und in `handle_settings` zurückgeschrieben.
  - `dialogs/settings_dialog.py` – `SettingsDialog` mit 3 Tabs
    (Allgemein / Reports / Erweitert), Reset-Button und Briefpapier-
    Vorschau via `QDesktopServices`. Konstruktor nimmt das aktuelle
    `AppSettings`; OK liefert ein neues `AppSettings`, Cancel `None`.

## Settings

`AppSettings` (siehe `ui/settings_store.py`) ist die zentrale Quelle
für Anwender-Präferenzen:

- `default_auditor_name` – Vorbelegung im New-Engagement-Dialog.
- `engagements_dir` – Default-Pfad für die SQLite-Ablage.
- `reset_keeps_filter` – Reset entfernt nur das Sample, lässt den
  Filter stehen.
- `default_include_briefpapier` / `default_include_statistics` –
  Default-Checkboxen im AuditTrail-PDF-Dialog.
- `custom_briefpapier_path` – User-Override für das Briefpapier
  (höchste Priorität in `_resolve_briefpapier`).
- `advanced_mode` – Schaltet im Sampling-Dialog zusätzliche Methoden
  (Cluster, Stratifiziert) und Detail-Optionen (Cluster-/Schicht-Feld,
  Spalten-Filter, manueller Seed mit Würfel-Button) frei. Default
  `False` – auch für Bestandsuser ohne `advanced_mode`-Key. Wird vom
  `MainController` direkt an die `SamplingDialog`-Factory durchgereicht.
- `show_dashboard` / `show_audit_trail` – Default `True`. Steuern die
  Tab-Sichtbarkeit im unteren `QTabWidget`. Sind beide `False`, wird
  das gesamte untere Panel ausgeblendet und die Datentabelle nutzt die
  volle Höhe. `MainController` ruft `MainWindow.apply_panel_visibility`
  beim App-Start und nach jedem Settings-OK auf – kein Neustart nötig.
  Splitter-Größen werden beim Collapse in `_cached_splitter_sizes`
  gemerkt und beim Re-Show wiederhergestellt; `_save_workspace_state`
  schreibt im Collapse-Zustand die echten (gecachten) Größen, nicht
  den `[total, 0]`-Snapshot.
- `first_run_completed` – Default `False`. Triggert beim App-Start in
  `__main__.main` den `FirstRunWizard` (Begrüßung → Ordner → Auditor
  → Zusammenfassung). Nach Wizard-Accept oder -Cancel wird das Flag
  auf `True` gesetzt und persistiert. Bestands-User werden in
  `load_settings` über eine Heuristik erkannt (eigener `engagements_dir`-
  Key oder Default-Ordner existiert bereits) und das Flag wird in
  dem Fall einmalig auf `True` gesetzt + sofort in QSettings geschrieben,
  damit der Wizard nie auftaucht.
- `undo_depth` / `snapshot_retention_days` / `log_level` – reserviert
  für spätere Erweiterungen, aktuell informativ.

## Resource-Loading (Sprint 8.1)

Dev-Layout und PyInstaller-Bundle-Layout für Resource-Dateien unterscheiden
sich. **Niemals** Resources direkt via `Path(__file__).parent / ...` adressieren –
das schlägt im Frozen-Bundle stillschweigend fehl (z. B. Stylesheet wird nicht
geladen, App fällt aufs System-Theme zurück).

Stattdessen den zentralen Resolver in `sampling_tool.resources` nutzen:

- **`package_resource("foo/bar")`** – Files, die zum Paket gehören:
  - Dev: `src/sampling_tool/foo/bar`
  - Bundle: `sys._MEIPASS/sampling_tool/foo/bar`
  - Beispiele: `ui/styles/bdo_light.qss`, `persistence/migrations`.
- **`shared_resource("foo/bar")`** – Top-Level `resources/`-Ordner:
  - Dev: `resources/foo/bar` (im Projekt-Root)
  - Bundle: `sys._MEIPASS/resources/foo/bar`
  - Beispiele: `briefpapier/bdo_placeholder.pdf`,
    `templates/audit_report.html`, `icons/app.icns`.

Konsequenzen:

- Neue Resources im Projekt-Root `resources/` ablegen, wenn sie eher
  "Daten" sind (Templates, Briefpapier, Icons). Inside-Package nur dann,
  wenn die Datei eng mit Code verzahnt ist (Stylesheets, Migrations).
- Wer Resources lädt, importiert `from sampling_tool.resources import
  package_resource, shared_resource` – kein direkter Pfadbau mehr.
- Spec-File (`sampling_tool.spec`) muss neue Resource-Pfade in `datas`
  ergänzen. Aktuell: `resources/` (top-level), `sampling_tool/persistence/
  migrations`, `sampling_tool/ui/styles`.

## Distribution (Sprint 8)

Das Tool wird als doppelklickbare App ausgeliefert. **Code-Signing ist
bewusst nicht konfiguriert** – Anwender bekommen beim ersten Start eine
"unbekannter Entwickler"-Warnung (siehe `docs/INSTALL_USER.md` für den
Workaround).

- **Build lokal:** `python scripts/build_app.py [--dmg]` (benötigt
  `pip install -e ".[build]"`). Output unter `dist/`:
  - Mac: `Audit Sampling Tool.app` (+ optional `.dmg` via `create-dmg`)
  - Windows: Ordner `AuditSamplingTool/` mit `AuditSamplingTool.exe`
- **Build via CI:** `git tag v0.X.Y && git push --tags` triggert
  `.github/workflows/release.yml`. Baut auf `macos-latest` +
  `windows-latest` parallel, lädt beide Bundles als ZIPs in einen
  Draft-Release.
- **Spec-File:** `sampling_tool.spec` (PyInstaller-Konfiguration). One-folder
  Mode, `noarchive=False`. Resources werden unter `sampling_tool/...`
  gebundelt, damit `Path(__file__).parent / ...`-Lookups (Briefpapier,
  QSS, HTML-Templates) im Frozen-Bundle weiterhin funktionieren.
- **Hidden Imports:** matplotlib-Backends, openpyxl-Writer, reportlab-Font-
  Tabellen, `pdfrw`, `platformdirs`. PyInstaller findet diese nicht
  automatisch – im Spec explizit aufgeführt.
- **Icons:** `resources/icons/app.icns` (Mac) + `app.ico` (Windows). Werden
  vom Build-Script bei Bedarf via `scripts/generate_app_icon.py`
  regeneriert (Platzhalter BDO-Rot + Schrift "BDO"). Austauschbar ohne
  Code-Änderung.
- **Anwender-Doku:** `docs/INSTALL_USER.md` mit ZIP-Entpacken-Anleitung +
  "Trotzdem öffnen"-Workaround für Mac- und Windows-Gatekeeper.

## Code-Style

- Python 3.11+ Syntax: `from __future__ import annotations`, PEP-604-Unions (`X | None`),
  `match`-`case` wo es Lesbarkeit verbessert.
- **Volle Type-Hints**, mypy strict-konform. Keine `Any` ohne Begründung.
- **Frozen Dataclasses** für alle Modelle (Immutability → Reproducibility).
- **Ruff** als Lint+Format (siehe `[tool.ruff]` in `pyproject.toml`). Line-length **100**.
- **Docstrings auf Deutsch**, knapp. Module-Docstring oben in jeder Datei (eine Zeile reicht).
- Fehlermeldungen für Endnutzer (Auditoren) **deutsch**, technische Logs englisch.
- Keine Kommentare, die nur das WAS beschreiben — gut benannte Symbole reichen. Kommentare
  nur für nicht-offensichtliche WHYs (Algorithmus-Begründung, ISAE-Anforderung etc.).

## Migration-Mapping VBA → Python

Grobe Übersetzungstafel zwischen altem VBA-Tool und neuer Python-Architektur.

| VBA (alt)                                  | Python (neu)                                       |
|--------------------------------------------|----------------------------------------------------|
| `modSampling.bas` – Random-Logik           | `core/sampling.py` + `core/rng.py`                 |
| `Rnd()` / `Randomize`                      | `numpy.random.default_rng(seed)` (reproduzierbar!) |
| Inline-Shuffle in VBA                      | `fisher_yates_shuffle()` in `core/rng.py`          |
| `clsEngagement.cls`                        | `core.models.Engagement` (frozen dataclass)        |
| `clsDataset.cls`                           | `core.models.Dataset` + `DatasetRow`               |
| `frmMain.frm` (UserForm)                   | `ui/main_window.py` (Sprint 4)                     |
| `frmSampleConfig.frm`                      | `ui/dialogs/sample_config_dialog.py` (Sprint 5)    |
| Excel-Sheet als „DB"                       | SQLite via `persistence/` (Sprint 2)               |
| `Worksheets("Audit").Range(...)`           | `audit/logger.py` + `AuditRepo`, append-only Trigger |
| `Worksheets("UndoHistory")` Hidden-Sheet   | `core/undo.py` `UndoManager` + Tabelle `undo_snapshots` |
| `Application.Mailer` / Outlook-COM         | `pywin32` in `ui/bug_report.py` (Sprint 7)         |
| Stratifiziert via `Dictionary`-Hack        | `core.sampling.StratifiedSampler` (sauber, getestet)|
| Cluster-Sampling (war buggy in VBA)        | `core.sampling.ClusterSampler` (neu spezifiziert)  |
| Manuelle CRLF-Exportlogik                  | `io/exporters/` mit Jinja2 / openpyxl (Sprint 3+6) |

**Wichtig:** Das alte VBA-Tool hatte einen bekannten Bug bei stratifizierter Auswahl mit
ungerader Verteilung (siehe interne Bug-Liste). Im Python-Port lösen wir das mit der
**Largest-Remainder-Methode** in `StratifiedSampler` und decken es mit Tests ab.

## Persistenz-Architektur (Sprint 2)

Drei Kerndogmen, die sich durch die ganze DB-Schicht ziehen:

1. **Eine SQLite-Datei pro Engagement.** Mandanten-Trennung, einfaches Archivieren,
   DSGVO-konform. Es gibt keinen "globalen" Pool. Standard-Ablageort ist
   `~/Documents/BDO Audit Sampling/<MandantSanitized>/<MandantSanitized>.db`
   (vgl. `config.ENGAGEMENTS_DIR` + `config.sanitize_for_path`). Beim Öffnen
   landet jeweils eine Sicherheitskopie unter `archiv/` (siehe
   `persistence/version_manager.py`).
2. **Append-only Audit-Log.** `audit_events` darf ausschließlich per `INSERT`
   befüllt werden. Zwei BEFORE-Trigger (`audit_events_no_update`,
   `audit_events_no_delete`) blockieren UPDATE/DELETE hart mit
   `RAISE(ABORT, 'audit_events is append-only')`. Korrekturen sind neue Events
   mit `event_type='correction'` und `corrects_event_id`-FK aufs Original.
3. **WAL-Mode + Foreign Keys an.** `connect()` setzt `journal_mode=WAL`,
   `foreign_keys=ON`, `synchronous=NORMAL`. Autocommit (`isolation_level=None`),
   Transaktionen werden via `session()` und `savepoint()` explizit gesteuert.

**Repositories als Eintrittspunkt für Sprint 3 (I/O):**

- Excel-Importer (Sprint 3, in 11.1 refaktoriert) konstruiert ein `Dataset`
  (Metadaten) + ein `tuple[DatasetRow, ...]` separat. Aufrufer ruft
  `DatasetRepo.create(dataset, rows)`. Atomar – schlägt das fehl, bleibt
  nichts zurück. `dataset.row_count` wird vom Repo auf `len(rows)` gesetzt.
  Danach `AuditLogger.log_import(dataset)`.
- Row-Zugriffe siehe Streaming-Architektur-Block oben (`get_row`,
  `get_rows_in_range`, `iter_rows`, `iter_row_ids`, `get_rows_by_ids`,
  `get_all_rows` als Ausnahme).
- UI-Controller (Sprint 4+) bekommt `Database`-Instanz, baut bei Bedarf eigene
  Repo-Instanzen pro Operation. Connection-Lebensdauer = App-Sitzung.
- `UndoManager(db, engagement_id)` ist persistiert (überlebt Connection-Wechsel).
  `MAX_DEPTH = 20`, neuer `push` löscht den Redo-Stack (Standard-Editor-Verhalten).

**Datetime-Handling:** Eigene Adapter/Konverter in `database.py` registrieren
UTC-aware ISO-8601 für `INSERT` und parsen sowohl unser Format als auch SQLites
`CURRENT_TIMESTAMP`-Default (`YYYY-MM-DD HH:MM:SS`) beim Lesen. Kein naives Datetime
mehr – Python-3.12-Deprecation umgangen.

**UI-State pro Engagement (Sprint 8.2):** Die Tabelle `engagement_state` (Migration
`002`) hält pro Engagement genau eine Zeile mit `active_dataset_id`,
`active_sample_id` und `filter_active`. Der `MainController` schreibt diesen
State nach jeder mutierenden Aktion (Sample-Auswahl, Dataset-Wechsel,
Filter-Toggle, Reset, Sampling, Undo/Redo) via `EngagementStateRepo.upsert`
und liest ihn bei `handle_open_engagement` über `_restore_state()` zurück.
Damit überlebt die zuletzt aktive Stichprobe inkl. Filter-Status den
App-Neustart. Stale IDs (Dataset/Sample inzwischen gelöscht) werden im
Restore stillschweigend übersprungen – kein blockierender Error-Dialog.
Während `_restore_state` läuft, blockiert `_restoring_state` die
`_persist_state`-Aufrufe der orchestrierten `handle_*`-Methoden, damit der
gespeicherte State nicht zwischenüberschrieben wird.

**JSON-Spalten:** `columns_json`, `values_json`, `details_json` sowie `filter_value`,
`visible_rows`, `highlighted_rows` sind alle JSON-Roundtrip,
um Typ-Information (int vs. str vs. nested dict) zu erhalten.
`dataset_rows.values_json` nutzt zusätzlich einen tagged Encoder
(`_values_to_json` / `_values_from_json` in `repositories.py`), damit
`datetime`/`date`/`time`-Werte aus dem Excel-Import roundtrip-sicher
persistiert werden – ohne Tagging würden diese Typen nicht
serialisieren.

**Encoder seit Sprint 10.3: `orjson` (C-basiert)** statt stdlib-json.
3–10× schneller bei Bulk-Inserts, gleicher Tagged-Encoder-Pattern.
`orjson.dumps` liefert `bytes` – die zentralen Helper `_json_dumps` /
`_json_loads` in `repositories.py` konvertieren auf `str`, weil
SQLite-TEXT-Spalten str erwarten (bytes würde als BLOB landen).

**Bulk-Insert-Pragmas:** `bulk_insert_pragmas(conn)` in
`database.py` setzt temporär `synchronous=OFF` und ist als Werkzeug
für isolierte Offline-Bulk-Importe verfügbar. Wird AKTUELL NICHT
aus dem Production-Pfad aufgerufen: bereits ein einfacher Pragma-
Wechsel innerhalb der `DatasetRepo.create`-Transaktion hat mit der
parallel offenen MainController-Repo-Connection (zwei Connections
auf derselben WAL-DB) deadlockt. Den Speedup auf der DB-Seite holen
sich orjson + executemany-Generator (siehe PERFORMANCE.md
Sprint 10.3).

**executemany mit Generator:** `DatasetRepo.create` füttert
`executemany` mit einem Generator, der pro Row einen JSON-String
yieldet. Spart bei großen Datasets den vollen Listcomp-Buffer im
RAM (100k Rows: 55 MB → 0.2 MB Peak).

## Reproduzierbarkeit (kritisch!)

ISAE-3402-Anforderung: Jede gezogene Stichprobe muss zu jedem späteren Zeitpunkt mit
gespeichertem Seed + gespeichertem Datensatz identisch reproduziert werden können.

Konsequenzen für den Code:
- **Niemals** `random` aus stdlib verwenden. Immer `numpy.random.default_rng(seed)`.
- **Niemals** Zeitstempel, UUIDs oder Hash-Ordnung in die Stichprobenauswahl einfließen lassen.
- Sortierung vor RNG-Verbrauch immer deterministisch (z. B. nach `row_id`).
- Tests müssen explizit „same seed → same result" verifizieren.

## Konventionen für Tests

- `tests/unit/` – schnell, deterministisch, keine I/O.
- `tests/integration/` – darf SQLite-Files anlegen (in `tmp_path`), darf openpyxl nutzen.
- `tests/fixtures/` – statische Test-Daten.
- Coverage-Ziel: **>= 90 %** für `core/`, **>= 80 %** restlich.
- Test-Klassen pro Komponente, deutsche Test-Methodennamen erlaubt aber nicht Pflicht.

## Bekannte Stolperfallen

- `pywin32` ist Windows-only → in `pyproject.toml` per `sys_platform`-Marker abgesichert.
  Auf macOS NICHT importieren auf Modul-Ebene; Late-Imports innerhalb von Funktionen.
- PyQt6-Tests benötigen `pytest-qt` und einen X-Server bzw. Offscreen-Plattform
  (`QT_QPA_PLATFORM=offscreen`) – wird in CI gesetzt.
- openpyxl wirft `DeprecationWarning` bei `data_only=True` Read von formelhaltigen Zellen
  → in `pyproject.toml` gefiltert.
- `python-calamine` paniced (`Option::unwrap()` in src/types/sheet.rs)
  bei `iter_rows()` auf einem komplett leeren Sheet (`sheet.start is None`).
  `_parse_excel_sheet` fängt den Fall vor dem `iter_rows`-Call ab.
- `python-calamine` liefert leere Zellen als `""` (empty string), nicht
  `None`. Excel-Zahlen kommen IMMER als `float` (auch ganzzahlige), und
  Datums-Zellen ohne Uhrzeit kommen als `date` statt `datetime`. Der
  `_coerce_value`-Mapper im Importer normalisiert das alles.
- `orjson.dumps` liefert `bytes`, nicht `str`. SQLite-TEXT-Spalten
  brauchen `str` – der `_json_dumps`-Helper konvertiert via
  `.decode("utf-8")`. Wer direkt mit `orjson` arbeitet, muss daran
  denken.
- `journal_mode`-Wechsel auf einer WAL-DB mit parallel offenen
  Connections kann deadlocken (Tooltest Sprint 10.3). Deshalb setzt
  `bulk_insert_pragmas` nur `synchronous=OFF`, kein `journal_mode`.
  Selbst dieser CM ist aktuell nicht aus Production aufgerufen.
- Beim Aufruf von `PRAGMA <name>=<value>` IMMER `.fetchall()`
  hinterherschicken – manche Pragmas (z. B. `journal_mode`) geben
  eine Result-Row zurück. Ohne Fetch bleibt das Cursor-Statement
  offen und ein nachfolgendes `SAVEPOINT` crasht mit "SQL statements
  in progress".

## End-to-End-Smoke-Test

`scripts/demo_full_workflow.py` durchläuft den kompletten Sprint-1-bis-3-
Datenpfad: SQLite anlegen → Engagement → Excel-Import → Simple- und
Stratified-Sampling → Excel-Export → AuditTrail-PDF. Alle Artefakte
landen unter `./demo_output/` (gitignored). Aufruf:

```bash
python scripts/demo_full_workflow.py
```

Wenn UI-Features in Sprint 4+ ergänzt werden, dieses Skript bitte
mitziehen – es ist der schnellste manuelle Smoke-Test über alle Layer.

## Performance-Probe (Sprint 10.1)

`scripts/perf_probe.py` ist ein Standalone-Discovery-Tool für
Performance-Messungen mit großen synthetischen Datasets (10k bis
5M Zeilen, 15 Spalten gemischt int/datetime/float/string, seed-fix
für Reproduzierbarkeit). Misst 8 Phasen pro Größe: Setup, Import,
DB-Speicherung, Tabelle-Anzeige, Sampling (Simple/Cluster/
Stratified), Filter-Toggle, Highlight, Excel-/HTML-Reports,
AuditTrail-PDF. Pro Phase: `time.perf_counter` + tracemalloc
Peak-RAM + optional `psutil.Process().rss`-Delta als Cross-Check.

Output: `PERFORMANCE.md` im Repo-Root mit Mess-Tabellen je Größe
und automatisch detektierten Soft-Target-Verfehlungen (linear auf
die getestete Größe skaliert). Datei wird committet, damit man
die Baseline + Veränderungen über Sprints hinweg sieht.

Aufruf:

```bash
python scripts/perf_probe.py                                  # Default 10k/100k/1M
python scripts/perf_probe.py --sizes 100000 1000000 5000000   # größere Probe
python scripts/perf_probe.py --sizes 100 --quick              # schneller Test
```

Soft-Targets bei 1M Zeilen (Sprint-10.2-Kriterien): Import < 60 s,
DB-Speicherung < 30 s, Tabelle-Anzeige < 5 s, Sampling < 10–15 s,
Filter < 2 s, Excel-Export < 60 s, PDF mit 5k Events < 30 s.
Verfehlungen sind Kandidaten für Sprint 10.2.

Zwischen-Dateien landen unter `tmp/perf/` (gitignored) und werden
nach jedem Größen-Lauf weggeräumt – wichtig bei 5M Zeilen, da
generierte .xlsx + .db zusammen mehrere GB werden.

Der Smoke-Test `tests/integration/test_perf_probe_runs.py` ruft
das Script als Subprozess mit `--sizes 100 --quick --audit-events 10`
auf – läuft in <1 Minute und stellt sicher, dass sich keine
Signaturen unbemerkt verändert haben.

## Wenn du Code schreibst

- Erst `pyproject.toml` und `core/models.py` lesen, bevor du neue Symbole erfindest.
- Bei neuen Dependencies: erst hier kurz begründen, dann zu `pyproject.toml` hinzufügen.
- Bei Sprint-Übergängen: alte Stub-`__init__.py` ersetzen, nicht parallele Module anlegen.
- Bei Reproducibility-relevanten Änderungen: Test schreiben, dann Code.

## Sprint-Abschluss-Protokoll (verbindlich für Claude Code)

Bei jedem neuen Sprint folgt Claude Code diesem festen Workflow:

### 1. Branch anlegen (BEVOR Code geschrieben wird)
```bashgit checkout main
git pull
git checkout -b feat/<sprint-name>

Wenn ein gleichnamiger Branch existiert: `git branch -D feat/<sprint-name>` davor.

### 2. Code schreiben und Tests grün halten
Nach jeder größeren Änderung kurz `pytest` lokal laufen lassen.

### 3. Vor dem Push: alle Checks durchlaufen
```bashpytest
ruff check .
ruff format --check .
mypy src tests

Bei Fehler: **STOPP**, fixen, neu prüfen. Nicht committen mit roten Tests.

### 4. Commit + Push + Auto-Merge (wenn alles grün)
```bashgit add .
git status
git commit -m "Sprint N: <title><bullet-points über Änderungen>Co-Authored-By: Claude Opus 4.7 noreply@anthropic.com"git push -u origin feat/<sprint-name>gh pr create --title "Sprint N: <title>" --body "<beschreibung>"gh pr merge --squash --auto --delete-branchgit checkout main
git pull

`--auto` bedeutet: GitHub merged automatisch sobald alle CI-Checks grün sind. Aktuell sind keine GitHub Actions konfiguriert → merged sofort. Sobald Actions eingerichtet sind (geplant Sprint 7), wartet `--auto` auf grüne Checks.

### 5. Pre-Push-Hook
Automatischer Doppel-Check via `.githooks/pre-push`. Aktiv durch `git config core.hooksPath .githooks`.

### Goldene Regeln
- **Niemals** direkt auf main pushen (außer winzige `chore:`-Commits wie .gitignore-Updates)
- **Immer** auf main zurückwechseln am Sprint-Ende
- **Niemals** einen Sprint als "fertig" melden, wenn der PR noch nicht gemerged ist
- Bei Unsicherheit: lieber stoppen und nachfragen als kaputt mergen
