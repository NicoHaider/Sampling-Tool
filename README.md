# Sampling Tool

Python-Port des BDO-internen, VBA-basierten Excel-Audit-Sampling-Tools (ISAE 3402).
Cross-Platform (macOS/Windows), PyQt6-UI, SQLite-Persistenz, reproduzierbare Stichprobenziehung.

## Status

**Sprint 3 von 7** – I/O-Schicht ✅ **erledigt** (110/110 Tests grün, Ruff + Mypy clean,
Coverage 92 %).

| Sprint | Inhalt                                              | Status      |
|-------:|-----------------------------------------------------|-------------|
| 1      | Projekt-Skelett, Config, Sampling-Core + Tests      | **done**    |
| 2      | SQLite-Persistenz, Audit-Trail, Undo, Migrations    | **done**    |
| 3      | I/O: Excel-/CSV-Import, Excel-Export, AuditTrail-PDF| **done**    |
| 4      | PyQt6-UI: Hauptfenster, Engagement-Verwaltung       | offen       |
| 5      | UI: Sample-Konfigurator, Vorschau, Export-Dialog    | offen       |
| 6      | Reports: HTML (jinja2), erweiterte Excel-Reports    | offen       |
| 7      | Bug-Mail (pywin32/Outlook), PyInstaller-Build       | offen       |

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
