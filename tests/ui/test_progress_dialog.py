"""Tests für `TaskProgressDialog` – Konstruktor, Callback-Adapter, Close.

Hintergrund: Sprint 14 / T-001 (Pass 4) – der Dialog hatte 0 % Coverage und
keinen Production-Caller. Mit dem Sprint-14-Wireup in `handle_import_excel`
ist er jetzt aktiv; diese Tests sichern den Adapter und das Reset-Verhalten.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from pytestqt.qtbot import QtBot

from sampling_tool.ui.dialogs.progress_dialog import TaskProgressDialog

pytestmark = pytest.mark.ui


class TestTaskProgressDialog:
    def test_constructor_initializes_application_modal(self, qtbot: QtBot) -> None:
        dlg = TaskProgressDialog("Importiere Datei…", None)
        qtbot.addWidget(dlg)
        assert dlg.labelText() == "Importiere Datei…"
        assert dlg.windowModality() == Qt.WindowModality.ApplicationModal
        assert dlg.value() == 0
        assert dlg.minimumDuration() == 300

    def test_progress_callback_sets_value_and_maximum(self, qtbot: QtBot) -> None:
        dlg = TaskProgressDialog("Test", None)
        qtbot.addWidget(dlg)
        cb = dlg.progress_callback()

        cb(50, 100)

        assert dlg.maximum() == 100
        assert dlg.value() == 50

    def test_progress_callback_resyncs_maximum_when_total_changes(self, qtbot: QtBot) -> None:
        """Wenn der ExcelImporter den Initial-Schätzwert nach unten korrigiert
        (siehe `importer._row_generator`), muss der Dialog mitziehen."""
        dlg = TaskProgressDialog("Test", None)
        qtbot.addWidget(dlg)
        cb = dlg.progress_callback()

        cb(500, 1000)
        assert dlg.maximum() == 1000
        assert dlg.value() == 500

        cb(700, 1200)
        assert dlg.maximum() == 1200
        assert dlg.value() == 700
