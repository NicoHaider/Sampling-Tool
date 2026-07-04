# Sprint 35: Advanced-Sampling-Streaming (P-003) + Import-Pipeline (profiling-first) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die beiden größten offenen Performance-Posten aus der Sprint-34-Analyse: (A) Cluster-/Stratified-Sampling ohne 1-GB-Row-Materialisierung (P-003) und (B) den dominanten Posten der Import-Pipeline (profiling-first) – beides ausschließlich mit Bit-Repro-/Byte-Identitäts-Beweis.

**Architecture:** (A) „Pairs-Pfad" nach dem P-002-Muster: Sampler brauchen pro Row nur `(row_id, feldwert)`. Neue Repo-Methode `iter_row_field_pairs` (json_extract + vorhandener `_distinct_decode`), neue Sampler-Methoden `sample_pairs` (spiegeln `_select` exakt: gleiche Gruppierung, gleiche Sortierung, gleiche RNG-Konsumreihenfolge → bit-identische `selected_row_ids`), Controller-Weiche nur für `filter_field is None and not from_sample_only` (wie P-002). (B) Erst `bench_import.py`-Baseline + cProfile, dann NUR den dominanten, byte-identisch beweisbaren Hebel fixen (Gate ≥20 % einer Phase); Coercion-SEMANTIK und Write-Pfad (executemany/PRAGMAs) bleiben unangetastet.

**Tech Stack:** Python 3.13, sqlite3 (json_extract/json_type), numpy-RNG (unverändert), `scripts/bench_import.py`, tracemalloc/perf_counter.

**Rote Linie (verschärft):** `core/rng.py` unangetastet. Änderungen an `core/sampling.py`/`dataset_repo.py` sind additiv (neue Methoden, `_select`/`sample`/`_collect_pool` bleiben wörtlich unverändert). Jede Ziehung mit gleichem Seed muss bit-identisch zur heutigen Implementierung bleiben – Oracle-Tests zuerst (rot geht nicht: Oracles vergleichen neu gegen alt, sie sind ab Implementierung grün; „TDD-rot" ist hier der fehlende Symbol-Fehler).

---

### Task 0: Branch (erledigt) + WP-A-Baseline

**Files:** Create `tmp/perf/s35_bench_sampling.py` (nicht committen)

- [ ] **Step 1: Benchmark-Skript** – baut EINMAL eine 1M-Zeilen-DB (15 Spalten wie perf_probe: `kostenstelle` 10 distinct, `status` 5 distinct, gemischte Typen) direkt via `DatasetRepo.create` (kein xlsx) nach `tmp/perf/s35_1m.db` (bleibt liegen für die Nachher-Messung). Misst pro Methode (Cluster size=5 seed=43 / Stratified size=500 seed=44 PROPORTIONAL, `population_size=row_count`): 3 Timing-Läufe OHNE tracemalloc (Median) + 1 RAM-Lauf MIT tracemalloc (Peak). Misst `rows`-Pfad immer, `pairs`-Pfad nur falls implementiert (hasattr-Guard).
- [ ] **Step 2: Baseline exklusiv laufen lassen** (nichts parallel), Werte notieren. Erwartung ~ perf_probe-Größenordnung: Cluster ~13 s, Stratified ~16 s, Peak ~1.08 GB (tracemalloc-Lauf zeitlich NICHT werten).

### Task 1: Repo – `iter_row_field_pairs` (WP-A)

**Files:**
- Modify: `src/sampling_tool/persistence/dataset_repo.py` (additiv, nach `iter_row_ids`)
- Test: `tests/integration/test_repositories.py` (oder wo `distinct_values`-Tests liegen) – neue Klasse `TestIterRowFieldPairs`

- [ ] **Step 1: Failing Test (Symbol fehlt) – Decode-Oracle gegen `iter_rows`**

```python
class TestIterRowFieldPairs:
    """Sprint 35 / P-003: (row_id, wert)-Stream muss bit-identisch zu iter_rows decodieren."""

    def test_pairs_match_iter_rows_for_mixed_types(self, ...):
        # Fixture: Dataset mit Spalten über alle Typen: str (inkl. Umlaute),
        # int, float, bool, None, datetime, date, time, fehlender Key.
        repo = DatasetRepo(conn)
        for column in dataset.columns:
            expected = [(r.row_id, r.get(column)) for r in repo.iter_rows(dataset.id)]
            got = list(repo.iter_row_field_pairs(dataset.id, column))
            assert got == expected  # Werte inkl. Typen (repr-genau via ==)
            assert [type(v) for _, v in got] == [type(v) for _, v in expected]

    def test_pairs_sorted_by_row_index(self, ...): ...
    def test_missing_column_yields_none(self, ...): ...
```

- [ ] **Step 2: Implementierung** (nutzt vorhandenen `_distinct_decode` + gleiche Quote-Escape-Konvention wie `distinct_values`):

```python
    def iter_row_field_pairs(self, dataset_id: int, column: str) -> Iterator[tuple[int, Any]]:
        """Streaming über (row_index, decodierter Spaltenwert), sortiert.

        Sprint 35 / P-003: Cluster-/Stratified-Sampler brauchen pro Row nur
        row_id + EIN Feld. json_extract zieht das Feld in C; decodiert wird
        mit exakt der `_distinct_decode`-Mechanik aus P-005 (bit-identisch
        zu `DatasetRow.get`, Oracle-Test). RAM ~ 2-Tupel statt 15-Spalten-Dict.
        Gleiche Limitierung wie `distinct_values` bei `"` im Spaltennamen.
        """
        json_path = '$."' + column.replace('"', '""') + '"'
        cur = self.conn.execute(
            "SELECT row_index, json_extract(values_json, ?) AS raw, "
            "       json_type(values_json, ?) AS jtype "
            "FROM dataset_rows WHERE dataset_id = ? ORDER BY row_index",
            (json_path, json_path, dataset_id),
        )
        for r in cur:
            jtype = r["jtype"]
            value = None if jtype is None or jtype == "null" else _distinct_decode(r["raw"], jtype)
            yield int(r["row_index"]), value
```

- [ ] **Step 3: Tests grün + Commit**

### Task 2: Sampler – `sample_pairs` für Cluster + Stratified (WP-A, Bit-Repro-Oracles)

**Files:**
- Modify: `src/sampling_tool/core/sampling.py` (NUR additiv; `sample`/`_collect_pool`/`_select` unverändert)
- Test: `tests/unit/test_sampling.py` – neue Klassen `TestClusterSamplerPairsPath`, `TestStratifiedSamplerPairsPath`

- [ ] **Step 1: Oracle-Tests zuerst** (Property-Stil über viele Seeds/Größen; Fixtures mit None-Werten, gemischten Typen (int/str/datetime-Keys), Duplikat-Keys, Einzel-Element-Schichten):

```python
class TestClusterSamplerPairsPath:
    """Sprint 35 / P-003: sample_pairs ⇔ sample(rows) bit-identisch (gleicher Seed)."""

    @pytest.mark.parametrize("seed", [0, 1, 42, 43, 99991])
    @pytest.mark.parametrize("n_clusters", [1, 3, 5])
    def test_pairs_match_rows_path(self, seed, n_clusters):
        rows = _mixed_rows()  # inkl. None-Cluster-Werte + Duplikat-Keys
        cfg = SampleConfig(method=SamplingMethod.CLUSTER, size=n_clusters, seed=seed,
                           cluster_field="ks")
        expected = ClusterSampler(cfg).sample(iter(rows), population_size=len(rows))
        pairs = [(r.row_id, r.get("ks")) for r in rows]
        got = ClusterSampler(cfg).sample_pairs(iter(pairs), population_size=len(rows))
        assert got.selected_row_ids == expected.selected_row_ids
        assert got.population_size == expected.population_size

    def test_pairs_reject_filter_config(self): ...  # SamplingError wie sample_ids
    def test_pairs_empty_raises(self): ...
    def test_pairs_too_many_clusters_raises_same_message(self): ...
```

(Analog `TestStratifiedSamplerPairsPath` mit PROPORTIONAL + EQUAL, Schicht-zu-klein-Fehlerfall, `size < len(strata)`-Fehlerfall.)

- [ ] **Step 2: Implementierung** – exakte `_select`-Spiegelung auf `(row_id, value)`:

```python
# ClusterSampler:
    def sample_pairs(self, pairs: Iterable[tuple[int, Any]], population_size: int) -> SampleResult:
        """P-002-Muster für Cluster: (row_id, cluster_wert) statt DatasetRow.

        Bit-identisch zu sample(rows) bei filter_field is None: Gruppierung in
        row_id-Reihenfolge, Keys via _sort_key sortiert, Fisher-Yates über die
        Key-Liste verbraucht dieselbe RNG-Sequenz (hängt nur an der Länge),
        Ergebnis wird ohnehin sortiert. Oracle: TestClusterSamplerPairsPath.
        """
        if self.config.filter_field is not None:
            raise SamplingError(...)  # wie sample_ids
        pool = sorted(pairs)  # (row_id, value) – row_id ist eindeutig → nur row_id sortiert
        if not pool:
            raise SamplingError("Nach Anwendung des Filters sind keine Datensätze mehr verfügbar.")
        clusters: dict[Any, list[int]] = defaultdict(list)
        for row_id, value in pool:
            clusters[value].append(row_id)
        cluster_keys = sorted(clusters.keys(), key=_sort_key)
        if self.config.size > len(cluster_keys):
            raise SamplingError(<identische Meldung wie _select>)
        rng = make_rng(self.config.seed)
        chosen = fisher_yates_shuffle(list(cluster_keys), rng)[: self.config.size]
        selected = [rid for key in chosen for rid in clusters[key]]
        return SampleResult(config=self.config,
                            selected_row_ids=tuple(sorted(selected)),
                            population_size=population_size)
```

WICHTIG `sorted(pairs)`: Tupel-Vergleich fällt bei row_id-Gleichstand auf die Values zurück → bei nicht vergleichbaren Typen TypeError. row_ids sind eindeutig (PK) → `sorted(pairs, key=lambda p: p[0])` verwenden, NICHT plain `sorted(pairs)`. (Analog Stratified: Gruppierung, `_compute_sizes` über `[len(ids) for key]`-Gewichte, Verfügbarkeits-Check mit identischer Fehlermeldung, ein gemeinsamer `rng`, `fisher_yates_shuffle(list(ids))[:target]` pro Schicht in Key-Reihenfolge.)

- [ ] **Step 3: Alle Sampling-Tests grün** (`pytest tests/unit/test_sampling.py -q --no-cov`), inkl. Bestands-Guards `TestSimpleSamplerIdsPath`. Commit.

### Task 3: Controller-Weiche + perf_probe-Spiegel (WP-A)

**Files:**
- Modify: `src/sampling_tool/ui/controllers/workspace_controller.py` (Dispatch in `handle_new_sampling`)
- Modify: `scripts/perf_probe.py` (Spiegel-Dispatch, Kommentar)
- Test: `tests/ui/test_main_controller.py::TestSamplingPathDispatch` (bestehende Klasse erweitern: Cluster/Stratified ohne Filter → pairs-Pfad; mit Filter/from_sample_only → Legacy)

- [ ] **Step 1: Dispatch-Test erweitern (Monkeypatch-Spies auf sample_pairs/sample)**
- [ ] **Step 2: Weiche implementieren:**

```python
            if (
                isinstance(sampler, SimpleSampler)
                and result.config.filter_field is None
                and not result.from_sample_only
            ):
                sample_result = sampler.sample_ids(...)
            elif (
                isinstance(sampler, ClusterSampler)
                and result.config.filter_field is None
                and not result.from_sample_only
            ):
                assert result.config.cluster_field is not None
                sample_result = sampler.sample_pairs(
                    repo.iter_row_field_pairs(s.dataset.id, result.config.cluster_field),
                    population_size=s.dataset.row_count,
                )
            elif (
                isinstance(sampler, StratifiedSampler)
                and result.config.filter_field is None
                and not result.from_sample_only
            ):
                ... analog mit stratum_field ...
            else:
                <Legacy-Pfad unverändert>
```

- [ ] **Step 3: perf_probe analog** (damit M-Läufe den Production-Pfad messen; `test_perf_probe_runs`-Smoke bleibt grün, läuft ohne Cluster/Stratified nur im --quick-Mode – voller Modus deckt die neuen Zweige).
- [ ] **Step 4: End-to-End-Repro-Test** (Pflicht bei Sampling-Pfad-Änderung): über den echten Controller (`_real_sampling_dialog_driver`-Muster aus test_main_controller.py) eine Cluster- und eine Stratified-Ziehung mit festem Seed VOR/NACH der Weiche vergleichen – d. h. Oracle: Controller-Ergebnis == direktes `sampler.sample(iter_rows)`-Ergebnis mit gleicher Config. Commit.

### Task 4: WP-A Nachher-Messung (gleiche 1M-DB, exklusiv)

- [ ] **Step 1: `s35_bench_sampling.py` erneut** – jetzt misst er beide Pfade. Beleg-Ziel: ≥20 % Zeit ODER dominanter RAM-Gewinn (~1 GB → zweistellige MB). Zahlen für PERFORMANCE.md notieren. Danach `tmp/perf/s35_1m.db` löschen.

### Task 5: WP-B Baseline + Gate (Import-Pipeline)

- [ ] **Step 1: `bench_import.py` Baseline** (Median 3, beide Formate, exklusiv; ~20–40 min): `python scripts/bench_import.py 2>&1 | tee tmp/perf/s35_bench_import_baseline.txt`
- [ ] **Step 2: cProfile-Gegenprobe** `--quick`? Nein – `--rows 200000 --profile` als Kompromiss (Profil skaliert, voller 1M-Profile-Lauf wäre doppelt teuer).
- [ ] **Step 3: Gate-Entscheidung dokumentieren.** Kandidaten nach Aktenlage: (a) doppelter calamine-Pass (Header-Pass konsumiert iter_rows, Row-Generator parst das Sheet KOMPLETT NEU – `importer.py` ~Z. 223; Fix: Header-Zeilen puffern, einen einzigen Pass streamen; Byte-Identität via `TestImportResultUnchanged` + Sprint-29-Oracles), (b) `_coerce_value`-Dispatch-Mikro-Optimierung (nur Implementierung, Semantik gepinnt durch Byte-Oracle), (c) NICHTS, falls Profil keinen ≥20 %-Hebel außerhalb der Semantik-Rote-Linie zeigt → ehrlich dokumentieren.

### Task 6: WP-B Fix (nur bei bestandenem Gate)

- [ ] **Step 1: TDD** – für (a): Test, der zählt, dass das Sheet nur EINMAL geparst wird (calamine-Aufruf-Spy) + bestehende Byte-Oracles; für (b): reiner Byte-Oracle reicht (existiert).
- [ ] **Step 2: Implementierung ≤ ~60 LoC**, Nachher-Messung `bench_import.py` (Median 3), Vorher/Nachher in PERFORMANCE.md. Commit.

### Task 7: Doku + Abschluss

- [ ] **Step 1: PERFORMANCE.md**: Sektion „Sprint 35 – Advanced-Sampling-Streaming (P-003)" (Vorher/Nachher-Tabelle Zeit+RAM, Bit-Repro-Beleg) + „Sprint 35 – Import-Pipeline" (Baseline, Gate-Verdikt, ggf. Vorher/Nachher).
- [ ] **Step 2: CLAUDE.md + README Sprint-Zeile 35**; CLAUDE.md-Architektur-Notizen (Streaming-Block: Cluster/Stratified jetzt pairs-basiert; `sample_pairs` in der Repo-API-Liste).
- [ ] **Step 3: requesting-code-review** (Schwerpunkt: Bit-Repro-Beweisführung), Findings fixen.
- [ ] **Step 4: Pre-Push-Checks** (`pytest -q`, `ruff check .`, `ruff format --check .`, `mypy src tests`) – alle grün.
- [ ] **Step 5: PR + Squash-Merge** (Titel „Sprint 35: Advanced-Sampling-Streaming (P-003) + Import-Pipeline (profiling-first)"), Branch löschen, zurück auf main.
