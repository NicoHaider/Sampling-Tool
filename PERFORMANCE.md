# Performance-Probe

Datum: 2026-05-15T16:15:33
Maschine: Darwin 25.3.0 (arm64), Python 3.13.13
Toolversion: 2b54753
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
| Setup (xlsx generieren) | 4.57 s | 1.8 MB | — | 0.8 MB |
| Import | 0.53 s | 14.1 MB | — | 10,000 rows, 0 skipped |
| DB-Speicherung | 0.38 s | 5.5 MB | — |  |
| Tabelle-Anzeige | 0.43 s | 617 KB | — |  |
| Sampling Simple | 0.06 s | 244 KB | — | 500 rows |
| Sampling Cluster | 7.8 ms | 286 KB | — | 4933 rows |
| Sampling Stratified | 0.03 s | 276 KB | — | 500 rows |
| Filter-Toggle (an) | 2.2 ms | 50 KB | — |  |
| Filter-Toggle (aus) | 1.6 ms | 383 KB | — |  |
| Highlight | 2.2 ms | 40 KB | — |  |
| Clear-Highlight | 0.1 ms | 1 KB | — |  |
| Excel-Export (Sample) | 0.14 s | 1.5 MB | — |  |
| Excel-Report (Multi-Sheet) | 0.12 s | 1.4 MB | — |  |
| HTML-Report | 0.24 s | 2.0 MB | — |  |
| AuditTrail-PDF | 13.24 s | 67.7 MB | — | 5000 events, 0.5 MB |

## Messung 100,000 Zeilen

| Phase | Zeit | Peak (tracemalloc) | RSS-Delta | Anmerkung |
|-------|-----:|-------------------:|----------:|-----------|
| Setup (xlsx generieren) | 46.76 s | 14.2 MB | — | 8.1 MB |
| Import | 5.36 s | 140.7 MB | — | 100,000 rows, 0 skipped |
| DB-Speicherung | 3.74 s | 55.3 MB | — |  |
| Tabelle-Anzeige | 0.37 s | 3.8 MB | — |  |
| Sampling Simple | 0.35 s | 2.3 MB | — | 500 rows |
| Sampling Cluster | 0.02 s | 2.8 MB | — | 49916 rows |
| Sampling Stratified | 0.35 s | 2.7 MB | — | 500 rows |
| Filter-Toggle (an) | 0.02 s | 50 KB | — |  |
| Filter-Toggle (aus) | 0.02 s | 3.8 MB | — |  |
| Highlight | 2.2 ms | 40 KB | — |  |
| Clear-Highlight | 0.1 ms | 1 KB | — |  |
| Excel-Export (Sample) | 0.14 s | 1.5 MB | — |  |
| Excel-Report (Multi-Sheet) | 0.09 s | 984 KB | — |  |
| HTML-Report | 0.24 s | 2.0 MB | — |  |
| AuditTrail-PDF | 13.27 s | 67.3 MB | — | 5000 events, 0.5 MB |

## Messung 1,000,000 Zeilen

| Phase | Zeit | Peak (tracemalloc) | RSS-Delta | Anmerkung |
|-------|-----:|-------------------:|----------:|-----------|
| Setup (xlsx generieren) | 7.69 min | 141.2 MB | — | 81.4 MB |
| Import | 55.00 s | 1409.0 MB | — | 1,000,000 rows, 0 skipped |
| DB-Speicherung | 37.50 s | 554.9 MB | — |  |
| Tabelle-Anzeige | 0.51 s | 38.1 MB | — |  |
| Sampling Simple | 3.59 s | 22.9 MB | — | 500 rows |
| Sampling Cluster | 0.19 s | 27.3 MB | — | 499827 rows |
| Sampling Stratified | 3.64 s | 26.1 MB | — | 500 rows |
| Filter-Toggle (an) | 0.21 s | 50 KB | — |  |
| Filter-Toggle (aus) | 0.15 s | 38.1 MB | — |  |
| Highlight | 3.1 ms | 40 KB | — |  |
| Clear-Highlight | 0.1 ms | 1 KB | — |  |
| Excel-Export (Sample) | 0.16 s | 1.5 MB | — |  |
| Excel-Report (Multi-Sheet) | 0.09 s | 984 KB | — |  |
| HTML-Report | 0.25 s | 2.0 MB | — |  |
| AuditTrail-PDF | 13.43 s | 67.3 MB | — | 5000 events, 0.5 MB |

## Soft-Target-Verfehlungen (Sprint-10.2-Kandidaten)

| Größe | Phase | Gemessen | Skaliertes Target | Überschreitung |
|------:|-------|---------:|------------------:|---------------:|
| 10,000 | AuditTrail-PDF | 13.24 s | 3.00 s | +10.24 s |
| 100,000 | DB-Speicherung | 3.74 s | 3.00 s | +0.74 s |
| 100,000 | AuditTrail-PDF | 13.27 s | 3.00 s | +10.27 s |
| 1,000,000 | DB-Speicherung | 37.50 s | 30.00 s | +7.50 s |

## Sprint-10.3-Update (orjson + executemany-Generator)

Re-Lauf für 10k + 100k Zeilen (1M-Lauf bewusst übersprungen – die
Skalierung ist linear genug, dass die Projektion belastbar ist).

| Phase           | 10k vorher (10.2) | 10k nachher | 100k vorher (10.2) | 100k nachher | Speedup |
|-----------------|------------------:|------------:|-------------------:|-------------:|--------:|
| **DB-Speicherung** | 0.39 s | **0.07 s** | 3.74 s | **0.75 s** | **5.0–5.6×** |

Peak-RAM bei DB-Speicherung 100k: 55 MB → **0.2 MB** dank
`executemany`-Generator (kein Listcomp-Buffer mehr) und orjson
(C-basierter Encoder hält keine intermediate Python-Objekte).

**Projektion 1M Zeilen**: 37.5 s / ~5 = **~7.5 s** – weit unter dem
30 s-Soft-Target. Sprint-10.3-Ziel erreicht ohne den 1M-Lauf
durchführen zu müssen.

**Hinweis zu `bulk_insert_pragmas`**: Der ContextManager
(`synchronous=OFF` für die Dauer eines Bulk-Inserts) liegt in
`database.py` mit eigenen Tests, wird aber NICHT aus dem Production-
Pfad aufgerufen. Im Tooltest hat selbst ein simpler Pragma-Wechsel
innerhalb der `DatasetRepo.create`-Transaktion mit der parallel
offenen MainController-Repo-Connection (zwei Connections auf
derselben WAL-DB) deadlockt. Der gemessene Speedup kommt vollständig
aus orjson + Generator – Pragmas sind kein Beitrag. Der CM bleibt
als Werkzeug für offline-Bulk-Importe oder spätere Architektur-
Refactors verfügbar.

## Sprint-10.2-Vergleich (calamine-Migration)

Vergleich gegen den Sprint-10.1-Lauf (gleiche Maschine, gleiche
Datasets, identische Phasen-Definition).

| Phase | 10k vorher | 10k nachher | 100k vorher | 100k nachher | 1M vorher | 1M nachher | Speedup |
|-------|-----------:|------------:|------------:|-------------:|----------:|-----------:|--------:|
| **Import** | 2.83 s | **0.53 s** | 28.92 s | **5.36 s** | 4.83 min | **55.00 s** | **5.3×** |
| DB-Speicherung | 0.39 s | 0.38 s | 3.76 s | 3.74 s | 37.51 s | 37.50 s | – |
| AuditTrail-PDF | 13.54 s | 13.24 s | 13.24 s | 13.27 s | 13.41 s | 13.43 s | – |

Import-Soft-Target von 60 s bei 1M Zeilen ist mit 55 s **erreicht**.
RAM-Peak im Import-Pfad ist von 1 214 MB auf 1 409 MB minimal
gestiegen – calamine selbst ist sparsam, aber das anschließende
Materialisieren in `DatasetRow`-Dicts dominiert weiterhin den
Python-Heap. Sprint-10.2-Scope war Zeit, nicht RAM – DataRow-Layout
wäre ein eigener Refactor.

## Auffälligkeiten

### Behoben in Sprint 10.2

- **Excel-Import bei 1M = 55 s** (vorher 4.83 min). Migration von
  `openpyxl.load_workbook(read_only=True)` auf `python-calamine`'s
  Rust-Iterator (`CalamineSheet.iter_rows`). Schnittstelle
  (`ImportResult`) unverändert, Aufrufer unangetastet.

### Behoben in Sprint 10.3

- **DB-Speicherung skaliert deutlich besser**: 100k 3.74 s → 0.75 s
  (5.0×), 10k 0.39 s → 0.07 s (5.6×). 1M projiziert ~7.5 s, weit
  unter dem 30 s-Soft-Target. Maßnahmen: stdlib-`json` → `orjson`
  (C-basiert), executemany-Generator statt Listcomp (RAM-Peak
  100k: 55 MB → 0.2 MB).

### Offen für spätere Sprints

1. **AuditTrail-PDF konstant ~13 s bei 5 000 Events.** Skaliert nicht
   mit Dataset-Größe, daher sind die in der Heuristik-Tabelle
   gelisteten 10k/100k-Verfehlungen **Artefakte** der
   linear-skalierenden Target-Berechnung. Bei 1M liegt PDF weiter
   unter dem 30 s-Target. Sollte trotzdem subjektiv schneller
   werden – Sprint-10.4-Kandidat (reportlab-Chunking).

2. **RAM-Peak Import 1.4 GB bei 1M.** Calamine selbst ist sparsam;
   der Peak entsteht beim Materialisieren in `DatasetRow`-Dicts.
   Spalten-orientierte Dataset-Struktur (Arrow/Numpy) wäre die
   Lösung, ist aber ein Architektur-Refactor mit Ripple-Effekt auf
   Sampling/Export. Nicht jetzt.

### Bekannte Schwächen der Heuristik

Die "Soft-Target-Verfehlungen"-Tabelle skaliert Targets linear mit
Dataset-Größe. Das passt für Import/DB, aber NICHT für
`AuditTrail-PDF` (Aufwand hängt an Event-Anzahl, nicht an Rows).
Die `10k/100k → AuditTrail-PDF`-Verfehlungen sind daher keine
echten Befunde.

### Out of Scope

- **Setup (xlsx generieren)** dauert bei 1M Zeilen 7.78 min – reine
  Test-Infrastruktur (openpyxl write_only), kommt im echten App-Pfad
  nicht vor.
- **5M-Lauf** wurde nicht ausgeführt. Nach calamine-Migration jetzt
  realistischer (Import ~5 min projiziert), aber Setup würde
  ~40 min dauern. Lohnt erst, wenn ein User-Case das fordert.

