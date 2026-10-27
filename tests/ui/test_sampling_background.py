"""Sprint 98: der Stichproben-Dialog liest nichts mehr auf dem UI-Thread.

Kern (`TestNoScanOnUiThread`): an den lesenden `DatasetRepo`-Methoden wird bei
jedem Aufruf der Thread aufgezeichnet. Der ganze Ablauf über den Controller –
Filterfeld wählen, Werte wechseln, Cluster-Feld wählen, OK – darf keinen davon
auf dem Main-Thread aufrufen. Der Dialog ist der echte `SamplingDialog`; nur
`exec()` ist durch ein Skript ersetzt, das die Eingaben macht und OK drückt.

Sprint-98-Symbole werden nur lokal in den Tests importiert, die sie brauchen –
`TestNoScanOnUiThread` läuft dadurch unverändert gegen `main` (dort rot).
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from sampling_tool import __version__
from sampling_tool.config import POPULATION_BASIS_SELECTION
from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    Engagement,
    FilterCondition,
    FilterOperator,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.core.provenance import SamplingProvenance
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import (
    AuditRepo,
    DatasetRepo,
    EngagementRepo,
    SampleRepo,
)
from sampling_tool.ui.controllers.main_controller import MainController
from sampling_tool.ui.dialogs.sampling_dialog import (
    NO_FILTER_LABEL,
    SamplingDialog,
    SamplingDialogResult,
)
from sampling_tool.ui.main_window import MainWindow
from sampling_tool.ui.recent import RecentEngagementsStore
from sampling_tool.ui.settings_store import AppSettings
from tests.ui._progress_cancel import CancelClicker

pytestmark = pytest.mark.ui

# Die lesenden Methoden, die eine ganze Spalte oder Tabelle scannen.
_SCANNING_METHODS = (
    "iter_rows",
    "iter_row_ids",
    "iter_row_field_pairs",
    "iter_row_multi_field_values",
    "distinct_values",
    "value_counts",
)
_N_ROWS = 200
_KONTEN = ("K1", "K2", "K3", "K4", "K5", "K6", "K7")

# Hinweistexte aus Sprint 98 – als Literal, damit der Test auch gegen main läuft.
_MATCH_COUNT_UNKNOWN = "Trefferzahl nicht ermittelt"
_CLUSTER_COUNT_UNKNOWN = "Clusterzahl nicht ermittelt"


# ---------------------------------------------------------------------------
# Fixtures und Helfer
# ---------------------------------------------------------------------------


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    return win


@pytest.fixture
def engagement_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "engagement.db"
    db = Database(db_path)
    db.migrate()
    eng = EngagementRepo(db.connect()).get_or_create(
        Engagement(
            auditor_name="Anna",
            client_name="ACME",
            auditor_position="Senior",
            audit_type="ISAE 3402",
        )
    )
    rows = tuple(
        DatasetRow(
            row_id=i,
            values={
                "Konto": _KONTEN[i % len(_KONTEN)],
                "Betrag": i * 10,
                "Gruppe": f"G{i % 4}",
                "Datum": datetime(2026, 1, 1 + i % 28),
            },
        )
        for i in range(1, _N_ROWS + 1)
    )
    DatasetRepo(db.connect()).create(
        Dataset(
            name="Buchungen",
            columns=("Konto", "Betrag", "Gruppe", "Datum"),
            engagement_id=eng.id,
        ),
        rows,
    )
    db.close()
    return db_path


@pytest.fixture
def controller(window: MainWindow, tmp_path: Path, engagement_db: Path) -> Iterator[MainController]:
    ctrl = MainController(
        window,
        recent_store=RecentEngagementsStore(path=tmp_path / "r.json"),
        settings=dataclasses.replace(AppSettings.defaults(), advanced_mode=True),
    )
    ctrl.engagement.handle_open_engagement(engagement_db)
    datasets = window.sidebar().datasets_widget()
    item = datasets.item(0)
    assert item is not None
    ctrl.selection.handle_dataset_selected(int(item.data(int(Qt.ItemDataRole.UserRole))))
    yield ctrl
    ctrl.engagement.handle_close_engagement()


class _ScanRecorder:
    """Zeichnet je Aufruf einer scannenden Repo-Methode Name und Thread auf.

    Methoden, die es (auf `main`) noch nicht gibt, werden übersprungen – so
    läuft derselbe Test als Positiv-Kontrolle gegen den Stand vor Sprint 98.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[tuple[str, bool]] = []
        self._lock = threading.Lock()
        for name in _SCANNING_METHODS:
            original = getattr(DatasetRepo, name, None)
            if original is not None:
                monkeypatch.setattr(DatasetRepo, name, self._wrap(name, original))

    def _wrap(self, name: str, original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(repo: DatasetRepo, *args: Any, **kwargs: Any) -> Any:
            with self._lock:
                self.calls.append((name, threading.current_thread() is threading.main_thread()))
            return original(repo, *args, **kwargs)

        return wrapper

    def on_main_thread(self) -> list[str]:
        return [name for name, on_main in self.calls if on_main]

    def in_workers(self) -> list[str]:
        return [name for name, on_main in self.calls if not on_main]


class _SlowInWorker:
    """Hält eine Repo-Methode im Worker an, bis `release()` – damit der
    Fortschrittsdialog erscheint und „Abbrechen" gedrückt werden kann."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
        self._gate = threading.Event()
        self.entered = 0
        original = getattr(DatasetRepo, name)

        def wrapper(repo: DatasetRepo, *args: Any, **kwargs: Any) -> Any:
            if threading.current_thread() is not threading.main_thread():
                self.entered += 1
                self._gate.wait(10)
            return original(repo, *args, **kwargs)

        monkeypatch.setattr(DatasetRepo, name, wrapper)

    def release(self) -> None:
        self._gate.set()


def _run_dialog(
    controller: MainController,
    monkeypatch: pytest.MonkeyPatch,
    script: Callable[[SamplingDialog], None],
) -> None:
    """`handle_new_sampling` mit echtem Dialog; `script` ersetzt die Nutzereingaben.

    Hat das Skript den Dialog per `accept()` geschlossen, gilt er als
    angenommen – sonst als abgebrochen (wie das Schließen des Fensters).
    """

    def scripted_exec(dialog: SamplingDialog) -> int:
        script(dialog)
        return int(dialog.result())

    monkeypatch.setattr(SamplingDialog, "exec", scripted_exec)
    controller.workspace.handle_new_sampling()


def _choose(combo: Any, text: str) -> None:
    index = combo.findText(text)
    assert index >= 0, text
    combo.setCurrentIndex(index)


def _sample_rows(db_path: Path) -> list[Any]:
    db = Database(db_path)
    try:
        return list(db.connect().execute("SELECT id FROM samples").fetchall())
    finally:
        db.close()


def _sampling_events(db_path: Path) -> list[Any]:
    db = Database(db_path)
    try:
        conn = db.connect()
        return [
            e
            for e in AuditRepo(conn).list_for_engagement(1, limit=10_000)
            if e.event_type == "sampling"
        ]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNoScanOnUiThread:
    def test_full_flow_reads_only_in_workers(
        self,
        controller: MainController,
        engagement_db: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        recorder = _ScanRecorder(monkeypatch)

        def script(dialog: SamplingDialog) -> None:
            row = dialog._filter_rows[0]
            _choose(row.field, "Konto")
            row.value.setCurrentIndex(1)
            row.value.setCurrentIndex(2)
            dialog._radio_cluster.setChecked(True)
            _choose(dialog._cluster_field, "Gruppe")
            dialog._size_spin.setValue(1)
            dialog.accept()

        _run_dialog(controller, monkeypatch, script)

        assert recorder.on_main_thread() == []
        assert recorder.in_workers(), "der Recorder hat nichts gesehen"
        assert len(_sample_rows(engagement_db)) == 1

    def test_two_filters_read_only_in_workers(
        self,
        controller: MainController,
        engagement_db: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        recorder = _ScanRecorder(monkeypatch)

        def script(dialog: SamplingDialog) -> None:
            first = dialog._filter_rows[0]
            _choose(first.field, "Konto")
            first.value.setCurrentIndex(3)
            dialog._add_filter_row()
            second = dialog._filter_rows[1]
            _choose(second.field, "Gruppe")
            second.value.setCurrentIndex(1)
            dialog._size_spin.setValue(2)
            dialog.accept()

        _run_dialog(controller, monkeypatch, script)

        assert recorder.on_main_thread() == []
        assert "iter_row_multi_field_values" in recorder.in_workers()
        assert len(_sample_rows(engagement_db)) == 1


def test_value_change_after_field_stats_needs_no_scan(
    controller: MainController, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _ScanRecorder(monkeypatch)
    hints: list[str] = []
    calls_after_field: list[int] = []

    def script(dialog: SamplingDialog) -> None:
        row = dialog._filter_rows[0]
        _choose(row.field, "Konto")
        calls_after_field.append(len(recorder.calls))
        hints.append(dialog._lbl_size_hint.text())
        for index in (1, 2, 3):
            row.value.setCurrentIndex(index)
            hints.append(dialog._lbl_size_hint.text())
        calls_after_field.append(len(recorder.calls))

    _run_dialog(controller, monkeypatch, script)

    assert calls_after_field[0] > 0
    assert calls_after_field[1] == calls_after_field[0], "Wertwechsel ohne neuen Scan"
    # K1 steht bei i ≡ 0 (mod 7), K2 bei i ≡ 1 usw.: 28, 29, 29, 29 von 200 Zeilen.
    expected = [sum(1 for i in range(1, _N_ROWS + 1) if i % 7 == k) for k in (0, 1, 2, 3)]
    assert hints == [f"max. {n} verfügbar" for n in expected]


class TestCancelBehaviour:
    def test_cancel_value_list_resets_filter_row(
        self, controller: MainController, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        slow = _SlowInWorker(monkeypatch, "value_counts")
        seen: dict[str, Any] = {}

        def script(dialog: SamplingDialog) -> None:
            row = dialog._filter_rows[0]
            clicker = CancelClicker()
            try:
                _choose(row.field, "Konto")
            finally:
                clicker.stop()
                slow.release()
            seen["labels"] = clicker.labels
            seen["field"] = row.field.currentText()
            seen["cached"] = "Konto" in dialog._distinct_cache
            seen["values_enabled"] = row.value.isEnabled()
            # Nichts gecacht: dieselbe Spalte erneut gewählt lädt die Werte.
            _choose(row.field, "Konto")
            seen["values_after_retry"] = row.value.count()

        _run_dialog(controller, monkeypatch, script)

        assert seen["labels"] == ["Werte werden gelesen…"]
        assert seen["field"] == NO_FILTER_LABEL
        assert seen["cached"] is False
        assert seen["values_enabled"] is False
        assert seen["values_after_retry"] == len(_KONTEN)

    def test_cancel_match_count_shows_hint_and_ok_does_not_recount(
        self,
        controller: MainController,
        engagement_db: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: dict[str, Any] = {}
        recorder = _ScanRecorder(monkeypatch)

        def script(dialog: SamplingDialog) -> None:
            first = dialog._filter_rows[0]
            _choose(first.field, "Konto")
            dialog._add_filter_row()
            second = dialog._filter_rows[1]
            # Ab zwei Filtern zählt ein Scan über die Filterfelder – den anhalten.
            slow = _SlowInWorker(monkeypatch, "iter_row_multi_field_values")
            clicker = CancelClicker()
            try:
                _choose(second.field, "Gruppe")
            finally:
                clicker.stop()
                slow.release()
            seen["labels"] = clicker.labels
            seen["hint"] = dialog._lbl_size_hint.text()
            seen["cached_two_filter_counts"] = [
                key for key in dialog._match_count_cache if len(key[0]) == 2
            ]
            # Der abgelöste Zähl-Worker scannt nach der Freigabe noch – erst abwarten.
            from sampling_tool.ui.dialogs.progress_dialog import wait_for_detached_workers

            wait_for_detached_workers()
            before_ok = recorder.in_workers().count("iter_row_multi_field_values")
            dialog._size_spin.setValue(1)
            dialog.accept()
            # Beim OK prüft die Probeziehung (ein Scan), keine zweite Zählung.
            seen["scans_at_ok"] = (
                recorder.in_workers().count("iter_row_multi_field_values") - before_ok
            )

        _run_dialog(controller, monkeypatch, script)

        assert seen["labels"] == ["Treffer werden gezählt…"]
        assert seen["hint"] == _MATCH_COUNT_UNKNOWN
        assert seen["cached_two_filter_counts"] == []
        assert seen["scans_at_ok"] == 1
        assert len(_sample_rows(engagement_db)) == 1

    def test_cancel_group_count_shows_hint(
        self, controller: MainController, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        def script(dialog: SamplingDialog) -> None:
            dialog._radio_cluster.setChecked(True)
            slow = _SlowInWorker(monkeypatch, "value_counts")
            clicker = CancelClicker()
            try:
                _choose(dialog._cluster_field, "Gruppe")
            finally:
                clicker.stop()
                slow.release()
            seen["labels"] = clicker.labels
            seen["hint"] = dialog._lbl_size_hint.text()
            seen["cached"] = "Gruppe" in dialog._group_count_cache
            # Erst eine Änderung der Eingabe startet die Zählung neu.
            _choose(dialog._cluster_field, "Konto")
            _choose(dialog._cluster_field, "Gruppe")
            seen["hint_after_retry"] = dialog._lbl_size_hint.text()

        _run_dialog(controller, monkeypatch, script)

        assert seen["labels"] == ["Gruppen werden gezählt…"]
        assert seen["hint"] == _CLUSTER_COUNT_UNKNOWN
        assert seen["cached"] is False
        assert seen["hint_after_retry"] == "max. 4 Cluster verfügbar"

    def test_cancel_draw_keeps_dialog_open_and_saves_nothing(
        self,
        controller: MainController,
        engagement_db: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: dict[str, Any] = {}

        def script(dialog: SamplingDialog) -> None:
            dialog._size_spin.setValue(3)
            seed = dialog._seed_spin.value()
            slow = _SlowInWorker(monkeypatch, "iter_row_ids")
            clicker = CancelClicker()
            try:
                dialog.accept()
            finally:
                clicker.stop()
                slow.release()
            seen["labels"] = clicker.labels
            seen["result"] = dialog.result()
            seen["get_result"] = dialog.get_result()
            seen["inputs"] = (dialog._size_spin.value(), dialog._seed_spin.value() == seed)
            seen["messages"] = [label.text() for label in dialog._inline_errors.values()]
            seen["general"] = dialog._error_label.text()

        _run_dialog(controller, monkeypatch, script)

        assert seen["labels"] == ["Stichprobe wird gezogen…"]
        assert seen["result"] != int(QDialog.DialogCode.Accepted)
        assert seen["get_result"] is None
        assert seen["inputs"] == (3, True)
        assert all(text == "" for text in seen["messages"])
        assert seen["general"] == ""
        assert _sample_rows(engagement_db) == []
        assert _sampling_events(engagement_db) == []


def test_saved_sample_identical_to_main(
    controller: MainController, engagement_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gleiche Eingaben ⇒ gespeicherte Stichprobe und Audit-Event wie vor Sprint 98."""
    # Lokal importiert: die Datei läuft so auch gegen main (Positiv-Kontrolle).
    from tests.integration.test_sampling_fast_paths import _reference_draw

    def script(dialog: SamplingDialog) -> None:
        first = dialog._filter_rows[0]
        _choose(first.field, "Gruppe")
        first.value.setCurrentIndex(2)
        dialog._add_filter_row()
        second = dialog._filter_rows[1]
        _choose(second.field, "Betrag")
        _choose(second.operator, "≥ (größer/gleich)")
        second.value_text.setText("700")
        second.value_text.editingFinished.emit()
        dialog._seed_spin.setValue(4711)
        dialog._size_spin.setValue(7)
        dialog.accept()

    _run_dialog(controller, monkeypatch, script)

    config = SampleConfig(
        method=SamplingMethod.SIMPLE,
        size=7,
        seed=4711,
        filters=(
            FilterCondition("Gruppe", FilterOperator.EQ, "G2"),
            FilterCondition("Betrag", FilterOperator.GTE, 700),
        ),
    )
    db = Database(engagement_db)
    try:
        conn = db.connect()
        repo = DatasetRepo(conn)
        (dataset,) = repo.list_for_engagement(1)
        assert dataset.id is not None
        reference = _reference_draw(repo, dataset, SamplingDialogResult(config=config), None)
        (stored,) = SampleRepo(conn).list_for_dataset(dataset.id)
    finally:
        db.close()

    assert stored.config == config
    assert stored.selected_row_ids == reference.selected_row_ids
    assert stored.population_size == reference.population_size
    assert stored.algorithm_version == reference.algorithm_version
    assert len(stored.selected_row_ids) == 7

    expected: SampleResult = dataclasses.replace(
        reference, id=stored.id, created_by=stored.created_by
    )
    provenance = SamplingProvenance.from_sample_result(
        expected, dataset_id=dataset.id, app_version=__version__
    )
    (event,) = _sampling_events(engagement_db)
    assert event.sample_id == stored.id
    assert event.sample_size == len(reference.selected_row_ids)
    assert event.total_count == reference.population_size
    assert event.seed == 4711
    assert event.sample_percent == pytest.approx(
        len(reference.selected_row_ids) / reference.population_size * 100.0
    )
    assert event.details == {
        "dataset_rows": _N_ROWS,
        "population_basis": POPULATION_BASIS_SELECTION,
        **provenance.to_audit_details(),
    }
