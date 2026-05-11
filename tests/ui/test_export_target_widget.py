"""Tests für `ExportTargetWidget` – Vorschau-Label, Validierung, Path-Bau."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from sampling_tool.ui.dialogs._export_base import ExportTargetWidget

pytestmark = pytest.mark.ui


class TestExportTargetWidget:
    def test_preview_substitutes_tokens(self, qtbot: QtBot) -> None:
        w = ExportTargetWidget(
            default_name="ACME", default_id="42", file_extension=".pdf", type_token="audit_trail"
        )
        qtbot.addWidget(w)
        preview = w.preview_filename()
        today = datetime.now().strftime("%Y%m%d")
        assert preview == f"ACME_ID42_BDO_audit_trail_{today}.pdf"

    def test_preview_updates_when_fields_change(self, qtbot: QtBot) -> None:
        w = ExportTargetWidget(default_name="A", default_id="1", file_extension=".xlsx")
        qtbot.addWidget(w)
        w._name_field.setText("Mandant_Neu")
        assert "Mandant_Neu" in w.preview_filename()
        w._id_field.setText("99")
        assert "ID99" in w.preview_filename()

    def test_is_valid_false_without_directory(self, qtbot: QtBot) -> None:
        w = ExportTargetWidget(default_name="ACME", default_id="1", file_extension=".pdf")
        qtbot.addWidget(w)
        assert w.is_valid() is False

    def test_is_valid_true_with_all_fields(self, qtbot: QtBot, tmp_path: Path) -> None:
        w = ExportTargetWidget(default_name="ACME", default_id="1", file_extension=".pdf")
        qtbot.addWidget(w)
        w.set_output_dir(tmp_path)
        assert w.is_valid() is True

    def test_is_valid_false_when_dir_missing(self, qtbot: QtBot, tmp_path: Path) -> None:
        w = ExportTargetWidget(default_name="ACME", default_id="1", file_extension=".pdf")
        qtbot.addWidget(w)
        w.set_output_dir(tmp_path / "ghost")
        assert w.is_valid() is False

    def test_get_path_combines_dir_and_filename(self, qtbot: QtBot, tmp_path: Path) -> None:
        w = ExportTargetWidget(
            default_name="ACME",
            default_id="42",
            file_extension=".html",
            type_token="report",
        )
        qtbot.addWidget(w)
        w.set_output_dir(tmp_path)
        path = w.get_path()
        assert path is not None
        assert path.parent == tmp_path
        assert path.suffix == ".html"
        assert "ACME" in path.name
        assert "ID42" in path.name

    def test_changed_signal_fires_on_text_edit(self, qtbot: QtBot) -> None:
        w = ExportTargetWidget(default_name="A", default_id="1", file_extension=".pdf")
        qtbot.addWidget(w)
        with qtbot.waitSignal(w.changed, timeout=500):
            w._name_field.setText("Neu")

    def test_sanitize_replaces_forbidden_chars(self, qtbot: QtBot) -> None:
        w = ExportTargetWidget(default_name="Mandant/<bad>", default_id="1", file_extension=".pdf")
        qtbot.addWidget(w)
        preview = w.preview_filename()
        # Forbidden chars dürfen nicht im Dateinamen landen.
        for forbidden in '<>:"/\\|?*':
            assert forbidden not in preview
