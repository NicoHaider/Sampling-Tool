"""Tests für `ExportTargetWidget` – Vorschau-Label, Validierung, Path-Bau."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Final

import pytest
from PyQt6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from sampling_tool.config import (
    EXPORT_FILENAME_PATTERN,
    EXPORT_SUFFIX_SAMPLING,
    EXPORT_TYPE_SAMPLING,
    export_date_token,
    local_export_now,
)
from sampling_tool.ui.dialogs._export_base import (
    HINT_MISSING_ID,
    HINT_MISSING_NAME,
    HINT_NO_DIR,
    ExportTargetWidget,
    hint_missing_dir,
)

pytestmark = pytest.mark.ui

# Ein Anker pro Testdatei (Sprint 74 / §4.4), alle weiteren Zeitpunkte werden
# per timedelta abgeleitet – kein zweites Datums-Literal daneben.
FROZEN_NOW: Final = datetime(2026, 5, 13, 23, 59)

# Europe/Vienna im Sommer als FESTER Offset statt `ZoneInfo("Europe/Vienna")`:
# Windows liefert ohne das `tzdata`-Paket keine IANA-Zonen, und der Test soll
# auf allen drei CI-Betriebssystemen identisch laufen.
LOCAL_OFFSET: Final = timezone(timedelta(hours=2))


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

        # Sprint 74: BEIDE Seiten bekommen denselben Zeitpunkt übergeben.
        # Vorher standen hier zwei unabhängige `datetime.now()`-Lesungen in
        # einer Assertion – um Mitternacht flaky (§4.5).
        for name, id_ in [("Müller & Co", "1"), ("a/b:c*d", "2"), ("X" * 150, "3")]:
            w = ExportTargetWidget(
                default_name=name,
                default_id=id_,
                file_extension=EXPORT_SUFFIX_SAMPLING,
                type_token=EXPORT_TYPE_SAMPLING,
                now_provider=lambda: FROZEN_NOW,
            )
            qtbot.addWidget(w)
            assert w.preview_filename() == ExcelExporter._build_filename(name, id_, w.now())


def _ticking_provider(start: datetime = FROZEN_NOW) -> Callable[[], datetime]:
    """Uhr, die bei JEDEM Aufruf einen Tag weiterspringt.

    Simuliert den Tageswechsel zwischen Dialog-Öffnen und OK-Klick. Wer die
    Uhr mehr als einmal liest, bekommt garantiert ein anderes Datum – genau
    das macht Befund B sichtbar, statt auf eine echte Mitternacht zu warten.
    """
    ticks = iter(range(1_000))

    def provider() -> datetime:
        return start + timedelta(days=next(ticks))

    return provider


class TestPreviewMatchesWrittenName:
    """Sprint 74 / Befund B – der Kern des Sprints.

    Der Dateiname der geschriebenen Datei muss der Vorschau PER KONSTRUKTION
    entsprechen, nicht per Zufall. Vorher liefen zwei unabhängige Uhren
    (`_export_base.preview_filename` und `ExcelExporter._build_filename`),
    die nur so lange übereinstimmten, wie kein Tageswechsel dazwischenlag.
    """

    def test_preview_is_stable_when_the_day_rolls_over(self, qtbot: QtBot) -> None:
        """Die Vorschau darf die Uhr nicht bei jedem Aufruf neu lesen."""
        w = ExportTargetWidget(
            default_name="ACME",
            default_id="42",
            file_extension=EXPORT_SUFFIX_SAMPLING,
            type_token=EXPORT_TYPE_SAMPLING,
            now_provider=_ticking_provider(),
        )
        qtbot.addWidget(w)
        first = w.preview_filename()
        second = w.preview_filename()
        third = w.preview_filename()
        assert first == second == third, (
            "preview_filename() liest die Uhr mehrfach – zwischen zwei "
            "Aufrufen kann sich das Datum ändern."
        )

    def test_written_name_equals_preview_across_midnight(self, qtbot: QtBot) -> None:
        """Vorschau == der Name, den `ExcelExporter` tatsächlich baut."""
        from sampling_tool.io.exporter import ExcelExporter

        w = ExportTargetWidget(
            default_name="ACME",
            default_id="42",
            file_extension=EXPORT_SUFFIX_SAMPLING,
            type_token=EXPORT_TYPE_SAMPLING,
            now_provider=_ticking_provider(),
        )
        qtbot.addWidget(w)
        preview = w.preview_filename()
        # Der Controller reicht genau diesen Zeitpunkt an den Export-Task durch.
        written = ExcelExporter._build_filename(w.get_name(), w.get_id(), w.now())
        assert written == preview

    def test_get_path_uses_the_same_clock_reading_as_the_label(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Die drei Report-Dialoge schreiben nach `get_path()` – der Pfad muss
        dem angezeigten Label entsprechen, auch wenn dazwischen ein Tag
        vergeht."""
        w = ExportTargetWidget(
            default_name="ACME",
            default_id="7",
            file_extension=".pdf",
            type_token="audit_trail",
            now_provider=_ticking_provider(),
        )
        qtbot.addWidget(w)
        w.set_output_dir(tmp_path)
        label = w.findChild(QLabel, "exportTargetPreview")
        assert label is not None
        path = w.get_path()
        assert path is not None
        assert path.name == label.text()

    def test_default_id_and_date_token_share_one_reading(self, qtbot: QtBot) -> None:
        """Sprint 74: `default_id` der drei Report-Dialoge ist dasselbe Datum
        wie der `{date}`-Token – vorher zwei unabhängige Uhren, die im selben
        Dateinamen zwei verschiedene Tage stehen lassen konnten."""
        from sampling_tool.core.models import Engagement
        from sampling_tool.ui.dialogs.export_html_report_dialog import ExportHtmlReportDialog

        engagement = Engagement(auditor_name="Anna", client_name="ACME", id=1)
        dialog = ExportHtmlReportDialog(engagement, now_provider=_ticking_provider())
        qtbot.addWidget(dialog)
        name = dialog._target.preview_filename()
        token = export_date_token(dialog._target.now())
        assert name.count(token) == 2, (
            f"ID- und Datums-Token müssen aus derselben Uhr stammen: {name!r}"
        )


class TestDateTokenSemantics:
    """Sprint 74 / §2.4 – 🔒 der `{date}`-Token bleibt LOKALZEIT."""

    def test_date_token_uses_local_time_not_utc(self) -> None:
        """Ein Prüfer erwartet den Tag, an dem ER exportiert hat.

        Auf UTC umzustellen sähe wie eine Verbesserung aus, würde aber in
        Europe/Vienna (UTC+2) kurz nach Mitternacht den VORTAG in den
        Dateinamen schreiben. Der Anker trägt hier bewusst einen expliziten
        Offset, damit der Test auf Ubuntu/Windows/macOS identisch urteilt.
        """
        just_after_midnight_local = datetime(2026, 5, 14, 0, 30, tzinfo=LOCAL_OFFSET)

        # Vorbedingung: derselbe Moment ist in UTC noch der Vortag. Ohne diese
        # Zusicherung könnte der Test grün sein, ohne etwas zu unterscheiden.
        assert just_after_midnight_local.astimezone(UTC).date() == date(2026, 5, 13)

        assert export_date_token(just_after_midnight_local) == "20260514", (
            "Der Datums-Token folgt der LOKALEN Kalendergrenze (§2.4). "
            "Ein Wechsel auf UTC würde hier 20260513 liefern."
        )

    def test_default_clock_is_naive_local_wall_time(self) -> None:
        """Die Default-Uhr ist `datetime.now()` ohne tz – kein `now(UTC)`.

        Bewusst KEIN Vergleich zweier unabhängiger Uhr-Lesungen auf Gleichheit
        (Sprint-73-Lehre, §4.5): geprüft wird die Einklammerung und die
        Naivität des Werts.
        """
        before = datetime.now()
        value = local_export_now()
        after = datetime.now()
        assert value.tzinfo is None, "UTC-Umstellung erkannt – §2.4 verletzt."
        assert before <= value <= after

    def test_widget_default_provider_is_the_shared_local_clock(self, qtbot: QtBot) -> None:
        """Ohne `now_provider` hängt das Widget an der gemeinsamen Modul-Uhr."""
        w = ExportTargetWidget(default_name="ACME", default_id="1", file_extension=".pdf")
        qtbot.addWidget(w)
        assert w.now_provider() is local_export_now


class TestFilenamePatternIsSingleSource:
    """Sprint 74 / §2.3 – das Pattern lebt in `config.py`, sonst nirgends."""

    def test_export_base_has_no_own_pattern_literal(self) -> None:
        import sampling_tool.ui.dialogs._export_base as export_base

        assert export_base.DEFAULT_FILENAME_PATTERN is EXPORT_FILENAME_PATTERN

    def test_exporter_has_no_own_template_literal(self) -> None:
        import sampling_tool.io.exporter as exporter_module

        assert not hasattr(exporter_module, "_FILENAME_TEMPLATE")

    def test_pattern_renders_the_documented_scheme(self) -> None:
        """Zeichengleichheit zum Bestandsverhalten (§6), gegen die Konstante
        formatiert statt gegen ein wiederholtes Literal."""
        body = EXPORT_FILENAME_PATTERN.format(
            name="ACME", id="42", type=EXPORT_TYPE_SAMPLING, date="20260513"
        )
        assert f"{body}{EXPORT_SUFFIX_SAMPLING}" == "ACME_ID42_BDO_sampling_20260513.xlsx"
