# Performance-Probe

Datum: 2026-05-15T04:29:53
Maschine: Darwin 25.3.0 (arm64), Python 3.13.13
Toolversion: 5ba161a
psutil RSS-Cross-Check: aus

## Soft-Targets (1M Zeilen)

| Phase | Target |
|-------|-------:|
| Import | < 60 s |
| DB-Speicherung | < 30 s |
| Tabelle-Anzeige | < 5 s |
| Sampling Simple | < 10 s |
| Sampling Cluster | < 15 s |
| Sampling Stratified | < 15 s |
| Filter-Toggle (an) | < 2 s |
| Filter-Toggle (aus) | < 2 s |
| Highlight | < 2 s |
| Excel-Export (Sample) | < 60 s |
| Excel-Report (Multi-Sheet) | < 60 s |
| HTML-Report | < 30 s |
| AuditTrail-PDF | < 30 s |

Bei kleineren Größen werden Targets linear skaliert (z. B. 30 s/M → 3 s/100k); reine Heuristik.

## Messung 10,000 Zeilen

| Phase | Zeit | Peak (tracemalloc) | RSS-Delta | Anmerkung |
|-------|-----:|-------------------:|----------:|-----------|
| Setup (xlsx generieren) | 4.66 s | 1.8 MB | — | 0.8 MB |
| Import | 2.83 s | 13.1 MB | — | 10,000 rows, 0 skipped |
| DB-Speicherung | 0.39 s | 5.5 MB | — |  |
| Tabelle-Anzeige | 0.43 s | 616 KB | — |  |
| Sampling Simple | 0.03 s | 244 KB | — | 500 rows |
| Sampling Cluster | 1.9 ms | 286 KB | — | 4933 rows |
| Sampling Stratified | 0.03 s | 276 KB | — | 500 rows |
| Filter-Toggle (an) | 2.2 ms | 50 KB | — |  |
| Filter-Toggle (aus) | 1.6 ms | 383 KB | — |  |
| Highlight | 2.2 ms | 40 KB | — |  |
| Clear-Highlight | 0.1 ms | 1 KB | — |  |
| Excel-Export (Sample) | 0.14 s | 1.5 MB | — |  |
| Excel-Report (Multi-Sheet) | 0.12 s | 1.4 MB | — |  |
| HTML-Report | 0.24 s | 2.0 MB | — |  |
| AuditTrail-PDF | 13.54 s | 67.7 MB | — | 5000 events, 0.5 MB |

## Messung 100,000 Zeilen

| Phase | Zeit | Peak (tracemalloc) | RSS-Delta | Anmerkung |
|-------|-----:|-------------------:|----------:|-----------|
| Setup (xlsx generieren) | 47.23 s | 14.2 MB | — | 8.1 MB |
| Import | 28.92 s | 121.3 MB | — | 100,000 rows, 0 skipped |
| DB-Speicherung | 3.76 s | 55.3 MB | — |  |
| Tabelle-Anzeige | 0.37 s | 3.8 MB | — |  |
| Sampling Simple | 0.34 s | 2.3 MB | — | 500 rows |
| Sampling Cluster | 0.02 s | 2.8 MB | — | 49916 rows |
| Sampling Stratified | 0.35 s | 2.7 MB | — | 500 rows |
| Filter-Toggle (an) | 0.02 s | 50 KB | — |  |
| Filter-Toggle (aus) | 0.02 s | 3.8 MB | — |  |
| Highlight | 2.3 ms | 40 KB | — |  |
| Clear-Highlight | 0.1 ms | 1 KB | — |  |
| Excel-Export (Sample) | 0.14 s | 1.5 MB | — |  |
| Excel-Report (Multi-Sheet) | 0.09 s | 984 KB | — |  |
| HTML-Report | 0.25 s | 2.0 MB | — |  |
| AuditTrail-PDF | 13.24 s | 67.3 MB | — | 5000 events, 0.5 MB |

## Messung 1,000,000 Zeilen

| Phase | Zeit | Peak (tracemalloc) | RSS-Delta | Anmerkung |
|-------|-----:|-------------------:|----------:|-----------|
| Setup (xlsx generieren) | 7.78 min | 141.2 MB | — | 81.4 MB |
| Import | 4.83 min | 1214.3 MB | — | 1,000,000 rows, 0 skipped |
| DB-Speicherung | 37.51 s | 554.9 MB | — |  |
| Tabelle-Anzeige | 0.50 s | 38.1 MB | — |  |
| Sampling Simple | 3.53 s | 22.9 MB | — | 500 rows |
| Sampling Cluster | 0.16 s | 27.3 MB | — | 499827 rows |
| Sampling Stratified | 3.61 s | 26.1 MB | — | 500 rows |
| Filter-Toggle (an) | 0.21 s | 50 KB | — |  |
| Filter-Toggle (aus) | 0.15 s | 38.1 MB | — |  |
| Highlight | 3.1 ms | 40 KB | — |  |
| Clear-Highlight | 0.1 ms | 1 KB | — |  |
| Excel-Export (Sample) | 0.16 s | 1.5 MB | — |  |
| Excel-Report (Multi-Sheet) | 0.09 s | 983 KB | — |  |
| HTML-Report | 0.24 s | 2.0 MB | — |  |
| AuditTrail-PDF | 13.41 s | 67.3 MB | — | 5000 events, 0.5 MB |

## Soft-Target-Verfehlungen (Sprint-10.2-Kandidaten)

| Größe | Phase | Gemessen | Skaliertes Target | Überschreitung |
|------:|-------|---------:|------------------:|---------------:|
| 10,000 | AuditTrail-PDF | 13.54 s | 3.00 s | +10.54 s |
| 100,000 | Import | 28.92 s | 6.00 s | +22.92 s |
| 100,000 | DB-Speicherung | 3.76 s | 3.00 s | +0.76 s |
| 100,000 | AuditTrail-PDF | 13.24 s | 3.00 s | +10.24 s |
| 1,000,000 | Import | 4.83 min | 1.00 min | +3.83 min |
| 1,000,000 | DB-Speicherung | 37.51 s | 30.00 s | +7.51 s |

## Auffälligkeiten

### Klare Bottlenecks (Sprint-10.2 priorisieren)

1. **Excel-Import skaliert ~linear, aber viel zu hoch.**
   10k → 2.8 s · 100k → 29 s · 1M → **4.83 min** (Target 60 s).
   Peak RAM bei 1M: **1.2 GB** trotz `openpyxl read_only`. Der
   Importer baut `Dataset` als immutable `tuple[DatasetRow, ...]` mit
   `dict[str, Any]` pro Row – pro 1M Rows ca. 15 × 1M Dict-Entries +
   Python-Object-Overhead, was das RAM-Profil erklärt.
   Ansatzpunkte 10.2: (a) `Dataset` als spalten-orientierte Numpy-/
   Arrow-Struktur, (b) Importer auf echtes Streaming umstellen
   (Generator → DB direkt, kein voller In-Memory-Materialize), (c)
   Progress-Callback-Frequenz prüfen.

2. **DB-Speicherung knapp über Target bei 1M.**
   10k → 0.39 s · 100k → 3.76 s · 1M → 37.5 s (Target 30 s).
   `executemany` ist bereits aktiv – die Restzeit dürfte
   `_values_to_json` pro Row sein (tagged JSON-Encoder, kein
   C-Beschleuniger). Peak RAM 555 MB = Listcomp baut alle Tuples
   vor dem `executemany`-Call auf.
   Ansatzpunkte 10.2: (a) Generator-basierter `executemany`-Feed
   statt Listcomp, (b) `PRAGMA synchronous=OFF` während Bulk-Insert,
   (c) Encoder ggf. via `orjson`.

3. **AuditTrail-PDF konstant ~13 s bei 5 000 Events.**
   Skaliert nicht mit Dataset-Größe (gut), aber 5 000 Events sind
   ein realistischer Quartal-Wert und 13 s ist subjektiv langsam.
   Peak RAM 67 MB – Reportlab hält alle Flowables im Speicher.
   Ansatzpunkte 10.2: (a) Tabelle in Chunks von 500 Rows aufteilen,
   (b) optionalen "kompakten" Modus ohne `Paragraph`-Wrap pro
   Zelle anbieten.

### Unkritisch / im Target

- **Tabelle-Anzeige** bleibt selbst bei 1M unter 1 s – das
  `QAbstractTableModel`-Design (virtuelles Model, `_visible_indices`)
  zahlt sich aus.
- **Sampling** (Simple/Stratified) bei 1M ≈ 3.5 s, Cluster fast
  instant. `numpy.random.default_rng` + Fisher-Yates skaliert
  problemlos.
- **Filter-/Highlight-Toggles** bleiben durchgängig im ms-Bereich –
  Set-Lookup im `BackgroundRole` ist ausreichend.
- **Excel-Export Sample** bleibt bei 0.16 s, weil nur 500 Sample-Rows
  geschrieben werden – unabhängig von der Dataset-Größe.
- **HTML-/Multi-Sheet-Report**: <0.3 s, weil sie keine Dataset-Rows
  rendern, sondern nur Engagement-Metadaten + Sample-Übersicht.

### Bekannte Schwächen der Heuristik

- Die "Soft-Target-Verfehlungen"-Tabelle skaliert Targets linear mit
  Dataset-Größe. Das passt für Import/DB, aber NICHT für
  `AuditTrail-PDF` (Aufwand hängt an Event-Anzahl, nicht an
  Rows). Die `10k → AuditTrail-PDF`-Verfehlung ist daher kein
  echter Befund – die Phase liegt bei jeder Größe konstant bei
  ≈13 s, also weit unter dem 30 s-Target bei 1M.

### Out of Scope / nicht der App anzulasten

- **Setup (xlsx generieren)** dauert bei 1M Zeilen 7.78 min. Das ist
  reine Test-Infrastruktur (openpyxl write_only mit 15 Spalten und
  datetime-Zellen) und kommt im echten App-Pfad nicht vor.
- **5M-Lauf** wurde nicht ausgeführt – Setup würde bei aktueller
  Rate ~40 min und Import den Peak-RAM des Test-Hosts vermutlich
  sprengen (1M = 1.2 GB linear → 6 GB). Erst nach Import-Refactor in
  Sprint 10.2 sinnvoll.

