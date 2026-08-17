"""Die Zusagen in `.github/workflows/` als Test (Sprint 77 / Befund #4).

`ci.yml` läuft auf `pull_request`, `release.yml` nur auf Tags und
`workflow_dispatch`. Eine PR, die `release.yml` ändert, bekommt drei grüne
Checks aus `ci.yml` – von denen keiner eine Zeile der geänderten Datei
ausführt. Diese Datei schließt die Lücke: sie prüft auf **jeder** PR
(inklusive Dependabot) in Millisekunden, dass die Absicherungen der Sprints
54/61/73–76 noch dort stehen.

Drei Klassen, drei Aufgaben:

* `TestWorkflowGuarantees` – jede Zusage gegen die **echten** Dateien.
* `TestPolicyChecksDetectViolations` – für **jede** Zusage eine mutierte Kopie,
  bei der die Prüffunktion einen Verstoß melden MUSS. Ohne diese
  Positiv-Kontrolle wäre eine grüne Prüfung kein Beweis, sondern nur eine
  Behauptung: eine Funktion, die immer `[]` zurückgibt, bestünde die erste
  Klasse mühelos.
* `TestPolicyIsRobustToFormatting` – Umformatierung darf kein Ergebnis ändern.
  Belegt, dass hier Struktur und nicht Text geprüft wird.
"""

from __future__ import annotations

import copy
import inspect
from collections.abc import Callable
from typing import Any, ClassVar

import pytest
import yaml

from tests._test_floor import ENFORCE_TEST_FLOOR_ENV
from tests._workflow_policy import (
    CI_CHECKS,
    RELEASE_CHECKS,
    SHARED_CHECKS,
    Workflow,
    check_actions_are_sha_pinned,
    check_build_does_not_need_audit,
    check_gh_release_fails_on_unmatched_files,
    check_macos_packaging_preserves_symlinks,
    check_no_continue_on_error,
    check_pip_audit_not_in_test_job,
    check_piped_run_steps_have_pipefail,
    check_release_files_name_every_build_artefact,
    check_release_publishes_after_checksums,
    check_required_check_identity,
    check_smoke_runs_on_the_packaged_artefact,
    check_test_floor_is_armed,
    check_upload_artifact_fails_on_empty,
    check_uv_sync_is_locked,
    check_verification_steps_run_independently,
    jobs,
    load_workflow,
    run_all_checks,
    steps,
    steps_using,
    workflow_path,
    workflow_triggers,
)

pytestmark = pytest.mark.unit

CI = "ci.yml"
RELEASE = "release.yml"
BOTH = (CI, RELEASE)


@pytest.fixture(scope="module")
def workflows() -> dict[str, Workflow]:
    """Beide Workflows einmal geladen – die Prüfungen mutieren nur Kopien."""
    return {name: load_workflow(name) for name in BOTH}


def mutated(workflows: dict[str, Workflow], name: str) -> Workflow:
    """Tiefe Kopie, damit eine Mutation die anderen Tests nicht vergiftet."""
    return copy.deepcopy(workflows[name])


def find_step(
    workflow: Workflow, job_id: str, predicate: Callable[[dict[str, Any]], bool]
) -> dict[str, Any]:
    """Erster Step des Jobs, auf den `predicate` passt – sonst harter Fehler.

    Der harte Fehler ist Absicht: findet die Mutation ihren Angriffspunkt nicht
    mehr, ist die Positiv-Kontrolle wertlos geworden und muss auffallen, statt
    still auf einer leeren Menge grün zu bleiben.
    """
    for step in steps(jobs(workflow)[job_id]):
        if predicate(step):
            return step
    raise AssertionError(f"Kein passender Step in Job '{job_id}' gefunden")


def runs(fragment: str) -> Callable[[dict[str, Any]], bool]:
    def predicate(step: dict[str, Any]) -> bool:
        body = step.get("run")
        return isinstance(body, str) and fragment in body

    return predicate


# ---------------------------------------------------------------------------
# 1. Die Zusagen gegen die echten Dateien
# ---------------------------------------------------------------------------


class TestWorkflowGuarantees:
    """Jede Zusage, die ein stiller Default aufheben kann, gegen die echte Datei."""

    def test_both_workflows_exist_and_parse(self, workflows: dict[str, Workflow]) -> None:
        for name in BOTH:
            assert workflow_path(name).exists(), name
            assert jobs(workflows[name]), f"{name} hat keine Jobs"

    def test_on_key_is_read_despite_yaml_boolean_trap(self, workflows: dict[str, Workflow]) -> None:
        """YAML 1.1 liest unquotiertes `on` als Boolean `True`, nicht als String.

        Kein Sprint-Erbe, sondern die Falle, über die diese Prüfung selbst
        stolpern würde: `workflow["on"]` wirft hier `KeyError`.
        """
        assert "on" not in workflows[CI], "Annahme überholt – safe_load liefert jetzt 'on'"
        assert workflow_triggers(workflows[CI]) is not None
        assert "pull_request" in workflow_triggers(workflows[CI])
        assert "push" in workflow_triggers(workflows[RELEASE])

    def test_all_actions_are_sha_pinned(self, workflows: dict[str, Workflow]) -> None:
        """Sprint 54 – die Zusage, die ein Dependabot-PR am ehesten berührt."""
        for name in BOTH:
            assert check_actions_are_sha_pinned(workflows[name], name=name) == []

    def test_sha_pin_check_sees_a_non_empty_population(
        self, workflows: dict[str, Workflow]
    ) -> None:
        """Anti-Vakuum: eine Prüfung über null `uses:`-Steps wäre wirkungslos grün."""
        total = sum(
            1
            for name in BOTH
            for job in jobs(workflows[name]).values()
            for step in steps(job)
            if step.get("uses")
        )
        assert total >= 15, total

    def test_upload_artifact_fails_on_empty(self, workflows: dict[str, Workflow]) -> None:
        """Sprint 75 / B.1 – ohne `if-no-files-found: error` lädt der Step 0 Dateien
        hoch und bleibt grün."""
        for name in BOTH:
            assert check_upload_artifact_fails_on_empty(workflows[name], name=name) == []
        assert len(steps_using(workflows[RELEASE], "actions/upload-artifact")) == 2

    def test_piped_run_steps_have_pipefail(self, workflows: dict[str, Workflow]) -> None:
        """Sprint 75 / B.2 – GitHubs Default-Shell ist `bash -e`, OHNE pipefail."""
        for name in BOTH:
            assert check_piped_run_steps_have_pipefail(workflows[name], name=name) == []

    def test_gh_release_fails_on_unmatched_files(self, workflows: dict[str, Workflow]) -> None:
        """Sprint 75 / B.3 – ohne den Key wird ein `files:`-Eintrag ohne Treffer
        still übersprungen und das Release entsteht trotzdem."""
        assert check_gh_release_fails_on_unmatched_files(workflows[RELEASE], name=RELEASE) == []
        assert len(steps_using(workflows[RELEASE], "softprops/action-gh-release")) == 1

    def test_macos_packaging_preserves_symlinks(self, workflows: dict[str, Workflow]) -> None:
        """Sprint 76 – ohne `-y` folgt `zip -r` den Symlinks des .app statt sie zu
        speichern (gemessen: 107 -> 0, entpackt 3,90× so groß)."""
        assert check_macos_packaging_preserves_symlinks(workflows[RELEASE], name=RELEASE) == []

    def test_smoke_runs_on_the_packaged_artefact(self, workflows: dict[str, Workflow]) -> None:
        """Sprint 76 – vorher lief der Smoke gegen `dist/`: geprüft wurde X,
        ausgeliefert wurde Y."""
        assert check_smoke_runs_on_the_packaged_artefact(workflows[RELEASE], name=RELEASE) == []

    def test_uv_sync_is_locked(self, workflows: dict[str, Workflow]) -> None:
        """Sprint 61 – `--frozen` installiert den Lock, ohne ihn gegen
        pyproject.toml zu prüfen; nur `--locked` bemerkt die Drift."""
        for name in BOTH:
            assert check_uv_sync_is_locked(workflows[name], name=name) == []

    def test_pip_audit_is_in_no_test_job(self, workflows: dict[str, Workflow]) -> None:
        """Sprint 73/74 – als Step vor pytest verschluckte er in Sprint 72 den
        kompletten Ubuntu-Testlauf."""
        for name in BOTH:
            assert check_pip_audit_not_in_test_job(workflows[name], name=name) == []
            assert "audit" in jobs(workflows[name]), f"{name}: eigener audit-Job fehlt"

    def test_verification_steps_run_independently(self, workflows: dict[str, Workflow]) -> None:
        """Sprint 73/74 – ohne `if: !cancelled()` verdeckt ein roter pytest-Lauf
        ruff und mypy vollständig."""
        for name in BOTH:
            assert check_verification_steps_run_independently(workflows[name], name=name) == []

    def test_build_does_not_need_audit(self, workflows: dict[str, Workflow]) -> None:
        """Sprint 74 – sonst wäre die Maskierung nur in den Job-Graphen verschoben."""
        for name in BOTH:
            assert check_build_does_not_need_audit(workflows[name], name=name) == []
        assert jobs(workflows[RELEASE])["build"].get("needs") == ["test"]

    def test_no_continue_on_error_anywhere(self, workflows: dict[str, Workflow]) -> None:
        """Sprint 73/74 – der direkteste Weg, einen roten Check grün zu machen,
        ohne die Ursache zu beheben."""
        for name in BOTH:
            assert check_no_continue_on_error(workflows[name], name=name) == []

    def test_release_publishes_after_checksums(self, workflows: dict[str, Workflow]) -> None:
        """Sprint 75 – die Erwartungsliste entsteht aus den heruntergeladenen
        Artefakt-Verzeichnissen; vor dem Download wäre sie leer."""
        assert check_release_publishes_after_checksums(workflows[RELEASE], name=RELEASE) == []

    def test_release_files_name_every_build_artefact(self, workflows: dict[str, Workflow]) -> None:
        """Sprint 75 / B.3 – `files:` ist die einzige NICHT-zirkuläre Erwartung
        zum Veröffentlichungszeitpunkt und darf kein Glob werden."""
        assert check_release_files_name_every_build_artefact(workflows[RELEASE], name=RELEASE) == []

    def test_required_check_identity_is_unchanged(self, workflows: dict[str, Workflow]) -> None:
        """Sprint 73 – die Required Checks heißen `test (<os>, <python-version>)`;
        Job-ID, Reihenfolge und Werte der Matrix stecken im Namen."""
        assert check_required_check_identity(workflows[CI], name=CI) == []

    def test_test_floor_is_armed_in_both_workflows(self, workflows: dict[str, Workflow]) -> None:
        """Sprint 77 – ohne die Umgebungsvariable ist der Testmengen-Wächter
        überall stumm."""
        for name in BOTH:
            assert check_test_floor_is_armed(workflows[name], name=name) == []

    def test_actionlint_job_exists_and_is_independent(self, workflows: dict[str, Workflow]) -> None:
        """Sprint 77 – eigener Job nach dem Muster von `audit` (Sprint 73), damit
        er nichts verschluckt und nichts ihn verschluckt."""
        job = jobs(workflows[CI]).get("actionlint")
        assert job is not None, "ci.yml hat keinen actionlint-Job"
        assert job.get("needs") is None
        assert job.get("continue-on-error") is not True
        assert any(
            (step.get("uses") or "").startswith("raven-actions/actionlint@") for step in steps(job)
        )

    def test_every_real_workflow_holds_every_promise(self, workflows: dict[str, Workflow]) -> None:
        """Der Sammel-Lauf: keine einzige Zusage ist verletzt."""
        for name in BOTH:
            assert run_all_checks(workflows[name], name=name) == []


# ---------------------------------------------------------------------------
# 2. Positiv-Kontrollen: jede Zusage muss ihren Bruch bemerken
# ---------------------------------------------------------------------------


class TestPolicyChecksDetectViolations:
    """Für jede Zusage eine mutierte Kopie, die einen Verstoß auslösen MUSS.

    Ohne diese Klasse ist jede grüne Prüfung oben unbewiesen (§2.4). Mutiert
    wird ausschließlich in-memory – kein Wegwerf-Branch, kein CI-Lauf.
    """

    def test_every_registered_check_has_a_positive_control(self) -> None:
        """Jede Zusage braucht hier eine Mutation – sonst ist sie unbewiesen.

        Ohne diese Prüfung könnte eine neue `check_*`-Funktion in die Registry
        wandern, auf der echten Datei grün sein und trotzdem nie belegt haben,
        dass sie überhaupt etwas bemerkt. Genau die Sorte Lücke, die dieser
        Sprint schließt – sie hier zu wiederholen wäre besonders schlecht.
        """
        registered = set(SHARED_CHECKS) | set(RELEASE_CHECKS) | set(CI_CHECKS)
        source = inspect.getsource(TestPolicyChecksDetectViolations)
        unproven = sorted(check.__name__ for check in registered if check.__name__ not in source)
        assert unproven == [], f"Zusagen ohne Positiv-Kontrolle: {unproven}"
        assert len(registered) == 15, sorted(check.__name__ for check in registered)

    def test_tag_instead_of_sha_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        broken = mutated(workflows, CI)
        steps(jobs(broken)["test"])[0]["uses"] = "actions/checkout@v4"
        violations = check_actions_are_sha_pinned(broken, name=CI)
        assert violations
        assert "40-stelliger" in violations[0]

    def test_missing_if_no_files_found_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        broken = mutated(workflows, RELEASE)
        step = find_step(broken, "build", lambda s: "upload-artifact" in (s.get("uses") or ""))
        del step["with"]["if-no-files-found"]
        assert check_upload_artifact_fails_on_empty(broken, name=RELEASE)

    def test_if_no_files_found_warn_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        broken = mutated(workflows, RELEASE)
        step = find_step(broken, "build", lambda s: "upload-artifact" in (s.get("uses") or ""))
        step["with"]["if-no-files-found"] = "warn"
        assert check_upload_artifact_fails_on_empty(broken, name=RELEASE)

    def test_pipe_without_bash_shell_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        broken = mutated(workflows, RELEASE)
        step = find_step(broken, "release", runs("SHA256SUMS"))
        del step["shell"]
        step["run"] = step["run"].replace("set -euo pipefail", "set -eu")
        violations = check_piped_run_steps_have_pipefail(broken, name=RELEASE)
        assert violations
        assert "pipefail" in violations[0]

    def test_pipe_in_powershell_without_error_preference_is_rejected(
        self, workflows: dict[str, Workflow]
    ) -> None:
        broken = mutated(workflows, RELEASE)
        step = find_step(broken, "build", lambda s: s.get("shell") == "pwsh")
        step["run"] = step["run"].replace("$ErrorActionPreference = 'Stop'", "")
        assert check_piped_run_steps_have_pipefail(broken, name=RELEASE)

    def test_gh_release_without_fail_on_unmatched_is_rejected(
        self, workflows: dict[str, Workflow]
    ) -> None:
        broken = mutated(workflows, RELEASE)
        step = find_step(broken, "release", lambda s: "action-gh-release" in (s.get("uses") or ""))
        del step["with"]["fail_on_unmatched_files"]
        assert check_gh_release_fails_on_unmatched_files(broken, name=RELEASE)

    def test_zip_without_symlink_flag_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        broken = mutated(workflows, RELEASE)
        step = find_step(broken, "build", runs("zip -q -r -y"))
        step["run"] = step["run"].replace("zip -q -r -y", "zip -q -r")
        violations = check_macos_packaging_preserves_symlinks(broken, name=RELEASE)
        assert violations
        assert "-y" in violations[0]

    def test_smoke_before_packaging_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        broken = mutated(workflows, RELEASE)
        job = jobs(broken)["build"]
        build_steps = steps(job)
        package = next(
            i for i, s in enumerate(build_steps) if "zip -q -r -y" in (s.get("run") or "")
        )
        build_steps[package], build_steps[package + 1] = (
            build_steps[package + 1],
            build_steps[package],
        )
        job["steps"] = build_steps
        assert check_smoke_runs_on_the_packaged_artefact(broken, name=RELEASE)

    def test_deleted_smoke_steps_are_rejected(self, workflows: dict[str, Workflow]) -> None:
        """Anti-Vakuum: null Smoke-Steps verletzen keine Reihenfolge – und wären
        ohne diese Zählung die eleganteste Art, die Prüfung stillzulegen."""
        broken = mutated(workflows, RELEASE)
        job = jobs(broken)["build"]
        job["steps"] = [s for s in steps(job) if "Round-Trip" not in (s.get("name") or "")]
        violations = check_smoke_runs_on_the_packaged_artefact(broken, name=RELEASE)
        assert violations
        assert "Smoke-Step" in violations[0]

    def test_upload_before_smoke_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        broken = mutated(workflows, RELEASE)
        job = jobs(broken)["build"]
        build_steps = steps(job)
        upload = build_steps.pop()
        assert "upload-artifact" in (upload.get("uses") or "")
        build_steps.insert(5, upload)
        job["steps"] = build_steps
        assert check_smoke_runs_on_the_packaged_artefact(broken, name=RELEASE)

    def test_uv_sync_frozen_instead_of_locked_is_rejected(
        self, workflows: dict[str, Workflow]
    ) -> None:
        broken = mutated(workflows, CI)
        step = find_step(broken, "test", runs("uv sync"))
        step["run"] = step["run"].replace("--locked", "--frozen")
        violations = check_uv_sync_is_locked(broken, name=CI)
        assert violations
        assert "--locked" in violations[0]

    def test_pip_audit_inside_test_job_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        broken = mutated(workflows, CI)
        job = jobs(broken)["test"]
        job_steps = steps(job)
        job_steps.insert(3, {"name": "audit", "run": "uv run pip-audit"})
        job["steps"] = job_steps
        violations = check_pip_audit_not_in_test_job(broken, name=CI)
        assert violations
        assert "verschluckt" in violations[0]

    def test_verification_step_without_cancelled_guard_is_rejected(
        self, workflows: dict[str, Workflow]
    ) -> None:
        broken = mutated(workflows, CI)
        step = find_step(broken, "test", runs("mypy"))
        del step["if"]
        violations = check_verification_steps_run_independently(broken, name=CI)
        assert violations
        assert "!cancelled()" in violations[0]

    def test_deleted_verification_steps_are_rejected(self, workflows: dict[str, Workflow]) -> None:
        """Anti-Vakuum: ein Testlauf, den es nicht mehr gibt, kann nicht rot werden."""
        broken = mutated(workflows, CI)
        job = jobs(broken)["test"]
        job["steps"] = [s for s in steps(job) if not str(s.get("name", "")).startswith("Run ")]
        assert check_verification_steps_run_independently(broken, name=CI)

    def test_build_needing_audit_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        broken = mutated(workflows, RELEASE)
        jobs(broken)["build"]["needs"] = ["test", "audit"]
        violations = check_build_does_not_need_audit(broken, name=RELEASE)
        assert violations
        assert "audit" in violations[0]

    def test_build_needing_audit_as_bare_string_is_rejected(
        self, workflows: dict[str, Workflow]
    ) -> None:
        """`needs: audit` (String) muss genauso auffallen wie `needs: [audit]`."""
        broken = mutated(workflows, RELEASE)
        jobs(broken)["build"]["needs"] = "audit"
        assert check_build_does_not_need_audit(broken, name=RELEASE)

    def test_continue_on_error_on_step_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        broken = mutated(workflows, CI)
        find_step(broken, "test", runs("pytest"))["continue-on-error"] = True
        assert check_no_continue_on_error(broken, name=CI)

    def test_continue_on_error_on_job_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        broken = mutated(workflows, CI)
        jobs(broken)["audit"]["continue-on-error"] = True
        assert check_no_continue_on_error(broken, name=CI)

    def test_checksums_before_download_are_rejected(self, workflows: dict[str, Workflow]) -> None:
        broken = mutated(workflows, RELEASE)
        job = jobs(broken)["release"]
        release_steps = steps(job)
        checksums = next(
            i for i, s in enumerate(release_steps) if "SHA256SUMS" in (s.get("run") or "")
        )
        job["steps"] = [release_steps.pop(checksums), *release_steps]
        assert check_release_publishes_after_checksums(broken, name=RELEASE)

    def test_deleted_checksum_step_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        broken = mutated(workflows, RELEASE)
        job = jobs(broken)["release"]
        job["steps"] = [s for s in steps(job) if "SHA256SUMS" not in (s.get("run") or "")]
        violations = check_release_publishes_after_checksums(broken, name=RELEASE)
        assert violations
        assert "Prüfsummen" in violations[0]

    def test_glob_instead_of_named_files_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        """Die `files:`-Literale sind lasttragend – ein Glob nimmt ihnen genau
        die nicht-zirkuläre Eigenschaft."""
        broken = mutated(workflows, RELEASE)
        step = find_step(broken, "release", lambda s: "action-gh-release" in (s.get("uses") or ""))
        step["with"]["files"] = "artifacts/*\nsbom.cdx.json\n"
        violations = check_release_files_name_every_build_artefact(broken, name=RELEASE)
        assert len(violations) == 2, violations

    def test_renamed_test_job_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        broken = mutated(workflows, CI)
        broken["jobs"]["tests"] = broken["jobs"].pop("test")
        violations = check_required_check_identity(broken, name=CI)
        assert violations
        assert "Required Checks" in violations[0]

    def test_job_name_override_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        """Ein `name:` am Job ersetzt die Job-ID im Check-Namen – die Required
        Checks zeigten danach ins Leere."""
        broken = mutated(workflows, CI)
        jobs(broken)["test"]["name"] = "Test gate"
        assert check_required_check_identity(broken, name=CI)

    def test_swapped_matrix_dimension_order_is_rejected(
        self, workflows: dict[str, Workflow]
    ) -> None:
        """Die Reihenfolge steckt im Check-Namen `test (<os>, <python-version>)`."""
        broken = mutated(workflows, CI)
        matrix = jobs(broken)["test"]["strategy"]["matrix"]
        jobs(broken)["test"]["strategy"]["matrix"] = {
            "python-version": matrix["python-version"],
            "os": matrix["os"],
        }
        violations = check_required_check_identity(broken, name=CI)
        assert violations
        assert "Reihenfolge" in violations[0]

    def test_changed_python_version_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        broken = mutated(workflows, CI)
        jobs(broken)["test"]["strategy"]["matrix"]["python-version"] = ["3.14"]
        assert check_required_check_identity(broken, name=CI)

    def test_dropped_os_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        broken = mutated(workflows, CI)
        jobs(broken)["test"]["strategy"]["matrix"]["os"] = ["ubuntu-latest"]
        assert check_required_check_identity(broken, name=CI)

    def test_missing_test_floor_env_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        for name in BOTH:
            broken = mutated(workflows, name)
            step = find_step(broken, "test", runs("pytest"))
            del step["env"][ENFORCE_TEST_FLOOR_ENV]
            violations = check_test_floor_is_armed(broken, name=name)
            assert violations
            assert "stumm" in violations[0]

    def test_deleted_pytest_step_is_rejected(self, workflows: dict[str, Workflow]) -> None:
        """Anti-Vakuum: ohne pytest-Step hat der Wächter keinen Ort zu greifen."""
        broken = mutated(workflows, CI)
        job = jobs(broken)["test"]
        job["steps"] = [s for s in steps(job) if "pytest" not in (s.get("run") or "")]
        assert check_test_floor_is_armed(broken, name=CI)

    @pytest.mark.parametrize("name", BOTH)
    def test_run_all_checks_reports_a_broken_workflow(
        self, workflows: dict[str, Workflow], name: str
    ) -> None:
        """Der Sammel-Lauf meldet, was eine Einzelprüfung meldet."""
        broken = mutated(workflows, name)
        steps(jobs(broken)["test"])[0]["uses"] = "actions/checkout@v4"
        assert run_all_checks(broken, name=name)


# ---------------------------------------------------------------------------
# 3. Struktur statt Text
# ---------------------------------------------------------------------------


class TestPolicyIsRobustToFormatting:
    """Umformatierung darf kein Ergebnis ändern (§2.2).

    Ein `grep`-Gate auf dem Rohtext bräche bei jeder Umformatierung aus dem
    falschen Grund – und wäre damit über kurz oder lang das erste, was jemand
    entschärft. Diese Klasse belegt, dass hier die geladene Struktur zählt.
    """

    @pytest.mark.parametrize("name", BOTH)
    def test_sorted_keys_change_nothing(self, workflows: dict[str, Workflow], name: str) -> None:
        reordered = yaml.safe_load(yaml.safe_dump(workflows[name], sort_keys=True))
        assert run_all_checks(reordered, name=name) == run_all_checks(workflows[name], name=name)

    @pytest.mark.parametrize("name", BOTH)
    def test_flow_style_changes_nothing(self, workflows: dict[str, Workflow], name: str) -> None:
        flow = yaml.safe_load(yaml.safe_dump(workflows[name], default_flow_style=True))
        assert run_all_checks(flow, name=name) == []

    #: Je Datei ein YAML-Kommentar, der NICHT in einem `run`-Körper steht –
    #: `safe_dump` verliert ihn zwangsläufig, ein Text-Gate hinge daran.
    YAML_LEVEL_COMMENT: ClassVar[dict[str, str]] = {
        CI: "Required Checks heißen",
        RELEASE: "Der Job-Name `test` bleibt exakt",
    }

    @pytest.mark.parametrize("name", BOTH)
    def test_comments_are_irrelevant(self, workflows: dict[str, Workflow], name: str) -> None:
        """`safe_dump` schreibt keine YAML-Kommentare – das Ergebnis bleibt gleich.

        Belegt, dass die Prüfungen nicht an der (dichten) Kommentierung beider
        Dateien hängen, sondern an dem, was die Datei tut.
        """
        marker = self.YAML_LEVEL_COMMENT[name]
        assert marker in workflow_path(name).read_text(encoding="utf-8")
        dumped = yaml.safe_dump(workflows[name], sort_keys=False)
        assert marker not in dumped
        assert run_all_checks(yaml.safe_load(dumped), name=name) == []

    def test_shell_body_checks_survive_reindentation(self, workflows: dict[str, Workflow]) -> None:
        """Auch die Text-nächsten Prüfungen hängen nicht an der Einrückung.

        `zip -y` und `uv sync --locked` lassen sich nur im `run`-Körper prüfen.
        Getestet wird deshalb, dass zusätzliche Einrückung und Leerzeilen im
        Körper nichts ändern – nur eine echte Änderung des Kommandos tut das.
        """
        indented = mutated(workflows, RELEASE)
        for job in jobs(indented).values():
            for step in steps(job):
                if isinstance(step.get("run"), str):
                    step["run"] = "\n".join(f"  {line}" for line in step["run"].splitlines())
        assert check_macos_packaging_preserves_symlinks(indented, name=RELEASE) == []
        assert check_uv_sync_is_locked(indented, name=RELEASE) == []

    def test_comment_mentioning_a_command_is_not_mistaken_for_the_command(
        self, workflows: dict[str, Workflow]
    ) -> None:
        """Beide Dateien nennen `pip-audit` und `zip -r` in Kommentaren.

        Ohne das Entfernen der Kommentarzeilen prüfte die Funktion die
        Begründung statt der Zeile – ein Kommentar würde einen Verstoß erfinden.
        """
        commented = mutated(workflows, CI)
        step = find_step(commented, "test", runs("pytest"))
        step["run"] = "# pip-audit lief hier früher, siehe Sprint 73\n" + step["run"]
        assert check_pip_audit_not_in_test_job(commented, name=CI) == []
