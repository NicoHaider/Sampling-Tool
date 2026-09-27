"""`scripts/check_export_integrity.py` (Sprint 86 / D): findet Sample-Exporte,
deren Datei die Zeilen eines anderen Datensatzes enthält – rein lesend."""

from __future__ import annotations

import errno
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from sampling_tool.audit.logger import AuditLogger
from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    Engagement,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.io.exporter import ExcelExporter
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import (
    AuditRepo,
    DatasetRepo,
    EngagementRepo,
    SampleRepo,
)

_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from check_export_integrity import (  # type: ignore[import-not-found]  # noqa: E402
    ExportStatus,
    check_exports,
    main,
)


class _Project:
    """Projekt mit zwei Datensätzen (gleiche Zeilen-IDs, andere Werte) und
    einer Stichprobe (Zeilen 2, 4) auf dem ersten."""

    def __init__(self, directory: Path) -> None:
        self.db_path = directory / "smoke.db"
        self.out_dir = directory / "exports"
        self.out_dir.mkdir()
        self.db = Database(self.db_path)
        self.db.migrate()
        engagement = EngagementRepo(self.db.connect()).get_or_create(
            Engagement(auditor_name="Anna", client_name="SMOKE", audit_type="ISAE 3402")
        )
        assert engagement.id is not None
        self.engagement = engagement
        ds_repo = DatasetRepo(self.db.connect())
        self.own = self._dataset(ds_repo, "Buchungen", "A")
        self.other = self._dataset(ds_repo, "08_gross", "B")
        assert self.own.id is not None
        sample = SampleResult(
            config=SampleConfig(method=SamplingMethod.SIMPLE, size=2, seed=1133314472),
            selected_row_ids=(2, 4),
            population_size=6,
            created_by="tester",
        )
        sample_id = SampleRepo(self.db.connect()).create_from_result(sample, self.own.id)
        loaded = SampleRepo(self.db.connect()).get_by_id(sample_id)
        assert loaded is not None
        self.sample = loaded

    def _dataset(self, repo: DatasetRepo, name: str, prefix: str) -> Dataset:
        assert self.engagement.id is not None
        return repo.create(
            Dataset(name=name, columns=("Beleg",), engagement_id=self.engagement.id),
            tuple(DatasetRow(row_id=i, values={"Beleg": f"{prefix}-{i}"}) for i in range(1, 7)),
        )

    def export(self, dataset: Dataset, name: str) -> Path:
        """Schreibt den Export so, wie der Controller es tat – `dataset` ist der
        Datensatz, aus dem gelesen wurde (vor Sprint 86 ggf. der falsche)."""
        return ExcelExporter().export_sample(
            self.sample,
            dataset,
            DatasetRepo(self.db.connect()),
            columns=["Beleg"],
            output_dir=self.out_dir,
            custom_name=name,
            custom_id=str(self.sample.id),
            engagement=self.engagement,
        )

    def log_export(self, path: Path, archived_previous: Path | None = None) -> None:
        assert self.engagement.id is not None
        assert self.sample.id is not None
        AuditLogger(AuditRepo(self.db.connect()), "tester", self.engagement.id).log_export(
            self.sample.id, path, 2, archived_previous
        )

    def close(self) -> None:
        self.db.close()


@pytest.fixture
def project(tmp_path: Path) -> _Project:
    return _Project(tmp_path)


def _statuses(db_path: Path) -> list[tuple[str, str]]:
    return [(check.file.name, check.status.value) for check in check_exports(db_path)]


class TestCheckExports:
    def test_export_from_own_dataset_is_ok(self, project: _Project) -> None:
        path = project.export(project.own, "Buchungen")
        project.log_export(path)
        project.close()

        [check] = check_exports(project.db_path)
        assert check.status is ExportStatus.OK
        assert check.sample_id == project.sample.id
        assert check.sample_dataset_id == project.own.id
        assert check.file_dataset_id == project.own.id

    def test_export_read_from_other_dataset_is_a_mismatch(self, project: _Project) -> None:
        """Genau der Befund: Stichprobe des einen Datensatzes, Zeilen des anderen."""
        path = project.export(project.other, "08_gross")
        project.log_export(path)
        project.close()

        [check] = check_exports(project.db_path)
        assert check.status is ExportStatus.MISMATCH
        assert check.sample_dataset_id == project.own.id
        assert check.file_dataset_id == project.other.id

    def test_missing_file_is_reported(self, project: _Project) -> None:
        path = project.export(project.own, "Buchungen")
        project.log_export(path)
        project.close()
        path.unlink()

        [check] = check_exports(project.db_path)
        assert check.status is ExportStatus.FILE_MISSING
        assert check.file == path

    def test_overwritten_export_is_checked_in_its_archive_location(self, project: _Project) -> None:
        """Sprint 84 / C: wer eine Exportdatei überschreibt, verschiebt die alte
        Fassung ins Archiv. Das alte Event muss dort nachsehen, nicht in der
        neuen Datei am selben Pfad."""
        path = project.export(project.other, "same")
        project.log_export(path)
        archived = project.out_dir / "archiv" / path.name
        archived.parent.mkdir()
        shutil.move(path, archived)
        rewritten = project.export(project.own, "same")
        assert rewritten == path
        project.log_export(path, archived_previous=archived)
        project.close()

        checks = check_exports(project.db_path)
        assert [(c.file, c.status) for c in checks] == [
            (archived, ExportStatus.MISMATCH),
            (path, ExportStatus.OK),
        ]

    def test_report_exports_are_not_sample_exports(self, project: _Project) -> None:
        assert project.engagement.id is not None
        AuditLogger(
            AuditRepo(project.db.connect()), "tester", project.engagement.id
        ).log_report_export(project.out_dir / "bericht.pdf", "AuditTrail-PDF")
        project.close()
        assert check_exports(project.db_path) == []

    def test_mixed_project(self, project: _Project) -> None:
        ok = project.export(project.own, "Buchungen")
        project.log_export(ok)
        bad = project.export(project.other, "08_gross")
        project.log_export(bad)
        gone = project.export(project.own, "weg")
        project.log_export(gone)
        project.close()
        gone.unlink()

        assert _statuses(project.db_path) == [
            (ok.name, "OK"),
            (bad.name, "ABWEICHUNG"),
            (gone.name, "DATEI FEHLT"),
        ]


class TestReadOnly:
    def test_neither_database_nor_export_files_are_touched(self, project: _Project) -> None:
        path = project.export(project.other, "08_gross")
        project.log_export(path)
        project.close()
        before = {p: p.read_bytes() for p in project.db_path.parent.rglob("*") if p.is_file()}

        check_exports(project.db_path)

        after = {p: p.read_bytes() for p in project.db_path.parent.rglob("*") if p.is_file()}
        assert after == before


class TestCommandLine:
    def test_main_prints_one_line_per_event_and_fails_on_mismatch(
        self, project: _Project, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ok = project.export(project.own, "Buchungen")
        project.log_export(ok)
        bad = project.export(project.other, "08_gross")
        project.log_export(bad)
        project.close()

        assert main([str(project.db_path)]) == 1
        out = capsys.readouterr().out
        ok_line = next(line for line in out.splitlines() if ok.name in line)
        bad_line = next(line for line in out.splitlines() if bad.name in line)
        assert ok_line.startswith("OK")
        assert bad_line.startswith("ABWEICHUNG")

    def test_main_succeeds_without_mismatch(
        self, project: _Project, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project.log_export(project.export(project.own, "Buchungen"))
        project.close()
        assert main([str(project.db_path)]) == 0

    def test_script_runs_as_subprocess(self, project: _Project) -> None:
        bad = project.export(project.other, "08_gross")
        project.log_export(bad)
        project.close()

        result = subprocess.run(
            [sys.executable, str(_SCRIPTS / "check_export_integrity.py"), str(project.db_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            env=dict(os.environ),
        )
        assert result.returncode == 1, result.stderr
        assert "ABWEICHUNG" in result.stdout
        assert bad.name in result.stdout

    def test_missing_database_is_a_usage_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main([str(tmp_path / "gibt-es-nicht.db")]) == 2
        assert "nicht gefunden" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Sprint 87 / D: kein falsches Grün (WAL, unlesbare Datei, alte Projekte)
# ---------------------------------------------------------------------------


def _sidecar(db_path: Path, suffix: str) -> Path:
    return db_path.with_name(db_path.name + suffix)


def _copy_with_pending_wal(project: _Project, target_dir: Path) -> Path:
    """Kopie der Projektdatei samt `-wal`, solange die App (hier: `project.db`)
    noch offen ist – der Export-Event steht nur im WAL. Kein `-shm` daneben."""
    target_dir.mkdir()
    copy = target_dir / project.db_path.name
    shutil.copy2(project.db_path, copy)
    shutil.copy2(_sidecar(project.db_path, "-wal"), _sidecar(copy, "-wal"))
    return copy


class TestPendingWal:
    def test_export_only_in_wal_is_found(self, project: _Project, tmp_path: Path) -> None:
        path = project.export(project.other, "08_gross")
        project.log_export(path)
        copy = _copy_with_pending_wal(project, tmp_path / "kopie")
        project.close()

        assert _statuses(copy) == [(path.name, "ABWEICHUNG")]

    def test_original_files_stay_byte_identical_and_no_shm_appears(
        self, project: _Project, tmp_path: Path
    ) -> None:
        project.log_export(project.export(project.own, "Buchungen"))
        copy = _copy_with_pending_wal(project, tmp_path / "kopie")
        project.close()
        before = {p: p.read_bytes() for p in copy.parent.iterdir()}

        check_exports(copy)

        after = {p: p.read_bytes() for p in copy.parent.iterdir()}
        assert after == before
        assert not _sidecar(copy, "-shm").exists()

    def test_open_app_is_left_untouched(self, project: _Project) -> None:
        """Die App hält die Projektdatei offen: Skript liest den WAL mit, ändert nichts."""
        path = project.export(project.own, "Buchungen")
        project.log_export(path)
        watched = (project.db_path, _sidecar(project.db_path, "-wal"))
        before = {p: p.read_bytes() for p in watched}

        statuses = _statuses(project.db_path)

        assert {p: p.read_bytes() for p in watched} == before
        project.close()
        assert statuses == [(path.name, "OK")]

    def test_main_mentions_the_wal(
        self, project: _Project, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project.log_export(project.export(project.own, "Buchungen"))
        copy = _copy_with_pending_wal(project, tmp_path / "kopie")
        project.close()

        assert main([str(copy)]) == 0
        out = capsys.readouterr().out
        assert "WAL" in out
        assert "1 Sample-Exporte geprüft" in out


class TestUnreadableProject:
    @pytest.mark.parametrize(
        ("target", "error"),
        [
            ("sqlite3.connect", sqlite3.OperationalError("disk I/O error")),
            ("shutil.copy2", OSError(errno.EDEADLK, "Resource deadlock avoided")),
        ],
    )
    def test_unreadable_project_exits_2_with_cloud_hint(
        self,
        project: _Project,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        target: str,
        error: Exception,
    ) -> None:
        project.log_export(project.export(project.own, "Buchungen"))
        copy = _copy_with_pending_wal(project, tmp_path / "kopie")
        project.close()

        def fail(*_args: object, **_kwargs: object) -> None:
            raise error

        module, attribute = target.split(".")
        monkeypatch.setattr(f"check_export_integrity.{module}.{attribute}", fail)

        assert main([str(copy)]) == 2
        err = capsys.readouterr().err
        assert "Projektdatei nicht lesbar" in err
        assert "Cloud" in err
        assert str(copy) in err
        assert "Traceback" not in err

    def test_not_a_database_exits_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bogus = tmp_path / "kein.db"
        bogus.write_bytes(b"das ist keine SQLite-Datei" * 10)
        assert main([str(bogus)]) == 2
        assert "Traceback" not in capsys.readouterr().err


class TestProjectWithoutAuditTrail:
    @pytest.mark.parametrize("content", ["empty", "other_table"])
    def test_no_audit_events_table_is_ok_with_hint(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str
    ) -> None:
        db_path = tmp_path / "alt.db"
        if content == "empty":
            db_path.write_bytes(b"")
        else:
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE engagements (id INTEGER PRIMARY KEY)")
            conn.commit()
            conn.close()

        assert check_exports(db_path) == []
        assert main([str(db_path)]) == 0
        assert "keine Audit-Events in dieser Projektdatei" in capsys.readouterr().out


class TestOldPython:
    def test_too_old_python_exits_2_not_1(self, tmp_path: Path) -> None:
        """Sprint 88 / B4: Exit 1 heißt ABWEICHUNG – ein Abbruch wegen zu altem
        Python darf nicht so aussehen. Simuliert: `enum.StrEnum` fehlt (< 3.11)."""
        code = (
            "import enum, runpy, sys\n"
            "db, script = sys.argv[1], sys.argv[2]\n"
            "del enum.StrEnum\n"
            "sys.argv = [script, db]\n"
            "runpy.run_path(script, run_name='__main__')\n"
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                code,
                str(tmp_path / "egal.db"),
                str(_SCRIPTS / "check_export_integrity.py"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            env={**os.environ, "PYTHONPATH": str(_SCRIPTS)},
        )
        assert result.returncode == 2, result.stderr
        assert "3.11" in result.stderr
