# Sampling Tool

Python-Port des BDO-internen, VBA-basierten Excel-Audit-Sampling-Tools (ISAE 3402).
Cross-Platform (macOS/Windows), PyQt6-UI, SQLite-Persistenz, reproduzierbare Stichprobenziehung.

## Status

**Sprint 1 von 7** – Setup & Sampling-Core ✅ **erledigt** (22/22 Tests grün, Ruff clean).

| Sprint | Inhalt                                              | Status      |
|-------:|-----------------------------------------------------|-------------|
| 1      | Projekt-Skelett, Config, Sampling-Core + Tests      | **done**    |
| 2      | SQLite-Persistenz, Audit-Trail, Migrations         | offen       |
| 3      | I/O: Excel-Import (openpyxl), CSV, Validierung      | offen       |
| 4      | PyQt6-UI: Hauptfenster, Engagement-Verwaltung       | offen       |
| 5      | UI: Sample-Konfigurator, Vorschau, Export-Dialog    | offen       |
| 6      | Reports: PDF (reportlab), HTML (jinja2), Excel-Out  | offen       |
| 7      | Bug-Mail (pywin32/Outlook), PyInstaller-Build       | offen       |

### Was Sprint 1 liefert

- Build-Setup: `pyproject.toml` (setuptools src-Layout), Ruff (line=100), Mypy strict, Pytest+Coverage
- VSCode-Workspace (`.vscode/`): Interpreter, Pytest, Ruff-Format-on-Save, Launch-Configs
- `core/models.py` – frozen Dataclasses + StrEnums (`SamplingMethod`, `StratifyMode`)
- `core/rng.py` – `make_rng(seed)` + deterministischer Fisher-Yates-Shuffle
- `core/sampling.py` – `SimpleSampler`, `ClusterSampler`, `StratifiedSampler` (Largest-Remainder),
  Factory `create_sampler`, einheitliche `SamplingError` mit deutschen Messages
- 22 Unit-Tests inkl. „same seed → bit-genau gleiches Ergebnis"
- Stubs für `io/`, `persistence/` (mit `001_initial.sql`), `audit/`, `ui/`

## Voraussetzungen

- Python **3.13+**
- macOS oder Windows 10/11
- Aktives venv (siehe unten)

## Installation

```bash
# venv aktivieren (falls noch nicht aktiv)
source .venv/bin/activate         # macOS/Linux
# .\.venv\Scripts\activate        # Windows

# Editable install inkl. Dev-Tools
pip install -e ".[dev]"
```

## Start

```bash
python -m sampling_tool
# oder via Console-Script:
sampling-tool
```

## Tests

```bash
pytest                            # alle Tests + Coverage
pytest tests/unit                 # nur Unit-Tests
pytest -k "stratified"            # einzelne Tests filtern
pytest --cov-report=html          # HTML-Coverage in ./htmlcov/
```

## Code-Qualität

```bash
ruff check .                      # Lint
ruff format .                     # Format
mypy src tests                    # Typcheck (strict)
```

## Projektstruktur

```
src/sampling_tool/
├── core/           Sampling-Algorithmen, Modelle, RNG
├── io/             Excel-/CSV-Import, Export        (Sprint 3)
├── persistence/    SQLite + Migrations              (Sprint 2)
├── audit/          Audit-Trail / Event-Log          (Sprint 2)
└── ui/             PyQt6-Frontend                   (Sprint 4–5)

tests/
├── unit/           schnelle, isolierte Tests
├── integration/    DB- / Filesystem-Tests           (Sprint 2+)
└── fixtures/       Test-Daten
```

## Lizenz

Proprietär. BDO-intern.
