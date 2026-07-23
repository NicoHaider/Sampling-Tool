# BDO Audit Sampling Tool – Anwender-Handbuch

Dieses Handbuch beschreibt die wichtigsten Arbeitsabläufe für Auditor:innen.
Es ersetzt nicht das interne Methoden-Handbuch, sondern erklärt die
Bedienung der Software. Bezeichnungen und Beschriftungen entsprechen dem
aktuellen Programmstand.

## Inhaltsverzeichnis

1. [Erste Schritte](#1-erste-schritte)
2. [Projekt anlegen und Daten importieren](#2-projekt-anlegen-und-daten-importieren)
3. [Menü und Toolbar im Überblick](#3-menü-und-toolbar-im-überblick)
4. [Stichprobe ziehen: Methode, Größe, Seed](#4-stichprobe-ziehen-methode-größe-seed)
5. [Filter, Nachstichprobe und Vorlagen](#5-filter-nachstichprobe-und-vorlagen)
6. [Ansicht: Markierung, Reset, Undo](#6-ansicht-markierung-reset-undo)
7. [Reports: PDF, Excel, HTML](#7-reports-pdf-excel-html)
8. [Einstellungen und Briefpapier](#8-einstellungen-und-briefpapier)
9. [Zuletzt geöffnete Projekte](#9-zuletzt-geöffnete-projekte)
10. [Tastatur-Shortcuts](#10-tastatur-shortcuts)

---

## 1. Erste Schritte

Beim ersten Start begleitet ein kurzer Einrichtungs-Assistent durch die
Grundeinstellungen (Standard-Ordner und Auditor-Name). Danach – und bei
jedem weiteren Start ohne geladenes Projekt – erscheint der
**Welcome-Screen** mit zwei Aktionen:

- **Neues Projekt** – legt eine frische SQLite-Datei und den zugehörigen
  Projektordner unter dem konfigurierten Projekt-Ordner an
  (Default: `~/Documents/BDO Audit Sampling/`).
- **Bestehende öffnen…** – öffnet eine vorhandene `.db`-Datei.

Darunter listet **Zuletzt geöffnet** die letzten Projekte als anklickbare
Karten. Pro Projekt entsteht ein eigener Unterordner mit der `.db`, einem
`archiv/`-Ordner (automatische Snapshots beim Öffnen) und einem
`exports/`-Ordner für generierte Berichte.

> Hinweis zur Terminologie: In der Oberfläche heißt eine Prüfung durchgängig
> **„Projekt"**. Ältere Beschreibungen sprachen von „Engagement" – gemeint
> ist dasselbe.

## 2. Projekt anlegen und Daten importieren

**Neues Projekt** öffnet den Dialog **Neues Projekt anlegen** mit vier
Pflichtangaben:

| Feld           | Beschreibung                                             |
|----------------|----------------------------------------------------------|
| Auditor-Name   | Wird in jedem Audit-Event protokolliert (vorbelegt mit dem OS-Login). |
| Position       | z. B. „Senior Auditor", „Manager".                       |
| Mandant        | Name des geprüften Unternehmens.                         |
| Prüfungstyp    | Auswahl: **ISAE 3402 Typ 2**, **IDW PS 951** oder **Sonstige** (Freitextfeld). |

Der Button **Speicherort wählen…** ist erst aktiv, wenn alle Felder gefüllt
sind, und öffnet in einem zweiten Schritt den Datei-Dialog für den
Speicherort. Existiert am Ziel bereits ein Projekt, erscheint der Dialog
**Projekt existiert bereits** mit den Optionen **Bestehendes öffnen**
(Default), **Anderen Namen wählen**, **Überschreiben (mit Backup)** und
**Abbrechen**. Beim Überschreiben wird das alte Projekt zuvor automatisch
ins `archiv/`-Verzeichnis gesichert.

Nach dem Speichern landet man im **Workspace** mit Sidebar links und einer
leeren Datentabelle.

### Daten importieren

Über **Bearbeiten → Datei importieren…** (Cmd/Ctrl+I) lassen sich Excel
(`.xlsx`, `.xlsm`) und CSV (`.csv`, `.tsv`) importieren. Saubere Dateien
(ein Blatt, Kopfzeile in Zeile 1) werden ohne Rückfrage importiert.

Braucht der Import eine Entscheidung (mehrere Blätter oder unsichere
Kopfzeilen-Erkennung), öffnet sich der Dialog **Datei importieren** mit:

- **Sheet auswählen** – Blatt-Auswahl bei mehreren Tabellenblättern (bei CSV
  ausgeblendet).
- **Vorschau (erste 20 Zeilen)** – ein Klick auf eine Vorschau-Zeile setzt
  sie als Kopfzeile.
- **Header-Zeile** – alternativ die Kopfzeile numerisch wählen.
- **Keine Kopfzeile – Spaltennamen automatisch vergeben** – vergibt generische
  Namen (`Spalte 1`, `Spalte 2`, …) und behandelt alle Zeilen als Daten.

Danach kann optional eine **ID-Spalte** gewählt werden (Dialog **ID-Spalte
wählen (optional)**). Sie wird pro gezogener Stichprobe in der Sidebar
angezeigt. Die Wahl ist optional, gilt anwendungsweit pro Datensatz und
verändert weder die Daten noch die Reproduzierbarkeit.

## 3. Menü und Toolbar im Überblick

Die Menüleiste gliedert sich in fünf Menüs:

- **Datei** – Neues Projekt…, Projekt öffnen…, Zuletzt geöffnet, Projekt
  schließen, Datensätze aus Ansicht entfernen, Einstellungen…, Beenden.
- **Bearbeiten** – Datei importieren…, Sample exportieren…, AuditTrail-PDF…,
  Excel-Report exportieren…, HTML-Report generieren…
- **Ansicht** – die drei Funktions-Umschalter Filter, Cluster-Sampling und
  Geschichtete Stichprobe (blenden die jeweiligen Funktionen im
  Stichproben-Dialog ein) sowie die Anzeige-Umschalter Dashboard anzeigen
  und Audit-Trail anzeigen.
- **Stichprobe** – Neue Stichprobe…, Vorlagen verwalten…, Auswahl
  zurücksetzen, Rückgängig, Wiederherstellen.
- **Hilfe** – Tastatur-Shortcuts…, Bug melden…, Über…

Die Toolbar bündelt die häufigsten Aktionen. Ganz links liegt **Projekt
wechseln**, rechts die Buttons für **Einstellungen** und **Bug melden**.
Der Button **Sampling zurücksetzen** existiert ausschließlich in der Toolbar
(nicht im Menü) und setzt die gezogene Stichprobe zurück, während
importierte Daten und Parameter erhalten bleiben.

## 4. Stichprobe ziehen: Methode, Größe, Seed

Über **Stichprobe → Neue Stichprobe…** öffnet sich der Konfigurator
**Neue Stichprobe**. Drei Methoden stehen zur Verfügung:

- **Einfach** – n Zeilen rein zufällig (Fisher-Yates, seed-basiert).
- **Cluster** – wählt zufällig k **Cluster** anhand eines Cluster-Felds
  vollständig aus. Die Stichprobengröße bezeichnet hier die **Anzahl der
  Cluster**, nicht der Zeilen; das Sample enthält alle Zeilen der gewählten
  Cluster.
- **Geschichtet** – proportionale Verteilung pro Schicht via
  Largest-Remainder-Methode. Über **Schicht-Verteilung** wählbar zwischen
  **Proportional** (Default) und **Gleich**.

Die Methodenauswahl sowie Cluster-/Schicht-Felder und der Spaltenfilter sind
**erweiterte Funktionen**. Sie erscheinen nur, wenn sie im Menü **Ansicht**
einzeln eingeschaltet sind oder in den Einstellungen der **erweiterte Modus**
aktiviert ist. Ist keine erweiterte Funktion aktiv, läuft der Dialog im
**Einfach-Modus** (Methode fest „Einfach"); ein dezenter Hinweis unten links
erklärt das.

Das Feld **Stichprobengröße** hat kein hartes Limit; darunter zeigt
„max. N verfügbar" die aktuell verfügbare Menge an. Eine zu große oder zu
kleine Eingabe wird beim Bestätigen mit einer Warnung abgefangen.

### Seed und Reproduzierbarkeit

Der **Seed** garantiert Reproduzierbarkeit: gleicher Seed + gleiche Daten →
bit-genau gleiche Stichprobe (ISAE-3402-Anforderung).

> **Wichtig:** Im Stichproben-Dialog ist das Seed-Feld **schreibgeschützt** –
> es zeigt den verwendeten Seed nur an (Transparenz). Der Hinweis daneben
> lautet „in den Einstellungen änderbar". Geändert wird der Seed
> ausschließlich unter **Einstellungen → Erweitert → Sampling-Seed**. Dort
> lässt er sich per **🎲 Würfeln** neu erzeugen; der Sonderwert
> **„Zufällig (bei jeder Ziehung neu)"** (Seed 0) würfelt bei jeder Ziehung
> einen neuen Seed. Einen „Würfel"-Button direkt im Stichproben-Dialog gibt
> es nicht.

## 5. Filter, Nachstichprobe und Vorlagen

### Spaltenfilter

Ist die Funktion **Filter** aktiv (Menü Ansicht bzw. erweiterter Modus),
zeigt der Stichproben-Dialog die Zeile **Filter (optional)**. Ausgewählt
werden ein Feld (Default `(kein Filter)`) und ein Operator:

| Operator          | Eingabe                                             |
|-------------------|-----------------------------------------------------|
| `= (gleich)` / `≠ (ungleich)` | Wert aus einem Dropdown der vorkommenden Werte. |
| `> (größer als)` / `≥ (größer/gleich)` / `< (kleiner als)` / `≤ (kleiner/gleich)` | Freier **Schwellenwert** im Textfeld (`Schwellenwert…`). |

Der Filter schränkt die Population **vor** der Ziehung ein; die Trefferzahl
fließt live in den „max. N verfügbar"-Hinweis ein.

### Nachstichprobe und Einschränken

Zwei Checkboxen steuern, aus welcher Grundmenge gezogen wird (sie schließen
sich gegenseitig aus):

- **Nur aus aktueller Auswahl ziehen (einschränken)** – die nächste Ziehung
  beschränkt sich auf die Zeilen der aktuell aktiven Stichprobe.
- **Ergänzen – bereits gezogene Datensätze ausschließen (Nachstichprobe)** –
  zieht zusätzlich aus der Grundgesamtheit **ohne** die bereits gezogenen
  Datensätze (dublettenfrei). Beide sind nur bei einer aktiven Stichprobe
  wählbar.

### Vorlagen

Wiederkehrende Konfigurationen (Methode, Größe, Filter, Cluster-/Schicht-Feld)
lassen sich als **Vorlage** speichern und projektübergreifend anwenden. Im
Stichproben-Dialog wählt das Dropdown **Vorlagen** eine gespeicherte Vorlage
aus (Platzhalter `(Vorlage wählen…)`); das Anwenden setzt **nur die
Parameter**, zieht nicht und lässt den Seed unangetastet. Angelegt, umbenannt,
dupliziert oder gelöscht werden Vorlagen im Fenster **Vorlagen verwalten**
(Menü **Stichprobe → Vorlagen verwalten…**). Eine Vorlage speichert bewusst
**keinen** Seed und keine Daten.

## 6. Ansicht: Markierung, Reset, Undo

Nach dem Sampling wird die Tabelle automatisch auf die gezogenen Zeilen
gefiltert und grün markiert. Über die Sidebar-Checkbox
**„Nur markierte Zeilen anzeigen"** lässt sich dieser Filter ein- und
ausschalten; ein **Doppelklick** auf eine Stichprobe in der Sidebar setzt
den Filter auf genau diese Stichprobe.

Zum Zurücksetzen gibt es zwei Wege mit bewusst unterschiedlicher Semantik:

- **Stichprobe → Auswahl zurücksetzen** entfernt Stichprobe und Markierung
  (per Einstellung lässt sich der Filter dabei behalten).
- **Sampling zurücksetzen** (Toolbar) setzt die gezogene Stichprobe komplett
  zurück; Population und Parameter bleiben erhalten.

Beide Wege sind **audit-sicher**: Es wird nichts aus der Datenbank gelöscht.
Der Audit-Trail ist **anwendungsseitig append-only** – Einträge werden nur
hinzugefügt, Korrekturen als neue Ereignisse erfasst. Eine identische
Re-Ziehung mit gleichem Seed rekonstruiert die Stichprobe bit-genau.
**Rückgängig** und **Wiederherstellen** (Menü Stichprobe) machen die letzten
Aktionen schrittweise rückgängig bzw. stellen sie wieder her.

## 7. Reports: PDF, Excel, HTML

Vier Export-Pfade stehen im Menü **Bearbeiten** zur Verfügung:

| Export             | Inhalt                                                | Wann nutzen?                          |
|--------------------|-------------------------------------------------------|---------------------------------------|
| Sample exportieren | Ausgewählte Spalten der Stichprobe + Metadaten-Sheet  | Übergabe ans Prüfungsteam.            |
| AuditTrail-PDF     | Projekt-Block + Event-Log (A4-Querformat)             | Ablage in der Akte (Compliance).      |
| Excel-Report       | Multi-Sheet-Bericht (Übersicht, AuditTrail, Samples, Statistiken) | Interne Dokumentation, Archiv. |
| HTML-Report        | Selbstständige HTML-Datei mit eingebetteten Charts    | E-Mail-Versand, schnelle Vorschau.    |

Je Report lässt sich der Inhalt wählen: der **Sample-Export** über
**Zu exportierende Spalten** (mit „Alle auswählen"/„Alle abwählen"); die
**AuditTrail-PDF** über **Aktionstypen**, einen optionalen **Zeitraum**
(Von/Bis, nur wenn in den Einstellungen aktiviert), **BDO-Gesellschaft &
Standort** sowie die Optionen **Briefpapier verwenden** und **Statistik-Seite
anhängen**; der **Excel-Report** über die **Sheets** (Übersicht, AuditTrail,
Samples, Statistiken); der **HTML-Report** über die **Inhalte** (Charts
einbetten, AuditTrail-Tabelle, Samples-Übersicht).

Alle Export-Dialoge teilen sich die rechte Spalte (**Dateiname**, **ID**,
**Zielordner**, **Vorschau Dateiname**). Der Default-Dateiname folgt dem
Muster `{Name}_ID{ID}_BDO_{Typ}_{Datum}` plus Endung, z. B.
`ACME_ID1_BDO_sampling_20260723.xlsx`.

## 8. Einstellungen und Briefpapier

**Datei → Einstellungen…** (Cmd/Ctrl+,) öffnet den Dialog **Einstellungen**
mit drei Tabs:

- **Allgemein** – Standard-Auditor-Name, Projekt-Ordner sowie unter
  **Angezeigte Bereiche** die Schalter „Dashboard anzeigen", „Audit-Trail
  anzeigen" und „ID in Stichprobenliste anzeigen".
- **Reports** – „Reset behält Filter aktiv", „Briefpapier standardmäßig im PDF
  einbetten", „Statistik-Seite standardmäßig anhängen", der Umschalter „Im
  Audit-PDF-Export einen Datumsfilter (von/bis) anbieten", die
  **Briefpapier**-Auswahl (Platzhalter vs. eigene Datei mit Vorschau) und der
  **BDO-Adressblock** (Standard-BDO-Gesellschaft/-Standort).
- **Erweitert** – „Erweiterten Modus aktivieren", „Undo-Tiefe (max.
  Aktionen)", „Log-Level" und das Feld **Sampling-Seed** (die einzige Stelle,
  an der der Seed geändert wird – siehe Abschnitt 4).

Das **Briefpapier-System** sucht in dieser Reihenfolge:

1. Eigene Datei aus den Einstellungen (`custom_briefpapier_path`).
2. User-Override unter `~/Documents/BDO Audit Sampling/briefpapier/
   bdo_letterhead.{png,jpg,jpeg,pdf}`.
3. Mitgeliefertes Platzhalter-PDF (`bdo_placeholder.pdf`).
4. Kein Briefpapier (Reports laufen ohne Layer).

Unterstützte Briefpapier-Formate: PNG, JPG/JPEG und (einseitiges) PDF.

## 9. Zuletzt geöffnete Projekte

Der Welcome-Screen zeigt die zuletzt geöffneten Projekte als Karten; das Menü
**Datei → Zuletzt geöffnet** spiegelt diese Liste. Defekte Pfade
(verschobene/gelöschte Dateien) werden beim nächsten Start automatisch
entfernt.

## 10. Tastatur-Shortcuts

Die meisten Shortcuts folgen dem Betriebssystem-Standard (auf macOS `Cmd`,
auf Windows `Ctrl`); nur „Datei importieren" ist fest auf `Ctrl+I` gelegt.

| Shortcut         | Aktion                  |
|------------------|-------------------------|
| `Cmd/Ctrl+N`     | Neues Projekt           |
| `Cmd/Ctrl+O`     | Projekt öffnen          |
| `Cmd/Ctrl+I`     | Datei importieren       |
| `Cmd/Ctrl+W`     | Projekt schließen       |
| `Cmd/Ctrl+,`     | Einstellungen           |
| `Cmd/Ctrl+Z`     | Rückgängig              |
| OS-Standard (z. B. `⌘⇧Z` / `Ctrl+Y`) | Wiederherstellen |
| `Cmd/Ctrl+Q`     | Beenden                 |

Die Übersicht ist auch über **Hilfe → Tastatur-Shortcuts…** erreichbar.
