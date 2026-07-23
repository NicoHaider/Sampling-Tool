# ADR 0001 – Versionsfester RNG-Vertrag (`PCG64` + `bdo-v1`)

- **Status:** Angenommen (Sprint 39 / S1.2, R-001)
- **Betrifft:** `core/rng.py`, `core/sampling.py`, Migration `004_algorithm_version.sql`

## Kontext

Das Tool ist ISAE-3402-getrieben: Jede gezogene Stichprobe muss zu jedem späteren
Zeitpunkt mit gespeichertem Seed + gespeichertem Datensatz **bit-genau**
reproduzierbar sein. Der ursprüngliche Code nutzte `numpy.random.default_rng(seed)`.
Dessen Default-BitGenerator ist von NumPy jedoch **nicht als stabil zugesichert**
und darf sich versionsübergreifend ändern – damit wäre die Bit-Identität einer
historischen Ziehung nicht garantiert.

## Entscheidung

1. **Expliziter BitGenerator.** `core.rng.make_rng(seed)` gibt
   `Generator(PCG64(seed))` zurück (expliziter `PCG64`-Kern statt des impliziten
   `default_rng`-Defaults). Der Roh-Zufallsstrom ist damit an eine benannte
   Implementierung gebunden, nicht an einen versionsabhängigen Default.
2. **Eigener Fisher-Yates statt `rng.shuffle()`.** `fisher_yates_shuffle` mischt
   über `rng.integers(0, i+1)` (klassischer Knuth, rückwärts iterierend), weil
   die interne Swap-Reihenfolge von `rng.shuffle()` nicht spezifiziert ist und
   sich ändern darf.
3. **Eine Algorithmus-Version als SSOT.** `core.rng.SAMPLING_ALGORITHM_VERSION`
   (aktuell `"bdo-v1"`) ist die **einzige** Quelle der Ziehungs-Algorithmus-
   Version. Jedes `SampleResult` persistiert sie (`algorithm_version`, Migration
   `004`, Backfill `bdo-v1` für Bestandssamples – korrekt, da diese mit exakt
   diesem Output gezogen wurden). Die Version ändert sich **nur**, wenn sich der
   tatsächliche Ziehungs-Output ändert.
4. **NumPy-Range gepinnt.** `numpy>=2.0,<3` in `pyproject.toml`; Bit-Identität
   gilt nur innerhalb dieser Range.

## Konsequenzen

- **Niemals** `random` aus der stdlib verwenden – ausschließlich
  `core.rng.make_rng(seed)`. Keine Zeitstempel/UUIDs/Hash-Ordnung in die
  Stichprobenauswahl einfließen lassen. Sortierung vor RNG-Verbrauch immer
  deterministisch (nach `row_id`).
- **Rote Linie:** kein Wechsel des Ziehungs-Algorithmus. `rng.integers(0, i+1)`,
  Fisher-Yates, Key-Sortierung und Largest-Remainder bleiben unverändert – nur
  die BitGenerator-Konstruktion wurde explizit gemacht (output-identisch zum
  vorherigen Default).
- Abgesichert durch `tests/unit/test_golden_vectors.py`: committete Referenz-
  Row-IDs über alle Methoden / Filter-Operatoren / Stratify-Modi + Nachstichprobe,
  5 Seeds, in CI auf Ubuntu/Windows/macOS geprüft. Ein unbeabsichtigter
  Output-Drift lässt diese Vektoren fehlschlagen.
- Ein bewusster künftiger Algorithmus-Wechsel erfordert eine **neue** Version
  (`bdo-v2`) plus neue Golden-Vektoren – die alten Ergebnisse bleiben über ihre
  persistierte `algorithm_version` eindeutig zuordenbar.
