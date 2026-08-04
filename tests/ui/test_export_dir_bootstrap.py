"""Sprint 71 / Befund 1 (P0): `<projekt>/exports` wurde nie angelegt.

`WorkspaceSession.default_export_dir()` liefert `<db-parent>/exports`, aber
kein einziger Produktionspfad hat dieses Verzeichnis erzeugt – erst
`io/_atomic.py` beim tatsächlichen Schreiben, also nach dem OK-Klick.
`ExportTargetWidget.is_valid()` verlangt jedoch `output_dir.is_dir()`,
weshalb der OK-Button in **allen vier** Export-Dialogen auf einem frischen
Projekt dauerhaft grau blieb.

Diese Tests laufen bewusst über den echten Controller-Pfad: die
Widget-Tests waren grün, weil sie `tmp_path` durchgereicht haben – und
`tmp_path` existiert immer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QListWidget
from pytestqt.qtbot import QtBot

from sampling_tool.config import EXPORT_DIR_NAME
from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    Engagement,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import (
    DatasetRepo,
    EngagementRepo,
    SampleRepo,
)
from sampling_tool.ui.controllers._factories import (
    default_audit_pdf_factory,
    default_excel_report_factory,
    default_export_factory,
    default_html_report_factory,
)
from sampling_tool.ui.controllers.main_controller import MainController
from sampling_tool.ui.controllers.workspace_session import WorkspaceSession
from sampling_tool.ui.main_window import MainWindow
from sampling_tool.ui.recent import RecentEngagementsStore
from sampling_tool.ui.settings_store import AppSettings

pytestmark = pytest.mark.ui


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reject_export_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Alle vier Export-Dialoge sind modal – `exec()` würde headless
    blockieren. Rejected beendet den Handler direkt nach der Konstruktion;
    geprüft wird der Dialog-Zustand, nicht der Export selbst."""
    for module, cls in (
        ("export_audit_pdf_dialog", "ExportAuditPdfDialog"),
        ("export_excel_report_dialog", "ExportExcelReportDialog"),
        ("export_html_report_dialog", "ExportHtmlReportDialog"),
        ("export_sample_dialog", "ExportSampleDialog"),
    ):
        monkeypatch.setattr(
            f"sampling_tool.ui.dialogs.{module}.{cls}.exec",
            lambda _self: int(QDialog.DialogCode.Rejected),
        )


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Diese Tests bauen echte MainWindows; `closeEvent` -> `_window_state.save()`
    wuerde sonst in die echten Benutzer-Prefs schreiben. Gleiches Muster wie
    `test_main_window.TestWindowGeometryFitsScreen._isolated_qsettings` –
    bewusst kein HOME-Umbiegen (hat in Sprint 67 echte Prefs korrumpiert).
    """
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    monkeypatch.setattr(
        "sampling_tool.ui.main_window.QSettings",
        lambda organization, application: QSettings(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, organization, application
        ),
    )


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    return win


@pytest.fixture
def recent_store(tmp_path: Path) -> RecentEngagementsStore:
    return RecentEngagementsStore(path=tmp_path / "recent.json")


@pytest.fixture
def fresh_db(tmp_path: Path) -> Path:
    """Frisches Projekt inkl. Dataset + Sample – aber OHNE `exports`-Ordner."""
    db_path = tmp_path / "projekt" / "engagement.db"
    db_path.parent.mkdir(parents=True)
    db = Database(db_path)
    db.migrate()
    eng = EngagementRepo(db.connect()).get_or_create(
        Engagement(
            auditor_name="Anna",
            auditor_position="Senior",
            client_name="ACME",
            audit_type="ISAE 3402",
        )
    )
    assert eng.id is not None
    rows = tuple(
        DatasetRow(row_id=i, values={"Konto": f"K{i}", "Betrag": i * 10}) for i in range(1, 6)
    )
    dataset = DatasetRepo(db.connect()).create(
        Dataset(name="Buchungen", columns=("Konto", "Betrag"), engagement_id=eng.id),
        rows,
    )
    assert dataset.id is not None
    SampleRepo(db.connect()).create_from_result(
        SampleResult(
            config=SampleConfig(method=SamplingMethod.SIMPLE, size=2, seed=42),
            selected_row_ids=(2, 4),
            population_size=5,
        ),
        dataset.id,
        "tester",
    )
    db.close()
    return db_path


@pytest.fixture
def session(window: MainWindow, recent_store: RecentEngagementsStore) -> Iterator[WorkspaceSession]:
    s = WorkspaceSession(window=window, settings=AppSettings.defaults(), recent_store=recent_store)
    yield s
    if s.db is not None:
        s.db.close()


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------


def _capture(default_factory: Callable[..., Any], box: list[Any]) -> Callable[..., Any]:
    """Baut den ECHTEN Dialog und merkt ihn sich, statt ihn zu stubben."""

    def factory(*args: Any, **kwargs: Any) -> Any:
        dialog = default_factory(*args, **kwargs)
        box.append(dialog)
        return dialog

    return factory


def _first_item_id(list_widget: QListWidget) -> int:
    item = list_widget.item(0)
    assert item is not None
    value = item.data(int(Qt.ItemDataRole.UserRole))
    assert isinstance(value, int)
    return value


def _assert_target_ready(dialog: Any, expected_dir: Path) -> None:
    """Zielordner ist gesetzt, existiert wirklich, und OK ist klickbar."""
    target = dialog._target
    assert target.get_output_dir() == expected_dir, (
        f"Zielordner {target.get_output_dir()!r} != erwartet {expected_dir!r}"
    )
    assert expected_dir.is_dir(), f"Zielordner {expected_dir} existiert nicht auf der Platte"
    ok_btn = dialog._buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert ok_btn is not None
    assert ok_btn.isEnabled(), "OK-Button ist grau, obwohl der Zielordner vorbelegt ist"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExportDirBootstrap:
    """Auf einem frischen Projekt muss der Export-Dialog sofort bedienbar sein."""

    def test_audit_pdf_dialog_ok_enabled_on_fresh_project(
        self, window: MainWindow, recent_store: RecentEngagementsStore, fresh_db: Path
    ) -> None:
        exports = fresh_db.parent / EXPORT_DIR_NAME
        assert not exports.exists(), "Vorbedingung: exports/ darf noch NICHT existieren"

        box: list[Any] = []
        controller = MainController(
            window,
            recent_store=recent_store,
            audit_pdf_dialog_factory=_capture(default_audit_pdf_factory, box),
        )
        try:
            controller.engagement.handle_open_engagement(fresh_db)
            controller.export.handle_export_audit_pdf()
        finally:
            controller.engagement.handle_close_engagement()

        assert box, "Der AuditTrail-PDF-Dialog wurde nicht erzeugt"
        _assert_target_ready(box[0], exports)

    def test_html_report_dialog_ok_enabled_on_fresh_project(
        self, window: MainWindow, recent_store: RecentEngagementsStore, fresh_db: Path
    ) -> None:
        exports = fresh_db.parent / EXPORT_DIR_NAME
        assert not exports.exists(), "Vorbedingung: exports/ darf noch NICHT existieren"

        box: list[Any] = []
        controller = MainController(
            window,
            recent_store=recent_store,
            html_report_dialog_factory=_capture(default_html_report_factory, box),
        )
        try:
            controller.engagement.handle_open_engagement(fresh_db)
            controller.export.handle_export_html_report()
        finally:
            controller.engagement.handle_close_engagement()

        assert box, "Der HTML-Report-Dialog wurde nicht erzeugt"
        _assert_target_ready(box[0], exports)

    def test_excel_report_dialog_ok_enabled_on_fresh_project(
        self, window: MainWindow, recent_store: RecentEngagementsStore, fresh_db: Path
    ) -> None:
        exports = fresh_db.parent / EXPORT_DIR_NAME
        assert not exports.exists(), "Vorbedingung: exports/ darf noch NICHT existieren"

        box: list[Any] = []
        controller = MainController(
            window,
            recent_store=recent_store,
            excel_report_dialog_factory=_capture(default_excel_report_factory, box),
        )
        try:
            controller.engagement.handle_open_engagement(fresh_db)
            controller.export.handle_export_excel_report()
        finally:
            controller.engagement.handle_close_engagement()

        assert box, "Der Excel-Report-Dialog wurde nicht erzeugt"
        _assert_target_ready(box[0], exports)

    def test_sample_export_dialog_ok_enabled_on_fresh_project(
        self, window: MainWindow, recent_store: RecentEngagementsStore, fresh_db: Path
    ) -> None:
        exports = fresh_db.parent / EXPORT_DIR_NAME
        assert not exports.exists(), "Vorbedingung: exports/ darf noch NICHT existieren"

        box: list[Any] = []
        controller = MainController(
            window,
            recent_store=recent_store,
            export_dialog_factory=_capture(default_export_factory, box),
        )
        try:
            controller.engagement.handle_open_engagement(fresh_db)
            controller.selection.handle_dataset_selected(
                _first_item_id(window.sidebar().datasets_widget())
            )
            controller.selection.handle_sample_selected(
                _first_item_id(window.sidebar().samples_widget())
            )
            controller.export.handle_export_sample()
        finally:
            controller.engagement.handle_close_engagement()

        assert box, "Der Sample-Export-Dialog wurde nicht erzeugt"
        _assert_target_ready(box[0], exports)


class TestEnsureExportDir:
    """`ensure_export_dir()` legt an, `default_export_dir()` bleibt seiteneffektfrei."""

    def test_ensure_export_dir_creates_directory(
        self, session: WorkspaceSession, fresh_db: Path
    ) -> None:
        session.db = Database(fresh_db)
        exports = fresh_db.parent / EXPORT_DIR_NAME
        assert not exports.exists()

        created = session.ensure_export_dir()

        assert created == exports
        assert exports.is_dir()

    def test_ensure_export_dir_is_idempotent(
        self, session: WorkspaceSession, fresh_db: Path
    ) -> None:
        session.db = Database(fresh_db)

        first = session.ensure_export_dir()
        second = session.ensure_export_dir()

        assert first == second
        assert second is not None
        assert second.is_dir()

    def test_ensure_export_dir_returns_none_on_oserror(
        self,
        session: WorkspaceSession,
        fresh_db: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        session.db = Database(fresh_db)

        def _boom(self: Path, *args: Any, **kwargs: Any) -> None:
            raise OSError("kein Platz auf dem Gerät")

        monkeypatch.setattr(Path, "mkdir", _boom)

        with caplog.at_level("ERROR"):
            result = session.ensure_export_dir()

        assert result is None
        assert caplog.records, "OSError muss geloggt werden"

    def test_default_export_dir_has_no_side_effect(
        self, session: WorkspaceSession, fresh_db: Path
    ) -> None:
        session.db = Database(fresh_db)
        exports = fresh_db.parent / EXPORT_DIR_NAME

        computed = session.default_export_dir()

        assert computed == exports
        assert not exports.exists(), "default_export_dir() darf NICHTS anlegen"
