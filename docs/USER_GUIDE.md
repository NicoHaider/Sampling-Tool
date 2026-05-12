# BDO Audit Sampling Tool – Anwender-Handbuch

Dieses Handbuch beschreibt die wichtigsten Arbeitsabläufe für Auditoren.
Es ersetzt nicht das interne Methoden-Handbuch, sondern erklärt die
Bedienung der Software.

## Inhaltsverzeichnis

1. [Erste Schritte](#1-erste-schritte)
2. [Engagement anlegen und Daten importieren](#2-engagement-anlegen-und-daten-importieren)
3. [Sampling-Methoden im Detail](#3-sampling-methoden-im-detail)
4. [Filter und Resampling](#4-filter-und-resampling)
5. [Reports: PDF, Excel, HTML](#5-reports-pdf-excel-html)
6. [Einstellungen und Briefpapier](#6-einstellungen-und-briefpapier)
7. [Recent-Engagements](#7-recent-engagements)
8. [Tastatur-Shortcuts](#8-tastatur-shortcuts)

---

## 1. Erste Schritte

Beim ersten Start zeigt die App den **Welcome-Screen** mit zwei Optionen:

- **Neues Engagement anlegen** – legt eine frische SQLite-Datei und das
  Engagement-Verzeichnis unter dem konfigurierten Engagement-Ordner an
  (Default: `~/Documents/BDO Audit Sampling/`).
- **Engagement öffnen** – öffnet eine bestehende `.db`-Datei.

Pro Engagement entsteht ein eigener Unterordner mit der `.db`, einem
`archiv/`-Ordner (Auto-Snapshots) und einem `exports/`-Ordner für
generierte Berichte.

## 2. Engagement anlegen und Daten importieren

Der Dialog **Neues Engagement** verlangt vier Pflichtangaben:

| Feld           | Beschreibung                                             |
|----------------|----------------------------------------------------------|
| Auditor-Name   | Wird in jedem Audit-Event protokolliert.                 |
| Position       | z. B. „Senior Auditor", „Manager".                       |
| Mandant        | Name des geprüften Unternehmens.                         |
| Prüfungstyp    | ISAE 3402 Typ 2 / IDW PS 951 / Sonstige (Freitext).      |

Nach dem Speichern landet man im **Workspace** mit Sidebar links und
einer leeren Datentabelle.

Mit **Datei → Datei importieren…** (Cmd/Ctrl+I) lassen sich Excel
(`.xlsx`, `.xlsm`) und CSV (`.csv`, `.tsv`) importieren. Der Importer
erkennt Header automatisch, unterstützt mehrere Encodings und meldet
übersprungene Leerzeilen am Ende.

## 3. Sampling-Methoden im Detail

Über **Stichprobe → Neue Stichprobe…** öffnet sich der Konfigurator.
Drei Methoden stehen zur Verfügung:

- **Einfach (Simple)** – n Zeilen rein zufällig (Fisher-Yates, seed-basiert).
- **Cluster** – wählt zufällig k Cluster komplett aus. Die Cluster-Spalte
  wird ausgewählt; das Sample enthält alle Zeilen aller gewählten Cluster.
- **Geschichtet (Stratified)** – proportionale Verteilung pro Schicht via
  Largest-Remainder. Optional gleichmäßige Schicht-Größen.

Der **Seed** garantiert Reproduzierbarkeit: gleicher Seed + gleiches
Dataset → bit-identische Stichprobe. Der Würfel-Button generiert einen
neuen zufälligen Seed.

Die Checkbox **„Nur aus aktuellem Sample ziehen"** ermöglicht
Resampling: das nächste Sampling beschränkt sich auf die Zeilen des
aktuell aktiven Samples.

## 4. Filter und Resampling

Nach dem Sampling wird die Tabelle automatisch auf die gezogenen Zeilen
gefiltert und die grüne Sample-Markierung gesetzt. Über die Sidebar-
Checkbox **„Nur markierte Zeilen anzeigen"** lässt sich der Filter
ein- und ausschalten.

**Doppelklick** auf ein Sample in der Sidebar setzt den Filter auf
genau dieses Sample. **Reset** (Stichprobe → Auswahl zurücksetzen)
entfernt Sample und Filter; per Setting lässt sich das Verhalten so
einstellen, dass der Filter aktiv bleibt.

## 5. Reports: PDF, Excel, HTML

Vier Export-Pfade stehen zur Verfügung:

| Export             | Inhalt                                                | Wann nutzen?                          |
|--------------------|-------------------------------------------------------|---------------------------------------|
| Sample (Excel)     | Die ausgewählten Zeilen + Metadaten-Sheet            | Übergabe ans Prüfungsteam.            |
| AuditTrail-PDF     | Engagement-Block + komplettes Event-Log              | Ablage in der Akte (Compliance).      |
| Excel-Report       | Multi-Sheet-Komplettbericht (Übersicht/Trail/Samples)| Interne Dokumentation, Archiv.        |
| HTML-Report        | Selbstständige HTML-Datei mit Inline-Charts           | E-Mail-Versand, schnelle Vorschau.    |

Alle Export-Dialoge teilen sich die rechte Spalte (Dateiname / ID /
Zielordner / Vorschau). Der Default-Dateiname folgt dem Schema
`{Mandant}_ID{ID}_BDO_sampling_{YYYYMMDD}.xlsx`.

Für PDF/Excel-/HTML-Reports kann individuell entschieden werden, welche
Inhalte einbettet werden (Briefpapier-Layer, Statistik-Seite, Charts,
AuditTrail-Tabelle, Samples-Übersicht).

## 6. Einstellungen und Briefpapier

**Datei → Einstellungen…** (Cmd/Ctrl+,) öffnet einen 3-Tab-Dialog:

- **Allgemein** – Standard-Auditor-Name (für den Neu-Engagement-Dialog),
  Engagement-Ordner.
- **Reports** – Default-Verhalten für PDF-Exports (Briefpapier ein/aus,
  Statistik-Seite ein/aus), Reset-Verhalten (Filter behalten oder
  vollständig entfernen), Briefpapier-Auswahl (Platzhalter vs. eigene
  Datei mit Vorschau).
- **Erweitert** – Undo-Tiefe, Snapshot-Retention, Log-Level.

Das **Briefpapier-System** sucht in dieser Reihenfolge:

1. Eigene Datei aus den Settings (`custom_briefpapier_path`).
2. User-Override unter `~/Documents/BDO Audit Sampling/briefpapier/
   bdo_letterhead.{png,jpg,jpeg,pdf}`.
3. Mitgeliefertes Platzhalter-PDF (`bdo_placeholder.pdf`).
4. Kein Briefpapier (Reports laufen ohne Layer).

## 7. Recent-Engagements

Der Welcome-Screen zeigt die zuletzt geöffneten Engagements als Karten;
das Menü **Datei → Zuletzt geöffnet** spiegelt diese Liste. Defekte
Pfade (verschobene/gelöschte Dateien) werden beim nächsten Start
automatisch entfernt.

## 8. Tastatur-Shortcuts

Auf macOS ist `Cmd`, auf Windows `Ctrl` der Modifier.

| Shortcut         | Aktion                  |
|------------------|-------------------------|
| `Cmd/Ctrl+N`     | Neues Engagement        |
| `Cmd/Ctrl+O`     | Engagement öffnen       |
| `Cmd/Ctrl+I`     | Datei importieren       |
| `Cmd/Ctrl+W`     | Engagement schließen    |
| `Cmd/Ctrl+,`     | Einstellungen           |
| `Cmd/Ctrl+Z`     | Rückgängig              |
| `Cmd/Ctrl+Shift+Z` | Wiederherstellen      |
| `Cmd/Ctrl+Q`     | Beenden                 |

Die Übersicht ist auch über **Hilfe → Tastatur-Shortcuts…** erreichbar.
