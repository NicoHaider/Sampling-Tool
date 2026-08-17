"""Prüffunktionen für die Zusagen in `.github/workflows/` (Sprint 77 / Befund #4).

`ci.yml` läuft auf `pull_request`, `release.yml` nur auf Tags und
`workflow_dispatch`. Eine PR, die `release.yml` ändert, bekommt damit drei grüne
Checks aus `ci.yml`, von denen **keiner eine Zeile der geänderten Datei
ausführt** – ein Dependabot-Bump kann die Absicherungen der Sprints 54/61/73–76
still fallen lassen und trotzdem grün mergen. Diese Datei macht die Zusagen zu
etwas, das auf **jeder** PR in Millisekunden geprüft wird.

Bauweise (Sprint 77 / §2.2 + §2.4):

* Jede Prüfung ist eine **reine Funktion** über einem bereits geladenen
  Workflow-Dict und gibt eine Liste von Verstoß-Meldungen zurück (leer = in
  Ordnung). Damit lässt sich dieselbe Funktion sowohl auf die echte Datei als
  auch auf eine **mutierte Kopie** anwenden – die Positiv-Kontrolle, die belegt,
  dass die Prüfung überhaupt etwas merkt.
* Geprüft wird die **Struktur**, nicht der Text. Kein `grep`, keine Regex über
  die Rohdatei – sonst bräche die Prüfung bei jeder Umformatierung aus dem
  falschen Grund. Wo eine Zusage zwangsläufig im Shell-Text steckt (`zip -y`,
  `uv sync --locked`), wird der `run`-Körper **tokenisiert**, nicht gematcht.

Die Zusagen selbst stehen in den Docstrings der `check_*`-Funktionen, jeweils
mit dem Sprint, der sie eingeführt hat (§2.3): wer eine Zeile entfernen will,
liest hier zuerst den Grund.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

# Der Name der Variablen wird NICHT zweimal getippt: der Wächter besitzt ihn,
# diese Datei prüft nur, dass die Workflows ihn setzen (§5.3 – keine
# SSOT-Literale in Tests).
from tests._test_floor import ENFORCE_TEST_FLOOR_ENV

# Bewusst `dict[Any, Any]` und nicht `dict[str, Any]`: YAML 1.1 liest das
# unquotierte `on:` als Boolean, der geladene Workflow hat also einen `True`-Key
# neben lauter String-Keys (siehe `workflow_triggers`).
Workflow = dict[Any, Any]
Step = dict[str, Any]

_SHA40 = re.compile(r"[0-9a-f]{40}")


# ---------------------------------------------------------------------------
# Laden & Navigieren
# ---------------------------------------------------------------------------


def repo_root() -> Path:
    """Repo-Wurzel über die nächstgelegene `pyproject.toml` (wie test_docs_smoke)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise AssertionError("pyproject.toml nicht gefunden – REPO_ROOT unklar")


def workflow_path(name: str) -> Path:
    return repo_root() / ".github" / "workflows" / name


def load_workflow(name: str) -> Workflow:
    """Lädt einen Workflow per `yaml.safe_load`."""
    import yaml

    data = yaml.safe_load(workflow_path(name).read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{name} ist keine Mapping-Struktur"
    return data


def workflow_triggers(workflow: Workflow) -> Any:
    """Der `on:`-Block.

    YAML 1.1 liest das unquotierte `on` als **Boolean** – `yaml.safe_load`
    liefert den Key `True`, nicht `"on"`. Gemessen, nicht vermutet: ein
    `workflow["on"]` wirft hier `KeyError`. Beide Schreibweisen werden bedient,
    damit ein späteres `"on":` in Anführungszeichen die Prüfung nicht kippt.
    """
    if True in workflow:
        return workflow[True]
    return workflow.get("on")


def jobs(workflow: Workflow) -> dict[str, Any]:
    result = workflow.get("jobs") or {}
    assert isinstance(result, dict)
    return result


def steps(job: dict[str, Any]) -> list[Step]:
    """Die Steps eines Jobs.

    Achtung beim Mutieren: die zurückgegebene LISTE ist eine gefilterte Kopie
    (die Step-Dicts darin sind dieselben Objekte). `steps(job).insert(...)`
    landet deshalb im Nichts – wer die Reihenfolge ändert, muss
    `job["steps"] = …` zurückschreiben.
    """
    result = job.get("steps") or []
    assert isinstance(result, list)
    return [s for s in result if isinstance(s, dict)]


def needs_of(job: dict[str, Any]) -> list[str]:
    """`needs:` normalisiert.

    GitHub erlaubt beides – `needs: build` (String) und `needs: [test]` (Liste).
    Im Repo kommen beide Formen vor; ohne Normalisierung prüfte die Funktion
    je nach Schreibweise etwas anderes.
    """
    raw = job.get("needs")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    return [str(item) for item in raw]


def step_label(job_id: str, index: int, step: Step) -> str:
    name = step.get("name") or step.get("uses") or "<unbenannt>"
    return f"Job '{job_id}' Step {index} ({name})"


def uses_ref(step: Step) -> tuple[str, str] | None:
    """`(action, ref)` eines `uses:`-Steps, sonst `None`."""
    raw = step.get("uses")
    if not isinstance(raw, str):
        return None
    action, _, ref = raw.partition("@")
    return action, ref


def with_of(step: Step) -> dict[str, Any]:
    raw = step.get("with")
    return raw if isinstance(raw, dict) else {}


def steps_using(workflow: Workflow, action: str) -> list[tuple[str, int, Step]]:
    """Alle Steps, die `action` verwenden (Ref/Version egal)."""
    found = []
    for job_id, job in jobs(workflow).items():
        for index, step in enumerate(steps(job)):
            ref = uses_ref(step)
            if ref is not None and ref[0] == action:
                found.append((job_id, index, step))
    return found


def run_steps(workflow: Workflow) -> list[tuple[str, int, Step]]:
    found = []
    for job_id, job in jobs(workflow).items():
        for index, step in enumerate(steps(job)):
            if isinstance(step.get("run"), str):
                found.append((job_id, index, step))
    return found


# ---------------------------------------------------------------------------
# Shell-Körper: tokenisieren statt matchen
# ---------------------------------------------------------------------------


def strip_shell_comments(body: str) -> str:
    """Entfernt reine Kommentarzeilen aus einem `run`-Körper.

    Beide Workflows sind dicht kommentiert, und die Kommentare nennen genau die
    Bezeichner, nach denen hier gesucht wird (`pip-audit`, `zip`, `--locked`).
    Ohne diesen Schritt prüfte die Funktion die Begründung statt der Zeile.
    """
    return "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))


def _tokenize_line(line: str) -> list[str]:
    """Eine Shell-Zeile in Tokens zerlegen – bewusst tolerant.

    `shlex.split` scheitert an unbalancierten Anführungszeichen (deutsche
    Apostrophe in Prosa). Der Fallback zerlegt dann grob an Whitespace; für die
    Frage „steht `-y` hinter `zip`?" reicht das, und ein harter Absturz der
    Prüffunktion wäre die schlechtere Antwort.
    """
    try:
        return shlex.split(line, comments=True)
    except ValueError:
        return line.split()


def tokenize(body: str) -> list[str]:
    """Alle Tokens eines `run`-Körpers, Kommentare entfernt."""
    tokens: list[str] = []
    for line in strip_shell_comments(body).splitlines():
        tokens.extend(_tokenize_line(line))
    return tokens


def command_args(body: str, command: str) -> list[list[str]]:
    """Alle Argumentlisten zu einem Kommando, je Zeile und bis zum nächsten Trenner.

    Zeilenweise, weil `shlex` Zeilenumbrüche als gewöhnlichen Whitespace
    schluckt: ohne die Zeilengrenze liefe die Argumentliste eines `zip`-Aufrufs
    in die nächsten Kommandos hinein, und ein `-y` drei Zeilen weiter zählte
    fälschlich als Flag dieses Aufrufs.
    """
    separators = {"|", "||", "&&", ";", "&", ">", ">>", "<"}
    slices = []
    for line in strip_shell_comments(body).splitlines():
        tokens = _tokenize_line(line)
        for i, token in enumerate(tokens):
            if token != command:
                continue
            args = []
            for follow in tokens[i + 1 :]:
                if follow in separators:
                    break
                args.append(follow)
            slices.append(args)
    return slices


def has_flag(args: list[str], flag: str) -> bool:
    """Prüft ein Kurz-Flag, auch in zusammengezogener Form (`-qry` enthält `-y`)."""
    letter = flag.lstrip("-")
    for arg in args:
        if arg == flag:
            return True
        if arg.startswith("-") and not arg.startswith("--") and letter in arg[1:]:
            return True
    return False


def has_real_pipe(body: str) -> bool:
    """Enthält der Körper eine echte Shell-Pipe (kein `||`, kein `|&`)?"""
    for line in strip_shell_comments(body).splitlines():
        probe = line.replace("||", "").replace("|&", "")
        if "|" in probe:
            return True
    return False


# ---------------------------------------------------------------------------
# Die geprüften Zusagen
# ---------------------------------------------------------------------------


def check_actions_are_sha_pinned(workflow: Workflow, *, name: str) -> list[str]:
    """Sprint 54: jede `uses:`-Referenz ist auf einen 40-stelligen Commit-SHA gepinnt.

    Die Zusage, die ein Dependabot-PR am ehesten berührt: ein Bump auf einen Tag
    (`@v5`) macht die Referenz beweglich – der Inhalt hinter dem Tag kann sich
    ohne Repo-Änderung ändern.
    """
    violations = []
    for job_id, job in jobs(workflow).items():
        for index, step in enumerate(steps(job)):
            ref = uses_ref(step)
            if ref is None:
                continue
            action, sha = ref
            if action.startswith("./") or action.startswith("docker://"):
                continue
            if not _SHA40.fullmatch(sha):
                violations.append(
                    f"{name}: {step_label(job_id, index, step)} verwendet "
                    f"'{action}@{sha or '<ohne Ref>'}' – erwartet ist ein 40-stelliger "
                    f"Commit-SHA (Sprint 54)."
                )
    return violations


def check_upload_artifact_fails_on_empty(workflow: Workflow, *, name: str) -> list[str]:
    """Sprint 75 / B.1: jeder `actions/upload-artifact`-Step hat `if-no-files-found: error`.

    Ohne den Key ist der Default `warn`: matcht `path` nichts, lädt der Step
    NULL Dateien hoch und bleibt GRÜN – der Weg in ein grünes, aber
    unvollständiges Release.
    """
    violations = []
    for job_id, index, step in steps_using(workflow, "actions/upload-artifact"):
        value = with_of(step).get("if-no-files-found")
        if value != "error":
            violations.append(
                f"{name}: {step_label(job_id, index, step)} hat "
                f"if-no-files-found={value!r} statt 'error' – ein Upload ohne Treffer "
                f"bliebe grün (Sprint 75 / B.1)."
            )
    return violations


def check_piped_run_steps_have_pipefail(workflow: Workflow, *, name: str) -> list[str]:
    """Sprint 75 / B.2: jeder `run:`-Step mit Pipe hat abgesicherte Pipe-Semantik.

    GitHubs Default-Shell ist `bash -e {0}` – **ohne** `pipefail`. `sha256sum …
    | sed … > SHA256SUMS` nimmt dann den Exit-Code von `sed` (immer 0). Genau so
    entstand die grüne, halb leere SHA256SUMS. `shell: bash` schaltet
    GitHub auf `bash --noprofile --norc -eo pipefail {0}`; ein explizites
    `set -o pipefail` im Körper tut dasselbe. Für PowerShell-Steps ist
    `$ErrorActionPreference = 'Stop'` das Äquivalent.
    """
    violations = []
    for job_id, index, step in run_steps(workflow):
        body = step["run"]
        if not has_real_pipe(body):
            continue
        shell = step.get("shell")
        if shell == "bash":
            continue
        if shell in {"pwsh", "powershell"}:
            if "ErrorActionPreference" in body:
                continue
            violations.append(
                f"{name}: {step_label(job_id, index, step)} nutzt eine Pipe unter "
                f"{shell!r}, setzt aber kein $ErrorActionPreference (Sprint 75 / B.2)."
            )
            continue
        if "pipefail" in body:
            continue
        violations.append(
            f"{name}: {step_label(job_id, index, step)} nutzt eine Pipe, hat aber "
            f"weder 'shell: bash' noch 'set -o pipefail' – die Default-Shell läuft "
            f"OHNE pipefail, ein Fehler in der Pipe bliebe unbemerkt (Sprint 75 / B.2)."
        )
    return violations


def check_gh_release_fails_on_unmatched_files(workflow: Workflow, *, name: str) -> list[str]:
    """Sprint 75 / B.3: `action-gh-release` hat `fail_on_unmatched_files: true`.

    Ohne den Key ist der Default `false`: ein Eintrag in `files:`, der nichts
    matcht, wird still übersprungen und das Release entsteht trotzdem – die
    letzte Stelle, an der eine fehlende Binärdatei lautlos verschwinden konnte.
    """
    violations = []
    for job_id, index, step in steps_using(workflow, "softprops/action-gh-release"):
        value = with_of(step).get("fail_on_unmatched_files")
        if value is not True and str(value).lower() != "true":
            violations.append(
                f"{name}: {step_label(job_id, index, step)} hat "
                f"fail_on_unmatched_files={value!r} statt true – ein Eintrag in 'files:' "
                f"ohne Treffer würde still übersprungen (Sprint 75 / B.3)."
            )
    return violations


def check_macos_packaging_preserves_symlinks(workflow: Workflow, *, name: str) -> list[str]:
    """Sprint 76: der `zip`-Aufruf im Packaging-Step trägt `-y`.

    OHNE das Flag FOLGT `zip -r` den Symlinks, die PyInstaller im .app anlegt,
    statt sie zu speichern. Am echten Bundle gemessen: 107 Symlinks -> 0,
    entpackt 3,90× so groß. Ein macOS-.app ist keine Ordnerhierarchie, sondern
    eine Struktur MIT Symlinks.
    """
    violations = []
    for job_id, index, step in run_steps(workflow):
        for args in command_args(step["run"], "zip"):
            if not has_flag(args, "-y"):
                violations.append(
                    f"{name}: {step_label(job_id, index, step)} ruft 'zip' ohne '-y' auf – "
                    f"die Symlinks des .app-Bundles würden dereferenziert (Sprint 76)."
                )
    return violations


def check_uv_sync_is_locked(workflow: Workflow, *, name: str) -> list[str]:
    """Sprint 61: jedes `uv sync` läuft mit `--locked`.

    `--frozen` installiert den Lock, ohne ihn gegen `pyproject.toml` zu prüfen –
    eine Metadaten-Änderung ohne `uv lock` liefe damit grün durch. `--locked`
    ist die einzige Variante, die die Drift bemerkt.
    """
    violations = []
    for job_id, index, step in run_steps(workflow):
        for args in command_args(step["run"], "uv"):
            if not args or args[0] != "sync":
                continue
            if "--locked" not in args:
                violations.append(
                    f"{name}: {step_label(job_id, index, step)} ruft 'uv sync' ohne "
                    f"'--locked' auf – Drift zwischen pyproject.toml und uv.lock bliebe "
                    f"unbemerkt (Sprint 61)."
                )
    return violations


def check_pip_audit_not_in_test_job(workflow: Workflow, *, name: str) -> list[str]:
    """Sprint 73/74: `pip-audit` steckt in keinem `test`-Job.

    Der Advisory-Stand ist eine LIVE-Quelle. Als Step vor `pytest` hat er in
    Sprint 72 den kompletten Ubuntu-Testlauf verschluckt – roter Check, aber
    kein einziges Testergebnis. In `release.yml` brach er zusätzlich getaggte
    Releases ab, bevor ein Test gelaufen war.
    """
    violations = []
    for job_id, job in jobs(workflow).items():
        if job_id != "test":
            continue
        for index, step in enumerate(steps(job)):
            body = step.get("run")
            if not isinstance(body, str):
                continue
            if "pip-audit" in tokenize(body):
                violations.append(
                    f"{name}: {step_label(job_id, index, step)} ruft 'pip-audit' im "
                    f"'test'-Job auf – er verschluckt den Testlauf (Sprint 73/74)."
                )
    return violations


_VERIFICATION_COMMANDS = ("pytest", "ruff", "mypy")
#: pytest + ruff check + ruff format + mypy = vier Steps. Die Zahl ist der
#: Anti-Vakuum-Wert: eine Prüfung, die nur die vorhandenen Steps betrachtet,
#: wäre nach dem Löschen aller vier zufrieden.
_MIN_VERIFICATION_STEPS = 4


def check_verification_steps_run_independently(workflow: Workflow, *, name: str) -> list[str]:
    """Sprint 73/74: die Prüf-Steps im `test`-Job haben `if: '!cancelled()'`.

    Ohne `if` überspringt der erste rote Step alle folgenden – ein
    fehlgeschlagener pytest-Lauf verdeckte ruff/mypy komplett. `!cancelled()`
    statt `always()`, damit abgebrochene Läufe NICHT weiterlaufen.

    Anti-Vakuum: fehlen die Prüf-Steps ganz, ist das ebenfalls ein Verstoß –
    sonst wäre die Prüfung nach dem Löschen des Testlaufs zufrieden.
    """
    violations = []
    for job_id, job in jobs(workflow).items():
        if job_id != "test":
            continue
        found = 0
        for index, step in enumerate(steps(job)):
            body = step.get("run")
            if not isinstance(body, str):
                continue
            tokens = tokenize(body)
            if not any(command in tokens for command in _VERIFICATION_COMMANDS):
                continue
            found += 1
            if step.get("if") != "!cancelled()":
                violations.append(
                    f"{name}: {step_label(job_id, index, step)} ist ein Prüf-Step ohne "
                    f"if: '!cancelled()' (hat {step.get('if')!r}) – ein roter Vorgänger "
                    f"würde ihn überspringen und sein Ergebnis verdecken (Sprint 73/74)."
                )
        if found < _MIN_VERIFICATION_STEPS:
            violations.append(
                f"{name}: Job '{job_id}' hat nur {found} Prüf-Step(s), erwartet "
                f"{_MIN_VERIFICATION_STEPS} ({', '.join(_VERIFICATION_COMMANDS)}) – ein "
                f"Testlauf, den es nicht mehr gibt, kann nicht rot werden (Sprint 73/74)."
            )
    return violations


def check_build_does_not_need_audit(workflow: Workflow, *, name: str) -> list[str]:
    """Sprint 74: `build` hängt nicht an `audit`.

    Sonst wäre die Maskierung nur von einem Step in eine Job-Abhängigkeit
    verschoben: ein neues Advisory in irgendeiner Dependency bräche den Build
    ab, obwohl der Code grün getestet ist.
    """
    violations = []
    for job_id, job in jobs(workflow).items():
        if job_id == "build" and "audit" in needs_of(job):
            violations.append(
                f"{name}: Job 'build' hat needs={needs_of(job)!r} – die Abhängigkeit auf "
                f"'audit' verschiebt die Maskierung nur in den Job-Graphen (Sprint 74)."
            )
    return violations


def check_no_continue_on_error(workflow: Workflow, *, name: str) -> list[str]:
    """Sprint 73/74: kein Job und kein Step trägt `continue-on-error: true`.

    Beide Workflows halten das ausdrücklich fest („Bewusst KEIN
    continue-on-error"). Der Key ist die direkteste Art, einen roten Check grün
    zu machen, ohne die Ursache zu beheben.
    """
    violations = []
    for job_id, job in jobs(workflow).items():
        if job.get("continue-on-error") is True:
            violations.append(
                f"{name}: Job '{job_id}' hat continue-on-error: true – der Job kann "
                f"nicht mehr rot werden (Sprint 73/74)."
            )
        for index, step in enumerate(steps(job)):
            if step.get("continue-on-error") is True:
                violations.append(
                    f"{name}: {step_label(job_id, index, step)} hat continue-on-error: "
                    f"true – der Step kann nicht mehr rot werden (Sprint 73/74)."
                )
    return violations


def check_test_floor_is_armed(workflow: Workflow, *, name: str) -> list[str]:
    """Sprint 77: der pytest-Step schaltet den Testmengen-Wächter scharf.

    Der Wächter in `tests/conftest.py` ist ohne
    `SAMPLING_TOOL_ENFORCE_TEST_FLOOR` bewusst ein No-Op (sonst schlüge jeder
    lokale Teil-Lauf fehl). Fehlt die Variable im Workflow, ist er überall
    stumm – ein Wächter, der nirgends läuft.
    """
    violations = []
    found = 0
    for job_id, index, step in run_steps(workflow):
        if "pytest" not in tokenize(step["run"]):
            continue
        found += 1
        env = step.get("env") or {}
        value = env.get(ENFORCE_TEST_FLOOR_ENV) if isinstance(env, dict) else None
        if str(value) != "1":
            violations.append(
                f"{name}: {step_label(job_id, index, step)} setzt "
                f"{ENFORCE_TEST_FLOOR_ENV}={value!r} statt '1' – der Testmengen-Wächter "
                f"bliebe stumm (Sprint 77)."
            )
    if found == 0:
        violations.append(
            f"{name}: kein pytest-Step gefunden – der Testmengen-Wächter hat keinen "
            f"Ort, an dem er greifen könnte (Sprint 77)."
        )
    return violations


# ---------------------------------------------------------------------------
# release.yml-spezifisch
# ---------------------------------------------------------------------------

_ARCHIVERS = ("zip", "7z")
_EXTRACTORS = ("unzip", "Expand-Archive")


def _is_packaging(step: Step) -> bool:
    body = step.get("run")
    if not isinstance(body, str):
        return False
    return any(command_args(body, archiver) for archiver in _ARCHIVERS)


def _is_smoke(step: Step) -> bool:
    body = step.get("run")
    if not isinstance(body, str):
        return False
    cleaned = strip_shell_comments(body)
    return any(extractor in cleaned for extractor in _EXTRACTORS)


def check_smoke_runs_on_the_packaged_artefact(workflow: Workflow, *, name: str) -> list[str]:
    """Sprint 76: im Job `build` kommt der Smoke NACH dem Packen und liest das Artefakt.

    Vorher lief der Smoke gegen `dist/`, also gegen das UNVERPACKTE
    Build-Ergebnis; die Symlink-Zerstörung durch `zip -r` passierte danach und
    war für jede bestehende Prüfung strukturell unerreichbar. Geprüft wurde X,
    ausgeliefert wurde Y.

    Zuordnung über die `if:`-Bedingung statt über Step-Namen: Packen und Smoke
    einer Plattform teilen dieselbe Bedingung, und eine umformulierte
    Step-Überschrift darf die Prüfung nicht kippen.

    GRENZE, ehrlich benannt: geprüft ist, dass der Smoke-Step das Archiv
    **entpackt** und nach dem Packen läuft. Dass jede einzelne Messung darin auf
    dem Entpackten sitzt, prüft diese Funktion nicht – der macOS-Step liest
    `dist/` bewusst weiter als gemessenen Vergleichswert.
    """
    violations = []
    for job_id, job in jobs(workflow).items():
        if job_id != "build":
            continue
        job_steps = steps(job)
        packaging = [(i, s) for i, s in enumerate(job_steps) if _is_packaging(s)]
        smoke = [(i, s) for i, s in enumerate(job_steps) if _is_smoke(s)]
        uploads = [
            i
            for i, s in enumerate(job_steps)
            if (uses_ref(s) or ("", ""))[0].endswith("upload-artifact")
        ]

        # Anti-Vakuum: ohne diese Zählung wäre die Prüfung nach dem Löschen
        # aller Smoke-Steps zufrieden – 0 Steps verletzen keine Reihenfolge.
        if not packaging:
            violations.append(f"{name}: Job 'build' hat keinen Packaging-Step (Sprint 76).")
        if len(smoke) != len(packaging):
            violations.append(
                f"{name}: Job 'build' hat {len(packaging)} Packaging-, aber {len(smoke)} "
                f"Smoke-Step(s) – jede gepackte Plattform braucht ihren Round-Trip-Smoke "
                f"(Sprint 76)."
            )

        for smoke_index, smoke_step in smoke:
            condition = smoke_step.get("if")
            earlier = [i for i, s in packaging if i < smoke_index and s.get("if") == condition]
            if not earlier:
                violations.append(
                    f"{name}: {step_label(job_id, smoke_index, smoke_step)} läuft nicht "
                    f"nach einem Packaging-Step derselben Bedingung ({condition!r}) – der "
                    f"Smoke prüfte damit etwas anderes als das Ausgelieferte (Sprint 76)."
                )
            for upload_index in uploads:
                if upload_index < smoke_index:
                    violations.append(
                        f"{name}: Der Upload (Step {upload_index}) liegt VOR dem Smoke "
                        f"(Step {smoke_index}) – hochgeladen würde ein ungeprüftes "
                        f"Artefakt (Sprint 76)."
                    )
    return violations


def check_release_publishes_after_checksums(workflow: Workflow, *, name: str) -> list[str]:
    """Sprint 75: im Job `release` liegt die Prüfsummen-Erzeugung zwischen Download und Upload.

    Die Erwartungsliste in `Generate SHA-256 checksums` wird aus den
    heruntergeladenen Artefakt-Verzeichnissen abgeleitet. Läuft der Step vor dem
    Download, ist die Liste leer; läuft der SBOM-Upload vorher, steht die
    SBOM-Datei als zusätzliche Zeile in der veröffentlichten SHA256SUMS
    (gemessen beim Re-Run des Jobs).
    """
    violations = []
    for job_id, job in jobs(workflow).items():
        if job_id != "release":
            continue
        job_steps = steps(job)
        download = [
            i
            for i, s in enumerate(job_steps)
            if (uses_ref(s) or ("", ""))[0] == "actions/download-artifact"
        ]
        checksums = [
            i
            for i, s in enumerate(job_steps)
            if isinstance(s.get("run"), str) and "SHA256SUMS" in s["run"]
        ]
        publish = [
            i
            for i, s in enumerate(job_steps)
            if (uses_ref(s) or ("", ""))[0] == "softprops/action-gh-release"
        ]
        if not checksums:
            violations.append(
                f"{name}: Job 'release' erzeugt keine SHA256SUMS mehr – das Release "
                f"ginge ohne Prüfsummen raus (Sprint 75)."
            )
        if not publish:
            violations.append(f"{name}: Job 'release' veröffentlicht nichts (Sprint 75).")
        for checksum_index in checksums:
            if download and checksum_index < min(download):
                violations.append(
                    f"{name}: Die Prüfsummen (Step {checksum_index}) entstehen VOR dem "
                    f"Download (Step {min(download)}) – die Erwartungsliste wäre leer "
                    f"(Sprint 75)."
                )
            for publish_index in publish:
                if publish_index < checksum_index:
                    violations.append(
                        f"{name}: Veröffentlicht wird (Step {publish_index}), bevor die "
                        f"Prüfsummen entstehen (Step {checksum_index}) (Sprint 75)."
                    )
    return violations


def check_release_files_name_every_build_artefact(workflow: Workflow, *, name: str) -> list[str]:
    """Sprint 75 / B.3: die `files:`-Liste nennt jedes Matrix-Artefakt namentlich.

    Das ist die einzige NICHT-zirkuläre Erwartung zum Veröffentlichungszeitpunkt:
    die Prüfsummen-Liste leitet sich aus dem ab, was da ist, `files:` aus dem,
    was da sein SOLL. Zu einem Glob „aufgeräumt" verlöre sie genau diese
    Eigenschaft.
    """
    violations = []
    all_jobs = jobs(workflow)
    build = all_jobs.get("build") or {}
    include = ((build.get("strategy") or {}).get("matrix") or {}).get("include") or []
    expected = [
        entry["artifact_name"]
        for entry in include
        if isinstance(entry, dict) and "artifact_name" in entry
    ]

    for job_id, index, step in steps_using(workflow, "softprops/action-gh-release"):
        files = with_of(step).get("files")
        listed = str(files or "")
        for artefact in expected:
            if artefact not in listed:
                violations.append(
                    f"{name}: {step_label(job_id, index, step)} nennt '{artefact}' nicht in "
                    f"'files:' – ein fehlendes Bundle würde beim Veröffentlichen nicht "
                    f"auffallen (Sprint 75 / B.3)."
                )
    return violations


# ---------------------------------------------------------------------------
# ci.yml-spezifisch: die Identität der Required Checks
# ---------------------------------------------------------------------------

REQUIRED_CHECK_JOB = "test"
REQUIRED_CHECK_MATRIX_KEYS = ("os", "python-version")
REQUIRED_CHECK_OS = ("ubuntu-latest", "windows-latest", "macos-latest")
REQUIRED_CHECK_PYTHON = ("3.13",)


def check_required_check_identity(workflow: Workflow, *, name: str) -> list[str]:
    """Sprint 73 / Branch-Protection: der Name der Required Checks bleibt exakt.

    Die Required Checks heißen `test (<os>, <python-version>)`. Der Name setzt
    sich zusammen aus der Job-ID, der **Reihenfolge** der Matrix-Dimensionen und
    deren Werten. Ein `name:`-Override am Job ersetzt die Job-ID im Check-Namen.
    Jede dieser Änderungen lässt die Required Checks ins Leere zeigen – `main`
    wäre danach ungeschützt oder dauerhaft blockiert.
    """
    violations = []
    job = jobs(workflow).get(REQUIRED_CHECK_JOB)
    if job is None:
        return [
            f"{name}: Job '{REQUIRED_CHECK_JOB}' fehlt – die Required Checks von main "
            f"zeigen ins Leere (Sprint 73)."
        ]
    if job.get("name") is not None:
        violations.append(
            f"{name}: Job '{REQUIRED_CHECK_JOB}' hat name={job['name']!r} – ein Override "
            f"ersetzt die Job-ID im Check-Namen (Sprint 73)."
        )
    matrix = (job.get("strategy") or {}).get("matrix") or {}
    actual_keys = tuple(matrix)
    if actual_keys != REQUIRED_CHECK_MATRIX_KEYS:
        violations.append(
            f"{name}: Matrix-Dimensionen sind {actual_keys!r}, erwartet "
            f"{REQUIRED_CHECK_MATRIX_KEYS!r} – Reihenfolge und Menge stecken im "
            f"Check-Namen (Sprint 73)."
        )
    if tuple(matrix.get("os") or ()) != REQUIRED_CHECK_OS:
        violations.append(
            f"{name}: matrix.os ist {matrix.get('os')!r}, erwartet "
            f"{list(REQUIRED_CHECK_OS)!r} (Sprint 73)."
        )
    if tuple(str(v) for v in (matrix.get("python-version") or ())) != REQUIRED_CHECK_PYTHON:
        violations.append(
            f"{name}: matrix.python-version ist {matrix.get('python-version')!r}, erwartet "
            f"{list(REQUIRED_CHECK_PYTHON)!r} (Sprint 73)."
        )
    return violations


# ---------------------------------------------------------------------------
# Registry – damit kein Check versehentlich ungenutzt bleibt
# ---------------------------------------------------------------------------

#: Zusagen, die für BEIDE Workflows gelten.
SHARED_CHECKS = (
    check_actions_are_sha_pinned,
    check_upload_artifact_fails_on_empty,
    check_piped_run_steps_have_pipefail,
    check_gh_release_fails_on_unmatched_files,
    check_macos_packaging_preserves_symlinks,
    check_uv_sync_is_locked,
    check_pip_audit_not_in_test_job,
    check_verification_steps_run_independently,
    check_build_does_not_need_audit,
    check_no_continue_on_error,
    check_test_floor_is_armed,
)

#: Zusagen, die nur `release.yml` betreffen.
RELEASE_CHECKS = (
    check_smoke_runs_on_the_packaged_artefact,
    check_release_publishes_after_checksums,
    check_release_files_name_every_build_artefact,
)

#: Zusagen, die nur `ci.yml` betreffen.
CI_CHECKS = (check_required_check_identity,)


def run_all_checks(workflow: Workflow, *, name: str) -> list[str]:
    """Alle für `name` zuständigen Prüfungen; leere Liste = alle Zusagen gehalten."""
    checks = list(SHARED_CHECKS)
    if name == "release.yml":
        checks += list(RELEASE_CHECKS)
    if name == "ci.yml":
        checks += list(CI_CHECKS)
    violations: list[str] = []
    for check in checks:
        violations.extend(check(workflow, name=name))
    return violations
