"""Tests für `ExportTargetWidget` – Vorschau-Label, Validierung, Path-Bau."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from sampling_tool.ui.dialogs._export_base import (
    HINT_MISSING_ID,
    HINT_MISSING_NAME,
    HINT_NO_DIR,
    ExportTargetWidget,
    hint_missing_dir,
)

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


class TestValidationHint:
    """Sprint 71 / Befund 1: `validation_hint()` ist die Single Source of
    Truth – `is_valid()` leitet sich davon ab. Der Hinweis erklärt dem
    Auditor, warum der Exportieren-Button grau ist (vorher: keine Erklärung).
    """

    def test_hint_is_empty_when_valid(self, qtbot: QtBot, tmp_path: Path) -> None:
        w = ExportTargetWidget(default_name="ACME", default_id="1", file_extension=".pdf")
        qtbot.addWidget(w)
        w.set_output_dir(tmp_path)
        assert w.validation_hint() == ""

    def test_hint_reports_missing_name(self, qtbot: QtBot, tmp_path: Path) -> None:
        w = ExportTargetWidget(default_name="", default_id="1", file_extension=".pdf")
        qtbot.addWidget(w)
        w.set_output_dir(tmp_path)
        assert w.validation_hint() == HINT_MISSING_NAME

    def test_hint_reports_missing_id(self, qtbot: QtBot, tmp_path: Path) -> None:
        w = ExportTargetWidget(default_name="ACME", default_id="", file_extension=".pdf")
        qtbot.addWidget(w)
        w.set_output_dir(tmp_path)
        assert w.validation_hint() == HINT_MISSING_ID

    def test_hint_reports_missing_dir(self, qtbot: QtBot) -> None:
        w = ExportTargetWidget(default_name="ACME", default_id="1", file_extension=".pdf")
        qtbot.addWidget(w)
        assert w.validation_hint() == HINT_NO_DIR

    def test_hint_reports_nonexistent_dir_and_includes_path(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        ghost = tmp_path / "gibtsnicht"
        w = ExportTargetWidget(default_name="ACME", default_id="1", file_extension=".pdf")
        qtbot.addWidget(w)
        w.set_output_dir(ghost)
        hint = w.validation_hint()
        assert hint == hint_missing_dir(ghost)
        # Der konkrete Pfad muss im Text auftauchen – plattformneutral
        # verglichen (Windows rendert Backslashes).
        assert str(ghost) in hint

    def test_is_valid_matches_hint_for_all_states(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Paritäts-Test gegen die Sprint-70-Semantik.

        Bewusst NICHT `is_valid() == (validation_hint() == "")` – das ist
        seit dem Refactoring eine Tautologie (`is_valid` ist buchstäblich
        `not validation_hint()`) und würde für jede beliebige Implementierung
        halten. Verglichen wird stattdessen gegen eine lokale Kopie der
        alten Bedingung: der Refactor darf die Wahrheitstabelle nicht
        verändert haben.
        """

        def old_is_valid(widget: ExportTargetWidget) -> bool:
            # Wortgleiche Kopie der Vor-Sprint-71-Implementierung.
            if not widget.get_name() or not widget.get_id():
                return False
            if widget.get_output_dir() is None:
                return False
            output_dir = widget.get_output_dir()
            assert output_dir is not None
            return output_dir.is_dir()

        existing = tmp_path / "da"
        existing.mkdir()
        missing = tmp_path / "weg"

        checked = 0
        for name in ("ACME", ""):
            for id_ in ("1", ""):
                for directory in (None, missing, existing):
                    w = ExportTargetWidget(default_name=name, default_id=id_, file_extension=".pdf")
                    qtbot.addWidget(w)
                    if directory is not None:
                        w.set_output_dir(directory)
                    checked += 1
                    assert w.is_valid() == old_is_valid(w), (
                        f"Semantik geändert für name={name!r} id={id_!r} dir={directory!r}: "
                        f"neu={w.is_valid()} alt={old_is_valid(w)}"
                    )
                    # Und der Hinweis muss zum Ergebnis passen.
                    assert w.is_valid() == (w.validation_hint() == "")
        assert checked == 12

    def test_hint_label_hidden_when_valid(self, qtbot: QtBot, tmp_path: Path) -> None:
        w = ExportTargetWidget(default_name="ACME", default_id="1", file_extension=".pdf")
        qtbot.addWidget(w)
        w.show()
        w.set_output_dir(tmp_path)
        label = w.findChild(QLabel, "exportTargetHint")
        assert label is not None
        assert label.isVisible() is False

        w._name_field.setText("")
        assert label.isVisible() is True
        assert label.text() == HINT_MISSING_NAME


class TestExportSanitizerSingleSource:
    """Sprint 60 / D.5 (Q-005): `_export_base.py` hat keinen eigenen `_sanitize`
    mehr – Widget-Preview und `ExcelExporter`-Writer teilen sich denselben
    Helfer (`config.sanitize_export_filename_token`), damit Preview == Datei
    garantiert ist (nicht nur zufällig)."""

    def test_export_base_module_has_no_local_sanitize(self) -> None:
        import sampling_tool.ui.dialogs._export_base as export_base

        assert not hasattr(export_base, "_sanitize")

    def test_widget_preview_matches_writer_for_tricky_tokens(self, qtbot: QtBot) -> None:
        from sampling_tool.io.exporter import ExcelExporter

        for name, id_ in [("Müller & Co", "1"), ("a/b:c*d", "2"), ("X" * 150, "3")]:
            w = ExportTargetWidget(
                default_name=name, default_id=id_, file_extension=".xlsx", type_token="sampling"
            )
            qtbot.addWidget(w)
            assert w.preview_filename() == ExcelExporter._build_filename(name, id_)
