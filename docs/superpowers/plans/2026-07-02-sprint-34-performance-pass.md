# Sprint 34: Performance-Pass (profiling-first) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein messungs-getriebener Performance-Pass: Such-Debounce (WP1, Pflicht), Startup-Import-Budget (WP2, gate-gebunden), Snapshot-Messung (WP3, gate-gebunden), 1M-Re-Baseline (WP4) und ein streng begrenzter Mikro-Pass (WP5) – jeder Fix nur mit Vorher/Nachher-Beweis.

**Architecture:** Kein Umbau, nur additive, beweisbare Optimierungen. Debounce lebt im Widget (`AuditTrailView`), der Proxy bleibt synchron und API-unverändert. Lazy-Imports (falls Gate gerissen) am Aufrufort mit `TYPE_CHECKING`-Typen + PyInstaller-`hiddenimports`. Alle Messungen laufen sequenziell/exklusiv; Rohdaten unter `tmp/perf/` (nicht committen).

**Tech Stack:** Python 3.13, PyQt6 (QTimer), pytest-qt, stdlib-Profiling (`-X importtime`, `time.perf_counter`), `scripts/perf_probe.py`.

**Entscheidungs-Gate (alle 4 Kriterien nötig):** G1 ≥20 % einer Phase ODER ≥200 ms UI-Latenz ODER ≥300 ms Startup-Anteil · G2 keine Rote-Linie-Datei · G3 ≤50 LoC (WP3: ≤80) · G4 Vorher/Nachher-Beleg führbar.

---

### Task 0: Branch anlegen

**Files:** keine (git only)

- [ ] **Step 1: Branch erstellen**

```bash
cd ~/dev/Sampling-Tool
git checkout -b perf/sprint-34-performance-pass
```

Expected: `Switched to a new branch 'perf/sprint-34-performance-pass'`

---

### Task 1: M1 – Startup-Import-Budget messen

**Files:**
- Create (Rohdaten, NICHT committen): `tmp/perf/importtime_run{1,2,3}.log`, `tmp/perf/m1_summary.txt`

- [ ] **Step 1: importtime-Läufe (3×) + Wall-Clock (3×)**

```bash
cd ~/dev/Sampling-Tool && mkdir -p tmp/perf
for i in 1 2 3; do
  .venv/bin/python -X importtime -c "import sampling_tool.ui.main_window, sampling_tool.ui.controllers.main_controller" 2> tmp/perf/importtime_run$i.log
done
for i in 1 2 3; do
  .venv/bin/python -c "import time; t=time.perf_counter(); import sampling_tool.ui.main_window, sampling_tool.ui.controllers.main_controller; print(f'{time.perf_counter()-t:.3f}s')"
done
```

- [ ] **Step 2: Auswertung – Top-10-Offender + Fragen beantworten**

Aus `importtime_run2.log` (Median-Lauf) die kumulativen ms je Top-Level-Paket extrahieren (Spalte `cumulative`, Zeilen ohne führende Leerzeichen im `import time:`-Feld = Top-Level). Konkret beantworten: Hängen **matplotlib, reportlab, numpy, pandas, openpyxl** in der Kette, mit wie viel ms? Und über welchen Import-Pfad (wer importiert sie transitiv – `tasks.py`? `chart_renderer.py`?)?

- [ ] **Step 3: Gate-Verdikt notieren**

Pro Lib: kumulativ ≥300 ms → WP2-Kandidat. Ergebnis in `tmp/perf/m1_summary.txt` festhalten (Median-Gesamtzeit, Tabelle Lib→ms→Pfad→Gate ja/nein).

---

### Task 2: M2 – Debounce-Ist-Zustand dokumentieren (bereits belegt)

**Files:** keine (nur Beleg für PERFORMANCE.md)

- [ ] **Step 1: Beleg festhalten**

Verdrahtung im Live-Code verifiziert: `src/sampling_tool/ui/widgets/audit_trail_view.py:309` (`self._search.textChanged.connect(self._on_search_changed)`) und `:397-398` (`_on_search_changed` ruft `self._proxy.set_search_text(text)` synchron). Kein QTimer → N Keystrokes = N Filterläufe à ~120 ms (Sprint-25-Messung, 20k Events). G1 erfüllt (wahrnehmbare UI-Latenz pro Anschlag, kumuliert beim Tippen).

---

### Task 3: M3 – Snapshot-Messung 50/200/500 MB

**Files:**
- Create (temporär): `tmp/perf/m3_snapshot_bench.py`, Ergebnis in `tmp/perf/m3_summary.txt`

- [ ] **Step 1: Bench-Skript schreiben**

```python
"""M3: EngagementVersionManager.create_snapshot isoliert messen (Sprint 34)."""
from __future__ import annotations

import os
import shutil
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from sampling_tool.persistence.version_manager import EngagementVersionManager

BASE = Path(__file__).resolve().parent / "m3_work"

for size_mb in (50, 200, 500):
    work = BASE / f"size_{size_mb}"
    work.mkdir(parents=True, exist_ok=True)
    db = work / "projekt.db"
    with db.open("wb") as fh:
        for _ in range(size_mb):
            fh.write(os.urandom(1024 * 1024))
    times = []
    for run in range(3):
        mgr = EngagementVersionManager(db)
        t0 = time.perf_counter()
        target = mgr.create_snapshot(f"perf_run{run}")
        times.append(time.perf_counter() - t0)
        target.chmod(0o644)
        target.unlink()
    print(f"{size_mb} MB: median {statistics.median(times):.3f}s  (runs: {[f'{t:.3f}' for t in times]})")
    shutil.rmtree(work)
shutil.rmtree(BASE, ignore_errors=True)
```

- [ ] **Step 2: Exklusiv ausführen (nichts parallel), Ergebnis notieren**

```bash
cd ~/dev/Sampling-Tool && .venv/bin/python tmp/perf/m3_snapshot_bench.py | tee tmp/perf/m3_summary.txt
```

- [ ] **Step 3: Gate-Verdikt**

WP3-Gate: >2 s bei ≤200 MB. Erwartung (lokale SSD): deutlich darunter → dann WP3 = „bleibt synchron", nur Doku.

---

### Task 4: M4 – 1M-Re-Baseline (exklusiv, 20–30 min)

**Files:**
- Create (Rohdaten, NICHT committen): `tmp/perf/PERFORMANCE_1M_sprint34.md`

- [ ] **Step 1: Lauf starten – zwingend mit `--output tmp/perf/…` (Default würde PERFORMANCE.md überschreiben!)**

```bash
cd ~/dev/Sampling-Tool && .venv/bin/python scripts/perf_probe.py --sizes 1000000 --output tmp/perf/PERFORMANCE_1M_sprint34.md
```

**Während des Laufs läuft NICHTS anderes** (keine Tests, keine Subagents, keine Edits mit Toolchecks). Läuft auf dem unveränderten Branch-Point (= `6c4691e`-Stand), damit die Re-Baseline direkt mit der Sprint-11-Tabelle vergleichbar ist.

- [ ] **Step 2: Ergebnis lesen, P-004-Verdikt bilden**

AuditTrail-PDF-Phase (5000 Events, jetzt Sprint-33-Querformat) gegen 0.40 s (Sprint 10.4) und 3.85 s (Sprint-11-Lauf) einordnen. Phasen >50 % über (skaliertem) Soft-Target, die kein WP abdeckt → NICHT fixen, als Follow-up-Finding mit Datei:Zeile-Verdacht notieren.

---

### Task 5: WP1 – Such-Debounce (TDD, Pflicht)

**Files:**
- Modify: `src/sampling_tool/ui/widgets/audit_trail_view.py` (Klasse `AuditTrailView`, ~Z. 290–310, 395–398)
- Test: `tests/ui/test_audit_trail_view.py` (neue Klasse `TestAuditSearchDebounce`)

Architektur (verbindlich): Debounce im **Widget**, `AuditTrailFilterProxy.set_search_text` bleibt synchron/API-unverändert. `QTimer(parent=self)`, singleShot, 150 ms; jeder `textChanged` restartet; bei Timeout genau ein `set_search_text(<aktueller Feldtext>)`. Feld-Leeren über denselben Pfad. Treffer-Semantik unverändert (literal, case-insensitiv, `" "` matcht alle, `ß`≠`ss`).

- [ ] **Step 1: Bestehende Tests auf QLineEdit-Nutzung prüfen**

```bash
grep -n "_search\|setText\|textChanged" tests/ui/test_audit_trail_view.py
```

Tests, die `view._search.setText(...)` nutzen und sofort sichtbare Rows asserten, brauchen nach dem Umbau `qtbot.wait(...)` – vorab identifizieren (nicht ändern, nur kennen; Proxy-direkte Tests bleiben unberührt).

- [ ] **Step 2: Failing Tests schreiben (Klassenname verbindlich)**

```python
class TestAuditSearchDebounce:
    """Sprint 34 / WP1: Volltextsuche ist über QTimer debounced (150 ms)."""

    def _view_with_events(self, qtbot: QtBot, count: int = 5) -> AuditTrailView:
        view = AuditTrailView()
        qtbot.addWidget(view)
        view.set_events(_make_events(count))
        return view

    def test_typing_coalesces_filter_runs(self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
        view = self._view_with_events(qtbot)
        calls: list[str] = []
        original = view.proxy().set_search_text
        monkeypatch.setattr(
            view.proxy(), "set_search_text", lambda text: (calls.append(text), original(text))
        )
        for fragment in ("a", "an", "ann", "anna", "anna ", "anna e", "anna ex", "anna exp", "anna expo", "anna export"):
            view._search.setText(fragment)
        assert calls == []  # noch kein Filterlauf während des Tippens
        qtbot.wait(AuditTrailView.AUDIT_SEARCH_DEBOUNCE_MS + 100)
        assert calls == ["anna export"]  # genau EIN Aufruf, finaler Text

    def test_debounced_result_matches_immediate(self, qtbot: QtBot) -> None:
        view = self._view_with_events(qtbot, count=8)
        oracle = self._view_with_events(qtbot, count=8)
        oracle.proxy().set_search_text("import")
        view._search.setText("import")
        qtbot.wait(AuditTrailView.AUDIT_SEARCH_DEBOUNCE_MS + 100)
        assert view.visible_row_count() == oracle.visible_row_count()
        assert _visible_texts(view) == _visible_texts(oracle)

    def test_clear_after_debounce_shows_all_rows(self, qtbot: QtBot) -> None:
        view = self._view_with_events(qtbot, count=6)
        view._search.setText("import")
        qtbot.wait(AuditTrailView.AUDIT_SEARCH_DEBOUNCE_MS + 100)
        assert view.visible_row_count() < 6
        view._search.setText("")
        qtbot.wait(AuditTrailView.AUDIT_SEARCH_DEBOUNCE_MS + 100)
        assert view.visible_row_count() == 6
```

(Helper `_make_events`/`_visible_texts`: vorhandene Fixtures/Helper der Datei wiederverwenden, sonst minimal ergänzen – exakte Namen beim Schreiben an die Datei anpassen.)

- [ ] **Step 3: Tests laufen lassen – MÜSSEN rot sein**

```bash
.venv/bin/python -m pytest tests/ui/test_audit_trail_view.py::TestAuditSearchDebounce -q --no-cov
```

Expected: FAIL (`AttributeError: AUDIT_SEARCH_DEBOUNCE_MS` bzw. `calls == [...]` schlägt fehl, weil synchron gefiltert wird).

- [ ] **Step 4: Implementierung im Widget**

```python
class AuditTrailView(QWidget):
    # Sprint 34 / WP1: 150 ms Debounce-Fenster für die Volltextsuche.
    # Begründung (P-009-Lehre, kein unbegründeter Tuning-Wert): Ein
    # Filterlauf kostet bei 20k Events ~120 ms (Sprint-25-Messung). 150 ms
    # liegt knapp darüber – schnelles Tippen koalesziert zu genau einem
    # Lauf – und bleibt unter der ~200-ms-Wahrnehmbarkeitsschwelle (G1),
    # sodass sich die Suche weiterhin unmittelbar anfühlt.
    AUDIT_SEARCH_DEBOUNCE_MS: ClassVar[int] = 150
```

In `__init__` (statt direkter Verdrahtung):

```python
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(self.AUDIT_SEARCH_DEBOUNCE_MS)
        self._search_debounce.timeout.connect(self._apply_search_text)
        self._search.textChanged.connect(self._on_search_changed)
```

Slots:

```python
    def _on_search_changed(self, _text: str) -> None:
        """Restartet den Debounce-Timer – gefiltert wird erst bei Timeout."""
        self._search_debounce.start()

    def _apply_search_text(self) -> None:
        self._proxy.set_search_text(self._search.text())
```

Imports ergänzen: `QTimer` aus `PyQt6.QtCore`, `ClassVar` aus `typing`.

- [ ] **Step 5: Neue Tests grün + komplette Datei grün**

```bash
.venv/bin/python -m pytest tests/ui/test_audit_trail_view.py -q --no-cov
```

Expected: PASS. Falls Bestandstests aus Step 1 rot: dort `qtbot.wait(AuditTrailView.AUDIT_SEARCH_DEBOUNCE_MS + 100)` nach `setText` ergänzen (Semantik unverändert, nur Timing).

- [ ] **Step 6: Commit**

```bash
git add src/sampling_tool/ui/widgets/audit_trail_view.py tests/ui/test_audit_trail_view.py
git commit -m "Sprint 34 / WP1: Such-Debounce (150 ms QTimer) im AuditTrail-Widget"
```

---

### Task 6: WP2 – Startup-Lazy-Imports (NUR falls M1-Gate ≥300 ms je Lib gerissen)

**Files (Fix-Zweig):**
- Modify: `src/sampling_tool/ui/workers/tasks.py` (Modul-Imports → Funktions-Scope in `run()`, Typen via bestehendem `TYPE_CHECKING`-Block)
- Modify (falls matplotlib über Dashboard-Kette kommt): `src/sampling_tool/ui/widgets/chart_renderer.py` (Lazy-Import von `sampling_tool.io.charts` in den `render_*`-Funktionen)
- Modify: `sampling_tool.spec` (`hiddenimports` + Sprint-34-Kommentar für jedes lazy gemachte Modul, z. B. `sampling_tool.io.pdf_report`, `sampling_tool.io.charts`)
- Test: `tests/integration/test_startup_imports.py` (neu, `TestStartupLazyImports`)

- [ ] **Step 1: Gate prüfen** – M1-Tabelle: nur Libs mit ≥300 ms kumulativ in der Startup-Kette anfassen. Kein Kandidat → Task komplett überspringen, Messtabelle trotzdem in PERFORMANCE.md (Task 9), Verdikt „bewusst nicht gefixt".

- [ ] **Step 2 (Fix-Zweig): Failing Subprocess-Test schreiben**

```python
"""Sprint 34 / WP2: Schwere Libs dürfen beim UI-Import nicht mehr laden."""
from __future__ import annotations

import subprocess
import sys

LAZY_LIBS = ("matplotlib", "reportlab")  # exakte Liste = M1-Gate-Ergebnis


class TestStartupLazyImports:
    def test_heavy_libs_not_imported_at_startup(self) -> None:
        code = (
            "import sys, sampling_tool.ui.main_window, "
            "sampling_tool.ui.controllers.main_controller; "
            f"leaked = [m for m in {LAZY_LIBS!r} if m in sys.modules]; "
            "print(','.join(leaked)); sys.exit(1 if leaked else 0)"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
        )
        assert proc.returncode == 0, f"Beim Startup geladen: {proc.stdout.strip()}"
```

Run: `.venv/bin/python -m pytest tests/integration/test_startup_imports.py -q --no-cov` → Expected: FAIL (Libs sind aktuell im Startup).

- [ ] **Step 3 (Fix-Zweig): Lazy-Imports umsetzen** – Muster in `tasks.py`: Modul-Level-Import der schweren io-Module entfernen, im jeweiligen `run()` lokal importieren (`from sampling_tool.io.pdf_report import AuditTrailPDF`), Typ-Annotationen über den bestehenden `TYPE_CHECKING`-Block. Analog `chart_renderer.py`, falls die Kette dort läuft. mypy muss voll typisiert bleiben.

- [ ] **Step 4 (Fix-Zweig): spec ergänzen** – jedes lazy gemachte Modul unter `hiddenimports` mit Kommentar `# Sprint 34 / WP2: Funktions-lokale Imports entgehen der statischen Analyse`.

- [ ] **Step 5 (Fix-Zweig): Test grün + Nachher-Messung M1 wiederholen (3 Läufe, Median)** – Vorher/Nachher in `tmp/perf/m1_summary.txt` ergänzen.

- [ ] **Step 6 (Fix-Zweig): Commit**

```bash
git add src/sampling_tool/ui/workers/tasks.py sampling_tool.spec tests/integration/test_startup_imports.py
git commit -m "Sprint 34 / WP2: Lazy-Imports für schwere io-Libs im Startup-Pfad (+hiddenimports)"
```

---

### Task 7: WP3 – Snapshot-Worker (NUR falls M3-Gate >2 s bei ≤200 MB gerissen)

**Files (Fix-Zweig, erwartet: entfällt):**
- Modify: `src/sampling_tool/ui/workers/tasks.py` (neue `SnapshotTask` nach `ExcelImportTask`-Muster)
- Modify: `src/sampling_tool/ui/controllers/engagement_controller.py` (beide Pfade: Öffnen Z. 162–167 nicht-kritisch, Überschreiben Z. 115–126 kritisch; Snapshot MUSS vollständig fertig sein, bevor Session initialisiert/DB beschrieben wird)
- Test: `TestSnapshotWorker` in `tests/ui/test_main_controller.py` (bestehende Engagement-Controller-Testdatei)

- [ ] **Step 1: Gate prüfen** – Median bei 200 MB >2 s? Erwartung: nein → Task überspringen, in PERFORMANCE.md dokumentieren: Messtabelle + Entscheidung „bleibt synchron" (Hebel zu klein). Fertig.

- [ ] **Step 2 (Fix-Zweig): STOPP-Kriterium beachten** – Controller-Umbau >~80 LoC ODER Reihenfolge-Garantie (Snapshot vor Session-Init/DB-Write) gefährdet → STOPP, Optionen an Nico melden statt bauen. Sonst: `SnapshotTask` (frozen dataclass, `run()` ruft `EngagementVersionManager(db_path).create_snapshot(user)`), via `TaskProgressDialog.run_task` in beide Pfade einhängen, Fehler-Semantik exakt erhalten (Öffnen: loggen + weiter; Überschreiben: abbrechen), Tests für beide Pfade + Reihenfolge.

---

### Task 8: WP5 – Mikro-Pass (streng begrenzt, max. 3 Items)

**Files:** offen (Scan-Ergebnis), Grenzen: je ≤50 LoC, je Vorher/Nachher ≥20 % auf dem Mikro-Pfad, KEINE §11-Dateien, keine Verhaltensänderung.

- [ ] **Step 1: Fan-out-Scan via Subagents (KEINE Benchmarks parallel)** – heiße UI-/IO-Pfade nach: per-Keystroke-Arbeit in anderen Suchfeldern/Filtern, redundanten QSettings-Reads in `data()`/paint-Pfaden, vermeidbaren Voll-Invalidierungen, N+1-SQLite-Queries in UI-Pfaden, unnötigen Listen-Kopien in heißen Schleifen. Ausschluss: `core/rng.py`, `core/sampling.py`, Coercion/Encoder, Import-Write-Pfad.

- [ ] **Step 2: Kandidaten bewerten** – pro Kandidat Gate-Check (G1–G4) + Mikro-Benchmark-Skizze. Nichts Passendes → explizit „keine" im PR-Text, Task fertig.

- [ ] **Step 3 (je Item): Mikro-Benchmark vorher (Median aus 3, sequenziell) → Fix → Benchmark nachher** – <20 % Gewinn → revert. Sonst Commit pro Item.

---

### Task 9: Doku – PERFORMANCE.md, CLAUDE.md, README

**Files:**
- Modify: `PERFORMANCE.md` (neue Sektionen: (a) „Sprint 34 – Startup-Import-Budget" mit M1-Tabelle + ggf. Vorher/Nachher, (b) Debounce-Follow-up als erledigt markieren mit Zähler-Beleg, (c) „Sprint 34 – Snapshot-Messung + Entscheidung" mit M3-Tabelle, (d) „Messung 1M – Sprint 34 (Datum, Toolversion)" mit Vergleichsspalte zur Sprint-11-Tabelle + P-004-Verdikt; alte 1M-Tabelle als historisch markieren, (e) ggf. WP5-Items mit Zahlen)
- Modify: `CLAUDE.md` (Sprint-Tabelle: Zeile 34, Muster wie Sprint 33)
- Modify: `README.md` (Sprint-Tabelle analog)

- [ ] **Step 1: PERFORMANCE.md-Sektionen schreiben** (Zahlen aus `tmp/perf/*`; die Sprint-11-1M-Tabelle bleibt als „historisch (Sprint 11, `19f18a1`)" markiert stehen)
- [ ] **Step 2: CLAUDE.md + README Sprint-Tabelle ergänzen**
- [ ] **Step 3: Commit**

```bash
git add PERFORMANCE.md CLAUDE.md README.md docs/superpowers/plans/2026-07-02-sprint-34-performance-pass.md
git commit -m "Sprint 34: PERFORMANCE.md-Sektionen (M1-M4), Sprint-Tabellen, Plan"
```

---

### Task 10: Code-Review + Pre-Push-Checks

- [ ] **Step 1: superpowers:requesting-code-review durchlaufen** – Findings nach receiving-code-review-Standard verifizieren/fixen.
- [ ] **Step 2: Pre-Push-Checks (exakt diese, alle grün; Reihenfolge frei, sequenziell)**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy src tests
```

Pflicht-Guards, die grün bleiben MÜSSEN: `tests/unit/test_sampling.py::TestSimpleSamplerIdsPath`, `tests/integration/test_import_result_unchanged.py::TestImportResultUnchanged`, Haystack-/Literal-Oracles in `tests/ui/test_audit_trail_view.py`, `tests/integration/test_perf_probe_runs.py`, `tests/integration/test_bench_import_runs.py`.

---

### Task 11: PR + Squash-Merge (kein `--auto`)

- [ ] **Step 1: Push + PR mit Gate-Tabelle** (jedes gemessene Item: Verdikt gefixt / bewusst nicht gefixt / Follow-up)

```bash
git push -u origin perf/sprint-34-performance-pass
gh pr create --title "Sprint 34: Performance-Pass (profiling-first) – Such-Debounce, Startup-Import-Budget, Snapshot-Messung, 1M-Re-Baseline" --body "<Gate-Tabelle + Vorher/Nachher-Zahlen>"
```

- [ ] **Step 2: Merge + Aufräumen**

```bash
gh pr merge --squash --delete-branch
git checkout main && git pull
```

`SPRINT_*.md` und `tmp/perf/` bleiben unversioniert.
