# Pass 1: Structure Review

**Datum:** 2026-05-18
**Reviewer:** Claude Code via superpowers/requesting-code-review (kein dedizierter Architektur-Skill im Plugin verfügbar – nächst-passender Review-Skill als Konventions-Anker gewählt; dieser Pass macht reine Bestandsaufnahme statt Subagent-Dispatch).
**Scope:** `src/sampling_tool/` (ohne `tests/`, `scripts/`, `docs/`, `resources/`, `pyproject.toml`)
**Methodik:** statische Analyse via `wc`, `grep`, manuelles file-by-file Lesen. Kein Test-Run, kein Lint/Type-Check, keine neuen Dependencies.

## Zusammenfassung

Die Codebasis umfasst 47 Python-Dateien (`src/sampling_tool/`) mit insgesamt **10 765 LoC**. Die Layer-Trennung aus [CLAUDE.md](../CLAUDE.md) ist im großen Ganzen umgesetzt – fast alle externen Lib-Imports landen am korrekten Layer (PyQt6 ausschließlich in `ui/`, openpyxl/reportlab/calamine in `io/`, orjson/sqlite3 in `persistence/`). Es gibt aber **zwei strukturelle Bruchstellen**, die das Layer-Modell konkret verletzen: (1) `core/undo.py` greift direkt auf `persistence/database.py` zu und führt eigenes SQL aus – core verliert damit seine Reinheit, was für die ISAE-3402-Reproduzierbarkeitsgarantie relevant ist; (2) die beiden Report-Generatoren in `io/` importieren `ui/widgets/chart_renderer`, wodurch `io/` indirekt PyQt6 in den Build zieht. Insgesamt **2 SEV-0**, **3 SEV-1**, **5 SEV-2** und **3 SEV-3** Findings. **Headline:** Der `MainController` ist mit 1 252 LoC + 18 `handle_*`-Methoden + DB-/Undo-/Settings-/Export-Orchestrierung ein klassisches God-Object und sollte vor weiteren Features in Sub-Controller aufgeteilt werden.

## Severity-Skala

- **SEV-0** — Kritisch. Layer-Verletzung mit Audit-/Reproducibility-Risiko ODER Modul > 1200 LoC. Blocker für neue Features.
- **SEV-1** — Hoch. Klare Architektur-Verletzung ODER Modul 800–1200 LoC ODER Import-Zyklus. In dedizierten Refactor-Sprint.
- **SEV-2** — Mittel. Concern-Mischung ODER Modul 500–800 LoC. Refactor-Kandidat, geplant adressieren.
- **SEV-3** — Niedrig. Kosmetik, fehlende `__all__`, leakende private Symbole, fehlender Module-Docstring. Backlog.

## Findings

### SEV-0

#### F-001: `MainController` ist ein 1 252-LoC-God-Object
- **Datei(en):** [src/sampling_tool/ui/controllers/main_controller.py](src/sampling_tool/ui/controllers/main_controller.py)
- **Zeilen:** 1–1252 (gesamt)
- **Befund:** Der Controller überschreitet mit **1 252 LoC** den SEV-0-Schwellwert. In einer Klasse bündeln sich Engagement-Lifecycle, DB-Connection-Verwaltung, Dataset-Import, Sampling-Orchestrierung inkl. `_build_sampling_dataset`, Undo-/Redo-Logik via `UndoManager`, Export-Dialoge (Excel/PDF/HTML/Multi-Sheet), Audit-/Dashboard-Refresh, Settings-Anwendung, Briefpapier-Resolution und State-Restore. 18 `handle_*`-Methoden zwischen [main_controller.py:222](src/sampling_tool/ui/controllers/main_controller.py#L222) und [main_controller.py:880](src/sampling_tool/ui/controllers/main_controller.py#L880) bedienen jeweils eigene Signal-Pfade. Tests und neue Features müssen jedes Mal diesen Block verstehen.
- **Belegt durch:** `wc -l src/sampling_tool/ui/controllers/main_controller.py` (Resultat: `1252`) sowie Volltext-Lese-Lauf.
- **Empfehlung:** In Sub-Controller aufteilen (z. B. `EngagementController`, `SamplingController`, `ExportController`, `UndoController`) mit gemeinsamem `ApplicationContext` für DB-/Settings-/Engagement-Handle. Dialog-Default-Factories nach unten in eine eigene Datei auslagern.

#### F-002: `core/undo.py` importiert `persistence.database` und führt SQL aus
- **Datei(en):** [src/sampling_tool/core/undo.py](src/sampling_tool/core/undo.py)
- **Zeilen:** [undo.py:20](src/sampling_tool/core/undo.py#L20), [undo.py:41–60](src/sampling_tool/core/undo.py#L41-L60), [undo.py:111–214](src/sampling_tool/core/undo.py#L111-L214)
- **Befund:** `core/` darf laut CLAUDE.md nur stdlib + `numpy` nutzen. `undo.py` importiert `Database, savepoint` aus `sampling_tool.persistence.database` und führt direktes SQL (`INSERT INTO undo_snapshots …`, `DELETE …`, `SELECT …`) gegen die SQLite-Connection aus. Damit hängt der gesamte Sampling-Reproduzierbarkeits-Pfad transitiv an SQLite. Audit-/ISAE-3402-Sicht: eine Domain-Klasse, die persistente Mutationen kennt, kann nicht mehr deterministisch im RAM rekonstruiert werden – `peek_undo()` ist datenbankzustandsabhängig.
- **Belegt durch:** `grep -rn "^from sampling_tool\|^import sampling_tool" src/sampling_tool/core/` (Zeile `core/undo.py:20:from sampling_tool.persistence.database import Database, savepoint`).
- **Empfehlung:** `UndoManager` aus `core/` nach `persistence/undo_repository.py` (oder einen neuen `persistence/undo_manager.py`) verschieben. Reine Stack-Logik (`UndoStack`-Verhalten, MAX_DEPTH-Trimm) als pure Datentyp in `core/models.py` belassen, persistente Operationen separieren.

### SEV-1

#### F-003: `io/multi_report_exporter.py` importiert UI-Widget (PyQt6 leaked in IO)
- **Datei(en):** [src/sampling_tool/io/multi_report_exporter.py](src/sampling_tool/io/multi_report_exporter.py)
- **Zeilen:** [multi_report_exporter.py:37](src/sampling_tool/io/multi_report_exporter.py#L37), Aufruf in [multi_report_exporter.py:274](src/sampling_tool/io/multi_report_exporter.py#L274)
- **Befund:** `from sampling_tool.ui.widgets.chart_renderer import render_bar_chart_bytes` zieht über die Import-Kette `chart_renderer.py` mit `from PyQt6.QtGui import QImage, QPixmap` ins `io/`-Modul. Damit hat jeder Konsument des Multi-Sheet-Excel-Reports eine harte PyQt6-Abhängigkeit – CI-Tools, Headless-Renderer und der Importer-Pfad bekommen die GUI-Library aufgebürdet, obwohl die Funktion nur PNG-Bytes liefert.
- **Belegt durch:** `grep -rn "^from sampling_tool\|^import sampling_tool" src/sampling_tool/io/` (Zeile 37) + Inspektion `chart_renderer.py` Zeile 24.
- **Empfehlung:** Chart-Bytes-Renderer in ein neutrales Modul ohne Qt-Import verschieben (z. B. `io/charts.py` oder `core/charts.py`); `chart_renderer.py` behält nur die QPixmap-Varianten und wrappt die Bytes-Funktion. Siehe auch F-005.

#### F-004: `io/html_report.py` importiert UI-Widget (PyQt6 leaked in IO)
- **Datei(en):** [src/sampling_tool/io/html_report.py](src/sampling_tool/io/html_report.py)
- **Zeilen:** [html_report.py:33–36](src/sampling_tool/io/html_report.py#L33-L36), Nutzung in [html_report.py:196, 218](src/sampling_tool/io/html_report.py#L196)
- **Befund:** Identisches Problem wie F-003: `from sampling_tool.ui.widgets.chart_renderer import render_bar_chart_bytes, render_line_chart_bytes` lädt PyQt6 in den HTML-Report-Pfad. Der HTML-Report soll explizit „selbstständig" und „per E-Mail oder File-Share verteilbar" sein (Docstring Zeilen 4–6) – das verträgt sich nicht mit einer GUI-Library als Pflicht-Dependency.
- **Belegt durch:** `grep -rn "^from sampling_tool\|^import sampling_tool" src/sampling_tool/io/` (Zeilen 33-36 in `html_report.py`).
- **Empfehlung:** Gleiche Refactor-Richtung wie F-003: gemeinsame Chart-Bytes-Funktion in ein Qt-freies Modul.

#### F-005: `chart_renderer.py` lebt im falschen Layer
- **Datei(en):** [src/sampling_tool/ui/widgets/chart_renderer.py](src/sampling_tool/ui/widgets/chart_renderer.py)
- **Zeilen:** [chart_renderer.py:24](src/sampling_tool/ui/widgets/chart_renderer.py#L24) (PyQt6-Import), [chart_renderer.py:106-168](src/sampling_tool/ui/widgets/chart_renderer.py#L106-L168) (Bytes-Funktionen)
- **Befund:** Das Modul mischt zwei klar getrennte Aufgaben in einer Datei: (1) `render_*_chart` liefert `QPixmap` für die UI; (2) `render_*_chart_bytes` liefert PNG-Bytes für Excel-/HTML-Reports. Letztere haben keinen Qt-Bezug, werden aber durch die gemeinsame Datei mit PyQt6 verheiratet – Ursache der Layer-Verletzungen F-003/F-004. Die Bytes-Funktionen sind außerdem die einzigen ihres Verzeichnisses, die von `io/`-Modulen konsumiert werden, was die "Widget"-Semantik des Ordners aufweicht.
- **Belegt durch:** Lesen `chart_renderer.py:1-211`; Konsumenten aus `grep -rn "chart_renderer" src/sampling_tool/`.
- **Empfehlung:** Datei splitten: `core/charts.py` (oder `io/charts.py`) für die Bytes-Renderer (matplotlib + Agg, kein Qt), `ui/widgets/chart_view.py` für den QPixmap-Wrapper. Damit fallen F-003 und F-004 automatisch weg.

### SEV-2

#### F-006: `ui/main_window.py` mischt 5 Concerns auf 683 LoC
- **Datei(en):** [src/sampling_tool/ui/main_window.py](src/sampling_tool/ui/main_window.py)
- **Zeilen:** 683 LoC gesamt; Concern-Blöcke in [main_window.py:81–125](src/sampling_tool/ui/main_window.py#L81-L125) (State-Machine), [main_window.py:286–332](src/sampling_tool/ui/main_window.py#L286-L332) (Workspace-Layout-Builder), [main_window.py:336–405](src/sampling_tool/ui/main_window.py#L336-L405) (QSettings-Restore + Splitter-Cache), [main_window.py:414–610](src/sampling_tool/ui/main_window.py#L414-L610) (Menü-/Toolbar-Build), [main_window.py:127–246](src/sampling_tool/ui/main_window.py#L127-L246) (Public Datensetter mit Sidebar-/Tabellen-Forwarding).
- **Befund:** 683 LoC sind im SEV-2-Bereich (500–800). Zusätzlich vereint die Klasse mehrere Verantwortlichkeiten: Stack-State-Machine zwischen Welcome/Workspace, Splitter-Größen-Persistierung inkl. Caching für Collapse-Zustand, Menü-/Toolbar-Konstruktion (~200 LoC), Statusbar-Pflege, Tab-Sichtbarkeits-Toggle. Jede einzelne UI-Erweiterung muss diese Datei anfassen.
- **Belegt durch:** `wc -l` + Lesen.
- **Empfehlung:** Menü- und Toolbar-Aufbau in `ui/main_menu.py` / `ui/main_toolbar.py` extrahieren, Workspace-Layout-Builder in `ui/workspace.py`. `MainWindow` bleibt als reiner Compositor + State-Machine zurück.

#### F-007: `persistence/repositories.py` bündelt 5 Repos + Datetime-Encoder auf 597 LoC
- **Datei(en):** [src/sampling_tool/persistence/repositories.py](src/sampling_tool/persistence/repositories.py)
- **Zeilen:** [repositories.py:49–145](src/sampling_tool/persistence/repositories.py#L49-L145) (`EngagementRepo`), [repositories.py:152–243](src/sampling_tool/persistence/repositories.py#L152-L243) (`DatasetRepo`), [repositories.py:250–355](src/sampling_tool/persistence/repositories.py#L250-L355) (`SampleRepo`), [repositories.py:363–440](src/sampling_tool/persistence/repositories.py#L363-L440) (`AuditRepo`), [repositories.py:448–530](src/sampling_tool/persistence/repositories.py#L448-L530) (`EngagementStateRepo`), [repositories.py:553–597](src/sampling_tool/persistence/repositories.py#L553-L597) (`_encode_value`/`_decode_value` Tagged-JSON-Encoder).
- **Befund:** 597 LoC im SEV-2-Bereich. Fünf Repos in einer Datei – jeder Repo-Test importiert das ganze Modul. Zusätzlich liegen Tagged-Datetime-JSON-Helfer hier, obwohl sie konzeptionell zur `database.py`-Adapter-Familie gehören.
- **Belegt durch:** `wc -l` + Lesen.
- **Empfehlung:** Pro Repo ein Modul (`persistence/engagement_repo.py`, `dataset_repo.py`, …) und ein gemeinsames `persistence/_json.py` für die Encoder. Re-Export aus `persistence/__init__.py`, damit Konsumenten nicht migrieren müssen.

#### F-008: `io/pdf_report.py` mischt PDF-Rendering, Briefpapier-Wrapping und Chunking-Strategie (429 LoC)
- **Datei(en):** [src/sampling_tool/io/pdf_report.py](src/sampling_tool/io/pdf_report.py)
- **Zeilen:** 429 LoC; Concerns in [pdf_report.py:74–141](src/sampling_tool/io/pdf_report.py#L74-L141) (Briefpapier-Resolution im Konstruktor), [pdf_report.py:213–272](src/sampling_tool/io/pdf_report.py#L213-L272) (Chunking-Sub-Tables), [pdf_report.py:275–307](src/sampling_tool/io/pdf_report.py#L275-L307) (Style + `_format_cell`-Optimierung), [pdf_report.py:358–416](src/sampling_tool/io/pdf_report.py#L358-L416) (Page-Hook + PDF-Briefpapier-Layer mit pdfrw).
- **Befund:** Datei liegt zwischen 300–500 LoC – nur erwähnenswert, weil Concerns klar getrennt werden könnten: Rendering-Logik, Performance-Chunking (Sprint 10.4) und Page-Hook mit Briefpapier-Embedding kollidieren in einer Datei. `AuditTrailPDF`-Konstruktor übernimmt zusätzlich die Briefpapier-Resolution, die bereits in [io/briefpapier.py](src/sampling_tool/io/briefpapier.py) lebt.
- **Belegt durch:** Lesen + `wc -l`.
- **Empfehlung:** Story-Bausteine (Header/Event-Table/Statistik) in `io/pdf_components.py` extrahieren, Page-Hook + Briefpapier-Embedding nach `io/briefpapier.py` ziehen. `pdf_report.py` bleibt als Orchestrator.

#### F-009: `io/importer.py` 455 LoC + Format-Mix (Excel + CSV + Coerce + Header-Detection)
- **Datei(en):** [src/sampling_tool/io/importer.py](src/sampling_tool/io/importer.py)
- **Zeilen:** [importer.py:138–179](src/sampling_tool/io/importer.py#L138-L179) (Excel- und CSV-Pfad in der Klasse), [importer.py:208–310](src/sampling_tool/io/importer.py#L208-L310) (Excel-Parsing-Helfer), [importer.py:313–378](src/sampling_tool/io/importer.py#L313-L378) (CSV-Parsing-Helfer), [importer.py:381–456](src/sampling_tool/io/importer.py#L381-L456) (Typ-Coercion).
- **Befund:** 455 LoC im 300–500-Bereich, plus drei klar separable Concerns: Calamine-Excel-Pfad, stdlib-CSV-Pfad und Wert-Coercion. Die Coercion-Helfer (`_coerce_value`/`_coerce_string`/`_try_int`/`_try_float`) sind dateigebunden, könnten aber auch von zukünftigen Importern (z. B. JSON) wiederverwendet werden.
- **Belegt durch:** Lesen + `wc -l`.
- **Empfehlung:** `io/importer/excel.py`, `io/importer/csv.py`, `io/importer/_coerce.py` mit einem dünnen Fassaden-Modul.

#### F-010: `ui/dialogs/sampling_dialog.py` 485 LoC mit verzweigtem Simple/Advanced-Modus
- **Datei(en):** [src/sampling_tool/ui/dialogs/sampling_dialog.py](src/sampling_tool/ui/dialogs/sampling_dialog.py)
- **Zeilen:** 485 LoC (knapp unter SEV-2-Schwellwert 500).
- **Befund:** Datei liegt im 300–500-Bereich, hat aber zwei klar verzweigte Pfade (Simple- vs. Advanced-Modus, Seed-Widget gemeinsam, method-spezifische Cluster-/Schicht-/Filter-Felder). Die `accept()`-Override-Validierung, die Größen-Hint-Berechnung und die Würfel-Seed-Generierung lassen sich für Tests sauberer in Helfer aufsplitten. Erwähnt mangels Über-500-LoC nur als Concern-Mischung.
- **Belegt durch:** `wc -l` + CLAUDE.md-Beschreibung.
- **Empfehlung:** Footer/Hinweis-Block und Seed-Widget in dedizierte Sub-Widgets auslagern.

### SEV-3

#### F-011: 6 Layer-`__init__.py` haben veraltete Stub-Docstrings
- **Datei(en):** [persistence/__init__.py](src/sampling_tool/persistence/__init__.py), [audit/__init__.py](src/sampling_tool/audit/__init__.py), [ui/__init__.py](src/sampling_tool/ui/__init__.py), [ui/widgets/__init__.py](src/sampling_tool/ui/widgets/__init__.py), [ui/dialogs/__init__.py](src/sampling_tool/ui/dialogs/__init__.py), [ui/controllers/__init__.py](src/sampling_tool/ui/controllers/__init__.py)
- **Zeilen:** je Zeile 1
- **Befund:** Sechs Layer-`__init__.py` enthalten noch Platzhalter-Docstrings wie `"""Persistenz-Layer: SQLite + Migrations. Implementierung folgt in Sprint 2."""` oder `"""PyQt6-UI-Layer. Implementierung folgt ab Sprint 4."""`. Die Implementierungen sind seit Sprint 2 bzw. 4 vorhanden – CLAUDE.md fordert explizit „Bei Sprint-Übergängen: alte Stub-`__init__.py` ersetzen, nicht parallele Module anlegen." Doku-Sicht wirkt unsauber, technisch funktionsfähig.
- **Belegt durch:** `cat src/sampling_tool/{persistence,audit,ui,ui/widgets,ui/dialogs,ui/controllers}/__init__.py`.
- **Empfehlung:** Docstrings entweder durch eine aktuelle 1-Zeilen-Beschreibung der tatsächlichen Layer-Verantwortung ersetzen oder als bewusstes Public-API-Re-Export (`__all__`) auffüllen.

#### F-012: Nur 4 Module deklarieren `__all__`
- **Datei(en):** Alle src-Module **außer** [src/sampling_tool/__init__.py](src/sampling_tool/__init__.py), [core/__init__.py](src/sampling_tool/core/__init__.py), [io/__init__.py](src/sampling_tool/io/__init__.py), [ui/widgets/audit_trail_view.py](src/sampling_tool/ui/widgets/audit_trail_view.py)
- **Zeilen:** —
- **Befund:** Nur vier Module deklarieren `__all__`. Insbesondere `core/sampling.py`, `core/models.py`, `core/rng.py`, `persistence/repositories.py`, `persistence/database.py`, `io/exporter.py`, `io/pdf_report.py`, `io/html_report.py`, `io/multi_report_exporter.py`, `io/briefpapier.py`, `audit/logger.py`, `ui/main_window.py`, `ui/recent.py`, `ui/settings_store.py`, alle Dialoge und alle Widgets haben keine explizite Public-API-Liste. Folgen: `from X import *`-Verhalten ist nicht reproduzierbar, Refactorings können stillschweigend interne Helfer mit-exportieren, IDE-Auto-Completes zeigen Internals.
- **Belegt durch:** `grep -rn "^__all__" src/sampling_tool > /tmp/exports.txt; cat /tmp/exports.txt`.
- **Empfehlung:** In jeder Datei mit mehr als einer öffentlichen Klasse `__all__ = [...]` ergänzen. Privates konsequent mit `_`-Präfix kennzeichnen (ist überwiegend bereits so).

#### F-013: `core/__init__.py` re-exportiert `AuditEvent` – konzeptionell aus dem Audit-Layer
- **Datei(en):** [src/sampling_tool/core/__init__.py](src/sampling_tool/core/__init__.py)
- **Zeilen:** [core/__init__.py:10-19, 30-46](src/sampling_tool/core/__init__.py#L10-L19)
- **Befund:** `AuditEvent` ist in `core/models.py` definiert und wird von `core/__init__.py` als Public-API exportiert. Das Datentyp-Schema ist legitim in `core/`, der Klassenname suggeriert aber Audit-Layer-Zugehörigkeit. Kein Layer-Bruch, nur eine kosmetische Inkohärenz, die Konsumenten in `audit/logger.py` (importiert aus `core.models`) bereits explizit machen.
- **Belegt durch:** Lesen `core/__init__.py` und `audit/logger.py:13`.
- **Empfehlung:** Entweder konsequent dokumentieren ("Domain-Modelle inkl. Audit-Event-Schema") oder den Datentyp als `core/models.audit.AuditEvent` umstrukturieren. Niedrigste Priorität.

## Modul-Größen

Alle Dateien > 300 LoC, sortiert absteigend:

| Datei                                       | LoC  | Severity-Beitrag                  |
|---------------------------------------------|------|-----------------------------------|
| ui/controllers/main_controller.py           | 1252 | SEV-0 (F-001)                     |
| ui/main_window.py                           |  683 | SEV-2 (F-006)                     |
| persistence/repositories.py                 |  597 | SEV-2 (F-007)                     |
| ui/dialogs/sampling_dialog.py               |  485 | SEV-2 (F-010, knapp unter Cutoff) |
| ui/widgets/audit_trail_view.py              |  461 | —                                 |
| io/importer.py                              |  455 | SEV-2 (F-009)                     |
| io/pdf_report.py                            |  429 | SEV-2 (F-008)                     |
| ui/widgets/dashboard_view.py                |  401 | —                                 |
| ui/dialogs/settings_dialog.py               |  345 | —                                 |
| io/multi_report_exporter.py                 |  330 | SEV-1 (F-003, Inhalt nicht Größe) |
| core/sampling.py                            |  302 | —                                 |

## Layer-Compliance-Matrix

Spalten = Quell-Layer (welche Module importieren); Zeilen = Ziel-Layer (was wird importiert). Zelleninhalt: ✅ erlaubt+gefunden / ❌ verboten+gefunden(=Finding) / · erlaubt+nicht gefunden / — verboten+nicht gefunden / n/a Selbst-Referenz.

|                    | von core | von io | von persistence | von audit | von ui/widgets | von ui/dialogs | von ui/controllers | von ui/main_window |
|--------------------|----------|--------|-----------------|-----------|----------------|----------------|--------------------|--------------------|
| core               | n/a      | ✅     | ✅              | ✅        | ✅             | ✅             | ✅                 | ✅                 |
| io                 | —        | n/a    | —               | —         | —              | —              | ✅                 | —                  |
| persistence        | ❌ (F-002) | —    | n/a             | ✅        | —              | —              | ✅                 | —                  |
| audit              | —        | —      | —               | n/a       | —              | —              | ✅                 | —                  |
| ui/widgets         | —        | ❌ (F-003/F-004) | —     | —         | n/a (✅ intern)| —              | —                  | ✅                 |
| ui/dialogs         | —        | —      | —               | —         | —              | n/a (✅ intern)| ✅                 | —                  |
| ui/controllers     | —        | —      | —               | —         | —              | —              | n/a                | —                  |
| PyQt6 (extern)     | —        | — (direkt) / ❌ indirekt via chart_renderer | —     | —         | ✅             | ✅             | ✅                 | ✅                 |
| sqlite3 (extern)   | — direkt (aber transitiv via undo, siehe F-002) | —     | ✅              | —         | —              | —              | · (via Database)   | —                  |
| openpyxl (extern)  | —        | ✅     | —               | —         | —              | —              | —                  | —                  |
| reportlab (extern) | —        | ✅     | —               | —         | —              | —              | —                  | —                  |
| python_calamine    | —        | ✅     | —               | —         | —              | —              | —                  | —                  |
| pdfrw (extern)     | —        | ✅     | —               | —         | —              | —              | —                  | —                  |
| orjson (extern)    | —        | —      | ✅              | —         | —              | —              | —                  | —                  |
| numpy (extern)     | ✅       | —      | —               | —         | —              | —              | —                  | —                  |

Belegt durch:
- `grep -rn "^from sampling_tool\|^import sampling_tool" core/ io/ persistence/ audit/ ui/`
- `grep -rn "from PyQt6\|^import PyQt6" core/ io/ persistence/ audit/` → leer (kein direkter Qt-Import in non-ui)
- `grep -rn "from sqlite3\|^import sqlite3" core/ io/ audit/ ui/widgets/ ui/dialogs/` → leer
- `grep -rn "from openpyxl|reportlab|python_calamine|pdfrw …" core/ persistence/ audit/ ui/widgets/ ui/dialogs/` → leer
- `grep -rn "from numpy" io/ persistence/ audit/ ui/` → leer

## Healthy Modules

Module ohne Findings – aktuell gut geschnitten:

- [core/models.py](src/sampling_tool/core/models.py) – reine frozen Dataclasses + Enums, keine I/O, keine Qt-Abhängigkeit, übersichtliche 190 LoC.
- [core/rng.py](src/sampling_tool/core/rng.py) – 53 LoC, einzige Verantwortung: deterministischer RNG + Fisher-Yates-Shuffle. Erfüllt das numpy-only-Mandat der Reproducibility-Anforderung.
- [core/sampling.py](src/sampling_tool/core/sampling.py) – 302 LoC für drei Sampler + Factory + Validierung, klare Public-API im Docstring, keine Layer-Verletzung.
- [resources.py](src/sampling_tool/resources.py) – 53 LoC, genau das was CLAUDE.md verlangt: `package_resource` + `shared_resource` + `is_frozen`-Helper.
- [config.py](src/sampling_tool/config.py) – 119 LoC, ausschließlich Konstanten + `sanitize_for_path`. Keine zusätzliche Logik.
- [__main__.py](src/sampling_tool/__main__.py) – 66 LoC, sauberer Bootstrap mit late-imports für PyQt6 (CI-Tests können das Modul ohne Qt importieren).
- [io/briefpapier.py](src/sampling_tool/io/briefpapier.py) – 130 LoC, Config-Dataclass + Resolution-Reihenfolge gemäß CLAUDE.md exakt umgesetzt, keine Querverbindungen.
- [io/exporter.py](src/sampling_tool/io/exporter.py) – 265 LoC, atomarer .tmp-Write + zwei Sheets, klar abgegrenzt.
- [io/html_report.py](src/sampling_tool/io/html_report.py) – außer F-004 (chart_renderer) sauber: Jinja2-Template, View-Modelle, ViewContext-Bau. Concern-Trennung gut.
- [persistence/database.py](src/sampling_tool/persistence/database.py) – 213 LoC, klare Trennung Connection/Session/Migrations/Pragmas. Datetime-Adapter sauber registriert.
- [persistence/version_manager.py](src/sampling_tool/persistence/version_manager.py) – 150 LoC für Compliance-Snapshots, klar gekapselt.
- [audit/logger.py](src/sampling_tool/audit/logger.py) – 137 LoC, eine `log_*`-Methode pro Event-Typ, dünner Wrapper um `AuditRepo`. Vorbildlich.
- [ui/recent.py](src/sampling_tool/ui/recent.py) – 171 LoC, JSON-Persistenz isoliert, keine Qt-Abhängigkeit – könnte sogar aus `ui/` rausgenommen werden, bleibt aber Beobachtungs-Kandidat statt Finding.
- [ui/settings_store.py](src/sampling_tool/ui/settings_store.py) – 200 LoC inkl. Bestandsuser-Heuristik, gut strukturiert.
- [ui/widgets/data_table.py](src/sampling_tool/ui/widgets/data_table.py) – 298 LoC, Model + View + Empty-State-Paint, unter dem 500-LoC-Cutoff und mit klarer interner Trennung.
- [ui/widgets/sidebar.py](src/sampling_tool/ui/widgets/sidebar.py) – 226 LoC, drei dedizierte Listen-Sektionen, keine Geschäftslogik.
- [ui/widgets/welcome.py](src/sampling_tool/ui/widgets/welcome.py) – 186 LoC, Welcome-Screen mit Recent-Karten.
- [ui/dialogs/_export_base.py](src/sampling_tool/ui/dialogs/_export_base.py) – 173 LoC, wiederverwendbares Export-Target-Widget mit Pattern-Token-Substitution.
- Kleine Dialoge ([about_dialog.py](src/sampling_tool/ui/dialogs/about_dialog.py), [bug_report_dialog.py](src/sampling_tool/ui/dialogs/bug_report_dialog.py), [duplicate_engagement_dialog.py](src/sampling_tool/ui/dialogs/duplicate_engagement_dialog.py), [progress_dialog.py](src/sampling_tool/ui/dialogs/progress_dialog.py), [first_run_wizard.py](src/sampling_tool/ui/dialogs/first_run_wizard.py), [new_engagement_dialog.py](src/sampling_tool/ui/dialogs/new_engagement_dialog.py)) – jeweils unter 240 LoC, fokussiert.

## Offene Fragen

1. **`AuditEvent` in `core/`**: bewusste Architektur-Entscheidung („Domain-Modell, Audit-Schema-Definition gehört zum Kern-Vokabular") oder Altlast aus Sprint 1, bevor `audit/` existierte? Falls Erstes: F-013 ignorieren.
2. **`UndoManager` in `core/`**: laut CLAUDE.md ist `core/undo.py` der vorgesehene Ort. Die Realität (SQL + Persistenz-Import) widerspricht aber dem "core ist pur"-Mandat. Frage: ist die Layer-Definition aus CLAUDE.md gemeint als „logische Domain-Schicht" (in der `Undo` als Konzept lebt) oder als „Pflicht-Import-Whitelist"? Pass 1 hat die strikte Lesart angewandt → F-002.
3. **`ui/recent.py` und `ui/settings_store.py`**: beides QSettings-/JSON-Persistenz, beides ohne Qt-Widget-Code. Bewusst unter `ui/`, weil Settings nur die UI braucht? Oder Refactor-Kandidat in `persistence/` / `app/`? Aktuell als „Healthy" gewertet, weil kein konkreter Bruch.
4. **PyQt6-Indirekt-Import in `io/`**: Quantifizierung wäre interessant – schlägt der Excel-Report-Pfad in einer Headless-CI (ohne `libqt6gui`) tatsächlich fehl, oder fängt matplotlib-Agg das ab? F-003/F-004 begründen aber bereits aus der Layer-Verletzung selbst, daher hier nur als Verifikations-Hinweis.
5. **Discrepancy CLAUDE.md ↔ aktueller Streaming-Stand**: die im System-Reminder eingeblendete CLAUDE.md beschreibt Sprint 11.1–11.5 (Streaming, `Dataset` ohne `rows`, `iter_rows`, …). Die Datei auf Platte ([CLAUDE.md](CLAUDE.md), 636 Zeilen, "Sprint 10.4 abgeschlossen") und der Code (`Dataset.rows: tuple[DatasetRow, ...]` in [core/models.py:104](src/sampling_tool/core/models.py#L104), `Dataset(...rows=rows...)` in [io/importer.py:155](src/sampling_tool/io/importer.py#L155)) reflektieren den Stand bis Sprint 10.4. Pass 1 hat sich an die On-Disk-CLAUDE.md gehalten – falls Streaming-Refactor aktuell läuft, ist das beim Lesen der Findings zu berücksichtigen.

## Empfehlung: Refactor-Sprint vs. Backlog

**In einen dedizierten Refactor-Sprint VOR weiteren Features:** F-001 (MainController-Split), F-002 (Undo aus core), F-003/F-004/F-005 (Chart-Renderer-Split entkoppelt io von ui). Diese vier Bereiche bilden zusammen das Fundament für Testbarkeit und Layer-Sauberkeit – jede neue Feature-Arbeit am Controller oder an einem Report multipliziert sonst die Komplexität, und der Layer-Bruch core→persistence macht jede Reproduzierbarkeits-Diskussion komplizierter. F-005 ist Voraussetzung, um F-003 und F-004 sauber zu fixen; F-001 lässt sich danach in inkrementellen Sub-Controller-Cuts angehen.

**Geplant adressieren (nächste 1–2 Sprints, jeweils im Rahmen passender Feature-Arbeit):** F-006 (main_window-Split), F-007 (Repositories aufteilen), F-008 (pdf_report-Concerns), F-009 (importer-Module). Diese sind Concern-Mischungen ohne harten Architektur-Bruch – Refactor lohnt sich, ist aber nicht blockierend.

**Backlog/Kosmetik:** F-010 (Sampling-Dialog Sub-Widgets), F-011 (Stub-Docstrings), F-012 (`__all__`), F-013 (AuditEvent-Konzeptdoku). Können beim nächsten Anfassen der jeweiligen Datei mitgenommen werden.

Sequenz-Abhängigkeit: F-005 → F-003 + F-004; F-007 → erleichtert spätere Streaming-Refactors (Sprint-11-Stand); F-001 sollte nicht parallel zu einem Streaming-Refactor laufen (zu viele bewegliche Teile).
