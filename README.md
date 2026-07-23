# BDO Audit Sampling Tool

[![CI](https://github.com/NicoHaider/Sampling-Tool/actions/workflows/ci.yml/badge.svg)](https://github.com/NicoHaider/Sampling-Tool/actions/workflows/ci.yml)

Das BDO Audit Sampling Tool ist eine Desktop-Anwendung für die nachvollziehbare
Stichprobenziehung aus Prüfungsdaten. Es löst ein VBA-basiertes Excel-Tool ab
und **unterstützt reproduzierbare, dokumentierte Audit-Stichproben für
ISAE-3402-Prüfungen**. Die Anwendung läuft auf macOS und Windows, verwendet eine
PyQt6-Oberfläche und speichert jedes Projekt lokal in einer SQLite-Datei.

## Aktueller Stand

Die Anwendung deckt den vollständigen Arbeitsablauf ab: Projekt anlegen oder
öffnen, Daten importieren, Stichprobe konfigurieren und ziehen, Ergebnisse prüfen
und als Excel-, PDF- oder HTML-Report dokumentieren. Die Sprint-für-Sprint-
Historie steht im [CHANGELOG](CHANGELOG.md); die langlebige Architektur-Referenz
in [CLAUDE.md](CLAUDE.md), bedeutende Grundsatzentscheidungen als
[Architecture Decision Records](docs/adr/).

Im Mittelpunkt stehen Reproduzierbarkeit und Nachvollziehbarkeit:

- Jede Ziehung erhält einen Seed und die Algorithmusversion `bdo-v1`.
- Gleiche Daten, Konfiguration und Seed führen zu denselben gezogenen
  Datensatz-IDs.
- Ziehungen, Importe, Exporte sowie Undo-/Redo-Aktionen werden in einem
  **anwendungsseitig append-only** Audit-Trail festgehalten.
- Vor dem Öffnen wird eine Datenbank read-only als Sampling-Tool-Projekt
  geprüft; erst danach werden Snapshot und Migration ausgeführt.

## So funktioniert der Workflow

1. Beim ersten Start legt ein kurzer Assistent den Standardordner und den
   Auditor fest. Anschließend wird ein neues Projekt angelegt oder eine
   bestehende Projektdatei geöffnet. Ein Projekt entspricht einer `.db`-Datei
   und enthält alle zugehörigen Daten, Stichproben und Audit-Ereignisse.
2. Excel- oder CSV-Dateien werden mit Vorschau importiert. Bei Excel-Dateien
   kann ein Blatt gewählt werden; für beide Formate lässt sich die Kopfzeile
   automatisch erkennen, per Klick bestimmen oder ganz weglassen. Ohne Kopfzeile
   erzeugt die Anwendung neutrale Spaltennamen wie „Spalte 1".
3. Der Import schreibt die Datensätze in die lokale Projekt-Datenbank. Die
   Oberfläche lädt für Tabelle, Suche und Ziehung nur die jeweils benötigten
   Daten nach und bleibt dadurch auch bei großen Populationen bedienbar.
4. Im Stichproben-Dialog werden Methode, Umfang, Seed und bei Bedarf Filter oder
   Gruppierungsfelder festgelegt. Die Ziehung wird gespeichert, in der Tabelle
   hervorgehoben und im Audit-Trail dokumentiert.
5. Über die Sidebar lassen sich Datasets und frühere Stichproben wieder aufrufen.
   Dashboard und Audit-Trail geben den aktuellen Projektstand und seine Historie
   wieder.
6. Die Ergebnisse lassen sich als einzelne Excel-Stichprobe, vollständiger
   Excel-Report, AuditTrail-PDF oder HTML-Report ausgeben.

```text
Excel / CSV
    │  Vorschau, Blatt- und Kopfzeilenauswahl
    ▼
Dataset in der Projekt-SQLite-Datei ──► Datentabelle, Sidebar und Dashboard
    │
    │  Methode + Umfang + Seed + optionale Einschränkungen
    ▼
Gespeicherte Stichprobe ──► Markierung in der Tabelle + Audit-Ereignis
    │
    ├──► Sample-Excel
    ├──► Excel-Projektreport
    ├──► AuditTrail-PDF
    └──► HTML-Report
```

### Was in einem Projekt gespeichert wird

| Bereich | Inhalt |
|---|---|
| Projektstammdaten | Mandant, Prüfungstyp, Auditor und Position |
| Datenbestände | Importquelle, Spalten, stabile Zeilen-IDs und die importierten Werte |
| Stichproben | Methode, gewünschte und tatsächliche Größe, Population, Seed, Filter und gegebenenfalls Eltern-Stichprobe |
| Audit-Trail | Importe, Ziehungen, Exporte, Rückgängig/Wiederherstellen, Resets und Korrekturen |
| Arbeitszustand | Aktuelle Auswahl und Undo-/Redo-Snapshots für die Bedienung |

### Projektordner und Lebenszyklus

Ein Projekt besteht nicht nur aus der Datenbankdatei. In der üblichen Ablage
entsteht ein eigener Ordner pro Mandant. Neben der `.db`-Datei nutzt die
Anwendung darin insbesondere diese Bereiche:

| Pfad bzw. Datei | Zweck |
|---|---|
| `<Mandant>/<Projekt>.db` | Die lokale Projektdatei mit Stammdaten, Datasets, Stichproben und Audit-Trail. |
| `<Mandant>/archiv/` | Automatisch erzeugte Datenbanksnapshots vor dem Öffnen bzw. vor einem Überschreiben. |
| `<Mandant>/exports/` | Vorgeschlagener Ablageort für erzeugte Reports und Exporte. |

Beim Anlegen werden Mandant und Prüfungstyp für den Dateinamen bereinigt, damit
der gleiche Ablauf auf macOS und Windows funktioniert. Beim erneuten Öffnen merkt
sich die Anwendung das Projekt für den Welcome-Screen und das Menü „Zuletzt
geöffnet". Nicht mehr existierende Einträge werden aus dieser Liste bereinigt.

## Funktionsumfang

### Projekte und Datenhaltung

- Ein separates SQLite-Projekt pro Mandant bzw. Prüfung, einschließlich Auditor,
  Position und Prüfungstyp.
- Neue Projekte werden in einem eigenen Mandantenordner abgelegt; der
  vorgeschlagene Dateiname enthält Mandant und Prüfungstyp. Bei bereits
  vorhandener Datei kann der Vorgang abgebrochen oder mit vorherigem Backup
  fortgesetzt werden.
- Beim Öffnen einer bestehenden Projektdatei prüft das Tool zuerst rein lesend,
  ob es sich um eine intakte und unterstützte Sampling-Tool-Datenbank handelt. Es
  erstellt erst danach einen Snapshot und führt gegebenenfalls Migrationen aus.
  Fremde, beschädigte oder zu neue Datenbanken bleiben unangetastet.
- Automatische Sitzungssnapshots liegen im Projektordner `archiv/`, tragen
  Zeitstempel und Auditor im Dateinamen und werden schreibgeschützt abgelegt.
- Kürzlich verwendete Projekte, Einstellungen und Stichprobenvorlagen werden
  app-weit gespeichert.
- Undo/Redo für den Arbeitszustand sowie ein klar abgegrenztes „Datensätze aus
  Ansicht entfernen", das keine Quelldaten aus der Datenbank löscht.

### Import und Verarbeitung

- Excel- und CSV-Import, inklusive Mehrblatt-Auswahl, Header-Vorschau,
  Zeichensatz-Erkennung für CSV und generischen Spaltennamen ohne Kopfzeile.
- Excel wird über die Rust-basierte `python-calamine`-Bibliothek zeilenweise
  gelesen (deutlich schneller und speicherschonender als ein voll
  materialisierter Read); CSV über die stdlib mit Encoding-Fallback. Unterstützte
  Eingaben sind `.xlsx`, `.xlsm`, `.csv` und `.tsv`.
- Streaming-orientierte Speicherung und Abfrage: auch große Populationen müssen
  nicht vollständig als Python-Objekte im Arbeitsspeicher liegen.
- Jeder importierte Datensatz erhält eine stabile Zeilen-ID. Werte wie Datum,
  Uhrzeit und Zahlen bleiben für Filter, Export und spätere Reproduktion
  typisiert erhalten.

#### Importablauf im Detail

Bei einer klar strukturierten Datei – einer Excel-Tabelle mit eindeutig erkannter
Kopfzeile oder einer entsprechend klaren CSV – startet der Import direkt. Bei
mehreren Excel-Blättern oder unsicherer Kopfzeilenerkennung zeigt das Tool
dagegen einen Konfigurationsdialog. Dort wird zuerst das Blatt und anschließend
die Kopfzeile gewählt:

1. Die Vorschau zeigt Rohzeilen, ohne sie vorab als Daten oder Überschriften zu
   interpretieren.
2. Die automatische Erkennung schlägt eine Kopfzeile mit einer
   Vertrauenseinschätzung vor.
3. Der Benutzer kann die vorgeschlagene Zeile übernehmen, eine andere Zeile in
   der Vorschau anklicken oder „keine Kopfzeile" wählen.
4. Zeilen vor einer gewählten Kopfzeile werden nicht als Daten importiert. Ohne
   Kopfzeile werden alle nicht leeren Zeilen importiert und die Spalten heißen
   `Spalte 1`, `Spalte 2` usw.
5. Während des vollständigen Imports werden die Daten zeilenweise verarbeitet und
   fortlaufend in die Projekt-Datenbank geschrieben. Der Vorgang ist abbrechbar
   und führt einen Fortschrittsdialog.

Der Import verändert die Quelldatei nie. Die Quelle wird im Dataset und im
Audit-Trail als Pfad festgehalten; die Arbeitsgrundlage für alle folgenden
Schritte ist die lokale Kopie der Daten in der Projektdatei.

### Stichproben

| Verfahren | Anwendung im Tool |
|---|---|
| Einfach | Zieht die gewünschte Anzahl zufällig und ohne Zurücklegen aus der verfügbaren Population. |
| Cluster | Wählt ganze Gruppen anhand einer frei wählbaren Spalte. Da vollständige Cluster übernommen werden, kann die tatsächliche Zeilenzahl über dem Zielwert liegen. |
| Geschichtet | Verteilt die Zielgröße auf Werte einer Schichtspalte – entweder proportional zur Schichtgröße oder gleichmäßig über die Schichten. Rundungen werden über die Largest-Remainder-Methode nachvollziehbar verteilt. |

Für jede Methode gilt:

- Vor der Ziehung kann eine Spalte mit `=`, `≠`, `>`, `≥`, `<` oder `≤` gefiltert
  werden. Für Gleichheit und Ungleichheit werden vorhandene Werte angeboten; bei
  Größenvergleichen wird ein Schwellenwert eingegeben. Die Vorschau zeigt die für
  die Ziehung verfügbare Menge.
- „Nur aus aktueller Auswahl ziehen" begrenzt eine neue Ziehung auf das aktive
  Sample. Die Alternative „Ergänzen" zieht aus der Restpopulation und schließt
  bereits gezogene Zeilen aus. Beide halten die Herkunft über eine
  Eltern-Stichprobe fest.
- Benannte Vorlagen speichern wiederkehrende Einstellungen wie Methode, Felder
  und Filter. Der Seed gehört bewusst nicht zur Vorlage und wird in den
  Einstellungen zentral festgelegt oder für eine neue Ziehung erzeugt.
- Vor der Zufallsauswahl wird die Population in eine stabile Reihenfolge gebracht.
  Der explizit versionierte Zufallsalgorithmus `bdo-v1` und der gespeicherte Seed
  machen eine Ziehung mit denselben Eingabedaten reproduzierbar (siehe
  [ADR 0001](docs/adr/0001-versionsfester-rng-vertrag.md)).

#### Wiederholen, einschränken oder ergänzen

Diese drei Fälle unterscheiden sich bewusst:

| Vorgang | Population der neuen Ziehung | Beziehung zur vorherigen Stichprobe |
|---|---|---|
| Neue unabhängige Ziehung | Gesamtes aktuelle Dataset, eventuell mit Spaltenfilter | Keine Eltern-Stichprobe |
| Nur aus aktueller Auswahl ziehen | Nur die Zeilen der aktiven Stichprobe | Neue Ziehung referenziert die aktive Stichprobe |
| Ergänzen / Nachstichprobe | Gesamte Basispopulation abzüglich der bereits gezogenen Zeilen | Referenziert die aktive Stichprobe, enthält keine Dubletten zu ihr |

Das Zurücksetzen einer Auswahl löscht keine gespeicherten Stichproben oder
Audit-Ereignisse. Es ändert nur den sichtbaren Arbeitszustand. Auch Undo und Redo
stellen diesen Arbeitszustand wieder her und hinterlassen selbst wieder
nachvollziehbare Audit-Ereignisse.

### Nachweis und Reports

Der Audit-Trail ist **anwendungsseitig append-only**: bestehende Einträge werden
nicht überschrieben oder gelöscht. Eine fachliche Korrektur wird als neuer,
referenzierter Korrektur-Eintrag protokolliert. Bei einer Ziehung enthält der
Eintrag unter anderem Methode, Größe, Population, Anteil, Seed sowie Filter- und
Gruppierungsparameter. Importe und Exporte halten außerdem Quelle bzw. Zieldatei
fest. Details und Grenzen des Modells: [ADR 0002](docs/adr/0002-anwendungsseitig-append-only-audit-trail.md).

| Ausgabe | Inhalt und Optionen |
|---|---|
| Sample-Excel | Die ausgewählten Zeilen in frei wählbaren Spalten plus Metadatenblatt mit Ziehungsdaten. Das Schreiben erfolgt zunächst in eine temporäre Datei und wird erst danach atomar an den Zielpfad verschoben. |
| Excel-Projektreport | Vier Arbeitsblätter: Projektübersicht, AuditTrail, alle Stichproben und Statistiken mit Diagramm. |
| AuditTrail-PDF | Chronologischer Ereignisnachweis im A4-Querformat; nach Zeitraum und Ereignistyp eingrenzbar, optional mit Statistikseite und Briefpapier. Gesellschaft und Standort sind unabhängig auswählbar. |
| HTML-Report | Eigenständige Datei mit Projektkennzahlen sowie optionalen Diagrammen, AuditTrail und Stichprobenübersicht. Diagramme werden eingebettet, sodass keine zusätzlichen Dateien nötig sind. |

Alle Excel-Exporte behandeln Inhalte aus Daten und Metadaten sicher als Text,
wenn diese wie Excel-Formeln aussehen. Dadurch wird verhindert, dass solche Werte
beim Öffnen der Datei als Formel ausgeführt werden. Alle Exportdialoge teilen sich
eine gemeinsame Zielauswahl mit Dateiname, Kennung, Zielordner und Pfadvorschau;
die erzeugten Dateien benennen Mandant, Kennung, Ausgabetyp und Datum.

### Oberfläche und Betrieb

- PyQt6-Desktop-Oberfläche mit Willkommensansicht, Navigation, Datentabelle,
  Audit-Trail und Dashboard.
- Der Audit-Trail kann nach Aktion, Benutzer und Zeitraum gefiltert sowie per
  Volltext durchsucht werden. Ein Doppelklick auf eine Stichprobenaktion führt
  zur zugehörigen Auswahl in der Datentabelle.
- Das Dashboard zeigt unter anderem Anzahl von Datasets, Stichproben und
  Audit-Ereignissen, eine Methodenverteilung und die jüngsten Aktivitäten.
- Zeitintensive Import- und Exportaufgaben laufen im Worker, damit die Oberfläche
  bedienbar bleibt und ein laufender Vorgang abgebrochen werden kann.
- Einstellbare Ansichtsfunktionen, Tastatur-Shortcuts, Fehlerbericht-Dialog und
  Ersteinrichtungsassistent.
- CI auf Ubuntu, macOS und Windows; lokale Qualitätssicherung mit Pytest, Ruff
  und Mypy.

## Architektur in Kürze

Die Anwendung trennt fachliche Ziehungslogik, lokale Speicherung, Ein-/Ausgabe
und Oberfläche. Dadurch bleibt die Reproduzierbarkeit unabhängig davon, ob eine
Aktion über einen Dialog, einen Worker oder einen Export ausgelöst wird.

| Baustein | Verantwortung |
|---|---|
| `core/` | Fachmodelle, Filtervergleich, Zufallsalgorithmus, Stichprobenverfahren, Vorlagen und Undo-Modelle. Kein Qt, keine SQL, keine I/O. |
| `persistence/` | SQLite-Verbindung, Schema-Migrationen, Repositories für Projekte, Daten, Samples, Audit-Ereignisse und Snapshots. |
| `audit/` | Baut für Benutzeraktionen strukturierte Audit-Ereignisse statt untypisierter Freitexteinträge. |
| `io/` | Liest Excel/CSV ein und erzeugt Excel-, PDF- und HTML-Ausgaben einschließlich Diagrammen und Briefpapier. |
| `ui/` | PyQt6-Fenster, Dialoge und Widgets; Controller koordinieren den Ablauf, Worker führen längere Aufgaben im Hintergrund aus. |

Für die wichtigsten Aktionen folgt der Code einem wiederkehrenden Muster: Ein
Controller nimmt die Eingabe entgegen, prüft die Voraussetzungen (Projekt,
Dataset, aktive Stichprobe), liest über Repositories genau die benötigten Daten
aus SQLite, lässt die Fachlogik in `core/` ein Ergebnis oder eine verständliche
Fehlermeldung liefern und persistiert bei einer Zustandsänderung die fachlichen
Daten und das Audit-Ereignis zusammen. So bleiben Ziehung, Export und Audit-Trail
über denselben Projektzustand verbunden.

### Datenbank und Migrationen

SQLite ist die alleinige Projektpersistenz, mit Foreign-Key-Prüfung und
WAL-Modus. Die Schemaversion wird in der Projektdatei mitgeführt; beim Öffnen
einer gültigen, älteren Datei spielt die Anwendung die vorhandenen SQL-Migrationen
in Versionsreihenfolge atomar ein. Eine read-only Preflight-Prüfung schützt davor,
dass dieser Prozess gegen eine beliebige oder zu neue SQLite-Datei läuft. Details:
[ADR 0003](docs/adr/0003-db-migrationen.md).

## Nachvollziehbarkeit und Schutzmechanismen

Die folgenden Mechanismen sind absichtlich Teil des fachlichen Ablaufs, nicht nur
technische Nebenwirkungen:

| Bereich | Umsetzung im aktuellen Stand | Praktische Wirkung |
|---|---|---|
| Reproduzierbarkeit | Seed, vollständige Sampling-Konfiguration und Algorithmusversion `bdo-v1` werden pro Sample gespeichert; die Eingabe wird vor der Ziehung stabil nach Zeilen-ID geordnet. | Eine Ziehung kann bei unveränderten Eingabedaten mit ihren Parametern erneut durchgeführt werden. |
| Auditierbarkeit | Audit-Ereignisse sind strukturiert und per Datenbank-Trigger gegen Update/Delete geschützt; Korrekturen entstehen als neue Ereignisse mit Verweis auf das Original. | Die Historie bleibt nachvollziehbar, statt nachträglich überschrieben zu werden. |
| Sicheres Öffnen | Eine Datei wird mit SQLite im rein lesenden, unveränderlichen Modus auf Integrität, Tool-Identität und Schemaalter geprüft. | Eine fremde oder beschädigte Datei wird nicht durch Snapshot, WAL-Dateien oder Migration verändert. |
| Versionsstände | Beim Öffnen wird ein schreibgeschützter Snapshot der `.db`-Datei unter `archiv/` angelegt. | Vor einer Sitzung liegt ein wiederherstellbarer Datenbankstand vor. |
| Excel-Schutz | Exportwerte, Spaltennamen und Metadaten werden vor dem Schreiben gegen formelartige Inhalte abgesichert. | Unvertrauenswürdige Daten starten beim Öffnen der Excel-Datei keine Formelberechnung. |
| HTML-Schutz | Der HTML-Report rendert dynamische Inhalte mit aktiviertem Autoescaping. | Inhalte aus Projekt- oder Quelldaten werden nicht als HTML-Markup interpretiert. |

Ein Snapshot ist eine Kopie der Projekt-`.db` vor dem regulären Öffnen und **kein
Ersatz** für eine organisationsweite Backup- oder Aufbewahrungsstrategie. Die
Tamper-Erkennung des Audit-Trails ist bewusst anwendungsseitig und kein
kryptografischer Manipulationsnachweis (siehe
[ADR 0002](docs/adr/0002-anwendungsseitig-append-only-audit-trail.md)).

## Installation für Anwender

Vorgefertigte Bundles für macOS und Windows stehen im
[Release-Bereich](https://github.com/NicoHaider/Sampling-Tool/releases) zur
Verfügung. Python, virtuelle Umgebung und Terminal sind für diese Variante nicht
erforderlich.

Die konkrete Installation ist in [docs/INSTALL_USER.md](docs/INSTALL_USER.md)
beschrieben; die tägliche Nutzung im [Anwender-Handbuch](docs/USER_GUIDE.md) und
Betrieb bzw. Wiederherstellung im [Admin-Handbuch](docs/ADMIN_GUIDE.md).

## Entwicklung

Voraussetzungen: Python **3.13+**, macOS oder Windows.

Empfohlen: [uv](https://docs.astral.sh/uv/) installieren, dann hash-geprüft exakt
aus `uv.lock` synchen – derselbe Weg, den CI und der Release-Build nutzen:

```bash
uv sync --locked --extra dev
git config core.hooksPath .githooks    # optional: lokale Pre-Push-Prüfung

uv run python -m sampling_tool
```

Alternativ klassisch mit `pip` (nutzt die offenen Ranges aus `pyproject.toml`,
nicht die gepinnten Hashes aus `uv.lock`):

```bash
python3.13 -m venv .venv
source .venv/bin/activate               # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m sampling_tool
```

Wichtige Kommandos (mit `uv run` voranstellen bzw. aktiviertem `.venv`):

```bash
pytest                    # Tests mit Coverage
pytest --no-cov           # schneller Testlauf
ruff check .              # Lint
ruff format --check .     # Format prüfen
mypy src tests            # strikter Typcheck
python scripts/demo_full_workflow.py   # End-to-End-Smoke über alle Layer
```

## Build und Release

Für lokale App-Bundles wird PyInstaller verwendet:

```bash
uv sync --locked --extra build
uv run python scripts/build_app.py          # Ausgabe in dist/
uv run python scripts/build_app.py --dmg    # zusätzliches DMG auf macOS
```

Ein Tag nach dem Muster `vX.Y.Z` startet den Release-Workflow für macOS und
Windows und legt einen Draft-Release mit beiden Bundles an. Die Konfigurationen
liegen in `sampling_tool.spec` und `.github/workflows/release.yml`.

## Projektstruktur

```text
src/sampling_tool/
├── core/          Fachmodelle, RNG, Sampling und Undo
├── persistence/   SQLite, Migrationen, Repositories und Snapshots
├── audit/         Anwendungsseitig append-only Audit-Trail
├── io/            Import sowie Excel-, PDF- und HTML-Reports
└── ui/            PyQt6-Fenster, Dialoge, Controller und Worker

scripts/           Build-, Demo- und Performance-Hilfen
tests/             Unit-, Integrations- und UI-Tests
docs/              Anwender-, Installations-, Admin-Doku und ADRs
```

## Weiterführende Dokumentation

- [CHANGELOG.md](CHANGELOG.md) – Sprint-Chronik.
- [CLAUDE.md](CLAUDE.md) – langlebige Architektur- und Konventionen-Referenz.
- [docs/adr/](docs/adr/) – Architecture Decision Records.

## Lizenz

Das Tool selbst ist **proprietär** und wird BDO-intern genutzt.

Die eingebundenen Fremdbibliotheken behalten ihre jeweiligen Lizenzen – die
vollständige Aufstellung des Laufzeit-Sets steht in
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md). PyQt6 ist dabei
GPL-v3-lizenziert; die lizenzrechtliche Einordnung für den aktuellen
(BDO-internen) Nutzungs-Scope steht unter BDO-Legal-Vorbehalt in
[ADR 0004 – PyQt6-Lizenz & Distributions-Scope](docs/adr/0004-pyqt-lizenz-und-distributions-scope.md).
