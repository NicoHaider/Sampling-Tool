# Pass 2: Quality Review

**Datum:** 2026-05-18
**Reviewer:** Claude Code via superpowers/requesting-code-review (kein dedizierter Code-Quality-/Dead-Code-Skill im Plugin verfügbar – wieder der nächst-passende generische Review-Skill als Konventions-Anker; tatsächliche Analyse rein toolbasiert).
**Scope:** `src/sampling_tool/`
**Methodik:** `ruff check --select F401,F811,F841`, `mypy --strict`, AST-Längen-Analyse, grep-Pattern, file-by-file Read der Top-10-Funktionen + aller Duplikat-Verdachtsstellen.
**Verknüpfung zu Pass 1:** [REVIEW/REVIEW_STRUCTURE.md](REVIEW/REVIEW_STRUCTURE.md) (PR #30, Branch `review/structure`, noch nicht gemerged).

## Methodik-Limitierungen

- **vulture** nicht installiert – kein eigenständiger Dead-Code-Lauf für Symbole, die ruff F401 nicht erkennt (z. B. ungenutzte Module-Level-Funktionen mit indirekten String-Referenzen). Per Konvention keine Tool-Installation in einem Review-Pass. Ersatz: gezielter `grep -rn "def NAME"` auf Verdachtsstellen.
- **radon/lizard** nicht installiert – Cyclomatic-Complexity wurde nicht numerisch ausgewertet, nur über Lese-Inspektion der Funktionsstruktur (Verschachtelung von if/elif/Loops).
- **`tests/`-Coverage-Lauf wurde NICHT erneut gefahren** – Pre-Push-Hook deckt das ab, Pass 2 fokussiert auf `src/`. Coverage-Lücken sind Pass-4-Thema.

## Zusammenfassung

Quality-Stand der Codebasis ist insgesamt **hoch** – ruff F401/F811/F841 läuft komplett grün, `mypy --strict` findet 0 Issues in 49 Source-Dateien, jedes Modul hat einen Docstring, jede `@dataclass` ist `frozen=True, slots=True`, und im Reproducibility-relevanten `core/`-Pfad gibt es keine `random`/`time.time`/`uuid`-Aufrufe und keine `for ... in set(...)`-Iteration. **Keine SEV-0-Findings.** Die identifizierten Reibungspunkte sind ausnahmslos Wartbarkeits-Themen: ein silent ImportError-Fallback im PDF-Briefpapier-Pfad (SEV-1), mehrere semantische Duplikate von `_format_dt`/`_ensure_utc`/`_autosize`/`_caption`/`_sanitize` quer durch `io/` und `ui/` (SEV-2 als Aggregat), und eine inkonsistente `json` vs. `orjson`-Nutzung in `core/undo.py`. Insgesamt **0 SEV-0**, **1 SEV-1**, **4 SEV-2** und **4 SEV-3** Findings. **7 von 9 Findings sind `linked_to` einem Pass-1-Strukturfix** – die echte eigenständige Quality-To-do ist klein: Q-001 (Silent-Fail), Q-003 (`_autosize`-Duplikat), Q-005 (`_caption`/`_sanitize`-Duplikat), Q-008 (Magic-Limit-Konstante).

## Severity-Skala

- **SEV-0** — Reproducibility-Verletzung oder unbehandelter Crash-Pfad. Sofort fixen.
- **SEV-1** — Klares Bug-Risiko: bare except, sehr lange Funktion, großes Duplikat, silent failure ohne User-Feedback.
- **SEV-2** — Wartbarkeit deutlich eingeschränkt: mittlere Duplikate (10–30 LoC), Inkonsistenz zwischen Modulen, Concern-Mischung in einer Funktion.
- **SEV-3** — Kosmetik / Hygiene: tote Imports, fehlende Docstrings, Magic Numbers ohne Konstante, Kleinst-Duplikate (< 10 LoC).

## Findings

### SEV-0

Keine SEV-0-Findings. Der Reproducibility-Pfad (`core/sampling.py`, `core/rng.py`) verwendet ausschließlich `numpy.random.default_rng(seed)`, sortiert deterministisch nach `row_id` und enthält weder `random` aus stdlib noch `time.time()` noch UUID-Generierung noch Set-Iteration. Belegt durch:
- `grep -rn "^import random\|^from random" src/sampling_tool/` → leer
- `grep -rn "datetime\.now\|time\.time\|time\.monotonic" src/sampling_tool/core/` → 1 Treffer (`_utcnow` in `core/models.py:22`, nur als Default-Factory für `Engagement.created_at` etc., NICHT im Sampling-RNG-Pfad)
- `grep -rn "for .* in set(" src/sampling_tool/core/ src/sampling_tool/io/exporter.py` → leer
- `grep -rn "import secrets" src/sampling_tool/` → 1 Treffer (`sampling_dialog.py:14` für UI-Seed-Vorbelegung, NICHT für die Sample-Ziehung)

### SEV-1

#### Q-001: Silent ImportError-Fallback im PDF-Briefpapier-Pfad
- **Datei(en):** [src/sampling_tool/io/pdf_report.py](src/sampling_tool/io/pdf_report.py)
- **Zeilen:** [pdf_report.py:378–388](src/sampling_tool/io/pdf_report.py#L378-L388)
- **Befund:** `_draw_background` versucht beim Briefpapier-Suffix `.pdf` die Imports `from pdfrw import PdfReader; pagexobj; makerl`. Schlägt der Import fehl, wird der Branch via `canvas.restoreState(); return` ohne **jegliches Logging oder User-Feedback** verlassen. Der Report wird ohne Briefpapier-Layer erzeugt, der Anwender weiß aber nicht warum. `pdfrw` ist laut [CLAUDE.md → Distribution (Sprint 8)](../CLAUDE.md) Pflicht-Hidden-Import, in der CI/Build-Welt aber kein hartes Pin – jede Bundle-Variante ohne `pdfrw` rendert klammheimlich nackte PDFs. Bei einer ISAE-3402-relevanten Prüfungs-Doku ist "fehlt heimlich" schlechter als "crasht hörbar".
- **Belegt durch:** `grep -rn "except ImportError" src/sampling_tool/io/pdf_report.py` + Lesen [pdf_report.py:378–392](src/sampling_tool/io/pdf_report.py#L378-L392).
- **linked_to:** —
- **Empfehlung:** Mindestens `logger.warning(...)` beim ImportError, idealerweise im Aufrufer ein `briefpapier_failed`-Flag setzen und im Status-Dialog anzeigen. Alternativ den `pdfrw`-Import top-of-module machen, sodass der Fehler beim App-Start sichtbar wird statt erst beim PDF-Build.

### SEV-2

#### Q-002: Briefpapier-Konstruktor-Logik dupliziert in `AuditTrailPDF.__init__`
- **Datei(en):** [src/sampling_tool/io/pdf_report.py](src/sampling_tool/io/pdf_report.py), [src/sampling_tool/io/briefpapier.py](src/sampling_tool/io/briefpapier.py)
- **Zeilen:** [pdf_report.py:85–98](src/sampling_tool/io/pdf_report.py#L85-L98) (Konstruktor isinstance-Switch) vs. [briefpapier.py:75–84](src/sampling_tool/io/briefpapier.py#L75-L84) (`briefpapier_from_path`)
- **Befund:** Der `AuditTrailPDF.__init__` macht eine Path/BriefpapierConfig/None-Fallunterscheidung mit Existenz-Check + Default-Fallback – exakt die Verantwortung von `briefpapier_from_path` und `get_default_briefpapier`. 14 LoC, die durch einen einzigen `briefpapier_from_path(path) or get_default_briefpapier()`-Aufruf ersetzbar wären. Außerdem fehlt im Inline-Code die Suffix-Validierung gegen `_SUFFIX_PRIORITY`, die in `briefpapier_from_path` vorhanden ist – stiller Behavior-Drift.
- **Belegt durch:** Lesen beider Stellen; `grep -rn "BriefpapierConfig\|get_default_briefpapier\|briefpapier_from_path" src/sampling_tool/io/`.
- **linked_to:** F-008 (Pass 1 empfiehlt, Briefpapier-Embedding ganz nach `io/briefpapier.py` zu ziehen)
- **Empfehlung:** Konstruktor reduzieren auf `self.briefpapier_config = briefpapier_from_path(p) if isinstance(briefpapier, Path) else (briefpapier or get_default_briefpapier())`. Reduzierte Severity wegen `linked_to`.

#### Q-003: `_autosize`-Funktion 10 Zeilen-Duplikat in zwei Exportern
- **Datei(en):** [src/sampling_tool/io/exporter.py](src/sampling_tool/io/exporter.py), [src/sampling_tool/io/multi_report_exporter.py](src/sampling_tool/io/multi_report_exporter.py)
- **Zeilen:** [exporter.py:246–255](src/sampling_tool/io/exporter.py#L246-L255), [multi_report_exporter.py:295–303](src/sampling_tool/io/multi_report_exporter.py#L295-L303)
- **Befund:** Beide Module definieren ein eigenes `_autosize(ws, columns)` mit identischer Body-Logik. Einziger Unterschied: `exporter.py` ruft `_display_string(val)`, `multi_report_exporter.py` ruft `_display(val)` – beide Helfer sind ebenfalls quasi-identisch (s. Q-006). Konstanten `_MAX_COLUMN_WIDTH=50` / `_MAX_COL_WIDTH=50` haben verschiedene Namen, gleichen Wert.
- **Belegt durch:** `grep -A10 "^def _autosize" src/sampling_tool/io/exporter.py src/sampling_tool/io/multi_report_exporter.py`.
- **linked_to:** —
- **Empfehlung:** Gemeinsames `io/_excel_helpers.py` (oder `io/openpyxl_utils.py`) mit `autosize(ws, columns, display_fn)` und `MAX_COLUMN_WIDTH`-Konstante. Beide Exporter importieren.

#### Q-004: Datetime-Formatter mehrfach implementiert (`_format_dt`/`_ensure_utc`/`_format_timestamp`)
- **Datei(en):** [src/sampling_tool/io/html_report.py](src/sampling_tool/io/html_report.py), [src/sampling_tool/io/multi_report_exporter.py](src/sampling_tool/io/multi_report_exporter.py), [src/sampling_tool/io/pdf_report.py](src/sampling_tool/io/pdf_report.py), [src/sampling_tool/ui/widgets/audit_trail_view.py](src/sampling_tool/ui/widgets/audit_trail_view.py), [src/sampling_tool/ui/widgets/dashboard_view.py](src/sampling_tool/ui/widgets/dashboard_view.py)
- **Zeilen:** [html_report.py:183–187](src/sampling_tool/io/html_report.py#L183-L187), [multi_report_exporter.py:318–322](src/sampling_tool/io/multi_report_exporter.py#L318-L322), [pdf_report.py:428–429](src/sampling_tool/io/pdf_report.py#L428-L429), [audit_trail_view.py:419–427](src/sampling_tool/ui/widgets/audit_trail_view.py#L419-L427), [dashboard_view.py:365–366](src/sampling_tool/ui/widgets/dashboard_view.py#L365-L366)
- **Befund:** Fünf Module pflegen eigene Mini-Datetime-Helper:
  - `_ensure_utc(ts)`: 2× identisch in `audit_trail_view.py` und `dashboard_view.py` (2 LoC).
  - `_format_dt(value)`: 2× identisch in `html_report.py` und `multi_report_exporter.py` (4 LoC).
  - `_format_timestamp(ts)`: 2× **NICHT identisch** – `audit_trail_view.py` normalisiert via `_ensure_utc(ts).astimezone()`, `pdf_report.py:428` macht `ts.strftime(...)` ohne TZ-Behandlung. Naive Datetimes erzeugen also in PDF und in der UI unterschiedlich formatierte Strings → Silent Behavior-Drift.
- **Belegt durch:** `grep -rn "^def _ensure_utc\|^def _format_dt\|^def _format_timestamp" src/sampling_tool/` + manueller Vergleich.
- **linked_to:** — (Pass 1 hat keine Datetime-Helper-Zentralisierung im Scope; weder F-007 noch F-009 deckt das ab)
- **Empfehlung:** `core/_datetime.py` (oder `core/formatters.py`) mit `ensure_utc`, `format_dt`, `format_timestamp` als kanonische Helfer; alle Konsumenten importieren. Behebt zusätzlich den `_format_timestamp`-Drift.

#### Q-005: `_caption` + `_sanitize` 100%-Duplikate in zwei Dialog-Modulen
- **Datei(en):** [src/sampling_tool/ui/dialogs/_export_base.py](src/sampling_tool/ui/dialogs/_export_base.py), [src/sampling_tool/ui/dialogs/export_sample_dialog.py](src/sampling_tool/ui/dialogs/export_sample_dialog.py)
- **Zeilen:** [_export_base.py:161–172](src/sampling_tool/ui/dialogs/_export_base.py#L161-L172), [export_sample_dialog.py:216–227](src/sampling_tool/ui/dialogs/export_sample_dialog.py#L216-L227)
- **Befund:** `_caption(text)` (4 LoC, identische Implementation inkl. Stylesheet-String) und `_sanitize(token)` (6 LoC, identisch) sind 1:1 dupliziert. `export_sample_dialog.py` importiert bereits `ExportTargetWidget` aus `_export_base.py` – die beiden Helfer müssten dort einfach mit-importiert oder direkt aus `_export_base.py` re-exportiert werden. Außerdem konkurriert `_sanitize` mit `_sanitize_filename_token` in [exporter.py:258](src/sampling_tool/io/exporter.py#L258), das im Kern dieselbe Forbidden-Char-Replacement-Logik macht.
- **Belegt durch:** `grep -A6 "^def _sanitize\|^def _caption" src/sampling_tool/ui/dialogs/_export_base.py src/sampling_tool/ui/dialogs/export_sample_dialog.py`.
- **linked_to:** —
- **Empfehlung:** Beide Helfer aus `_export_base.py` exportieren, `export_sample_dialog.py` lädt sie. Mittelfristig: gemeinsame `core/_paths.py` mit kanonischer `sanitize_filename(token)`-Funktion, damit auch `exporter._sanitize_filename_token` und `config.sanitize_for_path` (verwandter, aber leicht anders gearteter Token-Sanitizer) konsolidiert werden können.

### SEV-3

#### Q-006: `chart_renderer.py` – 6 Render-Funktionen mit nahezu identischen Bodies
- **Datei(en):** [src/sampling_tool/ui/widgets/chart_renderer.py](src/sampling_tool/ui/widgets/chart_renderer.py)
- **Zeilen:** [chart_renderer.py:41–168](src/sampling_tool/ui/widgets/chart_renderer.py#L41-L168)
- **Befund:** `render_bar_chart`/`render_bar_chart_bytes`, `render_line_chart`/`render_line_chart_bytes`, `render_pie_chart`/`render_pie_chart_bytes` – jeweils Paare mit identischem Body bis auf `_figure_to_pixmap` vs. `_figure_to_bytes`. ~10 LoC pro Funktion, insgesamt ~60 LoC redundant.
- **Belegt durch:** Lesen [chart_renderer.py:41–168](src/sampling_tool/ui/widgets/chart_renderer.py#L41-L168).
- **linked_to:** F-005 (Pass 1 empfiehlt Split in `core/charts.py` Bytes-Variante + `ui/widgets/chart_view.py` QPixmap-Wrapper – wenn Pixmap-Pfad nur `QPixmap.fromImage(QImage.fromData(bytes_fn(...)))` ist, fällt die Hälfte automatisch weg)
- **Empfehlung:** Beim Pass-1-Refactor F-005 mit-deduplizieren. Wegen `linked_to` SEV-3.

#### Q-007: `core/undo.py` nutzt `json` (stdlib) statt `orjson` wie der Rest der Persistenz
- **Datei(en):** [src/sampling_tool/core/undo.py](src/sampling_tool/core/undo.py)
- **Zeilen:** [undo.py:15, 58–59, 126–127, 168–169](src/sampling_tool/core/undo.py#L15)
- **Befund:** `core/undo.py` serialisiert `visible_rows`/`highlighted_rows` mit `json.dumps`/`json.loads` aus stdlib. Der Rest des Persistence-Layers (siehe [repositories.py:19–41](src/sampling_tool/persistence/repositories.py#L19-L41)) ist seit Sprint 10.3 auf `orjson` migriert. Inkonsistenz hat zwei Folgen: (1) Performance-Mismatch bei großen Undo-Snapshots, (2) wenn ein Bytes/Str-Bug im orjson-Pfad auftritt, fängt der Undo-Pfad ihn nicht auf, weil er stdlib-JSON spricht. Praktisch klein, weil Undo-Snapshots normalerweise <100 row-ids enthalten.
- **Belegt durch:** `grep -rn "orjson\|^import json\|^from json" src/sampling_tool/core/ src/sampling_tool/persistence/`.
- **linked_to:** F-002 (Pass 1 empfiehlt, `UndoManager` aus `core/` nach `persistence/` zu ziehen – dort würde dann automatisch der `_json_dumps`/`_json_loads`-Helper aus `repositories.py` genutzt)
- **Empfehlung:** Beim F-002-Refactor mit-migrieren. Bis dahin: kein eigenständiger Sprint.

#### Q-008: Magic-Limit `10_000` für AuditEvents 4× hardgecodet im MainController, Repo-Default `100`
- **Datei(en):** [src/sampling_tool/ui/controllers/main_controller.py](src/sampling_tool/ui/controllers/main_controller.py), [src/sampling_tool/persistence/repositories.py](src/sampling_tool/persistence/repositories.py)
- **Zeilen:** [main_controller.py:718, 842, 1016, 1025](src/sampling_tool/ui/controllers/main_controller.py#L718) (jeweils `limit=10_000`); [repositories.py:401](src/sampling_tool/persistence/repositories.py#L401) (`limit: int = 100`)
- **Befund:** `AuditRepo.list_for_engagement` hat einen Default-Limit von 100, der überall im Controller mit `10_000` überschrieben wird. Die Magic-Zahl ist 4× kopiert; ein Engagement mit >10 000 Events würde stillschweigend abgeschnitten werden (PDF-Report, Dashboard, Audit-Trail-View, Audit-Event-Doppelklick). Außerdem ist der Default vom Repo (100) für die UI-Pfade nutzlos – warum dann der Default?
- **Belegt durch:** `grep -rn "limit=" src/sampling_tool/ui/controllers/main_controller.py src/sampling_tool/persistence/repositories.py`.
- **linked_to:** F-001 (im Zuge des MainController-Splits sollten alle Audit-Reads sowieso in einen `AuditTrailService`-Helper wandern – dort kann die Konstante zentral leben)
- **Empfehlung:** Konstante `AUDIT_EVENT_DISPLAY_LIMIT: Final[int] = 10_000` in `config.py` oder `audit/logger.py`. Repo-Default belassen oder anheben.

#### Q-009: Magic Number `300` (ms) in `progress_dialog.py` ohne Konstante
- **Datei(en):** [src/sampling_tool/ui/dialogs/progress_dialog.py](src/sampling_tool/ui/dialogs/progress_dialog.py)
- **Zeilen:** [progress_dialog.py:24](src/sampling_tool/ui/dialogs/progress_dialog.py#L24)
- **Befund:** `self.setMinimumDuration(300)` – 300 ms ist der Standard-Schwellwert, ab dem Qt das Progress-Fenster überhaupt zeigt. Ohne Konstante wirkt es zufällig.
- **Belegt durch:** `grep -rEn "(^|[^a-zA-Z0-9_])300([^a-zA-Z0-9_.])" src/sampling_tool --include="*.py"`.
- **linked_to:** —
- **Empfehlung:** `_MIN_PROGRESS_VISIBILITY_MS: Final[int] = 300` als Modul-Konstante. Kleinst-Fix.

## Quality-Metriken

### Top 10 längste Funktionen (≥ 50 Zeilen)

| LoC | Datei:Zeile                                       | Funktion                  | Finding-ID            |
|----:|---------------------------------------------------|---------------------------|-----------------------|
| 142 | ui/dialogs/sampling_dialog.py:106                 | `_build_ui`               | linked F-010 (UI-Layout, nicht Concern-Mix) |
| 134 | ui/main_window.py:414                             | `_build_menu`             | linked F-006 |
| 102 | ui/dialogs/export_sample_dialog.py:48             | `__init__`                | —, UI-Layout |
|  90 | ui/dialogs/new_engagement_dialog.py:46            | `__init__`                | —, UI-Layout |
|  82 | ui/controllers/main_controller.py:102             | `__init__`                | linked F-001 |
|  75 | ui/dialogs/export_excel_report_dialog.py:43       | `__init__`                | —, UI-Layout |
|  75 | ui/dialogs/export_audit_pdf_dialog.py:124         | `_build_left`             | —, UI-Layout |
|  72 | ui/widgets/audit_trail_view.py:241                | `__init__`                | —, UI-Layout |
|  71 | ui/widgets/welcome.py:69                          | `__init__`                | —, UI-Layout |
|  66 | ui/dialogs/about_dialog.py:96                     | `__init__`                | —, UI-Layout |

Lese-Befund: Alle Top-10-Funktionen über 50 LoC sind entweder UI-Layout-Builder (linear, ein Concern „QLayout zusammensetzen") oder bereits von Pass-1-Findings abgedeckt. **Keine eigenständige Concern-Mischung über 80 LoC, die nicht via `linked_to` mit-gefixt wird.**

Funktionen 50–79 LoC, hier nicht gelistet, aber im Top-23-Block einsehbar: `handle_new_sampling` (62, F-001), `_build_toolbar` (62, F-006), `_build_advanced_tab` (57, UI-Layout), `handle_export_audit_pdf` (57, F-001), `_build_reports_tab` (54, UI-Layout), `load_settings` (54, linear), `MultiSheetReportExporter.export` (54, klar orchestriert), `handle_export_sample` (53, F-001), `__init__` export_audit_pdf_dialog (53, UI-Layout), `_export_base.__init__` (55, UI-Layout), `HtmlReportGenerator.render` (52, klar orchestriert).

### Duplikat-Cluster

| Cluster                                        | Vorkommen | Pfade                                                                                                                              | Finding-ID |
|------------------------------------------------|----------:|-----------------------------------------------------------------------------------------------------------------------------------|------------|
| `_autosize(ws, columns)` 10-LoC-Block          | 2         | io/exporter.py:246, io/multi_report_exporter.py:295                                                                               | Q-003      |
| `_ensure_utc(ts)` 2-LoC-Block                  | 2         | ui/widgets/audit_trail_view.py:425, ui/widgets/dashboard_view.py:365                                                              | Q-004      |
| `_format_dt(value)` 4-LoC-Block                | 2         | io/html_report.py:183, io/multi_report_exporter.py:318                                                                            | Q-004      |
| `_format_timestamp(ts)` (semantisch nicht 1:1) | 2         | io/pdf_report.py:428 (ohne TZ-Normalisierung), ui/widgets/audit_trail_view.py:419 (mit `_ensure_utc`)                              | Q-004      |
| `_caption(text)` 4-LoC-Block                   | 2         | ui/dialogs/_export_base.py:161, ui/dialogs/export_sample_dialog.py:216                                                            | Q-005      |
| `_sanitize(token)` 6-LoC-Block                 | 2         | ui/dialogs/_export_base.py:167, ui/dialogs/export_sample_dialog.py:222                                                            | Q-005      |
| Filename-Sanitizer-Familie                     | 3         | ui/dialogs/_export_base.py:167 (`_sanitize`), io/exporter.py:258 (`_sanitize_filename_token`), config.py:107 (`sanitize_for_path`) | Q-005 (verwandt) |
| Atomic-Write `.tmp → os.replace` (8-LoC-Block) | 2         | io/exporter.py:72–88, io/multi_report_exporter.py:77–110                                                                          | Erwähnt unter Q-003-Empfehlung |
| `chart_renderer` bar/line/pie Pixmap-vs-Bytes  | 6 Funktionen | ui/widgets/chart_renderer.py:41–168                                                                                            | Q-006 (linked F-005) |
| Briefpapier-Konstruktion (isinstance-Switch)   | 2         | io/pdf_report.py:85–98, io/briefpapier.py:75–84                                                                                   | Q-002 (linked F-008) |
| `_display`/`_display_string` Datetime-Stringifier | 3       | io/exporter.py:235, io/multi_report_exporter.py:325, ui/dialogs/sampling_dialog.py:467 (Triviale Variante)                         | Q-004 (verwandt) |

### Bare/Swallowing Exception-Handler

| Datei:Zeile                                     | Pattern                                                                  | Finding-ID |
|-------------------------------------------------|--------------------------------------------------------------------------|------------|
| ui/controllers/main_controller.py:281           | `except Exception: logger.exception(...)` ohne Re-Raise (Snapshot)       | —, per Docstring intendiert ("nicht-kritisch") |
| ui/controllers/main_controller.py:872           | `except OSError: logger.exception(...)` ohne Re-Raise (mkdir Settings)   | —, intendierter Defense-in-Depth |
| ui/controllers/main_controller.py:1145          | `except (FileNotFoundError, ValueError): logger.exception(...)` (Briefpapier-Fallback) | —, intendiert |
| io/pdf_report.py:383                            | `except ImportError: canvas.restoreState(); return` **ohne Logging**     | **Q-001** |

Alle anderen 25 `except`-Klauseln fangen gezielt domain-spezifische Exceptions (`DataImportError`, `SamplingError`, `ExportError`, `csv.Error`, `UnicodeDecodeError`, `sqlite3.OperationalError`, `TemplateNotFound`, `orjson.JSONDecodeError`, etc.) und/oder loggen+rethrowen sauber. Kein `except:`-bare, kein `except Exception: pass`.

### Tote Imports

| Datei | Anzahl F401 | Finding-ID |
|-------|------------:|------------|
| —     | 0           | —          |

`ruff check src/sampling_tool --select F401,F811,F841 --no-fix` meldet **"All checks passed!"**. Es gibt aktuell **keine** toten Imports, doppelten Definitionen oder ungenutzten lokalen Variablen.

### Sonstige Metriken (positive Befunde)

| Metrik                                    | Resultat       |
|-------------------------------------------|----------------|
| `mypy --strict` Issues                    | 0 (49 Dateien) |
| Module ohne Top-Level-Docstring           | 0              |
| `@dataclass` ohne `frozen=True`           | 0 (22/22 frozen) |
| `print(`-Calls in Produktivcode           | 0              |
| `random` / `uuid` / `time.time` in `core/` | 0             |
| `for ... in set(...)` in Sampling-Pfad    | 0              |

## Auto-Fix-Potenzial nach Pass-1-Refactor

Von 9 Findings sind **5 explizit `linked_to`** (Q-002, Q-006, Q-007, Q-008) ein Pass-1-Strukturfix, plus 2 Top-Funktions-Indikatoren (in der Längen-Tabelle linked F-001/F-006/F-010). Bei sauberer Abarbeitung des in Pass 1 vorgeschlagenen Refactor-Sprints (F-001 MainController-Split, F-002 Undo aus core, F-005 chart_renderer-Split, F-008 Briefpapier-Konsolidierung) entfallen:
- **Q-002** automatisch via F-008 (Briefpapier-Resolution wandert nach `briefpapier.py`).
- **Q-006** weitgehend via F-005 (Bytes-Renderer in `core/charts.py`, Pixmap-Wrapper sind dann 1-Zeiler).
- **Q-007** automatisch via F-002 (UndoManager landet in `persistence/`, nutzt dort `_json_dumps` aus `repositories.py`).
- **Q-008** zumindest teilweise via F-001 (Audit-Read-Pfad wandert in `AuditTrailService`).

Übrig bleiben **4 eigenständige Quality-Findings**: Q-001 (Silent-Fail), Q-003 (`_autosize`-Duplikat), Q-004 (Datetime-Helper-Duplikate), Q-005 (`_caption`/`_sanitize`-Duplikate), Q-009 (Magic 300 ms).

## Eigenständige Refactor-Kandidaten (nicht durch Pass-1 mit-gefixt)

Sortiert nach Aufwand-/Nutzen-Verhältnis:

1. **Q-001 (SEV-1)** – Silent ImportError im PDF-Briefpapier-Pfad. Drei Zeilen Fix (`logger.warning`), hoher Nutzen (Auditor weiß, warum sein Bericht ohne Briefpapier kommt).
2. **Q-005 (SEV-2)** – `_caption`/`_sanitize` zentralisieren. 30 Min Arbeit, zwei Module konsolidiert.
3. **Q-004 (SEV-2)** – `core/_datetime.py` mit kanonischen Helpern. Etwas mehr Arbeit (5 Konsumenten patchen), aber behebt zusätzlich den `_format_timestamp`-Behavior-Drift zwischen PDF und UI.
4. **Q-003 (SEV-2)** – `_autosize` + Atomic-Write-Block in gemeinsames `io/_excel_helpers.py`. Lohnt sich besonders, wenn ein weiterer Excel-Exporter geplant ist.
5. **Q-009 (SEV-3)** – Konstante für 300 ms im Progress-Dialog. Kosmetik, kann „mit dem nächsten Anfassen" mit.

## Offene Fragen

1. **`secrets.randbelow` in `sampling_dialog.py:475`**: bewusste Wahl gegen `numpy.random.default_rng().integers(...)` für die UI-Seed-Vorbelegung? `secrets` ist kryptographisch stark und damit definitiv nicht-reproduzierbar – das ist hier korrekt, weil der Würfel-Button explizit einen NEUEN Seed will, aber es weicht stilistisch von der core-Konvention ab. Wenn das bewusste Sicherheits-Wahl ist, im Modul-Docstring vermerken.
2. **`AuditRepo.list_for_engagement(limit=100)` Default**: Wenn alle Aufrufer 10 000 setzen, wäre ein höherer Default + ein `limit=None`-Sentinel für "alle" möglicherweise sinnvoller. Frage: gibt es noch CLI- oder Test-Konsumenten, die den 100-Default brauchen?
3. **`pdfrw`-Verfügbarkeit zur Laufzeit**: Wie wahrscheinlich ist es im PyInstaller-Bundle, dass `pdfrw` fehlt? Wenn die Antwort "nie, weil im Spec-File als Hidden-Import gepinnt" lautet, könnte der ImportError-Branch sogar komplett entfallen statt mit Logging versehen werden.
4. **Pass 1 F-009 Re-Check**: Pass 1 hat `io/importer.py:138-179` als "Excel- und CSV-Pfad in der Klasse" markiert. Beim Re-Read fällt auf: die beiden Pfade sind durch `_import_csv` und `_import_excel` schon klar getrennt (jeweils <20 LoC), die in CLAUDE.md genannte Concern-Mischung liegt eher in den Modul-Helfern unten (`_parse_csv`, `_parse_excel_sheet`, `_coerce_value`). Findings bleibt gültig, aber die Zeilen-Angabe in Pass 1 ist nicht ganz präzise.
5. **`progress_dialog.py` 0% Coverage**: Pre-Push-Hook zeigt `coverage=0%` für [ui/dialogs/progress_dialog.py](src/sampling_tool/ui/dialogs/progress_dialog.py). Das ist Pass-4-Thema (Tests), wird hier nur erwähnt damit es nicht verloren geht.
