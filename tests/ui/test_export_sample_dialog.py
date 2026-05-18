"""ExportSampleDialog – Spaltenauswahl, Vorschau, Validierung."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialogButtonBox
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import Dataset
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
        today = datetime.now().strftime("%Y%m%d")
        assert f"Foo_ID42_BDO_sampling_{today}.xlsx" in dialog._preview_label.text()
        dialog._name_field.setText("Bar")
        dialog._id_field.setText("99")
        assert f"Bar_ID99_BDO_sampling_{today}.xlsx" in dialog._preview_label.text()

    def test_validation_blocks_when_name_empty(self, qtbot: QtBot, tmp_path: Path) -> None:
        dialog = ExportSampleDialog(_dataset(), default_id="1", default_output_dir=tmp_path)
        qtbot.addWidget(dialog)
        dialog._name_field.setText("")
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
