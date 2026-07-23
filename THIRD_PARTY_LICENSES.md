# Third-Party-Lizenzen

Lizenzinventar der **Laufzeit-Abhängigkeiten** des BDO Audit Sampling Tools.
Das Tool selbst ist proprietär und BDO-intern (siehe [README](README.md#lizenz));
diese Datei betrifft ausschließlich die mit dem Tool gebündelten Fremdbibliotheken.

Die lizenzrechtliche Einordnung dieses Abhängigkeits-Sets für den aktuellen
Nutzungs-/Distributions-Scope steht in
[ADR 0004 – PyQt6-Lizenz & Distributions-Scope](docs/adr/0004-pyqt-lizenz-und-distributions-scope.md).
Alle Aussagen dort stehen unter **BDO-Legal-Vorbehalt**.

> **Stand:** Abgeleitet aus dem gelockten Laufzeit-Set (`uv.lock`), Tool-Version
> 0.8.0. Bei Dependency-Änderungen neu generieren (siehe unten).

## Copyleft-Hinweis (das Wichtigste zuerst)

Das Laufzeit-Set ist – bis auf drei Komponenten – durchgängig permissiv
(MIT/BSD/Apache/PSF/Zlib/0BSD/CC0). Die drei Copyleft-Komponenten:

| Komponente | Lizenz | Copyleft-Charakter | Relevanz |
|---|---|---|---|
| **PyQt6** | **GPL-3.0-only** | **stark** (ganzes Werk) | Dual-lizenziert GPLv3 **oder** kommerzielle Riverbank-Lizenz. **Treibt** die Disposition in [ADR 0004](docs/adr/0004-pyqt-lizenz-und-distributions-scope.md). |
| PyQt6-Qt6 (die Qt-Bibliotheken selbst) | LGPL-3.0 | schwach (dynamisch gelinkt) | Die Qt-Runtime steht – anders als die PyQt-Bindings – unter LGPLv3. Kompatibel mit proprietärer/interner Nutzung (Ersetz-/Relink-Möglichkeit). |
| orjson | `MPL-2.0 AND (Apache-2.0 OR MIT)` | schwach (dateiweise) | Der Kern ist Apache-2.0/MIT; ein Teil enthält MPL-2.0-Code. MPL greift nur dateiweise und erstreckt sich nicht auf das „Larger Work". |

Für den in [ADR 0004](docs/adr/0004-pyqt-lizenz-und-distributions-scope.md)
dokumentierten Scope (**Nutzung/Weitergabe abteilungsintern innerhalb einer
einzigen BDO-Gesellschaft**, kein externer Rollout) löst keine dieser drei
Komponenten eine Quelloffenlegungspflicht aus: Die interne Weitergabe innerhalb
**einer juristischen Person** ist nach etablierter GPL-Auslegung keine
Distribution/„conveying", und LGPL-3.0 wie MPL-2.0 sind ohnehin schwaches
Copyleft, das mit proprietärer Nutzung vereinbar ist. Die Auslöser für eine
Neubewertung stehen in ADR 0004.

## Direkte Laufzeit-Abhängigkeiten

Das in `pyproject.toml` deklarierte `dependencies`-Set:

| Paket | Version | Lizenz |
|---|---|---|
| **PyQt6** | 6.11.0 | **GPL-3.0-only** ⚠️ (oder kommerzielle Riverbank-Lizenz) |
| Jinja2 | 3.1.6 | BSD-3-Clause |
| matplotlib | 3.11.1 | Matplotlib-Lizenz (PSF-basiert, BSD-artig, permissiv) |
| numpy | 2.5.1 | `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0` |
| openpyxl | 3.1.5 | MIT |
| orjson | 3.11.9 | `MPL-2.0 AND (Apache-2.0 OR MIT)` ⚠️ (schwaches, dateiweises Copyleft) |
| pillow | 12.3.0 | MIT-CMU (HPND, permissiv) |
| platformdirs | 4.10.1 | MIT |
| pypdf | 6.14.2 | BSD-3-Clause |
| python-calamine | 0.8.2 | MIT |
| reportlab | 5.0.0 | BSD-3-Clause |

## Transitive Laufzeit-Abhängigkeiten

Von den direkten Abhängigkeiten mitgezogen (Laufzeit, ohne dev/build-Extras):

| Paket | Version | Lizenz |
|---|---|---|
| **PyQt6-Qt6** | 6.11.1 | **LGPL-3.0** ⚠️ (die Qt-Bibliotheken; schwaches Copyleft) |
| PyQt6-sip | 13.11.1 | BSD-2-Clause |
| charset-normalizer | 3.4.9 | MIT |
| contourpy | 1.3.3 | BSD-3-Clause |
| cycler | 0.12.1 | BSD-3-Clause |
| et_xmlfile | 2.0.0 | MIT |
| fonttools | 4.63.0 | MIT |
| kiwisolver | 1.5.0 | BSD-3-Clause |
| MarkupSafe | 3.0.3 | BSD-3-Clause |
| packaging | 26.2 | `Apache-2.0 OR BSD-2-Clause` |
| pyparsing | 3.3.2 | MIT |
| python-dateutil | 2.9.0.post0 | Apache-2.0 / BSD-3-Clause (dual, permissiv) |
| six | 1.17.0 | MIT |

**24 Laufzeit-Pakete gesamt** (11 direkt, 13 transitiv). Die vollständigen
Lizenztexte liegen in den `*.dist-info/`-Verzeichnissen der jeweils gelockten
Wheels (siehe `uv.lock`).

## Diese Datei neu generieren

Bei jeder Dependency-Änderung (`pyproject.toml`/`uv.lock`) neu erzeugen. Ein
Rohinventar liefert `pip-licenses` gegen die gelockte Umgebung:

```bash
uv run --with pip-licenses pip-licenses \
  --format=markdown --with-urls --order=license
```

Die hier eingetragenen Lizenz-Identifier sind zusätzlich gegen die
`License-Expression`/`License`/`Classifier`-Metadaten jeder installierten
Distribution (`importlib.metadata`) abgeglichen – `pip-licenses` liest nur das
`Classifier`-Feld und meldet z. B. für PyQt6 (nur `License-Expression`) sonst
`UNKNOWN`. Die drei Copyleft-Komponenten (PyQt6 = GPL-3.0-only,
PyQt6-Qt6 = LGPL-3.0, orjson = MPL-2.0-Anteil) wurden manuell verifiziert und
sind oben hervorgehoben; ihre Einordnung steht in
[ADR 0004](docs/adr/0004-pyqt-lizenz-und-distributions-scope.md).
