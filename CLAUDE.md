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
| 6      | Reports: HTML (jinja2), erweiterte Excel-Reports    | offen       |
| 7      | Bug-Mail (pywin32/Outlook), PyInstaller-Build       | offen       |

Bei Sprint-Wechsel: diese Tabelle hier UND im README.md aktualisieren.

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
  - `models.py` – frozen Dataclasses (Engagement, Dataset, SampleConfig, …)
  - `rng.py` – `make_rng(seed)` + `fisher_yates_shuffle` über `numpy.random.default_rng`
  - `sampling.py` – `BaseSampler` + Simple/Cluster/Stratified + `create_sampler`-Factory
- **`io/`** – Excel-/CSV-Import, Excel-Export, PDF-Report.
  - `importer.py` – `ExcelImporter` (read-only-Streaming via openpyxl,
    Header-Detection, Encoding-Fallback bei CSV, Progress-Callback).
    Liefert `ImportResult(dataset, skipped_rows, warnings)`. Native Python-
    Typen (kein numpy/pandas-Output).
  - `exporter.py` – `ExcelExporter`. Atomare Writes (`.tmp` → `os.replace`),
    Sheet "Sample" (BDO-rote Header) + Sheet "Metadaten" (Engagement, Seed,
    Methode). Dateiname-Schema:
    `{name}_ID{id}_BDO_sampling_{YYYYMMDD}.xlsx`.
  - `pdf_report.py` – `AuditTrailPDF` via `reportlab.platypus`.
    A4 Portrait, Engagement-Block oben, Tabelle aller Events mit
    Korrektur-Highlight, Footer mit Seitenzahl + Zeitstempel. Optionales
    Briefpapier (PNG/JPG) wird via `onPage`-Hook hinter den Content gelegt.
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
    Welcome ↔ Workspace. Menü, Toolbar, Splitter (Sidebar+Tabelle),
    Statusbar. Sendet typisierte Signals; *kein* DB-Zugriff hier.
  - `controllers/main_controller.py` – Glue-Schicht UI ↔ Persistence/IO.
    Hält `Database`-Instanz, das aktuelle Engagement und einen
    `UndoManager`. Übersetzt UI-Signals in Repo-Calls und orchestriert
    Sampling/Reset/Undo/Redo/Export. Undo-Konvention: nach jeder
    mutierenden Aktion wird der NEUE State auf den Undo-Stack
    gelegt; bei `handle_undo` wird der Top entfernt und der
    `peek_undo`-State angewandt (leerer State, wenn der Stack
    nach dem Pop leer ist).
  - `widgets/data_table.py` – `DatasetTableModel(QAbstractTableModel)` +
    `DataTableView`. Virtuelles Model (kein QStandardItemModel) –
    100k+ Zeilen scrollen flüssig. Sample-Highlighting per
    `BackgroundRole`, Filter ohne Proxy via `_visible_indices`.
  - `widgets/sidebar.py` – `NavigationSidebar` mit drei Sektionen
    (Engagement-Block, Datasets-Liste, Samples-Liste).
  - `widgets/welcome.py` – `WelcomeScreen` (Recent-Engagement-Karten +
    Buttons) wird angezeigt, wenn keine `.db` geladen ist.
  - `dialogs/new_engagement_dialog.py` – Modal-Dialog für die
    Pflichtfelder Auditor/Position/Mandant/Prüfungstyp +
    Save-Path-Auswahl.
  - `dialogs/sampling_dialog.py` – Sampling-Konfigurator (Simple/Cluster/
    Stratified, Filter, Seed mit Würfel, Resample-Checkbox). Liefert
    `SamplingDialogResult` mit `SampleConfig` + `from_sample_only`-Flag.
    Das Flag ist **nicht** persistiert – der Controller filtert das
    Dataset zur Laufzeit auf die Vorsample-Auswahl.
  - `dialogs/export_sample_dialog.py` – Spaltenauswahl (Checkboxen) +
    Filename/ID + Zielordner. Vorschau-Label live mit
    `{name}_ID{id}_BDO_sampling_{YYYYMMDD}.xlsx`.
  - `dialogs/bug_report_dialog.py` – 3 Freitextfelder + System-Info-
    Checkbox. Konstruiert `mailto:`-URL und öffnet sie via
    `QDesktopServices`. Auf Windows wird das in Sprint 7 von
    `pywin32`/Outlook abgelöst.
  - `dialogs/about_dialog.py` – statischer About-Dialog (Version,
    Beschreibung, Repo-Link).
  - `dialogs/progress_dialog.py` – `TaskProgressDialog` wrapt
    `QProgressDialog` mit Callback-Adapter im
    `ExcelImporter`-Signatur-Format.
  - `recent.py` – `RecentEngagementsStore` mit JSON-Persistenz unter
    `platformdirs.user_data_dir('AuditSamplingTool', 'BDO')`.
    Defekte Pfade werden beim `list()` gefiltert; `prune_missing()`
    räumt sie persistent weg.

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

- Excel-Importer (Sprint 3) konstruiert ein `Dataset` (engagement_id setzen!) und
  ruft `DatasetRepo.create(dataset)`. Atomar – schlägt das fehl, bleibt nichts
  zurück. Danach `AuditLogger.log_import(dataset)`.
- UI-Controller (Sprint 4+) bekommt `Database`-Instanz, baut bei Bedarf eigene
  Repo-Instanzen pro Operation. Connection-Lebensdauer = App-Sitzung.
- `UndoManager(db, engagement_id)` ist persistiert (überlebt Connection-Wechsel).
  `MAX_DEPTH = 20`, neuer `push` löscht den Redo-Stack (Standard-Editor-Verhalten).

**Datetime-Handling:** Eigene Adapter/Konverter in `database.py` registrieren
UTC-aware ISO-8601 für `INSERT` und parsen sowohl unser Format als auch SQLites
`CURRENT_TIMESTAMP`-Default (`YYYY-MM-DD HH:MM:SS`) beim Lesen. Kein naives Datetime
mehr – Python-3.12-Deprecation umgangen.

**JSON-Spalten:** `columns_json`, `values_json`, `details_json` sowie `filter_value`,
`visible_rows`, `highlighted_rows` sind alle `json.dumps`-/`json.loads`-Roundtrip,
um Typ-Information (int vs. str vs. nested dict) zu erhalten.
`dataset_rows.values_json` nutzt zusätzlich einen tagged Encoder
(`_values_to_json` / `_values_from_json` in `repositories.py`), damit
`datetime`/`date`/`time`-Werte aus dem Excel-Import roundtrip-sicher
persistiert werden – das normale `json.dumps` würde sie nicht
serialisieren können.

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
