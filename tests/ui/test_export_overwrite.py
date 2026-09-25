"""Kein Export überschreibt still (Sprint 84 / C).

Existiert die Zieldatei schon, fragt der Controller VOR dem Worker nach:
neuer Name (`_2`, `_3`, …; Default), überschreiben mit Sicherung der alten
Fassung nach `archiv/`, oder abbrechen. Das `export`-Audit-Event nennt die
tatsächlich geschriebene Datei und beim Überschreiben den Archivpfad.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from sampling_tool.config import ARCHIVE_DIR_NAME
from sampling_tool.core.models import (
    AuditEvent,
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
from sampling_tool.ui.controllers.export_controller import next_free_path
from sampling_tool.ui.controllers.main_controller import MainController
from sampling_tool.ui.dialogs.existing_export_dialog import (
    ExistingExportChoice,
    ExistingExportDialog,
)
from sampling_tool.ui.dialogs.export_audit_pdf_dialog import ExportAuditPdfDialogResult
from sampling_tool.ui.dialogs.export_excel_report_dialog import ExportExcelReportDialogResult
from sampling_tool.ui.dialogs.export_html_report_dialog import ExportHtmlReportDialogResult
from sampling_tool.ui.dialogs.export_sample_dialog import ExportSampleDialogResult
from sampling_tool.ui.main_window import MainWindow
from sampling_tool.ui.recent import RecentEngagementsStore

FIXED_NOW = datetime(2026, 9, 25, 14, 3, 7)
#: Ersetzt nach dem ersten Export dessen Inhalt: zwei Läufe in derselben
#: Sekunde erzeugen sonst byte-gleiche Dateien, und „nicht überschrieben"
#: ließe sich nicht von „identisch neu geschrieben" unterscheiden.
FIRST_VERSION = b"erste, bereits abgegebene Fassung"


# ---------------------------------------------------------------------------
# Stubs + Fixtures
# ---------------------------------------------------------------------------


class _StubResultDialog:
    DialogCode = QDialog.DialogCode

    def __init__(self, result: object) -> None:
        self._result = result

    def exec(self) -> int:
        return int(QDialog.DialogCode.Accepted)

    def get_result(self) -> object:
        return self._result


class _StubExistingExportDialog:
    """Liefert eine feste Wahl und merkt sich, womit er gefragt wurde."""

    DialogCode = QDialog.DialogCode

    def __init__(self, choice: ExistingExportChoice, calls: list[tuple[Path, Path]]) -> None:
        self._choice = choice
        self._calls = calls

    def bind(self, existing: Path, new_name: Path) -> _StubExistingExportDialog:
        self._calls.append((existing, new_name))
        return self

    def exec(self) -> int:
        accepted = self._choice != ExistingExportChoice.CANCEL
        return int(QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected)

    def choice(self) -> ExistingExportChoice:
        return self._choice


@dataclass(frozen=True)
class _ExportKind:
    """Ein Export-Pfad: welcher Handler, welche Dialog-Factory, welches Ziel."""

    name: str
    factory_kwarg: str
    handler: str
    build: Callable[[Path], tuple[object, Path]]


def _sample_result(out_dir: Path) -> tuple[object, Path]:
    result = ExportSampleDialogResult(
        columns=["Konto", "Betrag"],
        custom_name="stichprobe",
        custom_id="1",
        output_dir=out_dir,
        now=FIXED_NOW,
    )
    return result, out_dir / ExcelExporter.build_filename("stichprobe", "1", FIXED_NOW)


def _audit_pdf_result(out_dir: Path) -> tuple[object, Path]:
    target = out_dir / "trail.pdf"
    result = ExportAuditPdfDialogResult(
        output_path=target,
        date_from=None,
        date_to=None,
        event_types=set(),
        use_briefpapier=False,
        include_statistics=False,
    )
    return result, target


def _excel_report_result(out_dir: Path) -> tuple[object, Path]:
    target = out_dir / "bericht.xlsx"
    return ExportExcelReportDialogResult(output_path=target, sheets={"Übersicht"}), target


def _html_report_result(out_dir: Path) -> tuple[object, Path]:
    target = out_dir / "bericht.html"
    result = ExportHtmlReportDialogResult(
        output_path=target,
        include_charts=False,
        include_audit_trail=True,
        include_samples_table=True,
    )
    return result, target


EXPORT_KINDS = (
    _ExportKind("sample", "export_dialog_factory", "handle_export_sample", _sample_result),
    _ExportKind(
        "audit_pdf", "audit_pdf_dialog_factory", "handle_export_audit_pdf", _audit_pdf_result
    ),
    _ExportKind(
        "excel_report",
        "excel_report_dialog_factory",
        "handle_export_excel_report",
        _excel_report_result,
    ),
    _ExportKind(
        "html_report",
        "html_report_dialog_factory",
        "handle_export_html_report",
        _html_report_result,
    ),
)
AUDIT_PDF = EXPORT_KINDS[1]


@pytest.fixture
def project_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "projekt" / "engagement.db"
    db_path.parent.mkdir()
    db = Database(db_path)
    db.migrate()
    eng = EngagementRepo(db.connect()).get_or_create(
        Engagement(auditor_name="Anna", client_name="ACME", audit_type="ISAE 3402")
    )
    assert eng.id is not None
    dataset = DatasetRepo(db.connect()).create(
        Dataset(name="Buchungen", columns=("Konto", "Betrag"), engagement_id=eng.id),
        tuple(DatasetRow(row_id=i, values={"Konto": f"K{i}", "Betrag": i}) for i in range(1, 6)),
    )
    assert dataset.id is not None
    SampleRepo(db.connect()).create_from_result(
        SampleResult(
            config=SampleConfig(method=SamplingMethod.SIMPLE, size=2, seed=42),
            selected_row_ids=(2, 4),
            population_size=5,
            created_by="tester",
        ),
        dataset.id,
    )
    db.close()
    return db_path


class _Harness:
    """Controller mit gestubbten Dialogen; exportiert nach `out_dir`."""

    def __init__(
        self,
        qtbot: QtBot,
        tmp_path: Path,
        project_db: Path,
        kind: _ExportKind,
        conflict_choice: ExistingExportChoice,
    ) -> None:
        self.out_dir = tmp_path / "exports"
        self.out_dir.mkdir()
        self.kind = kind
        self.conflict_calls: list[tuple[Path, Path]] = []
        result, self.planned = kind.build(self.out_dir)
        stub = _StubExistingExportDialog(conflict_choice, self.conflict_calls)

        def ask(
            _parent: MainWindow, existing: Path, new_name: Path, _scale: float
        ) -> ExistingExportDialog:
            return cast("ExistingExportDialog", stub.bind(existing, new_name))

        self.window = MainWindow()
        qtbot.addWidget(self.window)
        dialog_factory: dict[str, Any] = {
            kind.factory_kwarg: lambda *_a, **_k: _StubResultDialog(result)
        }
        self.controller = MainController(
            self.window,
            recent_store=RecentEngagementsStore(path=tmp_path / "recent.json"),
            existing_export_dialog_factory=ask,
            **dialog_factory,
        )
        self.controller.engagement.handle_open_engagement(project_db)
        self.controller.session._now_provider = lambda: FIXED_NOW
        samples = self.window.sidebar().samples_widget()
        datasets = self.window.sidebar().datasets_widget()
        first_dataset = datasets.item(0)
        assert first_dataset is not None
        self.controller.selection.handle_dataset_selected(
            first_dataset.data(int(Qt.ItemDataRole.UserRole))
        )
        first_sample = samples.item(0)
        assert first_sample is not None
        self.controller.selection.handle_sample_selected(
            first_sample.data(int(Qt.ItemDataRole.UserRole))
        )

    def export_first(self) -> None:
        """Erster Export ohne Konflikt; danach trägt die Datei `FIRST_VERSION`."""
        self.export()
        assert self.conflict_calls == []
        self.planned.write_bytes(FIRST_VERSION)

    def export(self) -> None:
        with patch("sampling_tool.ui.controllers.export_controller.QMessageBox.information"):
            getattr(self.controller.export, self.kind.handler)()

    def export_events(self) -> list[AuditEvent]:
        s = self.controller.session
        assert s.db is not None
        assert s.engagement is not None
        assert s.engagement.id is not None
        events = AuditRepo(s.db.connect()).list_for_engagement(s.engagement.id)
        # `list_for_engagement` liefert neueste zuerst – hier chronologisch.
        return sorted((e for e in events if e.event_type == "export"), key=lambda e: e.id or 0)

    def close(self) -> None:
        self.controller.engagement.handle_close_engagement()


@pytest.fixture
def harness(
    qtbot: QtBot, tmp_path: Path, project_db: Path
) -> Iterator[Callable[[_ExportKind, ExistingExportChoice], _Harness]]:
    built: list[_Harness] = []

    def make(kind: _ExportKind, choice: ExistingExportChoice) -> _Harness:
        h = _Harness(qtbot, tmp_path, project_db, kind, choice)
        built.append(h)
        return h

    yield make
    for h in built:
        h.close()


def _suffixed(path: Path, n: int) -> Path:
    return path.with_name(f"{path.stem}_{n}{path.suffix}")


# ---------------------------------------------------------------------------
# Namens-Helfer
# ---------------------------------------------------------------------------


class TestNextFreePath:
    def test_first_free_number_before_suffix(self, tmp_path: Path) -> None:
        target = tmp_path / "trail.pdf"
        target.write_bytes(b"1")
        assert next_free_path(target) == tmp_path / "trail_2.pdf"

    def test_skips_taken_numbers(self, tmp_path: Path) -> None:
        target = tmp_path / "trail.pdf"
        for path in (target, _suffixed(target, 2), _suffixed(target, 3)):
            path.write_bytes(b"x")
        assert next_free_path(target) == tmp_path / "trail_4.pdf"


# ---------------------------------------------------------------------------
# Rückfrage-Dialog
# ---------------------------------------------------------------------------


class TestExistingExportDialog:
    def test_new_name_is_default_and_previewed(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExistingExportDialog(tmp_path / "trail.pdf", tmp_path / "trail_2.pdf")
        qtbot.addWidget(dialog)
        assert dialog._new_name_btn.isDefault()
        assert "trail_2.pdf" in dialog._message.text()
        assert dialog.choice() == ExistingExportChoice.CANCEL

    @pytest.mark.parametrize(
        ("button", "expected"),
        [
            ("_new_name_btn", ExistingExportChoice.NEW_NAME),
            ("_overwrite_btn", ExistingExportChoice.OVERWRITE),
            ("_cancel_btn", ExistingExportChoice.CANCEL),
        ],
    )
    def test_buttons_set_choice(
        self, qtbot: QtBot, tmp_path: Path, button: str, expected: ExistingExportChoice
    ) -> None:
        dialog = ExistingExportDialog(tmp_path / "a.pdf", tmp_path / "a_2.pdf")
        qtbot.addWidget(dialog)
        getattr(dialog, button).click()
        assert dialog.choice() == expected


# ---------------------------------------------------------------------------
# Controller-Pfade
# ---------------------------------------------------------------------------


class TestExportNewNameDefault:
    def test_second_export_writes_suffix_and_keeps_first(
        self, harness: Callable[[_ExportKind, ExistingExportChoice], _Harness]
    ) -> None:
        h = harness(AUDIT_PDF, ExistingExportChoice.NEW_NAME)
        h.export_first()

        h.export()

        second = h.out_dir / "trail_2.pdf"
        assert h.conflict_calls == [(h.planned, second)]
        assert second.is_file()
        assert h.planned.read_bytes() == FIRST_VERSION
        assert [Path(e.export_file or "") for e in h.export_events()][-1] == second


class TestExportOverwriteArchivesOld:
    def test_old_version_moves_to_archive_and_audit_names_it(
        self, harness: Callable[[_ExportKind, ExistingExportChoice], _Harness]
    ) -> None:
        h = harness(AUDIT_PDF, ExistingExportChoice.OVERWRITE)
        h.export_first()

        h.export()

        archived = h.out_dir / ARCHIVE_DIR_NAME / "trail_2026-09-25_14-03-07.pdf"
        assert archived.read_bytes() == FIRST_VERSION
        assert h.planned.is_file()
        assert list((h.out_dir / ARCHIVE_DIR_NAME).iterdir()) == [archived]
        last = h.export_events()[-1]
        assert Path(last.export_file or "") == h.planned
        assert Path(last.details["archived_previous"]) == archived

    def test_same_second_twice_does_not_clobber_archive(
        self, harness: Callable[[_ExportKind, ExistingExportChoice], _Harness]
    ) -> None:
        h = harness(AUDIT_PDF, ExistingExportChoice.OVERWRITE)
        h.export_first()
        h.export()
        h.export()
        archive = h.out_dir / ARCHIVE_DIR_NAME
        assert sorted(p.name for p in archive.iterdir()) == [
            "trail_2026-09-25_14-03-07.pdf",
            "trail_2026-09-25_14-03-07_2.pdf",
        ]


class TestExportOverwriteArchiveFails:
    def test_nothing_overwritten_and_error_shown(
        self, harness: Callable[[_ExportKind, ExistingExportChoice], _Harness]
    ) -> None:
        h = harness(AUDIT_PDF, ExistingExportChoice.OVERWRITE)
        h.export_first()
        events_before = len(h.export_events())
        # Eine DATEI namens `archiv` blockiert das Anlegen des Archivordners –
        # ein echter Fehler auf jedem Betriebssystem, ohne Mock.
        (h.out_dir / ARCHIVE_DIR_NAME).write_bytes(b"kein Ordner")

        with patch("sampling_tool.ui.controllers.workspace_session.QMessageBox.warning") as warning:
            h.export()

        assert h.planned.read_bytes() == FIRST_VERSION
        assert sorted(p.name for p in h.out_dir.iterdir()) == [ARCHIVE_DIR_NAME, "trail.pdf"]
        assert len(h.export_events()) == events_before
        warning.assert_called_once()
        body = warning.call_args.args[2]
        assert "nicht gesichert" in body
        assert "nichts überschrieben" in body


class TestExportCancel:
    def test_cancel_writes_nothing_and_logs_nothing(
        self, harness: Callable[[_ExportKind, ExistingExportChoice], _Harness]
    ) -> None:
        h = harness(AUDIT_PDF, ExistingExportChoice.CANCEL)
        h.export_first()
        events_before = len(h.export_events())

        h.export()

        assert h.conflict_calls == [(h.planned, h.out_dir / "trail_2.pdf")]
        assert h.planned.read_bytes() == FIRST_VERSION
        assert sorted(p.name for p in h.out_dir.iterdir()) == ["trail.pdf"]
        assert len(h.export_events()) == events_before


@pytest.mark.parametrize("kind", EXPORT_KINDS, ids=[k.name for k in EXPORT_KINDS])
class TestAllExportPathsAsk:
    def test_first_export_logs_written_file(
        self,
        kind: _ExportKind,
        harness: Callable[[_ExportKind, ExistingExportChoice], _Harness],
    ) -> None:
        h = harness(kind, ExistingExportChoice.NEW_NAME)
        h.export()

        assert h.planned.is_file()
        assert h.conflict_calls == []
        assert Path(h.export_events()[-1].export_file or "") == h.planned

    def test_existing_target_goes_through_conflict_dialog(
        self,
        kind: _ExportKind,
        harness: Callable[[_ExportKind, ExistingExportChoice], _Harness],
    ) -> None:
        h = harness(kind, ExistingExportChoice.NEW_NAME)
        h.export_first()

        h.export()

        second = _suffixed(h.planned, 2)
        assert h.conflict_calls == [(h.planned, second)]
        assert second.is_file()
        assert h.planned.read_bytes() == FIRST_VERSION
        assert Path(h.export_events()[-1].export_file or "") == second
