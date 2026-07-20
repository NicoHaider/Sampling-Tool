# Sprint 55 — Reproduzierbare uv-Locks + SBOM + Bundle-Smoke (S3.2b2 / S-005 Teil 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CI + Release installs deterministic and hash-verified (`uv.lock` + `uv sync --locked`),
publish a CycloneDX SBOM with every release, and add a minimal frozen-bundle-smoke to `release.yml`
that catches a broken PyInstaller bundle (e.g. a missing `pypdf` hiddenimport) before it ships.

**Architecture:** Pure CI/release-config + packaging-metadata sprint — no `src/` change, no
Sampling/RNG/schema impact. `uv` is introduced strictly as a lock/install tool; `setuptools` stays
the build backend (unchanged in `pyproject.toml`). All architecture decisions are fixed in
`SPRINT_55_PROMPT.md` §3 ("verbindlich — nicht selbst neu abwägen"); this plan implements them and
documents the concrete commands, which required hands-on verification since the prompt's decisions
were made without running `uv` against this repo.

**Tech Stack:** `uv` 0.11.29 (lock/sync/export), GitHub Actions YAML, `pip-audit` (via the locked
env), `uv export --format cyclonedx1.5` (native SBOM, no third-party tool), PyInstaller, bash/pwsh.

---

## Preliminary research already done (do not repeat)

- Read in full: `REVIEW/REVIEW_CODEBASE_2026-07.md` §S-005, `.github/workflows/ci.yml`,
  `.github/workflows/release.yml`, `pyproject.toml`, `scripts/build_app.py`, `sampling_tool.spec`,
  `.github/dependabot.yml`, `README.md`, `.githooks/pre-push`, and the Sprint 54 plan
  (`docs/superpowers/plans/2026-07-20-sprint-54-supply-chain-ci.md`) for repo convention.
- Confirmed via `gh api repos/NicoHaider/Sampling-Tool/branches/main/protection` that Required
  Status Checks are exactly `test (ubuntu-latest, 3.13)` / `test (windows-latest, 3.13)` /
  `test (macos-latest, 3.13)` — this plan does not rename the `test` job or change its matrix.
- Installed `uv` locally (`brew install uv`, resolved to `uv 0.11.29`) and ran `uv lock` against
  the real `pyproject.toml` in a fresh worktree — resolved 50 packages (73 with `pip-audit` added
  to `dev`) across 9 marker-split environments, **with hashes**, universal across OS (verified
  `pywin32` stays `sys_platform == 'win32'`-gated, `PyQt6`/`numpy`/`python-calamine`/`pillow` all
  resolve platform-specific wheels correctly within one lockfile).
- **Found and worked around a real trap**: `uv sync`-created venvs ship **no `pip` binary**. A bare
  `pip install X` after activating a uv venv silently falls through PATH to a *different* venv's
  `pip` (in this environment: the main checkout's `.venv`, auto-activated by the user's shell
  profile on every new shell — confirmed via `which pip` vs. `which python` resolving to two
  different trees, and the pip-audit warning message naming the wrong path explicitly). Fix: always
  use `uv sync` / `uv add` / `uv run`, never bare `pip`, inside a uv-managed venv.
- **Corrected a flag-name inconsistency in the prompt.** §3.2 names `uv sync --frozen` as the
  install command, and §4/§6 require it to "catch lock ≠ pyproject drift" and turn CI red on
  intentional drift. Empirically verified (`uv sync --help`, then a live test: bumped an
  `orjson` floor in `pyproject.toml` without re-locking):
  - `--frozen` = "Sync without updating `uv.lock`" — it did **not** detect the drift, exited 0
    silently using the stale lock.
  - `--locked` = "Assert that `uv.lock` will remain unchanged" — it **did** fail with
    `error: The lockfile at uv.lock needs to be updated, but --locked was provided.`
  - This plan therefore uses `--locked` everywhere the prompt says `--frozen`, since `--locked` is
    what actually satisfies the prompt's own stated Abnahme-Gate requirement. Both flags still
    install hash-checked from the lock; the only difference is whether drift is caught.
- **Verified the CycloneDX SBOM step end-to-end.** `uv export --format cyclonedx1.5` is a **native**
  uv command (no `cyclonedx-py`/third-party tool needed) — confirmed it produces valid CycloneDX
  1.5 JSON with correct `purl`s. Chose to scope it to the **base runtime deps only** (no
  `--extra dev/build`) since that's what's actually inside the shipped PyInstaller bundle — 27
  components, matches `pyproject.toml`'s `[project.dependencies]` exactly. uv marks this format
  "experimental" (stderr warning only, exit 0); passed `--preview-features sbom-export` to silence
  the warning. Low blast-radius if the format changes in a future uv release — it's a published
  artifact, not a build-blocking gate.
- **Built the app locally via `uv run python scripts/build_app.py`** (macOS) end-to-end from a
  `uv sync --locked --extra build` environment — succeeded, produced
  `dist/Audit Sampling Tool.app`.
- **Verified the bundle-smoke shell logic against the real bundle**, both success and failure paths:
  - Success: launched `dist/Audit Sampling Tool.app/Contents/MacOS/AuditSamplingTool` with
    `QT_QPA_PLATFORM=offscreen` in the background, confirmed `kill -0 $PID` still succeeds after the
    sleep window (process alive → app started without crashing), then killed it cleanly.
  - Failure: temporarily stripped the `pypdf` hiddenimport from `sampling_tool.spec` to try to
    reproduce a real crash — PyInstaller's static analysis still found `pypdf` via the module-level
    `from pypdf import ...` in `pdf_report.py`, so the app still started (the explicit hiddenimport
    entry is defensive/redundant for this particular import, same pattern as the `logging.handlers`
    comment already in the spec). Reverted the spec immediately. To still prove the *detection
    logic* works, ran the identical smoke shell logic against a synthetic script that prints a
    traceback and `exit 1` — confirmed the "process exited early → FAILED, surface the exit code"
    branch fires correctly. The detection mechanism (alive-after-N-seconds vs. exited-early) is
    sound; it does not depend on which specific import is missing.
  - Windows path (`dist\AuditSamplingTool\AuditSamplingTool.exe` via `Start-Process`/`Stop-Process`)
    could not be hands-on-verified locally (macOS dev machine) — will be verified for real by the
    CI matrix run in Task 6.
- Ran the exact pre-push-hook commands against the `uv sync --locked --extra dev` environment
  before writing any workflow YAML, to confirm nothing about switching to `uv` breaks local dev:
  `pytest -q` → 1412 passed, `ruff check .` → all checks passed, `ruff format --check .` → 172
  files already formatted, `mypy src tests` → no issues in 166 files, `uv run pip-audit` → no known
  vulnerabilities (the one `sampling-tool` "skip" is expected — it's not on PyPI).
- Resolved the exact SHA for the one new Action (`git ls-remote --tags`):
  `astral-sh/setup-uv@v8.3.2` → `11f9893b081a58869d3b5fccaea48c9e9e46f990`. Verified its
  `action.yml` inputs (`version`, `enable-cache`, `cache-dependency-glob`) via
  `gh api repos/astral-sh/setup-uv/contents/action.yml?ref=v8.3.2`.

---

## Task 1: Worktree + branch

```bash
cd /Users/kaufer/dev/Sampling-Tool
git fetch origin
git worktree add .claude/worktrees/sprint-55-uv-locks-sbom -b feat/sprint-55-uv-locks-sbom origin/main
cd .claude/worktrees/sprint-55-uv-locks-sbom
brew install uv   # or: curl -LsSf https://astral.sh/uv/install.sh | sh
```

- [x] Done — worktree created from `origin/main` (`85c2e9b`), `uv 0.11.29` installed via Homebrew.

---

## Task 2: Add `pip-audit` to the `dev` extra, generate `uv.lock`

**Files:**
- Modify: `pyproject.toml` (`[project.optional-dependencies].dev`)
- Create: `uv.lock`

`pip-audit` needs to live *inside* the locked/synced environment (so `uv run pip-audit` scans
exactly the hash-pinned set, not an ad-hoc `pip install` into an unrelated venv — see the PATH trap
in the research section above).

- [x] **Step 1:** add to `pyproject.toml`:

```toml
dev = [
    "pytest>=8.2",
    "pytest-qt>=4.4",
    "pytest-cov>=5.0",
    "ruff>=0.6",
    "mypy>=1.11",
    # Sprint 55 / S3.2b2: Vulnerability-Scan gegen die gelockte Umgebung
    # (CI + Release-Test-Gate), ersetzt das vorherige Ad-hoc-`pip install
    # pip-audit` in ci.yml.
    "pip-audit>=2.7",
]
```

- [x] **Step 2:** `uv lock` → resolved 73 packages (universal, 9 marker-split environments), with
  hashes. `pip` itself got pulled in transitively (pip-audit's own dependency) — expected, and it
  incidentally makes `uv run pip-audit` immune to the PATH trap since it now uses its own bundled
  `pip` module via `sys.executable -m pip`, not a PATH-resolved `pip` binary.
- [x] **Step 3:** `uv sync --locked --extra dev` → clean install, no errors.
- [x] **Step 4:** `uv run pip-audit` → `No known vulnerabilities found`.

---

## Task 3: `ci.yml` — install from the lock, hash-checked

**Files:** Modify `.github/workflows/ci.yml` (full file, 57 → 55 lines)

- [x] Replace `cache: 'pip'` + `pip install -e ".[dev]"` + ad-hoc `pip install pip-audit` with:

```yaml
      - name: Install uv
        uses: astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990 # v8.3.2
        with:
          version: "0.11.29"
          enable-cache: true
          cache-dependency-glob: "uv.lock"

      - name: Install dependencies (hash-checked from uv.lock)
        run: uv sync --locked --extra dev --python ${{ matrix.python-version }}
```

...and every `run: pytest ...` / `ruff ...` / `mypy ...` step becomes `run: uv run pytest ...` /
`uv run ruff ...` / `uv run mypy ...`. The `pip-audit` step becomes `run: uv run pip-audit` (no
more ad-hoc `pip install pip-audit` — it's in the lock now). Job name `test` and the
`os`/`python-version` matrix are untouched, so the three Required Status Check names are unchanged.

- [x] **Verify:** `uv run --with pyyaml python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` → valid YAML.
- [x] **Verify:** `git grep -nE "uses: .*@v[0-9]" -- .github/workflows/` → no output (all pinned).

---

## Task 4: `release.yml` — lock-based installs in `test`/`build`, Frozen-Bundle-Smoke, SBOM

**Files:** Modify `.github/workflows/release.yml` (full file, 129 → 194 lines)

- [x] **`test` job:** same `uv sync --locked --extra dev` swap as Task 3 (no matrix — single
  `ubuntu-latest` run), plus `uv run pip-audit` added here too (this job gates every release build,
  so it gets the same scan as CI).
- [x] **`build` job:** `pip install -e ".[build]"` → `uv sync --locked --extra build`; the actual
  PyInstaller invocation becomes `uv run python scripts/build_app.py` (runs inside the synced venv
  via `sys.executable`, so PyInstaller freezes exactly the locked/hash-checked packages).
- [x] **New step "Frozen-Bundle-Smoke (macOS)"** (`if: matrix.os == 'macos-latest'`), inserted
  after `Build` and before `Package macOS .app`:

```yaml
      - name: Frozen-Bundle-Smoke (macOS)
        if: matrix.os == 'macos-latest'
        env:
          QT_QPA_PLATFORM: offscreen
        run: |
          set -e
          BIN="dist/Audit Sampling Tool.app/Contents/MacOS/AuditSamplingTool"
          "$BIN" &
          PID=$!
          sleep 10
          if kill -0 "$PID" 2>/dev/null; then
            echo "Bundle-Smoke OK: Prozess läuft nach 10s (kein Startup-/Import-Crash)."
            kill "$PID"
            wait "$PID" 2>/dev/null || true
          else
            wait "$PID"
            STATUS=$?
            echo "Bundle-Smoke FAILED: Prozess ist vorzeitig beendet (exit $STATUS)."
            exit 1
          fi
        shell: bash
```

  Verified hands-on against the real local build (see research section): alive-after-10s → pass +
  clean kill; early-exit → fail + surfaced exit code (proven via a synthetic crashing script, since
  the real app didn't crash even with `pypdf` stripped from hiddenimports — PyInstaller's static
  analysis still found it via the module-level import in `pdf_report.py`).

- [x] **New step "Frozen-Bundle-Smoke (Windows)"** (`if: matrix.os == 'windows-latest'`), same
  position, PowerShell equivalent (`Start-Process -PassThru` / `Stop-Process`) — same
  alive-after-10s logic, targets `dist\AuditSamplingTool\AuditSamplingTool.exe`. Not hands-on
  verified locally (no Windows dev machine) — first real verification happens in CI (Task 6).
- [x] **`release` job:** now `checkout`s the repo (needed for `uv.lock`) and adds:

```yaml
      - name: Install uv
        uses: astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990 # v8.3.2
        with:
          version: "0.11.29"

      - name: Generate CycloneDX SBOM from the lock
        run: uv export --locked --format cyclonedx1.5 --preview-features sbom-export -o sbom.cdx.json
```

  ...and an `Upload SBOM artifact` step (`actions/upload-artifact`, same pinned SHA as the build
  artifacts), plus `sbom.cdx.json` appended to the existing `action-gh-release` `files:` list
  alongside the two ZIPs and `SHA256SUMS`.

- [x] **Verify:** YAML valid; job graph `test -> build -> release` confirmed via a small PyYAML
  script (see research section — `wf["jobs"]["build"]["needs"] == ["test"]`,
  `wf["jobs"]["release"]["needs"] == "build"`).
- [x] **Verify:** `uv export --locked --format cyclonedx1.5 -o /tmp/sbom.cdx.json` run locally
  against the real lock → valid CycloneDX 1.5 JSON, 27 components (base runtime deps only, matches
  `[project.dependencies]`), correct `purl`s, `pywin32` correctly marker-tagged
  `sys_platform == 'win32'`.

---

## Task 5: Dependabot + README

**Files:** Modify `.github/dependabot.yml`, `README.md`

- [x] `.github/dependabot.yml`: `package-ecosystem: "pip"` → `package-ecosystem: "uv"` (native uv
  ecosystem, tracks `uv.lock` + `pyproject.toml` together). `github-actions` entry unchanged.
- [x] `README.md` §"Installation für Entwickler" and §"Distribution / Release-Build": added
  `uv sync --locked --extra dev` / `uv run python -m sampling_tool` /
  `uv sync --locked --extra build` / `uv run python scripts/build_app.py` as the recommended,
  CI-parity path; kept the existing `pip install -e ".[dev]"` path as a documented alternative
  (open ranges, no hash verification) rather than removing it — the prompt says "ergänzen"
  (supplement), not replace. `CLAUDE.md`'s `Entwicklungs-Kommandos` deliberately left untouched
  (out of scope per this repo's established convention of not touching `CLAUDE.md` unless a sprint
  prompt explicitly asks for it — this prompt's file list names `README`/`docs`, not `CLAUDE.md`,
  and the existing `pip install -e ".[dev]"` commands there still work unchanged).

---

## Task 6: Full local verification (pre-push-hook parity) + push/PR/merge

**Files:** none (verification + git/gh operations only)

- [x] **Step 1:** ran the exact pre-push hook commands inside `uv sync --locked --extra dev`:
  `pytest -q` (1412 passed), `ruff check .`, `ruff format --check .`, `mypy src tests` — all green.
  No `src/` files changed this sprint, so this confirms "nothing broke," not new behavior.
- [ ] **Step 2:** `git add` the 6 changed/new paths, commit, push, `gh pr create`.
- [ ] **Step 3:** `gh run watch --exit-status` — first real cross-OS verification of
  `uv sync --locked` (all 3 OS) and the Windows half of the Frozen-Bundle-Smoke (only reachable via
  a `workflow_dispatch` run of `release.yml`, since `ci.yml` is what gates the PR). If CI is red for
  a reason not covered by the STOP conditions below, diagnose and fix; if it's a genuine `uv sync`
  platform-wheel resolution failure or an unfixable `pip-audit` finding, **STOP** per
  `SPRINT_55_PROMPT.md` §9.
- [ ] **Step 4:** once green on all three required checks, `gh pr merge --squash --delete-branch`.
- [ ] **Step 5:** clean up: `git worktree remove`, `git checkout main`, `git pull`.

---

## Self-Review

**Spec coverage** (against `SPRINT_55_PROMPT.md` §2 "In Scope" + Definition of Done):
- Universal `uv.lock` with hashes, committed → Task 2.
- CI + Release install from the lock, hash-checked, drift-detecting → Task 3 + Task 4 (`--locked`,
  with the flag-name correction documented above).
- `pip-audit` against the locked env → Task 2 (dev extra) + Task 3/4 (`uv run pip-audit`).
- CycloneDX SBOM published with the release + as artifact → Task 4.
- Frozen-Bundle-Smoke (start + pypdf-resolvable) on macOS + Windows, after Build before Package →
  Task 4.
- Dependabot tracks the uv lock → Task 5.
- Local dev unbroken, pre-push-hook commands unchanged, `uv sync` setup hint added → Task 5 + 6.
- `S3.2` complete (S-005 minus Signing) once merged.

**Placeholder scan:** no TBD/TODO; every step has literal, already-executed commands and their real
observed output, not hypothetical expected output — this plan was written after hands-on
verification, not before.

**Type/name consistency:** artifact names (`AuditSamplingTool-macOS.zip` / `-Windows.zip`) and job
names (`test`/`build`/`release`) unchanged from Sprint 54; `sbom.cdx.json` name matches between the
new SBOM step, the `upload-artifact` step, and the `action-gh-release` `files:` entry.
