# Changelog

Sprint-Chronik des BDO Audit Sampling Tools. Diese Datei hält die Historie fest,
die früher in `CLAUDE.md` mitlief; `CLAUDE.md` selbst trägt seit Sprint 62 nur
noch die langlebige Referenz (Architektur, Invarianten, Befehle, Konventionen).

**Hinweis zur Granularität.** Die ausführlichen Feature-Erzählungen unten decken
Sprints 11–33 ab (der Stand, der in `CLAUDE.md` chronikartig ausformuliert war).
Die Überblickstabelle reicht bis Sprint 53. Die granulare Historie **ab Sprint 37**
liegt im Git-/PR-Log (`git log`, GitHub-PRs) und in den untracked
`SPRINT_<N>_PROMPT.md`-Briefings im Repo-Root – sie wird hier bewusst **nicht**
nacherzählt. Bedeutende, langlebige Entscheidungen sind zusätzlich als ADRs unter
[docs/adr/](docs/adr/) destilliert.

---

## Sprint-Status (Überblick)

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
| 17     | Worker-Architektur (P-008): UI responsiv bei Import/Export | done |
| 18     | Quality-Polish (Q-001 pdfrw-Logging, Q-005 Timestamp-Drift, T-002) | done |
| 19     | P-005 SQL-DISTINCT + F-007 repositories-Split + F-006 main_window-Split | done |
| 20     | Toolbar „Sampling zurücksetzen" (audit-safe In-Memory-Reset) + engeres Toolbar-Spacing | done |
| 21     | Hotfix: Reproduzierbarkeit nach Reset (Sampling-Dialog merkt den zuletzt genutzten Seed) | done |
| 22     | Einzel-Toggles für Advanced-Funktionen im „Ansicht"-Menü (ODER-Logik neben Advanced-Mode, app-weit persistiert) | done |
| 23     | Sampling-Presets (benannte Profile, app-weit via QSettings/JSON, ohne Seed/Daten) | done |
| 24     | Performance-Polish: P-010 AuditTrail-Haystack-Cache (P-001/P-002 aus Pass 3 v2 waren seit Sprint 12.1 gefixt) | done |
| 25     | Bugfix: Audit-Volltextsuche matcht Nicht-Wort-/Nicht-ASCII-Zeichen literal (rohe Nadel statt escaptem Pattern) | done |
| 26     | Import-Performance (Profiling-first): Encode dominiert → orjson-Fast-Path im Tagged-Encoder (`OPT_PASSTHROUGH_DATETIME`), byte-identisch; `scripts/bench_import.py` | done |
| 27     | UI-Cleanup: Toolbar kompakt + QToolBar-Überlauf, Audit-Export-Datumsfilter gefixt (QDateEdit war disabled) + app-weit toggelbar (Default aus), „Engagement"→„Projekt" (nur sichtbarer Text), Seed schreibgeschützt im Haupt-Dialog + nur in Settings änderbar (RNG unverändert) | done |
| 28     | UI-Cleanup B: Vorlagen als Chip-Leiste + „+" im Stichproben-Dialog (Combobox/Buttons raus), Verwaltung (Bearbeiten/Umbenennen/Löschen/Duplizieren) in eigenem `TemplateManagerDialog` via Menü „Stichprobe → Vorlagen verwalten…"; Sprint-23-Mechanik unverändert wiederverwendet | done |
| 29     | Import-Dialoge erweitert (auf Sprint-16-Basis additiv): „keine Kopfzeile" (generische Spalten `Spalte 1, …`) + Header-Detection/Vorschau jetzt auch für CSV; `import_file_configured` akzeptiert `sheet_name=None` (CSV) und `header_row=None` (keine Kopfzeile); saubere Dateien (1 Blatt, Header Zeile 1) bleiben byte-identisch | done |
| 30     | Projekt-Anlage (UI/Bugfix): Prüfungsart im Default-Dateinamen (`<mandant>_<prüfungstyp>.db` via `sanitize_for_path`) + „Überschreiben (mit Backup)"-Option im `DuplicateEngagementDialog` (`OVERWRITE`), die die alte `.db` per `EngagementVersionManager.create_snapshot` ins `archiv/` sichert, bevor ein frisches Projekt angelegt wird; kein Schema-Change | done |
| 31     | Import & Sidebar (UI): „Datensätze aus Ansicht entfernen" (audit-safer In-Memory-/Ansichts-Reset, kein DB-Delete) + Header-Zeile per Klick in der Vorschau-Tabelle wählbar (zusätzlich zum Spin) + optionale ID-Spalte je Dataset (QSettings statt Schema-Feld), app-weiter Toggle `show_sample_id_column`, Anzeige in der Sidebar-Stichprobenliste | done |
| 32     | UI-Umbau: Vorlagen als Dropdown statt Chips im Stichproben-Dialog (Chip-Leiste + „+" raus, `QComboBox` mit Platzhalter „(Vorlage wählen…)" rein; Auswahl ruft `apply_preset`, manuelle Größen-/Methoden-/Filter-Änderung setzt zurück auf den Platzhalter, `_applying_preset`-Guard portiert) + „Neue Vorlage…"-Button im `TemplateManagerDialog` (einziger Anlege-Weg, Default-Preset SIMPLE/`DEFAULT_SAMPLE_SIZE` ohne Filter/Cluster/Schicht); `apply_preset`/`current_settings_as_preset`/`PresetStore`/`SamplingPreset` unverändert → Reproduzierbarkeit/Byte-Identität unberührt | done |
| 33     | AuditTrail-PDF: A4-Querformat (`landscape(A4)`) + neu verteilte Spaltenbreiten (Summe 257mm, großzügige „Datei"-Spalte, kein Überlauf) + zwei UNABHÄNGIGE Export-Dropdowns „BDO-Gesellschaft" + „Standort" (`io/bdo_locations.py`, frei kombinierbar, filtern sich nicht), die den Platzhalter-Adressblock ersetzen (Gesellschaft fett oben + Standort-Adresse rechts; Platzhalter-Briefpapier wird dabei unterdrückt, echtes Briefpapier behält eigenen Kopf); beide Keys app-weit via QSettings (`bdo_company_key`/`bdo_location_key`) gemerkt + in den Einstellungen als Default setzbar; kein Schema-Change, RNG/Excel/HTML unberührt | done |
| 34     | Performance-Pass (profiling-first): Such-Debounce im AuditTrail-Widget (150-ms-QTimer, Proxy bleibt synchron, Treffer-Semantik unverändert), Startup-Import-Budget gemessen (0,3 s – WP2-Lazy-Imports bewusst verworfen, Gate <300 ms/Lib), Snapshot-Messung (200 MB = 0,035 s – bleibt synchron), 1M-Re-Baseline (P-001/P-002-Fixes bestätigt: Tabelle 0,27 s, Simple 4,5 s/46 MB; P-004 geklärt: PDF 4,4 s reproduzierbar, kein Drift, < Target) + WP5-Mikro-Pass (refresh_views-Event-Doppel-Load, distinct-Memo im Sampling-Dialog, Export-Dialog-Bulk-Guard – je Zähler-Beleg); alles in PERFORMANCE.md | done |
| 35     | Advanced-Sampling-Streaming (P-003) + Import-Pipeline (profiling-first): Cluster/Stratified ohne Filter laufen über `sample_pairs(iter_row_field_pairs)` – (row_id, feldwert)-Stream via `json_extract` + `_distinct_decode` statt vollem DatasetRow-Pool; bit-identische Ziehung (58 Unit-Oracles + E2E-Controller-Oracle + 1M-Benchmark-Assert), 1M: Cluster 4,74→1,52 s / Stratified 5,35→2,30 s, RAM 1,12 GB→~155 MB (−86 %); u64-Decode-Fallback + `supports_field_pairs`-Guard (Review-Findings); `sample`/`_select`/`_collect_pool` wörtlich unverändert, Filter/Resampling weiter klassisch. Import-Pipeline: Baseline + cProfile → Coercion-Hebel gemessen (Digit-Guard −4 %) und nach 20-%-Gate bewusst revertiert; bleibend: `TestCoerceStringEquivalenceOracle` (Semantik-Pin mit Fuzz), Doppel-Pass-Hypothese widerlegt, tracemalloc-Einordnung der probe-Zahlen | done |
| 36     | Filter-Operatoren + Match-Preview (WP-A) & Ergänzungs-Ziehung ohne Dubletten (WP-B): Der Spaltenfilter bekommt Operatoren (`=`/`≠` über das Distinct-Dropdown, `>`/`≥`/`<`/`≤` über ein Schwellenwert-Textfeld) via neuem `FilterOperator`-Enum + `SampleConfig.filter_operator`. Eine gemeinsame `matches_filter()`-Funktion (core/sampling.py) ist die EINZIGE Operator-Semantik-Quelle – genutzt von `_collect_pool` (Ziehung) UND dem neuen `_count_filter_matches`-Preview-Provider (workspace_controller.py), sodass Vorschau-Zahl == Zieh-Pool ist (Konsistenz-Oracle in `test_filter_match_count.py`). Filter ab Werk sichtbar (`show_filter_feature=True`, ODER-Logik/Einzel-Toggle unverändert); der Größen-Hint zeigt die tatsächliche Filter-Trefferzahl (Streaming via `iter_row_field_pairs`/`iter_rows`-Fallback, pro Dialog memoisiert, refresh an `editingFinished`/Combo-Change statt pro Tastenanschlag). Persistenz: Migration `003` (`filter_operator TEXT NOT NULL DEFAULT 'eq'`, Bestands-Backfill = altes Gleichheits-Verhalten) + `SampleRepo` (14 Spalten) + `SamplingPreset` (backward-compat: altes JSON ohne Key → `EQ`, analog `stratify_mode`). Reproduzierbarkeit: Default `EQ` bit-identisch zum alten `==`-Pfad (Regressions-Oracle über mehrere Seeds). Eigener Schwellenwert-Parser `_parse_filter_threshold` (`int→float→datetime→Rohstring`; reines Datum → `datetime`-Mitternacht, damit ein Datums-Schwellenwert gegen die datetime-Spalten des Imports matcht statt per `TypeError` nichts zu treffen) – strikt getrennt von `_coerce_value`/`_coerce_string`. WP-B: neue Checkbox „Ergänzen – bereits gezogene Datensätze ausschließen (Nachstichprobe)" (mutual exclusive zur umbenannten „…(einschränken)"-Checkbox, disabled wenn Population komplett gezogen), `SamplingDialogResult.exclude_sample_ids` (reine UI-Anweisung, nicht persistiert) → Controller-`_build_supplement_iterator` zieht aus der Basis MINUS aktiver Stichprobe (dublettenfrei, `population_size = row_count − len(exclude)`), immer über den klassischen `sample()`-Pfad (P-002/P-003-Fastpath für Ergänzung gegated: `unfiltered_full_population and not exclude_sample_ids`), `parent_sample_id` gesetzt; Filter+Ergänzung komponieren (Ausschluss zuerst, Filter danach); kein core/rng- oder Schema-Change über die eine Spalte hinaus. Task 0 verifiziert: die Resample-Checkbox war nie kaputt (nach erster Ziehung korrekt aktiviert – der Guard greift nur ohne aktive Stichprobe). Details: `SPRINT_36_PROMPT.md` | done |
| 53     | pdfrw → pypdf-Konsolidierung (S3.2a / N-011, N-014): PDF-Briefpapier via pypdf-Post-Merge statt pdfrw-Canvas-XObject, `validate_briefpapier` auf pypdf umgestellt, pdfrw restlos entfernt (Code/pyproject/spec/mypy); pypdf dev→runtime (`>=6.13.3`), jinja2 (`>=3.1.6`) und pillow (`>=12.3`) auf Security-Fix-Floors gehoben | done |

> Ausführliche Notizen zu den Sprints 37–61 (u. a. Supply-Chain-CI, atomare
> Migrationen, DB-Preflight, uv-Migration, MainController-Fassade-Abbau,
> Export-Deduplikation, Fakten-/Compliance-Konsolidierung) stehen im Git-/PR-Log.

---

## Detaillierte Sprint-Notizen (Sprints 11–33)

Diese Abschnitte wurden aus `CLAUDE.md` hierher überführt (Sprint 62). Sie
beschreiben die zum jeweiligen Zeitpunkt umgesetzten Features im Detail.

### AuditTrail-PDF: Querformat + BDO-Gesellschaft/Standort-Adressblock (Sprint 33)

Zwei Änderungen am AuditTrail-PDF, **additiv** und ohne Schema-/DB-/Dependency-
Eingriff. RNG-/Sampling-/Import-Pfade sowie `html_report.py`/
`multi_report_exporter.py` (Excel) bleiben unangetastet.

- **A4-Querformat.** `AuditTrailPDF.render` nutzt `pagesize=landscape(A4)`;
  Ränder unverändert (20/20/22/22mm → nutzbare Breite 257mm). `_EVENT_TABLE_
  COL_WIDTHS` neu verteilt (`35/45/35/18/20/32/72`mm, Summe **257mm**) mit
  großzügiger „Datei"-Spalte, damit lange Dateinamen nicht mehr rechts aus der
  Tabelle laufen. `_format_cell`-Wrap-Logik unverändert.
- **BDO-Gesellschaft + Standort als zwei UNABHÄNGIGE Dropdowns.** Erfassung
  **beim Export** (nicht bei Projektanlage), Persistenz **app-weit via QSettings**
  (analog `default_auditor_name`) – kein Schema-Change. Die beiden Dropdowns
  filtern sich **nicht** gegenseitig: **jede Gesellschaft ist mit jedem Standort
  frei kombinierbar** (z. B. „BDO Consulting GmbH" + Linz).
- **Single Source of Truth `io/bdo_locations.py`** (reine Daten + Lookups, keine
  Qt-Imports): frozen `BdoLocation` (`key/display_name/bundesland/street/
  postal_code/city/phone/email`, **kein** `company`-Feld) und frozen
  `BdoCompany` (`key/name`); zwei getrennte `Final`-Tuples `BDO_LOCATIONS`
  (alle 9 Bundesländer) + `BDO_COMPANIES`; Lookups `location_by_key`/
  `company_by_key`/`default_location()` (Wien)/`default_company()`
  (austria_gmbh)/`locations()`/`companies()`. Keine BDO-Adressen woanders
  hartkodieren.
- **Adressblock ersetzt den Platzhalter.** `AuditTrailPDF.__init__` bekommt
  optional `location`/`company` (beide `None` ⇒ **exakt** bisheriges Verhalten,
  backward-compatible). Bei Auswahl rendert `_build_header` einen rechtsbündigen
  Adressblock als eigene Spalte neben dem Titel: **Gesellschaftsname fett oben**,
  darunter Straße, PLZ+Ort, `Tel: <phone>`, optional E-Mail. Regel
  (`_draws_address_block`/`_resolve_background`): Auswahl **und** aktives
  Briefpapier `== config.DEFAULT_BRIEFPAPIER` → Platzhalter **nicht** als
  Hintergrund zeichnen; **echtes** (User-)Briefpapier aktiv → Adressblock
  **nicht** zeichnen (eigener Kopf).
- **Datenfluss.** `ExportAuditPdfDialog` (zwei `QComboBox`, unabhängig voll
  befüllt) → `ExportAuditPdfDialogResult.company_key`/`location_key` →
  `export_controller.handle_export_audit_pdf` löst via `company_by_key`/
  `location_by_key` auf, gibt `company`/`location` an `AuditPdfExportTask` und
  **persistiert beide Keys** (leichtes Feature-Toggle-Muster, **nicht**
  `apply_new_settings`).
- **Settings.** `AppSettings.bdo_company_key`/`bdo_location_key` (Default `""`) –
  in dataclass/`defaults()`/`load_settings`/`save_settings` ergänzt.
  `SettingsDialog` (Reports-Tab) bekommt zwei Standard-Dropdowns.
- **Tests.** `tests/unit/test_bdo_locations.py`, `tests/integration/
  test_pdf_report.py::TestLandscapeLayout`/`::TestBdoAddressBlock`,
  `tests/ui/test_export_audit_pdf_dialog.py::TestBdoCompanyLocationDropdowns`,
  `tests/ui/test_settings_store.py`, `tests/ui/test_settings_dialog.py::
  TestBdoDefaultDropdowns`, `tests/ui/test_main_controller.py`.

### Vorlagen als Dropdown + Verwaltungsfenster (Sprint 28/32)

UI-Neuanordnung der Sprint-23-Vorlagen für eine aufgeräumtere Bedienung. Die
**Persistenz/Logik aus Sprint 23 wird unverändert wiederverwendet** –
`PresetStore`, `apply_preset`, `current_settings_as_preset` bleiben die Single
Source of Truth; keine neue Persistenz, kein Schema-/Migrations-Change, Vorlagen
weiterhin app-weit (QSettings, **nicht** Projekt-DB).

- **Stichproben-Dialog: Dropdown statt Chips/„+" (Sprint 32).** In
  `ui/dialogs/sampling_dialog.py` ist die „Vorlagen"-Gruppe ein kompaktes
  `QComboBox`-Dropdown (`self._preset_combo`): erster, neutraler Eintrag
  `PRESET_PLACEHOLDER` („(Vorlage wählen…)") plus je gespeicherter Vorlage ein
  Eintrag. Die Auswahl (Signal `activated`) ruft das unveränderte
  `apply_preset(...)` (setzt nur Parameter, **zieht nicht**, lässt den Seed in
  Ruhe). Eine manuelle Änderung an Größe/Methode/Filter setzt zurück auf den
  Platzhalter (`_reset_combo_selection`, `_applying_preset`-Guard). **Sprint 32
  hat den `„+"`-Speichern-Flow vollständig entfernt**; Anlegen passiert nur noch
  im Verwaltungsfenster. (Sprint 28 nutzte zuvor eine Chip-Leiste plus „+".)
- **Eigenes Verwaltungsfenster + Menüpunkt.** Anlegen (Sprint 32)/Bearbeiten/
  Umbenennen/Löschen/Duplizieren leben in `ui/dialogs/template_manager_dialog.py`
  (`TemplateManagerDialog`): Liste links, Bearbeiten-Formular rechts, alle
  Schreibvorgänge über `PresetStore`. **Sprint 32 – „Neue Vorlage…"-Button** ist
  der **einzige** Weg, eine (insb. die erste) Vorlage anzulegen. Erreichbar über
  **„Vorlagen verwalten…" im Menü „Stichprobe"** (immer aktiv, app-weit).
- **Einstiegspunkt / Passwort später.** Genau ein Einstiegspunkt:
  `HelpController.handle_manage_templates`. Es implementiert **kein** Passwort –
  das Gate kann später davor ergänzt werden.
- **Bearbeiten ohne geladene Population (bewusste Einschränkung).** Editierbar
  sind die populations-unabhängigen Felder (Methode, Größe, Cluster-/Schicht-
  Feldname als Text, Schicht-Verteilung). Der konkrete Filter-Wert lässt sich
  ohne Population nicht typ-sicher wählen; er wird nur angezeigt und beim
  Speichern unverändert mitgereicht.
- **Tests.** `tests/ui/test_template_dropdown.py`,
  `tests/ui/test_template_manager_dialog.py`, `tests/ui/test_manage_templates.py`.

### Import & Sidebar: Ansicht leeren, Header-Klick, optionale ID-Spalte (Sprint 31)

Drei unabhängige UI-Features, alle **additiv** und ohne Schema-/DB-Eingriff.

- **Teil A – „Datensätze aus Ansicht entfernen" (`Datei`-Menü).** Bewusst ein
  reiner *Ansichts*-Reset, **kein** Lösch-Feature.
  `WorkspaceController.handle_clear_loaded_datasets` ruft
  `WorkspaceSession.clear_view()`: leert aktive Dataset-/Sample-Auswahl,
  Highlight, Sample-Filter, Datentabelle und Sidebar-Listen – die Projekt-DB
  bleibt **unangetastet**. **Warum kein hartes DB-Delete?** Identisch zum
  Sampling-Reset (Sprint 20): der Append-only-Audit-Trail macht selektives
  Löschen ohne Schema-Änderung unmöglich und würde den ISAE-3402-Trail
  verletzen.
- **Teil B – Header-Zeile per Klick wählbar.** Zusätzlich zum `_header_spin`
  setzt jetzt auch ein Klick auf eine Vorschau-Zelle die Kopfzeile. **Single
  Source of Truth bleibt der Spin** – der Klick ruft nur `_select_header_row`.
- **Teil C – optionale ID-Spalte je Dataset → Sidebar-Stichprobenliste.** Beim
  Import wählt der User optional eine Spalte als ID-Spalte
  (`ui/dialogs/id_column_dialog.py`). Die Wahl wird **app-weit pro Dataset in
  `QSettings`** gemerkt (`ui/dataset_id_store.py`), **nicht** in der Projekt-DB.
  **Warum QSettings statt Schema-Feld:** Die ID-Spalte ist ein reines
  pro-Dataset-*Anzeige*-Metadatum; sie berührt weder Reproduzierbarkeit noch den
  Audit-Trail (Import-Byte-Identität bleibt gewahrt).
- **Teil C2 – app-weiter Toggle `AppSettings.show_sample_id_column`** (Default
  `True`), schaltbar im Settings-Dialog.
- **Anzeige (Sidebar).** `NavigationSidebar.set_samples(...)` rückwärtskompatibel
  via Default-Args erweitert. Ist der Toggle an UND eine ID-Spalte gesetzt UND
  liegen Werte vor, wird das Label ergänzt (erste `MAX_IDS_IN_LABEL=3`). Die
  ID-Werte holt `WorkspaceSession._resolve_sample_ids` über `get_rows_by_ids` –
  Streaming-konform, **kein** `get_all_rows`.

### Projekt-Anlage: Prüfungsart im Dateinamen + Überschreiben-mit-Backup (Sprint 30)

Zwei UI-/Workflow-Änderungen an der Engagement-Anlage, **kein** Schema-Change
(die Prüfungsart liegt bereits als `Engagement.audit_type` vor).

- **Prüfungsart im Default-Dateinamen.** `NewEngagementDialog._default_target_name`
  baut den vorgeschlagenen Namen als `<sanitize(mandant)>_<sanitize(prüfungstyp)>.db`.
  Es wird **dasselbe** `sanitize_for_path` wie für den Mandanten wiederverwendet.
  Nur der *Vorschlag* ändert sich; der User kann frei umbenennen.
- **„Überschreiben (mit Backup)" im Duplikat-Dialog.** Vierter Enum-Wert
  `DuplicateEngagementChoice.OVERWRITE` + Button. Button-Reihenfolge:
  Abbrechen, Anderen Namen wählen, Überschreiben (mit Backup), Bestehendes
  öffnen (bleibt Default).
- **Backup ist Pflicht, Datenverlust die rote Linie.** `_overwrite_with_backup`
  sichert die bestehende `.db` **zuerst** über die unveränderte
  `EngagementVersionManager.create_snapshot`-Mechanik ins `archiv/`. Erst
  **nach** erfolgreichem Backup wird die alte `.db` (samt `-wal`/`-shm`-Sidecars)
  entfernt und ein frisches Projekt angelegt. Schlägt das Backup fehl, bleibt
  die alte DB unangetastet.
- **Tests.** `tests/ui/test_new_engagement_dialog.py::TestDefaultFilenameWithAuditType`,
  `tests/ui/test_duplicate_engagement_dialog.py::TestOverwriteChoice`,
  `tests/ui/test_main_controller.py::TestOverwriteWithBackup`.

### Import-Dialoge: „keine Kopfzeile" + CSV (Sprint 29)

Zwei Komfort-Features aus dem alten VBA-Tool – **additiv auf der
Sprint-16-Infrastruktur** (kombinierter `ImportOptionsDialog` +
`list_sheets`/`preview_sheet`/`import_file_configured`), nicht neu gebaut.

- **„keine Kopfzeile".** Eine Checkbox im `ImportOptionsDialog`.
  `ImportOptionsResult.header_row` wird dann `None`;
  `ExcelImporter.import_file_configured(..., header_row=None)` vergibt
  generische Spaltennamen `Spalte 1, Spalte 2, …` und behandelt **alle**
  (nicht-leeren) Zeilen als Daten.
- **CSV-Header-Detection.** `import_file_configured` verzweigt nach Suffix. Neu:
  `preview_csv()` und `_csv_reader_rows` als gemeinsame Roh-Parse-Basis. Der
  Dialog erkennt CSV (`self._is_csv`), blendet das Sheet-Dropdown aus und
  liefert `sheet_name=None`.
- **Dialog-Entscheidung zentralisiert.** `ExcelImporter.requires_options_dialog(path)`
  kapselt „braucht es einen Dialog?" (Excel: >1 Blatt ODER `confidence != "high"`;
  CSV: `confidence != "high"`).
- **Verbesserte Auto-Erkennung (nur Vorschau).** `_detect_header_with_confidence`
  überspringt spärliche Titel-/Metazeilen. Betrifft **nur** die Dialog-Vorschau;
  der byte-identische Auto-Import bleibt unberührt.

**Rote Linie:** Coercion (`_coerce_*`, Sprint 26) unangetastet; der saubere
Default-Pfad (1 Blatt, Kopfzeile Zeile 1) ist byte-identisch (Oracle:
`tests/integration/test_sprint29_import_dialogs.py::TestImportUnchangedForCleanFiles`).

### Sampling-Presets (Sprint 23)

Wiederkehrende Sampling-Konfigurationen lassen sich als **benannte Profile**
speichern und app-weit anwenden. Baut auf den Einzel-Toggles (Sprint 22) auf.

- **Was ein Preset enthält – und was nicht.** Ein `SamplingPreset`
  (`core/presets.py`, frozen) bündelt Methode, Größe, Filter (Feld + Wert),
  Cluster-Feld, Schicht-Feld + -Verteilung. Es enthält **NICHT** den **Seed**
  (ziehungs-spezifisch), **keine Population/Daten** und **keine Ergebnisse**. Ein
  Preset ist ein `SampleConfig` minus Seed (plus Name).
- **Layer-Trennung.** `core/presets.py` – reines Domain-Modell + **stdlib-JSON**-
  Serialisierung (Qt-frei, SQL-frei). `ui/preset_store.py` – `PresetStore` (die
  *eine* Verwaltungs-Stelle), persistiert app-weit via `QSettings` unter
  `presets/json`, **nicht** in die Engagement-DB, **kein** Schema-Change.
- **„Settings-Owner" ist der Dialog.** `current_settings_as_preset(name)` friert
  den Widget-Stand ein; `apply_preset(preset)` spielt es zurück – setzt **nur
  Parameter**, **zieht nicht** und **fasst den Seed nicht an** (ISAE-3402). Ein
  Filter wird übersprungen und in `AppliedPresetResult.skipped_filters` gemeldet,
  wenn seine Spalte/sein Wert in der Population fehlt (kein stiller Fehlschlag,
  kein Crash).
- **Reproduzierbarkeit.** Ein angewendetes Preset zieht bit-identisch zur
  manuellen Einstellung. Getestet über `tests/unit/test_presets.py` und
  `tests/ui/test_sampling_presets.py`.

### Einzel-Feature-Toggles + „Ansicht"-Menü (Sprint 22)

Advanced Mode bleibt der Master-Schalter. Zusätzlich lässt sich seit Sprint 22
jede Funktion **einzeln** über das neue Menü **„Ansicht"** schalten.

- **Welche Funktionen?** Filter (Spaltenfilter), Cluster-Sampling, Geschichtete
  Stichprobe – alle im *modalen* `SamplingDialog`.
- **Single Source of Truth (ODER-Logik).** Pro Funktion gilt
  `feature_visible(f) = advanced_mode OR einzel_toggle(f)`. Diese Verodung lebt
  an **genau einer** Stelle: `AppSettings.resolve_feature_visible(feature)`.
  Die app-weiten Toggles sind drei `AppSettings`-Felder
  (`show_filter_feature`/`show_cluster_feature`/`show_stratified_feature`,
  Default `False`, via `QSettings`).
- **Dialog kennt kein advanced_mode mehr.** Der Controller löst via
  `settings.resolve_sampling_features()` ein frozen `SamplingFeatures`-Objekt auf
  und reicht es an die Sampling-Factory. Der frühere `advanced_mode: bool`-
  Parameter ist dadurch ersetzt.
- **„Ansicht"-Menü** (`ui/_window_menu.py`): drei checkbare Feature-Actions + zwei
  checkbare Panel-Actions (Dashboard/Audit-Trail). Die Häkchen spiegeln die
  **rohen** Einzel-Toggles.
- **Reproduzierbarkeit.** Das bloße Sichtbar-Schalten ändert die Stichprobe
  nicht. Getestet via `tests/ui/test_feature_toggles.py::TestToggleSamplingNeutrality`.

### Seed-Memory / Reproduzierbarkeit nach Reset (Sprint 21, Hotfix)

**Symptom:** Stichprobe ziehen → „Sampling zurücksetzen" → erneut ziehen → andere
Stichprobe, obwohl Seed + Größe unverändert waren (ISAE-3402-Verletzung).

**Root Cause (nicht der RNG):** Der Sampling-Core ist deterministisch. Der Fehler
saß im UI: `SamplingDialog._build_ui` würfelte bei **jedem** Öffnen einen neuen
Zufalls-Seed und nichts merkte sich den zuletzt genutzten.

**Warum der Sprint-20-Test grün war:** Er injizierte ein `_StubSamplingDialog` mit
hartkodiertem `seed=123` – die reale Seed-Quelle wurde nie ausgeführt.

**Fix (minimal, additiv):** `WorkspaceSession.last_seed` merkt den zuletzt
gezogenen Seed; `WorkspaceController.handle_new_sampling` reicht ihn via
`SamplingDialog.set_initial_seed(...)` als Default in den nächsten Dialog.
`last_seed` überlebt `reset_sampling()` bewusst und wird nur beim
Engagement-Wechsel geleert. Getestet über den **echten** Controller-/Dialog-Pfad
in `tests/ui/test_main_controller.py::TestReproducibilityViaController`.

### Sampling-Reset (Sprint 20)

Zwei Reset-Pfade mit bewusst unterschiedlicher Semantik (beide audit-safe – kein
DB-Delete, Append-only-Trail bleibt intakt):

- **Menü „Stichprobe → Auswahl zurücksetzen"** (`handle_reset`): respektiert
  `settings.reset_keeps_filter`, leert Highlight (+ ggf. Filter).
- **Toolbar „Sampling zurücksetzen"** (`handle_reset_sampling`): vollständiger
  In-Memory-Reset via `WorkspaceSession.reset_sampling()` – leert ausschließlich
  aktive Stichprobe, Highlight und Sample-Filter; Population und Parameter
  bleiben.

**Warum kein hartes DB-Delete der Stichprobe?** `audit_events.sample_id` ist
`REFERENCES samples(id) ON DELETE SET NULL`; mit `foreign_keys=ON` feuert diese
SET-NULL-Aktion den `audit_events_no_update`-Trigger (append-only) und bricht den
Delete mit `IntegrityError` ab. Daher In-Memory-Reset; eine identische Re-Ziehung
mit gleichem Seed rekonstruiert die Stichprobe bit-genau (`TestResetReproducibility`).

### Worker-Architektur (Sprint 17 / P-008)

Long-Running-Operations (Excel-Import, DB-Persist, AuditTrail-PDF,
Multi-Sheet-Excel-Report, HTML-Report) laufen seit Sprint 17 in einem
Hintergrund-Thread. Die UI bleibt responsiv und der „Abbrechen"-Button ist
funktional.

**Bausteine:**
- `core/cancellation.py` (Qt-frei) – `CancellationToken` + `OperationCancelled`
  (Kontroll-Fluss-Exception, kein Fehler).
- `ui/workers/task_worker.py` – `WorkerTask`-Protocol + `ProgressReporter` +
  `TaskWorker(QThread)` mit Signals `progress`/`finished_with_result`/`failed`/
  `cancelled`.
- `ui/workers/tasks.py` – 5 konkrete Tasks: `ExcelImportTask`,
  `SampleExportTask`, `AuditPdfExportTask`, `ExcelReportTask`, `HtmlReportTask`.
- `ui/dialogs/progress_dialog.py` – `TaskProgressDialog` ist der
  Worker-Coordinator: `run_task(task)` startet den Worker, blockt per `exec()`
  bis fertig (Event-Loop läuft weiter), liefert das Resultat oder `None` bei
  Cancel.

**Connection-Thread-Safety:** Tasks, die in die SQLite-DB schreiben, öffnen eine
eigene `Database(db_path)`-Instanz im Worker-Thread. WAL-Mode erlaubt parallele
Reader im Main-Thread, `BEGIN IMMEDIATE` serialisiert Writer.

**Reproducibility:** Bit-getestet via `tests/ui/test_tasks.py::TestReproducibility`.
Sampler bleiben im Main-Thread und sind unverändert.

### Streaming-Architektur (Sprint 11.x)

Zentraler Designgrundsatz nach Sprint 11.x: **das Tool hält Dataset-Rows nicht im
RAM**, sondern in SQLite. Alle Code-Pfade arbeiten mit Generatoren /
Range-Queries / Bulk-ID-Lookups, nicht mit voll-materialisierten Listen.

**Was lebt wo:**
- `Dataset` (frozen Dataclass): Metadaten + `row_count`, KEINE rows.
- Rows: in `dataset_rows`-Tabelle, abgerufen via `DatasetRepo`.
- `DatasetTableModel` (UI): FIFO-Cache mit 1000 Rows, Bulk-Load 250 pro
  Cache-Miss. RAM konstant ~3 MB.
- `ExcelImporter`: liefert `ImportResult.rows` als einmal-konsumierbaren
  `Iterator[DatasetRow]`.
- `BaseSampler.sample(rows, population_size)`: Single-Pass-Filter über Iterator.
- `ExcelExporter.export_sample(...)`: holt nur die Sample-Rows on-demand via
  `get_rows_by_ids`.

**Repo-API für Row-Zugriffe:** `create` (Generator), `get_by_id` (nur Metadaten),
`get_row`, `get_rows_in_range` (half-open, für UI-Pagination), `iter_rows`
(Streaming-Generator, sortiert), `iter_row_ids` (Light-Streaming),
`iter_row_field_pairs` (Streaming über `(row_index, decodierter Spaltenwert)` via
`json_extract` + `_distinct_decode`, Sprint 35 / P-003), `get_rows_by_ids`
(Bulk-Lookup, behält Reihenfolge, chunkt bei >900 Parametern), `get_all_rows`
(**Tests-Convenience, in Production nicht mehr verwendet**), `distinct_values`
(distinkte Nicht-None-Werte via `GROUP BY` + `MIN(row_index)`-Tie-Break).

**Reproduzierbarkeit bleibt gewahrt:** `row_id` ist die stabile Sortier-Ordnung,
`iter_rows` sortiert per `ORDER BY row_index`, Sampler nutzen row_id-basierte
Indices. Generator-Konsum ist deterministisch.
