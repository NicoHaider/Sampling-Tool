# Performance-Probe

Datum: 2026-05-18T18:09:33
Maschine: Darwin 25.3.0 (arm64), Python 3.13.13
Toolversion: 19f18a1
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

## Messung 1,000,000 Zeilen

| Phase | Zeit | Peak (tracemalloc) | RSS-Delta | Anmerkung |
|-------|-----:|-------------------:|----------:|-----------|
| Setup (xlsx generieren) | 7.71 min | 141.2 MB | — | 81.4 MB |
| Import | 7.60 s | 5 KB | — | Streaming – Zeilen-Anzahl steht nach Phase 2 fest |
| DB-Speicherung | 53.41 s | 41 KB | — | 1,000,000 rows, 0 skipped |
| Tabelle-Anzeige | 34.58 s | 1.7 MB | — |  |
| Sampling Simple | 15.90 s | 1074.6 MB | — | 500 rows |
| Sampling Cluster | 12.46 s | 1078.9 MB | — | 499827 rows |
| Sampling Stratified | 15.82 s | 1077.7 MB | — | 500 rows |
| Filter-Toggle (an) | 0.3 ms | 4 KB | — |  |
| Filter-Toggle (aus) | 0.1 ms | 0 KB | — |  |
| Highlight | 2.6 ms | 40 KB | — |  |
| Clear-Highlight | 0.1 ms | 1 KB | — |  |
| Excel-Export (Sample) | 0.28 s | 2.0 MB | — |  |
| Excel-Report (Multi-Sheet) | 0.13 s | 1.4 MB | — |  |
| HTML-Report | 0.25 s | 2.0 MB | — |  |
| AuditTrail-PDF | 3.85 s | 16.3 MB | — | 5000 events, 0.5 MB |

## Soft-Target-Verfehlungen (Sprint-10.2-Kandidaten)

| Größe | Phase | Gemessen | Skaliertes Target | Überschreitung |
|------:|-------|---------:|------------------:|---------------:|
| 1,000,000 | DB-Speicherung | 53.41 s | 30.00 s | +23.41 s |
| 1,000,000 | Tabelle-Anzeige | 34.58 s | 5.00 s | +29.58 s |
| 1,000,000 | Sampling Simple | 15.90 s | 10.00 s | +5.90 s |
| 1,000,000 | Sampling Stratified | 15.82 s | 15.00 s | +0.82 s |

## Auffälligkeiten

Werden manuell ergänzt, nachdem die Tabellen oben gelesen wurden. Erwartete Bottleneck-Hypothesen (siehe Sprint-10.1-Brief):

- DatasetRepo.create – `executemany`-Bulk-Insert, sollte skalieren
- values_json-Encoding pro Row – ein json.dumps-Aufruf je Zeile, potenziell sichtbar bei 1M+
- DataTableView.highlight_rows – Set-Lookup im BackgroundRole
- AuditTrail-PDF – reportlab.platypus mit vielen Flowables
- Stratified mit vielen Strata – largest-remainder-Schleifen

