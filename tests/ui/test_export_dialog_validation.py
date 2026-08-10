"""Sprint 72: die harte Invariante über ALLE Export-Dialoge.

**OK ist genau dann aktiv, wenn der Hinweistext leer ist.**

Sprint 71 hat den stummen OK-Button für Name/ID/Zielordner beseitigt, aber
drei der vier Dialoge hängen ihr Enablement zusätzlich an eine Auswahl, die
`ExportTargetWidget.validation_hint()` gar nicht sehen kann – alles abwählen
machte den Button grau und ließ das Hinweis-Label leer. Statt diese Bugklasse
Dialog für Dialog zu jagen, macht diese Suite sie strukturell unmöglich: die
Matrix läuft über alle Dialoge und alle Zustandskombinationen.

Ein fünfter Export-Dialog wird automatisch mitgeprüft, sobald er in
`DIALOG_SPECS` steht – bewusst eine Liste von Fabriken statt vier kopierter
Blöcke.
"""

from __future__ import annotations

import ast
import importlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QAbstractButton, QDialogButtonBox, QLabel
from pytestqt.qtbot import QtBot

from sampling_tool.core.models import Dataset, Engagement
from sampling_tool.ui.dialogs._export_base import (
    HINT_MISSING_NAME,
    HINT_NO_COLUMNS,
    HINT_NO_EVENT_TYPES,
    HINT_NO_SHEETS,
)
from sampling_tool.ui.dialogs.export_audit_pdf_dialog import ExportAuditPdfDialog
from sampling_tool.ui.dialogs.export_excel_report_dialog import ExportExcelReportDialog
from sampling_tool.ui.dialogs.export_html_report_dialog import ExportHtmlReportDialog
from sampling_tool.ui.dialogs.export_sample_dialog import ExportSampleDialog

pytestmark = pytest.mark.ui

# Die gemeinsame Naht aller Export-Dialoge: `_target`, `_buttons` und
# `_selection_hint()`. Als Union statt Protocol, damit `qtbot.addWidget`
# weiterhin ein echtes QWidget sieht und mypy die Attribute auflösen kann.
AnyExportDialog = (
    ExportSampleDialog | ExportAuditPdfDialog | ExportExcelReportDialog | ExportHtmlReportDialog
)


# ---------------------------------------------------------------------------
# Dialog-Fabriken – hier trägt sich ein fünfter Dialog ein und läuft überall mit
# ---------------------------------------------------------------------------


def _engagement() -> Engagement:
    return Engagement(
        auditor_name="Anna",
        client_name="ACME GmbH",
        auditor_position="Senior",
        audit_type="ISAE 3402",
        id=1,
    )


def _dataset() -> Dataset:
    return Dataset(name="Buchungen", columns=("Konto", "Betrag", "Datum"), row_count=1)


def _build_sample(output_dir: Path | None) -> AnyExportDialog:
    return ExportSampleDialog(
        _dataset(), default_name="ACME", default_id="1", default_output_dir=output_dir
    )


def _build_audit_pdf(output_dir: Path | None) -> AnyExportDialog:
    return ExportAuditPdfDialog(
        engagement=_engagement(),
        event_types_available=["sampling", "import"],
        briefpapier_available=True,
        default_output_dir=output_dir,
    )


def _build_excel_report(output_dir: Path | None) -> AnyExportDialog:
    return ExportExcelReportDialog(_engagement(), default_output_dir=output_dir)


def _build_html_report(output_dir: Path | None) -> AnyExportDialog:
    return ExportHtmlReportDialog(_engagement(), default_output_dir=output_dir)


def _select_sample(dialog: AnyExportDialog, checked: bool) -> None:
    assert isinstance(dialog, ExportSampleDialog)
    dialog._set_all_checked(checked)


def _select_audit_pdf(dialog: AnyExportDialog, checked: bool) -> None:
    assert isinstance(dialog, ExportAuditPdfDialog)
    dialog._set_all_types(checked)


def _select_excel_report(dialog: AnyExportDialog, checked: bool) -> None:
    assert isinstance(dialog, ExportExcelReportDialog)
    dialog._set_all_sheets(checked)


def _select_html_report(dialog: AnyExportDialog, checked: bool) -> None:
    """Der HTML-Dialog hat keine Auswahl-Bedingung – bewusst ein No-Op."""
    assert isinstance(dialog, ExportHtmlReportDialog)


@dataclass(frozen=True, slots=True)
class DialogSpec:
    """Ein Export-Dialog, wie ihn die Matrix ansteuert."""

    label: str
    module: str
    build: Callable[[Path | None], AnyExportDialog]
    set_selection: Callable[[AnyExportDialog, bool], None]
    # Hinweis, der bei leerer Auswahl erwartet wird ("" = Dialog kennt keine).
    hint_when_selection_empty: str


DIALOG_SPECS: tuple[DialogSpec, ...] = (
    DialogSpec("sample", "export_sample_dialog", _build_sample, _select_sample, HINT_NO_COLUMNS),
    DialogSpec(
        "audit_pdf",
        "export_audit_pdf_dialog",
        _build_audit_pdf,
        _select_audit_pdf,
        HINT_NO_EVENT_TYPES,
    ),
    DialogSpec(
        "excel_report",
        "export_excel_report_dialog",
        _build_excel_report,
        _select_excel_report,
        HINT_NO_SHEETS,
    ),
    DialogSpec(
        "html_report", "export_html_report_dialog", _build_html_report, _select_html_report, ""
    ),
)


# ---------------------------------------------------------------------------
# Zustands-Matrix
# ---------------------------------------------------------------------------

_NAMES: tuple[str, ...] = ("ACME", "")
_IDS: tuple[str, ...] = ("1", "")
_SELECTIONS: tuple[bool, ...] = (True, False)

# (Name) × (ID) × (Zielordner) × (Auswahl)
MATRIX_SIZE = len(_NAMES) * len(_IDS) * 3 * len(_SELECTIONS)


@dataclass(frozen=True, slots=True)
class State:
    """Ein Punkt der Matrix – `label` macht Fehlermeldungen lesbar."""

    name: str
    id_: str
    dir_label: str
    directory: Path | None
    selection: bool

    @property
    def label(self) -> str:
        return (
            f"name={self.name!r} id={self.id_!r} "
            f"dir={self.dir_label} auswahl={'voll' if self.selection else 'leer'}"
        )


def _states(tmp_path: Path) -> Iterator[State]:
    """Alle Zustandskombinationen. Zielordner-Varianten: existent, nicht
    existent, keiner – gegen `tmp_path` statt POSIX-Literalen gebaut."""
    existing = tmp_path / "da"
    existing.mkdir(exist_ok=True)
    directories: tuple[tuple[str, Path | None], ...] = (
        ("existiert", existing),
        ("fehlt", tmp_path / "weg"),
        ("keiner", None),
    )
    for name in _NAMES:
        for id_ in _IDS:
            for dir_label, directory in directories:
                for selection in _SELECTIONS:
                    yield State(name, id_, dir_label, directory, selection)


def _dialog_in_state(spec: DialogSpec, qtbot: QtBot, state: State) -> AnyExportDialog:
    dialog = spec.build(state.directory)
    qtbot.addWidget(dialog)
    dialog._target._name_field.setText(state.name)
    dialog._target._id_field.setText(state.id_)
    spec.set_selection(dialog, state.selection)
    return dialog


def _ok_button(dialog: AnyExportDialog) -> QAbstractButton:
    button = dialog._buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert button is not None
    return button


def _hint_label(dialog: AnyExportDialog) -> QLabel:
    label = dialog._target.findChild(QLabel, "exportTargetHint")
    assert label is not None
    return label


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", DIALOG_SPECS, ids=lambda s: s.label)
class TestOkMatchesHintInvariant:
    """Über jeden Dialog und jeden Zustand: Button und Hinweis erzählen dasselbe."""

    def test_ok_enabled_iff_hint_empty(
        self, spec: DialogSpec, qtbot: QtBot, tmp_path: Path
    ) -> None:
        checked = 0
        for state in _states(tmp_path):
            dialog = _dialog_in_state(spec, qtbot, state)
            hint = _hint_label(dialog).text()
            enabled = _ok_button(dialog).isEnabled()
            assert enabled == (hint == ""), (
                f"[{spec.label}] OK und Hinweis laufen auseinander bei {state.label}: "
                f"enabled={enabled} hinweis={hint!r}"
            )
            checked += 1
        assert checked == MATRIX_SIZE

    def test_hint_label_visible_iff_hint_nonempty(
        self, spec: DialogSpec, qtbot: QtBot, tmp_path: Path
    ) -> None:
        checked = 0
        for state in _states(tmp_path):
            dialog = _dialog_in_state(spec, qtbot, state)
            dialog.show()
            label = _hint_label(dialog)
            assert label.isVisible() == bool(label.text()), (
                f"[{spec.label}] Sichtbarkeit passt nicht zum Text bei {state.label}: "
                f"visible={label.isVisible()} text={label.text()!r}"
            )
            dialog.close()
            checked += 1
        assert checked == MATRIX_SIZE

    def test_target_validation_takes_precedence_over_selection(
        self, spec: DialogSpec, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Sind Name UND Auswahl ungültig, gewinnt der Ziel-Hinweis.

        Definierte Reihenfolge (§2.1) – ohne sie wäre der angezeigte Text
        davon abhängig, welcher Prüfzweig zufällig zuerst läuft.
        """
        dialog = _dialog_in_state(
            spec,
            qtbot,
            State("", "1", "existiert", tmp_path, selection=False),
        )
        assert _hint_label(dialog).text() == HINT_MISSING_NAME
        assert _ok_button(dialog).isEnabled() is False

    def test_selection_hint_shown_when_only_selection_invalid(
        self, spec: DialogSpec, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Ist das Ziel in Ordnung und nur die Auswahl leer, steht genau der
        dialogspezifische Grund da – der HTML-Dialog bleibt erwartungsgemäß
        hinweisfrei."""
        dialog = _dialog_in_state(
            spec,
            qtbot,
            State("ACME", "1", "existiert", tmp_path, selection=False),
        )
        assert _hint_label(dialog).text() == spec.hint_when_selection_empty
        assert _ok_button(dialog).isEnabled() is (spec.hint_when_selection_empty == "")


class TestEveryDialogIsCovered:
    """Schutz gegen den stillsten Fehler dieser Suite: ein neuer Export-Dialog
    wird gebaut, aber nicht in `DIALOG_SPECS` eingetragen – dann liefe die
    Matrix grün, ohne ihn je anzufassen."""

    def test_all_export_dialog_modules_appear_in_specs(self, qtbot: QtBot) -> None:
        import sampling_tool.ui.dialogs as dialogs_pkg

        modules = {
            path.stem for path in Path(dialogs_pkg.__file__).parent.glob("export_*_dialog.py")
        }
        covered: set[str] = set()
        for spec in DIALOG_SPECS:
            dialog = spec.build(None)
            qtbot.addWidget(dialog)
            actual = type(dialog).__module__.rsplit(".", 1)[-1]
            # Das `module`-Feld muss zum wirklich gebauten Dialog passen, sonst
            # prüft die AST-Suite unten die falsche Datei.
            assert spec.module == actual, f"{spec.label}: module={spec.module!r} != {actual!r}"
            covered.add(actual)
        assert modules == covered, (
            f"Nicht abgedeckte Export-Dialoge: {sorted(modules - covered)} – "
            "bitte in DIALOG_SPECS eintragen."
        )


class TestSingleWiringPoint:
    """Sprint 72 / §2.2: `apply_validation` ist der EINZIGE Ort, an dem
    Hinweistext und OK-Enablement gesetzt werden.

    Das ist der eigentliche Grund, warum diese Bugklasse nicht wiederkommt:
    solange kein Dialog selbst `setEnabled` ruft, KÖNNEN Button und Hinweis
    nicht auseinanderlaufen. Strukturell über den AST geprüft statt per grep –
    ein Kommentar oder ein Vorkommen in einer anderen Methode (z. B.
    `_cb_briefpapier.setEnabled(False)` im PDF-Dialog, völlig legitim) soll
    das Gate weder falsch-rot noch falsch-grün machen.
    """

    def _update_state_body(self, module_name: str) -> ast.FunctionDef:
        module = importlib.import_module(f"sampling_tool.ui.dialogs.{module_name}")
        assert module.__file__ is not None
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_update_state":
                return node
        raise AssertionError(f"{module_name} hat kein _update_state")

    @pytest.mark.parametrize("spec", DIALOG_SPECS, ids=lambda s: s.label)
    def test_update_state_delegates_to_apply_validation(self, spec: DialogSpec) -> None:
        node = self._update_state_body(spec.module)
        called = {
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        assert "apply_validation" in called, (
            f"[{spec.label}] _update_state ruft nicht apply_validation – "
            "damit gibt es wieder einen zweiten Prüfpfad."
        )

    @pytest.mark.parametrize("spec", DIALOG_SPECS, ids=lambda s: s.label)
    def test_update_state_never_calls_set_enabled_itself(self, spec: DialogSpec) -> None:
        node = self._update_state_body(spec.module)
        offenders = [
            child.func.attr
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "setEnabled"
        ]
        assert offenders == [], (
            f"[{spec.label}] _update_state ruft selbst setEnabled – das ist genau "
            "der zweite Pfad, den Sprint 72 beseitigt hat."
        )
