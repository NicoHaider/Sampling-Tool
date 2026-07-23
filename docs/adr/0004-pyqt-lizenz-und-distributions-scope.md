# ADR 0004 – PyQt6-Lizenz & Distributions-Scope

- **Status:** Akzeptiert (vorbehaltlich Bestätigung durch BDO-Legal) – 2026-07-23
- **Betrifft:** `sampling_tool.spec` (`datas`), `THIRD_PARTY_LICENSES.md`;
  **keine** `src/`-Logik. Schließt Befund **S-006** (PyQt-Lizenz-Gate) aus dem
  konsolidierten Codebase-Review dokumentarisch.

## Kontext

Das Tool ist proprietär und BDO-intern (siehe [README](../../README.md)) und
baut PyQt6 in doppelklickbare PyInstaller-Bundles ein. Die UI ist an PyQt6
gebunden (kein Web, kein TUI).

**Lizenzlage PyQt6.** Riverbank lizenziert die PyQt-Bindings **dual**: GPL v3
**oder** eine kommerzielle Riverbank-Lizenz – dazwischen liegt nichts
Permissives. Anders als Qt selbst (dessen Bibliotheken unter LGPLv3 stehen und
im Wheel `PyQt6-Qt6` mitkommen) stehen die **PyQt-Bindings** nicht unter LGPL.
Riverbanks FAQ hält fest, dass eine zur GPL inkompatible **proprietäre
Distribution** eine kommerzielle PyQt-Lizenz benötigt.

**Weitere Copyleft-Komponenten (schwach).** Das Laufzeit-Set enthält neben
PyQt6 zwei weitere Copyleft-Komponenten – beide schwach:
- `PyQt6-Qt6` (die Qt-Bibliotheken selbst) unter **LGPL-3.0**,
- `orjson` mit einem **MPL-2.0**-Anteil (`MPL-2.0 AND (Apache-2.0 OR MIT)`;
  dateiweises Copyleft, erstreckt sich nicht auf das „Larger Work").

Der Rest des Laufzeit-Sets ist permissiv (MIT/BSD/Apache/PSF/Zlib/0BSD/CC0).
Die vollständige Aufstellung steht in
[THIRD_PARTY_LICENSES.md](../../THIRD_PARTY_LICENSES.md).

**Scope (der entscheidende Punkt).** Nutzung und Weitergabe erfolgen
**abteilungsintern innerhalb einer einzigen BDO-Gesellschaft** an
Mitarbeitende. Es gibt **keinen** externen Rollout und **keine** Weitergabe an
andere BDO-Gesellschaften oder an Mandanten. Die vom Tool erzeugten Artefakte
(PDF-/Excel-/HTML-Reports) sind von PyQt's Lizenz **nicht** berührt – relevant
wäre allein die Weitergabe **des Programms** selbst.

## Entscheidung

1. **Nutzung unter GPL v3 im internen-Nutzungs-Scope.** Nach etablierter
   GPL-Auslegung (FSF GPL-FAQ, „interne Nutzung") ist die Weitergabe innerhalb
   **einer juristischen Person** an deren Mitarbeitende **keine Distribution /
   kein „conveying"**, sondern interne Nutzung. Damit entsteht für diesen Scope
   **keine** Copyleft-Quelloffenlegungspflicht und es ist **keine** kommerzielle
   PyQt-Lizenz erforderlich.
2. **Schwache Copyleft-Komponenten mitentschieden.** LGPL-3.0 (Qt-Runtime via
   `PyQt6-Qt6`) und der MPL-2.0-Anteil in `orjson` sind ohnehin schwaches
   Copyleft, das mit proprietärer/interner Nutzung vereinbar ist; im
   internen Scope greift auch hier keine „conveying"-Pflicht. Sie ändern die
   Einordnung nicht, werden aber in `THIRD_PARTY_LICENSES.md` ausgewiesen.
3. **Third-Party-Lizenzhinweise werden beigelegt.** `THIRD_PARTY_LICENSES.md`
   führt das reale Laufzeit-Set (Name + Version + Lizenz) auf und wird über
   `sampling_tool.spec` (`datas`) ins Frozen-Bundle gebündelt, damit verteilte
   Kopien die Hinweise mitführen.
4. **Kein Framework-Wechsel, keine gekaufte Lizenz, keine Quelloffenlegung** für
   diesen Scope – alles unnötig für die interne Nutzung innerhalb einer
   Gesellschaft.

## Konsequenzen

- **Auslöser für Neubewertung.** Eine Weitergabe an eine **andere**
  BDO-Gesellschaft, an **Mandanten** oder **extern** bzw. ein öffentlicher
  Rollout verlässt diesen Scope und erzwingt eine Neubewertung – dann stehen
  drei Wege offen:
  1. **GPL-Compliance** (Quelloffenlegung des verteilten Werks),
  2. **kommerzielle PyQt-Lizenz** (abgedeckte Entwickler/Versionen, Bezugskanal
     der Release-Artefakte dokumentieren),
  3. **Wechsel auf PySide6 (LGPL)** – rechtlich passend, aber ein eigenes,
     deutlich größeres Vorhaben; die Sampling-Engine bliebe dabei unberührt.
  Bei externer Verteilung sind zusätzlich die schwachen Copyleft-Komponenten zu
  bedienen (LGPL: Relink-/Austausch-Möglichkeit der Qt-Bibliotheken + Notice;
  MPL-2.0: Quelle der betroffenen orjson-Dateien anbieten).
- **Auslöser (Dependency-Seite).** Diese Disposition ist an das aktuelle reale
  Laufzeit-Set gepinnt. Eine materielle Änderung dieses Sets – insbesondere eine
  neue Abhängigkeit unter **Netzwerk-Copyleft** (AGPL/SSPL, deren Pflichten schon
  bei der bloßen Nutzung und nicht erst bei „conveying" greifen können) oder
  zusätzliches starkes Copyleft – erfordert nicht nur ein Neugenerieren von
  [THIRD_PARTY_LICENSES.md](../../THIRD_PARTY_LICENSES.md), sondern ein erneutes
  Durchdenken dieser Einordnung.
- **BDO-Legal-Bestätigung ausstehend.** Die Einordnung „eine Gesellschaft /
  interne Nutzung" ist **Voraussetzung** dieser Disposition und muss von
  BDO-Legal bestätigt werden; solange dies aussteht (siehe Status), gilt die
  Disposition ausdrücklich unter Vorbehalt. Diese ADR ist eine **dokumentierte
  Disposition unter Vorbehalt**, keine Rechtsauskunft.
- Die Disposition **überklärt nichts**: Sie stellt keine „garantierte
  Konformität" fest, sondern hält die getroffene Einordnung samt ihrer
  Randbedingungen und Auslöser fest.

## Referenzen

- FSF GPL-FAQ, „Is making and using multiple copies within one organization or
  company 'distribution'?": <https://www.gnu.org/licenses/gpl-faq.html#InternalDistribution>
- Riverbank PyQt License FAQ: <https://riverbankcomputing.com/commercial/license-faq>
- [THIRD_PARTY_LICENSES.md](../../THIRD_PARTY_LICENSES.md) – reales Laufzeit-Lizenzset.
- [ADR-Übersicht](README.md); Format/Nummerierung analog [ADR 0003](0003-db-migrationen.md).
