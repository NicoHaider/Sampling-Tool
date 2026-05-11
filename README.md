# Sampling Tool

Python-Port des BDO-internen, VBA-basierten Excel-Audit-Sampling-Tools (ISAE 3402).
Cross-Platform (macOS/Windows), PyQt6-UI, SQLite-Persistenz, reproduzierbare Stichprobenziehung.

## Status

**Sprint 6 von 7** – Dashboard, AuditTrail-View, Multi-Sheet-/HTML-Reports
✅ **erledigt** (Ruff + Mypy clean).

| Sprint | Inhalt                                              | Status      |
|-------:|-----------------------------------------------------|-------------|
| 1      | Projekt-Skelett, Config, Sampling-Core + Tests      | **done**    |
| 2      | SQLite-Persistenz, Audit-Trail, Undo, Migrations    | **done**    |
| 3      | I/O: Excel-/CSV-Import, Excel-Export, AuditTrail-PDF| **done**    |
| 4      | PyQt6-UI: Hauptfenster, Datentabelle, Sidebar       | **done**    |
| 5      | UI: Sampling-Dialog, Export, Undo/Redo, Bug/About   | **done**    |
| 5.5    | UX-Bugfixes + Engagement-Auto-Versionierung         | **done**    |
| 5.6    | Sample-Filter-Default, grüne Markierung, Engagement-Wechsel | **done** |
| 6      | Dashboard, AuditTrail-View, Multi-Sheet-/HTML-Report | **done**   |
| 7      | Bug-Mail (pywin32/Outlook), echtes BDO-Briefpapier, PyInstaller | offen |

### Was Sprint 6 liefert

- **Splitter-Layout** im Workspace: Tabelle oben (60 %), unten ein
  `QTabWidget` mit zwei Tabs (AuditTrail / Dashboard, 40 %).
  Splitter-Größen werden in `QSettings` persistiert.
- **AuditTrail-View** (`ui/widgets/audit_trail_view.py`): sortierbar,
  filterbar nach Aktion / User / Zeitraum + Volltext. Doppelklick auf
  einen Sample-Event markiert das Sample in der Tabelle.
- **Dashboard-View** (`ui/widgets/dashboard_view.py`): sechs Kacheln
  mit Statistiken und Mini-Charts (Sampling-Historie, Methoden-
  Verteilung, Top-Eventtypen). Klick auf eine Stichprobe in
  „Letzte Stichproben" selektiert sie.
- **Multi-Sheet Excel-Report** (`io/multi_report_exporter.py`): vier
  Sheets (Übersicht, AuditTrail, Samples, Statistiken) – komplettes
  Engagement in einer Datei, Chart als Bild eingebettet.
- **HTML-Report** (`io/html_report.py`): selbstständige Datei mit
  Inline-CSS und Base64-Charts, Jinja2-Template.
- **Briefpapier-System** (`io/briefpapier.py`): `BriefpapierConfig` +
  `get_default_briefpapier()` (User-Override → Resource-Fallback);
  echtes BDO-Briefpapier kommt Sprint 7.
- **Empty-States** in Tabelle, AuditTrail-, Dashboard- und
  Sidebar-Listen.
- **About-Dialog** mit Changelog der letzten drei Versionen.
- **matplotlib** als neue Dependency (Agg-Backend, headless).

### Was Sprint 5.5 liefert

- **Toolbar-Buttons** für Undo/Redo (Standard-Icons + deutsche Tooltips)
- **Sample-Highlight bleibt** beim Klick auf das aktive Dataset; bei
  Navigation auf ein fremdes Dataset wird `_active_sample_id` aber **nicht**
  vergessen → Rückkehr zum ursprünglichen Dataset stellt das Highlight wieder her
- **`ENGAGEMENTS_DIR`** = `~/Documents/BDO Audit Sampling/` als Standard-Ablage
  (idempotent beim Start erzeugt). Datei-Dialoge starten dort, neue
  Engagements werden in `{MandantSanitized}/{MandantSanitized}.db` vorgeschlagen
- **Sanitisierung** mit Umlaut-Transliteration: „Müller & Söhne GmbH" →
  `Mueller__Soehne_GmbH` (config.sanitize_for_path)
- **`EngagementVersionManager`**: Snapshot in `{mandant}/archiv/` bei jedem
  Öffnen einer Engagement-DB (Konzept A: Auto-Snapshot pro Session). Datei-
  Pattern: `{stem}_{YYYY-MM-DD}_{HH-MM-SS}_{Auditor}.db`. WAL-/SHM-Dateien
  werden bewusst NICHT mitkopiert. Compliance-Pfad für ISAE-3402-Versions-
  nachweis
- **Aktive Stichprobe sichtbar**: Statusbar zeigt
  `Aktive Stichprobe: #<id> (<Methode>, <gewählt>/<Population>)` und das
  Sidebar-Item bekommt einen „●"-Bullet plus fette Schrift

### Was Sprint 5 liefert

- `ui/dialogs/sampling_dialog.py` – Sampling-Konfigurator
  (Simple/Cluster/Stratified, Filter, Seed-Würfel, Resample-Checkbox)
- `ui/dialogs/export_sample_dialog.py` – Multi-Select-Spaltenauswahl +
  Filename/ID + Zielordner + Live-Vorschau
- `ui/dialogs/bug_report_dialog.py` – mailto-basierter Bug-Report mit
  URL-Encoding und optionaler System-Info
- `ui/dialogs/about_dialog.py` – Version, Beschreibung, Repo-Link
- `ui/dialogs/progress_dialog.py` – Wrapper für `QProgressDialog`
- `ui/controllers/main_controller.py` – Handler für alle Menü-Aktionen,
  Undo/Redo-State, Sampling/Reset/Export-Flow
- `ui/main_window.py` – alle Menü-Hooks verdrahtet, Undo/Redo via
  `QKeySequence.StandardKey.Undo/Redo`
- `ui/widgets/data_table.py` – Datums-Formatierung (Zeit nur bei != 00:00:00)
- `core/undo.py` – neue `peek_undo()`/`peek_redo()`-Methoden für
  saubere UI-Undo-Semantik
- ~40 neue UI-Tests via pytest-qt
- End-to-End-Workflow funktioniert: Engagement → Import → Sampling →
  Export → AuditTrail-PDF

### Was Sprint 4 liefert

- `ui/main_window.py` – `MainWindow` mit State-Maschine Welcome ↔ Workspace
  (`QStackedWidget`), Menü/Toolbar/Splitter/Statusbar, typisierte Signals
- `ui/widgets/data_table.py` – `DatasetTableModel(QAbstractTableModel)` +
  `DataTableView`. Virtuell, sample-highlighting per `BackgroundRole`,
  Filter ohne Proxy
- `ui/widgets/sidebar.py` – `NavigationSidebar` (Engagement/Datasets/Samples)
  mit Klick- und Doppelklick-Signals
- `ui/widgets/welcome.py` – `WelcomeScreen` mit Recent-Engagement-Karten
- `ui/dialogs/new_engagement_dialog.py` – Pflichtfeld-Dialog
  (Auditor/Position/Mandant/Prüfungstyp) + Save-Path-Auswahl
- `ui/recent.py` – `RecentEngagementsStore` mit JSON-Persistenz via
  `platformdirs.user_data_dir()`
- `ui/controllers/main_controller.py` – Glue-Schicht UI ↔ Persistence/IO
- `ui/styles/bdo_light.qss` – Qt-Stylesheet (BDO-Rot/Weiß/Grau)
- `__main__.py` startet die Qt-App
- 47 neue UI-Tests via pytest-qt (offscreen-fähig)

### Was Sprint 3 liefert

- `io/importer.py` – `ExcelImporter` mit Streaming-Read (openpyxl read_only),
  Header-Detection, Encoding-Fallback bei CSV (utf-8/utf-8-sig/latin-1/cp1252),
  Duplikat-Spalten-Suffix, Progress-Callback, Multi-Sheet-Auswahl + `preview()`
- `io/exporter.py` – `ExcelExporter` mit atomarem Write (`.tmp` + `os.replace`),
  Sheet "Sample" (BDO-rotes Header-Styling, Auto-Spaltenbreiten) + Sheet
  "Metadaten" (Engagement, Seed, Methode, Population). Dateiname-Schema:
  `{name}_ID{id}_BDO_sampling_{YYYYMMDD}.xlsx`
- `io/pdf_report.py` – `AuditTrailPDF` (reportlab.platypus): A4-Portrait,
  Engagement-Block, Event-Tabelle mit Korrektur-Highlight, optionales
  Briefpapier (PNG/JPG) als Layer hinter dem Content
- `scripts/demo_full_workflow.py` – End-to-End-Smoke-Test über alle Layer
- 40 neue Integration-Tests (10 Importer, 10 Exporter, 7 PDF, 1 datetime-
  Roundtrip in `DatasetRepo`, 12 Helper-Fixtures)
- Persistenz: `dataset_rows.values_json` nutzt jetzt einen tagged JSON-Encoder
  für `datetime`/`date`/`time` aus dem Excel-Import (roundtrip-sicher)

### Was Sprint 2 liefert

- `persistence/database.py` – `Database` mit WAL/FK-PRAGMAs, `session()`-Transaktionen,
  `savepoint()`-Helper, automatische Migrations + UTC-aware Datetime-Adapter
- `persistence/migrations/001_initial.sql` – 8 Tabellen, FKs, Indizes, Append-Only-Trigger
- `persistence/repositories.py` – `EngagementRepo`, `DatasetRepo`, `SampleRepo`, `AuditRepo`
- `audit/logger.py` – `AuditLogger` mit `log_sampling`/`log_import`/`log_export`/
  `log_undo`/`log_redo`/`log_reset`/`log_correction`
- `core/undo.py` – `UndoManager` mit Stack-Tiefe 20, Redo-Clear-on-Push, persistiert
  über Connection-Wechsel hinweg
- 48 neue Integration-Tests (DB-Lifecycle, Repos, Append-Only-Trigger, Logger, Undo)

### Was Sprint 1 liefert

- Build-Setup: `pyproject.toml` (setuptools src-Layout), Ruff (line=100), Mypy strict, Pytest+Coverage
- VSCode-Workspace (`.vscode/`): Interpreter, Pytest, Ruff-Format-on-Save, Launch-Configs
- `core/models.py` – frozen Dataclasses + StrEnums (`SamplingMethod`, `StratifyMode`)
- `core/rng.py` – `make_rng(seed)` + deterministischer Fisher-Yates-Shuffle
- `core/sampling.py` – `SimpleSampler`, `ClusterSampler`, `StratifiedSampler` (Largest-Remainder),
  Factory `create_sampler`, einheitliche `SamplingError` mit deutschen Messages
- 22 Unit-Tests inkl. „same seed → bit-genau gleiches Ergebnis"
- Stubs für `io/`, `persistence/` (mit `001_initial.sql`), `audit/`, `ui/`

## Voraussetzungen

- Python **3.13+**
- macOS oder Windows 10/11
- Aktives venv (siehe unten)

## Installation

```bash
# venv aktivieren (falls noch nicht aktiv)
source .venv/bin/activate         # macOS/Linux
# .\.venv\Scripts\activate        # Windows

# Editable install inkl. Dev-Tools
pip install -e ".[dev]"
```

## Start

```bash
python -m sampling_tool
# oder via Console-Script:
sampling-tool
```

## Tests

```bash
pytest                            # alle Tests + Coverage
pytest tests/unit                 # nur Unit-Tests
pytest -k "stratified"            # einzelne Tests filtern
pytest --cov-report=html          # HTML-Coverage in ./htmlcov/
```

## End-to-End-Demo (Sprint 1–3)

```bash
python scripts/demo_full_workflow.py
```

Erzeugt unter `./demo_output/` (gitignored):
- `engagement.db` – frische SQLite mit Sprint-2-Schema
- `source_data.xlsx` – generierte Quelldatei (200 Buchungssätze)
- `DemoSimple_ID001_BDO_sampling_<datum>.xlsx`
- `DemoStratified_ID002_BDO_sampling_<datum>.xlsx`
- `audit_trail.pdf`

## Code-Qualität

```bash
ruff check .                      # Lint
ruff format .                     # Format
mypy src tests                    # Typcheck (strict)
```

## Projektstruktur

```
src/sampling_tool/
├── core/           Sampling-Algorithmen, Modelle, RNG
├── io/             Excel-/CSV-Import, Export, PDF   (Sprint 3)
├── persistence/    SQLite + Migrations              (Sprint 2)
├── audit/          Audit-Trail / Event-Log          (Sprint 2)
└── ui/             PyQt6-Frontend                   (Sprint 4–5)

scripts/
└── demo_full_workflow.py   End-to-End-Smoke-Test    (Sprint 3)

tests/
├── unit/           schnelle, isolierte Tests
├── integration/    DB- / Filesystem-Tests           (Sprint 2+)
└── fixtures/       (zur Laufzeit erzeugt in conftest.py)
```

## Lizenz

Proprietär. BDO-intern.
