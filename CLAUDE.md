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
| 3      | I/O: Excel-Import (openpyxl), CSV, Validierung      | offen       |
| 4      | PyQt6-UI: Hauptfenster, Engagement-Verwaltung       | offen       |
| 5      | UI: Sample-Konfigurator, Vorschau, Export-Dialog    | offen       |
| 6      | Reports: PDF (reportlab), HTML (jinja2), Excel-Out  | offen       |
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
- **`io/`** *(Sprint 3)* – Excel-/CSV-Import, Export. Adapter-Pattern.
- **`persistence/`** – SQLite über sqlite3 (kein ORM-Overhead).
  - `database.py` – `Database`-Wrapper mit WAL+FK-PRAGMAs, `session()`-Transaktionen,
    `savepoint()`-Helper für nestbare Repo-Transaktionen, automatische Migrations.
  - `repositories.py` – `EngagementRepo`, `DatasetRepo`, `SampleRepo`, `AuditRepo`.
    Stateless, nehmen `sqlite3.Connection` im Konstruktor, geben Domain-Modelle zurück.
  - `migrations/NNN_*.sql` – nummerierte SQL-Files; `001_initial.sql` ist das
    komplette Sprint-2-Schema. Migrations-Runner liest `schema_version` und führt
    nur ausstehende Versionen aus.
- **`audit/`** – Append-only Event-Log via Trigger.
  - `logger.py` – `AuditLogger` ist der High-Level-Eingang: `log_sampling`,
    `log_import`, `log_export`, `log_undo`, `log_redo`, `log_reset`, `log_correction`.
  - Korrekturen werden als neue Events mit `event_type='correction'` und
    `corrects_event_id`-FK auf den Original-Event gespeichert (kein UPDATE/DELETE).
- **`ui/`** *(Sprint 4+)* – PyQt6. Strikt MVC: Widgets dumm, Controllers in
  `ui/controllers/`. Stylesheet (BDO-CI) unter `ui/styles/*.qss`.

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
   DSGVO-konform. Es gibt keinen "globalen" Pool.
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

## Wenn du Code schreibst

- Erst `pyproject.toml` und `core/models.py` lesen, bevor du neue Symbole erfindest.
- Bei neuen Dependencies: erst hier kurz begründen, dann zu `pyproject.toml` hinzufügen.
- Bei Sprint-Übergängen: alte Stub-`__init__.py` ersetzen, nicht parallele Module anlegen.
- Bei Reproducibility-relevanten Änderungen: Test schreiben, dann Code.
