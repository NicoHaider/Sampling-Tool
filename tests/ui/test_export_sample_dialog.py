"""ExportSampleDialog – Spaltenauswahl, Vorschau, Validierung."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialogButtonBox, QLabel
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import Dataset
from sampling_tool.io.exporter import ExcelExporter
from sampling_tool.ui.dialogs._export_base import HINT_NO_COLUMNS, ExportTargetWidget
from sampling_tool.ui.dialogs.export_sample_dialog import ExportSampleDialog

pytestmark = pytest.mark.ui


def _dataset() -> Dataset:
    return Dataset(
        name="Buchungen",
        columns=("Konto", "Betrag", "Datum"),
        row_count=1,
    )


def _ok_enabled(dialog: ExportSampleDialog) -> bool:
    box = dialog.findChild(QDialogButtonBox)
    assert box is not None
    btn = box.button(QDialogButtonBox.StandardButton.Ok)
    assert btn is not None
    return bool(btn.isEnabled())


def _hint_text(dialog: ExportSampleDialog) -> str:
    label = dialog._target.findChild(QLabel, "exportTargetHint")
    assert label is not None
    return str(label.text())


class TestExportSampleDialog:
    def test_default_all_columns_checked(self, qtbot: QtBot) -> None:
        dialog = ExportSampleDialog(_dataset(), default_id="1", default_output_dir=Path("/tmp"))
        qtbot.addWidget(dialog)
        assert dialog._selected_columns() == ["Konto", "Betrag", "Datum"]

    def test_select_none_button_clears_all(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportSampleDialog(_dataset(), default_id="1", default_output_dir=tmp_path)
        qtbot.addWidget(dialog)
        dialog._set_all_checked(False)
        assert dialog._selected_columns() == []
        assert _ok_enabled(dialog) is False

    def test_select_all_button_rechecks_all(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportSampleDialog(_dataset(), default_id="1", default_output_dir=tmp_path)
        qtbot.addWidget(dialog)
        dialog._set_all_checked(False)
        dialog._set_all_checked(True)
        assert len(dialog._selected_columns()) == 3

    def test_preview_updates_on_inputs(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportSampleDialog(
            _dataset(), default_name="Foo", default_id="42", default_output_dir=tmp_path
        )
        qtbot.addWidget(dialog)
        assert dialog._target.preview_filename() == ExcelExporter._build_filename("Foo", "42")
        dialog._target._name_field.setText("Bar")
        dialog._target._id_field.setText("99")
        assert dialog._target.preview_filename() == ExcelExporter._build_filename("Bar", "99")

    def test_validation_blocks_when_name_empty(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportSampleDialog(_dataset(), default_id="1", default_output_dir=tmp_path)
        qtbot.addWidget(dialog)
        dialog._target._name_field.setText("")
        assert _ok_enabled(dialog) is False

    def test_validation_blocks_when_no_output_dir(self, qtbot: QtBot) -> None:
        dialog = ExportSampleDialog(_dataset(), default_id="1")
        qtbot.addWidget(dialog)
        assert _ok_enabled(dialog) is False

    def test_get_result_returns_filled_dataclass(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportSampleDialog(
            _dataset(), default_name="My", default_id="7", default_output_dir=tmp_path
        )
        qtbot.addWidget(dialog)
        first = dialog._column_list.item(0)
        assert first is not None
        first.setCheckState(Qt.CheckState.Unchecked)
        dialog._on_accept()
        result = dialog.get_result()
        assert result is not None
        assert result.columns == ["Betrag", "Datum"]
        assert result.custom_name == "My"
        assert result.custom_id == "7"
        assert result.output_dir == tmp_path


class TestExportSampleDialogUsesTargetWidget:
    """Sprint 60 / D.5 (N-016): die rechte Spalte ist das gemeinsame
    `ExportTargetWidget` statt einer inline nachgebauten Kopie."""

    def test_dialog_constructs_export_target_widget(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportSampleDialog(_dataset(), default_id="1", default_output_dir=tmp_path)
        qtbot.addWidget(dialog)
        assert isinstance(dialog._target, ExportTargetWidget)

    def test_inline_duplicate_helpers_are_gone(self) -> None:
        import sampling_tool.ui.dialogs.export_sample_dialog as mod

        assert not hasattr(mod, "_build_preview")
        assert not hasattr(mod, "_sanitize")
        assert not hasattr(mod, "_FILENAME_PREVIEW")
        assert not hasattr(ExportSampleDialog, "_choose_dir")

    def test_ok_enable_requires_columns_and_widget_valid(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        dialog = ExportSampleDialog(_dataset(), default_id="1", default_output_dir=tmp_path)
        qtbot.addWidget(dialog)
        assert _ok_enabled(dialog) is True
        dialog._set_all_checked(False)
        assert _ok_enabled(dialog) is False
        dialog._set_all_checked(True)
        assert _ok_enabled(dialog) is True
        dialog._target.set_output_dir(tmp_path / "ghost")
        assert _ok_enabled(dialog) is False


class TestSelectionHint:
    """Sprint 72: „alle Spalten abgewählt" war ein stummer grauer OK-Button –
    die Bedingung lag im Dialog, `validation_hint()` konnte sie nicht sehen."""

    def test_hint_when_nothing_selected(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportSampleDialog(_dataset(), default_id="1", default_output_dir=tmp_path)
        qtbot.addWidget(dialog)
        dialog._set_all_checked(False)
        assert _hint_text(dialog) == HINT_NO_COLUMNS
        assert _ok_enabled(dialog) is False

    def test_hint_clears_when_selection_restored(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportSampleDialog(_dataset(), default_id="1", default_output_dir=tmp_path)
        qtbot.addWidget(dialog)
        dialog._set_all_checked(False)
        assert _hint_text(dialog) == HINT_NO_COLUMNS

        first = dialog._column_list.item(0)
        assert first is not None
        first.setCheckState(Qt.CheckState.Checked)

        assert _hint_text(dialog) == ""
        assert _ok_enabled(dialog) is True

    def test_bulk_suppression_leaves_no_stale_hint(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Die Sprint-34-Unterdrückung während „Alle abwählen/auswählen" darf
        den Hinweis nicht auf einem veralteten Stand stehen lassen – nach dem
        Bulk läuft genau ein `_update_state`, und der muss aufräumen."""
        dialog = ExportSampleDialog(_dataset(), default_id="1", default_output_dir=tmp_path)
        qtbot.addWidget(dialog)
        dialog._set_all_checked(False)
        assert _hint_text(dialog) == HINT_NO_COLUMNS

        dialog._set_all_checked(True)
        assert _hint_text(dialog) == ""
        assert _ok_enabled(dialog) is True


class TestBulkCheckSingleUpdate:
    """Sprint 34 / WP5: „Alle auswählen/abwählen" aktualisiert genau einmal.

    Vorher feuerte `itemChanged` pro Spalten-Item → `_update_state` lief
    N-mal mit je einem O(N)-CheckState-Scan (Audit-Rohdaten haben oft
    50–300 Spalten). Der Endzustand (Auswahl, OK-Button) bleibt identisch.
    Sprint 60: der Preview-Rebuild lebt jetzt komplett im
    `ExportTargetWidget` und ist von der Spaltenauswahl entkoppelt (das
    Widget reagiert nur auf sein eigenes `changed`) – gezählt wird deshalb
    direkt `_update_state` selbst.
    """

    def test_set_all_checked_runs_update_state_once(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        columns = tuple(f"Spalte_{i}" for i in range(1, 41))
        dataset = Dataset(name="Breit", columns=columns, row_count=1)
        dialog = ExportSampleDialog(dataset, default_id="1", default_output_dir=tmp_path)
        qtbot.addWidget(dialog)

        calls: list[str] = []
        original = dialog._update_state

        def counting() -> None:
            calls.append("x")
            original()

        monkeypatch.setattr(dialog, "_update_state", counting)

        dialog._set_all_checked(False)
        assert len(calls) == 1  # vorher: 40 (einmal pro itemChanged)
        assert dialog._selected_columns() == []
        assert _ok_enabled(dialog) is False

        calls.clear()
        dialog._set_all_checked(True)
        assert len(calls) == 1
        assert len(dialog._selected_columns()) == 40
