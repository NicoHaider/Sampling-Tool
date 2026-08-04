"""MainWindow – State-Maschine Welcome ↔ Workspace + Menu-Enablement."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PyQt6.QtCore import QRect, QSettings, QSize, Qt
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication, QLabel, QWidget
from pytestqt.qtbot import QtBot

from sampling_tool.config import APP_NAME, APP_ORG
from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    Engagement,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.persistence.database import Database
from sampling_tool.persistence.repositories import DatasetRepo, EngagementRepo
from sampling_tool.resources import package_resource
from sampling_tool.ui._geometry import fit_to_available
from sampling_tool.ui._scaling import load_scaled_stylesheet
from sampling_tool.ui._window_state import _DESIRED_HEIGHT, _DESIRED_WIDTH, _int_or_none
from sampling_tool.ui.main_window import MainWindow
from sampling_tool.ui.recent import RecentEntry

pytestmark = pytest.mark.ui


def _engagement() -> Engagement:
    return Engagement(
        auditor_name="Anna",
        auditor_position="Senior",
        client_name="ACME",
        audit_type="ISAE 3402",
        id=1,
    )


@pytest.fixture
def dataset_with_repo(tmp_path: Path) -> Iterator[tuple[Dataset, DatasetRepo]]:
    """Persistiert ein 3-Zeilen-Dataset und liefert (Dataset, Repo).

    Sprint-11.2: `MainWindow.show_dataset` braucht ein Repo statt rows.
    """
    db = Database(tmp_path / "mw.db")
    db.migrate()
    eng = EngagementRepo(db.connect()).get_or_create(
        Engagement(auditor_name="A", client_name="C", auditor_position="S", audit_type="ISAE 3402")
    )
    assert eng.id is not None
    repo = DatasetRepo(db.connect())
    rows = tuple(
        DatasetRow(row_id=i, values={"Konto": f"K{i}", "Betrag": i * 10}) for i in range(1, 4)
    )
    dataset = repo.create(
        Dataset(name="Buchungen", columns=("Konto", "Betrag"), engagement_id=eng.id),
        rows,
    )
    try:
        yield dataset, repo
    finally:
        db.close()


def _sample() -> SampleResult:
    return SampleResult(
        config=SampleConfig(method=SamplingMethod.SIMPLE, size=2, seed=42),
        selected_row_ids=(1, 3),
        population_size=3,
        id=1,
    )


class TestMainWindowState:
    def test_initial_state_is_welcome(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        assert win.is_workspace_visible() is False

    def test_show_workspace_switches_state(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        assert win.is_workspace_visible() is True
        assert win._action_close.isEnabled() is True
        assert win._action_import.isEnabled() is True

    def test_show_welcome_disables_workspace_actions(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.show_welcome()
        assert win._action_close.isEnabled() is False
        assert win._action_import.isEnabled() is False

    def test_show_dataset_enables_sampling(
        self, qtbot: QtBot, dataset_with_repo: tuple[Dataset, DatasetRepo]
    ) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.show_dataset(*dataset_with_repo)
        assert win._action_new_sample.isEnabled() is True
        assert win.data_table().table_model().rowCount() == 3

    def test_highlight_sample_enables_export(
        self, qtbot: QtBot, dataset_with_repo: tuple[Dataset, DatasetRepo]
    ) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.show_dataset(*dataset_with_repo)
        win.highlight_sample(_sample())
        assert win._action_export_sample.isEnabled() is True
        assert 1 in win.data_table().table_model().highlighted_row_ids()

    def test_set_recent_entries_builds_menu(self, qtbot: QtBot, tmp_path: Path) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        db_path = tmp_path / "x.db"
        db_path.write_text("")
        entry = RecentEntry(
            path=db_path,
            client_name="ACME",
            audit_type="ISAE 3402",
            last_opened=datetime.now(UTC),
            opened_count=1,
        )
        win.set_recent_entries([entry])
        assert win._recent_menu.isEnabled() is True
        assert len(win._recent_menu.actions()) == 1
        assert win.welcome_screen().recent_card_count() == 1

    def test_set_engagement_updates_sidebar_and_status(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.set_engagement(_engagement())
        assert win._status_engagement.text() == "ACME"

    def test_active_sample_status_label_filled(
        self, qtbot: QtBot, dataset_with_repo: tuple[Dataset, DatasetRepo]
    ) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.show_dataset(*dataset_with_repo)
        win.set_samples([_sample()])
        win.highlight_sample(_sample())
        text = win._status_sample.text()
        assert "Aktive Stichprobe" in text
        assert "#1" in text
        assert "Einfach" in text
        assert "2/3" in text

    def test_active_sample_status_label_empty_when_cleared(
        self, qtbot: QtBot, dataset_with_repo: tuple[Dataset, DatasetRepo]
    ) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.show_dataset(*dataset_with_repo)
        win.set_samples([_sample()])
        win.highlight_sample(_sample())
        win.clear_active_sample()
        assert win._status_sample.text() == "Aktive Stichprobe: keine"

    def test_active_sample_status_label_filtered_suffix(
        self, qtbot: QtBot, dataset_with_repo: tuple[Dataset, DatasetRepo]
    ) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.show_dataset(*dataset_with_repo)
        win.set_samples([_sample()])
        win.highlight_sample(_sample(), filtered=True)
        assert "– gefiltert" in win._status_sample.text()

    def test_active_sample_status_label_no_suffix_when_not_filtered(
        self, qtbot: QtBot, dataset_with_repo: tuple[Dataset, DatasetRepo]
    ) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()
        win.show_dataset(*dataset_with_repo)
        win.set_samples([_sample()])
        win.highlight_sample(_sample(), filtered=False)
        assert "gefiltert" not in win._status_sample.text()


class TestSwitchEngagementToolbar:
    """Sprint 5.6: neuer Toolbar-Button 'Projekt wechseln' (Sprint 27 umbenannt)."""

    def test_toolbar_action_exists(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        assert hasattr(win, "_action_switch_engagement")
        assert win._action_switch_engagement.text() == "Projekt wechseln"

    def test_toolbar_action_emits_close_signal(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        with qtbot.waitSignal(win.close_engagement_requested, timeout=500):
            win._action_switch_engagement.trigger()

    def test_close_action_in_file_menu_emits_close_signal(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show_workspace()  # Aktion ist nur enabled, wenn Workspace sichtbar.
        with qtbot.waitSignal(win.close_engagement_requested, timeout=500):
            win._action_close.trigger()


class TestSettingsAction:
    """Sprint 9.6: Einstellungen-Menüpunkt sichtbar im Datei-Menü."""

    def test_settings_action_im_datei_menue(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        assert win._action_settings in win._file_menu.actions()

    def test_settings_action_hat_preferences_role(self, qtbot: QtBot) -> None:
        from PyQt6.QtGui import QAction

        win = MainWindow()
        qtbot.addWidget(win)
        assert win._action_settings.menuRole() == QAction.MenuRole.PreferencesRole

    def test_settings_action_hat_preferences_shortcut(self, qtbot: QtBot) -> None:
        from PyQt6.QtGui import QKeySequence

        win = MainWindow()
        qtbot.addWidget(win)
        expected = QKeySequence(QKeySequence.StandardKey.Preferences)
        assert win._action_settings.shortcut() == expected

    def test_settings_action_emittiert_settings_signal(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        with qtbot.waitSignal(win.settings_requested, timeout=500):
            win._action_settings.trigger()


class TestSettingsToolbarButton:
    """Sprint 9.7: Einstellungen zusätzlich als Toolbar-Button."""

    def test_toolbar_enthaelt_settings_action(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        assert win._action_settings in win._toolbar.actions()

    def test_menue_und_toolbar_teilen_dieselbe_settings_action(self, qtbot: QtBot) -> None:
        # Identitäts-Check: dieselbe QAction-Instanz in Menü + Toolbar.
        win = MainWindow()
        qtbot.addWidget(win)
        assert win._action_settings in win._file_menu.actions()
        assert win._action_settings in win._toolbar.actions()

    def test_settings_action_hat_icon(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        assert not win._action_settings.icon().isNull()

    def test_settings_steht_in_toolbar_vor_bug_report(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        actions = win._toolbar.actions()
        settings_idx = actions.index(win._action_settings)
        bug_report_idx = actions.index(win._action_bug_report)
        assert settings_idx < bug_report_idx

    def test_settings_tooltip_enthaelt_shortcut(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        tooltip = win._action_settings.toolTip()
        assert "Einstellungen" in tooltip
        # Tooltip soll die plattformnative Shortcut-Repräsentation
        # enthalten – Format ist OS-abhängig (Mac "⌘,", Win "Ctrl+,",
        # offscreen-Plattform liefert "Settings"). Sanity: Klammer-Suffix
        # ist vorhanden, also wurde der Shortcut-Text angehängt.
        assert "(" in tooltip
        assert ")" in tooltip


class TestBugReportToolbarButton:
    """Sprint 9.2: Bug-Report jetzt zusätzlich rechtsbündig in der Toolbar."""

    def test_toolbar_enthaelt_bug_report_action(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        assert win._action_bug_report in win._toolbar.actions()

    def test_menue_und_toolbar_teilen_dieselbe_action(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        # Identitäts-Check: dieselbe QAction-Instanz in Menü + Toolbar.
        assert win._action_bug_report in win._help_menu.actions()
        assert win._action_bug_report in win._toolbar.actions()

    def test_toolbar_button_emittiert_bug_report_signal(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        with qtbot.waitSignal(win.bug_report_requested, timeout=500):
            win._action_bug_report.trigger()


class TestToolbarCompactOverflow:
    """Sprint 27: kompaktere Toolbar + Überlauf-Erreichbarkeit."""

    def test_toolbar_is_qtoolbar(self, qtbot: QtBot) -> None:
        # Eine echte QToolBar (kein Custom-Widget-Layout) → automatischer
        # Überlauf-/„»"-Extension-Button bei schmalem Fenster ist gegeben.
        from PyQt6.QtWidgets import QToolBar

        win = MainWindow()
        qtbot.addWidget(win)
        assert isinstance(win._toolbar, QToolBar)

    def test_toolbar_icons_are_compact(self, qtbot: QtBot) -> None:
        from sampling_tool.ui._window_toolbar import _TOOLBAR_ICON_SIZE

        win = MainWindow()
        qtbot.addWidget(win)
        assert win._toolbar.iconSize() == QSize(_TOOLBAR_ICON_SIZE, _TOOLBAR_ICON_SIZE)

    def test_all_main_actions_registered_in_toolbar(self, qtbot: QtBot) -> None:
        # Alle Haupt-Aktionen sind als QToolBar-Actions registriert und damit
        # auch bei Überlauf über das „»"-Menü erreichbar.
        win = MainWindow()
        qtbot.addWidget(win)
        actions = win._toolbar.actions()
        for attr in (
            "_action_switch_engagement",
            "_action_new",
            "_action_open",
            "_action_import",
            "_action_new_sample",
            "_action_reset_sampling",
            "_action_undo",
            "_action_redo",
            "_action_export_sample",
            "_action_export_pdf",
            "_action_excel_report",
            "_action_html_report",
            "_action_settings",
            "_action_bug_report",
        ):
            assert getattr(win, attr) in actions, f"{attr} fehlt in der Toolbar"

    def test_bug_report_action_hat_tooltip_und_icon(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        action = win._action_bug_report
        assert action.toolTip() == "Fehler melden oder Feedback senden"
        assert not action.icon().isNull()


class TestToolbarSpacerTransparent:
    """Sprint 69/6: Expanding-Spacer zwischen Haupt- und Settings-/Bug-Report-
    Aktionen zeigte einen weißen Block (generische QWidget-Regel malte ihn
    weiß über den etwas dunkleren Toolbar-Hintergrund)."""

    def test_toolbar_spacer_is_transparent(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)

        # Der Spacer ist das einzige per addWidget() eingefügte, nicht als
        # Separator markierte bare-QWidget in der Toolbar (Separatoren sind
        # ebenfalls QWidget-Instanzen, aber mit isSeparator()==True).
        spacer = next(
            widget
            for action in win._toolbar.actions()
            if not action.isSeparator()
            and type(widget := win._toolbar.widgetForAction(action)) is QWidget
        )
        assert spacer.objectName() != ""

        qss = package_resource("ui/styles/bdo_light.qss").read_text(encoding="utf-8")
        rule = re.search(rf"QWidget#{re.escape(spacer.objectName())}\s*\{{([^}}]*)\}}", qss)
        assert rule is not None, "erwarte eine QSS-Regel für den Spacer-Objektnamen"
        assert re.search(r"background(-color)?:\s*transparent", rule.group(1))


class TestToolbarChromeNotWhite:
    """Sprint 71 / Befund 2: weisses Chrome in der Toolbar.

    `TestToolbarSpacerTransparent` (Sprint 69/6) hat Separatoren per
    `if not action.isSeparator()` EXPLIZIT ausgeschlossen – genau diese
    Luecke schliesst diese Klasse.

    Messung statt QSS-Kaskaden-Argumentation: das echte Stylesheet wird
    global gesetzt, die Toolbar gerendert und Pixel gelesen.

    Zwei Fallen, die bei der Erstellung dieser Tests aufgefallen sind und
    beide zu still-gruenen Gates gefuehrt haetten:

    1. Der weisse Separator-Streifen liegt NICHT auf dem geometrischen
       Mittelpunkt des `actionGeometry`-Rechtecks, sondern zwei Pixel
       daneben (Qt zeichnet eine geaetzte Linie: `#E8E8E8` bei +4,
       `#FFFFFF` bei +5 eines 8px breiten Rechtecks). Ein Mittelpunkt-
       Pixel-Test liest `#F8F8F8` und ist faelschlich gruen – deshalb
       wird hier das GESAMTE Rechteck gescannt.
    2. Der Ueberlauf-Button heisst in PyQt6 nicht `QToolBarExtension`;
       `type(child).__name__` liefert `QToolButton`. Gesucht wird er
       daher ueber seinen Qt-internen objectName `qt_toolbar_ext_button`.
    """

    WHITE = (255, 255, 255)

    @pytest.fixture(autouse=True)
    def _isolated_qsettings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Diese Tests bauen echte MainWindows und veraendern deren Groesse;
        `closeEvent` -> `_window_state.save()` wuerde die Testgeometrie sonst
        in die echten Prefs schreiben. Gleiches Muster wie
        `TestWindowGeometryFitsScreen._isolated_qsettings`.
        """
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        monkeypatch.setattr(
            "sampling_tool.ui.main_window.QSettings",
            lambda organization, application: QSettings(
                QSettings.Format.IniFormat, QSettings.Scope.UserScope, organization, application
            ),
        )

    # Ein weisser HINTERGRUND bedeckt den ueberwiegenden Teil eines Widgets
    # (vor dem Fix: 67-100 % der Flaeche). Vereinzelte weisse Pixel stammen
    # aus Glyph-Antialiasing oder Stil-Dekorationen und sind plattform-
    # abhaengig – deshalb ein Flaechenanteil statt "kein einziges Pixel".
    MAX_WHITE_AREA_FRACTION = 0.10

    @staticmethod
    def _rgb(image: QImage, x: int, y: int) -> tuple[int, int, int]:
        colour = image.pixelColor(x, y)
        return (colour.red(), colour.green(), colour.blue())

    @staticmethod
    def _rect_inside(rect: QRect, image: QImage) -> bool:
        return (
            rect.width() > 0
            and rect.height() > 0
            and rect.x() >= 0
            and rect.y() >= 0
            and rect.x() + rect.width() <= image.width()
            and rect.y() + rect.height() <= image.height()
        )

    def _white_fraction(self, image: QImage, rect: QRect) -> float:
        """Anteil reinweisser Pixel im Bereich `rect` des Eltern-Bildes.

        Bewusst aus dem KOMPOSITIERTEN Eltern-Bild gelesen: ein
        `widget.grab()` auf ein Widget mit `background: transparent` malt
        nichts und liefert einen uninitialisierten Backing-Store – auf
        Ubuntu weiss, auf macOS nicht. Das hat genau diesen Test einmal
        falsch rot werden lassen.
        """
        white = sum(
            1
            for x in range(rect.x(), rect.x() + rect.width())
            for y in range(rect.y(), rect.y() + rect.height())
            if self._rgb(image, x, y) == self.WHITE
        )
        return white / max(1, rect.width() * rect.height())

    def test_separator_pixels_are_not_white(self, qtbot: QtBot) -> None:
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        previous_stylesheet = app.styleSheet()
        app.setStyleSheet(load_scaled_stylesheet(1.0))
        try:
            win = MainWindow()
            qtbot.addWidget(win)
            win.show()
            qtbot.waitExposed(win)
            # Breit genug, damit alle fuenf Separatoren wirklich ausgelegt
            # sind (bei schmalem Fenster wandern sie ins Ueberlauf-Menue).
            win.resize(2400, 800)
            qtbot.wait(50)

            toolbar = win._toolbar
            image = toolbar.grab().toImage()
            measured = 0
            offenders: list[str] = []
            for action in toolbar.actions():
                if not action.isSeparator():
                    continue
                # `isVisible()` des Separator-Widgets ist das verlaessliche
                # Ausgelegt-Signal. `actionGeometry()` liefert fuer Items im
                # Ueberlauf-Menue das Sentinel-Rechteck QRect(0,0,100,30) –
                # das liegt INNERHALB des Toolbar-Bildes und deckte auf
                # Windows das weisse Haus-Icon des ersten Buttons ab
                # (14 Falsch-Treffer).
                separator = toolbar.widgetForAction(action)
                if separator is None or not separator.isVisible():
                    continue
                rect = separator.geometry()
                if not self._rect_inside(rect, image):
                    continue
                measured += 1
                for x in range(rect.x(), rect.x() + rect.width()):
                    for y in range(rect.y(), rect.y() + rect.height()):
                        if self._rgb(image, x, y) == self.WHITE:
                            offenders.append(f"({x},{y}) in {rect}")
                            break

            assert measured, "kein einziger Separator konnte gemessen werden"
            assert not offenders, (
                f"{len(offenders)} Separator-Pixel sind reinweiss (#FFFFFF) "
                f"statt der Toolbar-Flaeche: {offenders[:5]}"
            )
            qtbot.wait(50)
        finally:
            app.setStyleSheet(previous_stylesheet)

    def test_extension_button_is_not_white(self, qtbot: QtBot) -> None:
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        previous_stylesheet = app.styleSheet()
        app.setStyleSheet(load_scaled_stylesheet(1.0))
        try:
            win = MainWindow()
            qtbot.addWidget(win)
            win.show()
            qtbot.waitExposed(win)
            win.resize(700, 700)  # erzwingt den Ueberlauf
            qtbot.wait(50)

            toolbar = win._toolbar
            extension = None
            for child in toolbar.children():
                if not isinstance(child, QWidget):
                    continue
                if (
                    child.objectName() == "qt_toolbar_ext_button"
                    or type(child).__name__ == "QToolBarExtension"
                ):
                    extension = child
                    break
            if extension is None or not extension.isVisible():
                pytest.skip(
                    "Kein sichtbarer QToolBar-Ueberlauf-Button in dieser "
                    "Qt-/Style-Kombination – nichts zu messen."
                )

            image = toolbar.grab().toImage()
            rect = extension.geometry()
            if not self._rect_inside(rect, image):
                pytest.skip("Ueberlauf-Button liegt ausserhalb des Toolbar-Bildes.")
            fraction = self._white_fraction(image, rect)
            assert fraction <= self.MAX_WHITE_AREA_FRACTION, (
                f"Ueberlauf-Button ist zu {fraction:.0%} reinweiss – er faellt "
                "auf die generische QWidget-Regel zurueck."
            )
            qtbot.wait(50)
        finally:
            app.setStyleSheet(previous_stylesheet)

    def test_statusbar_separator_is_transparent(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        status = win.statusBar()
        assert status is not None
        separators = [lbl for lbl in status.findChildren(QLabel) if lbl.text() == "│"]
        assert separators, "keine Statusbar-Trennzeichen gefunden"
        for label in separators:
            assert "background: transparent" in label.styleSheet(), (
                "Statusbar-Separator ohne transparenten Hintergrund – die "
                f"generische QWidget-Regel malt ihn weiss: {label.styleSheet()!r}"
            )

    def test_statusbar_has_no_white_widgets(self, qtbot: QtBot) -> None:
        """Nicht nur die Trennzeichen: auch die vier Statusfelder und der
        QSizeGrip hatten keine eigene QSS-Regel und wurden von der
        generischen QWidget-Regel weiss gemalt (gemessen: 4374 bzw. 289
        weisse Pixel). Dieser Test misst die komplette Statusbar, statt –
        wie der Test darueber – nur einen Stylesheet-String zu pruefen.
        """
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        previous_stylesheet = app.styleSheet()
        app.setStyleSheet(load_scaled_stylesheet(1.0))
        try:
            win = MainWindow()
            qtbot.addWidget(win)
            win.show()
            qtbot.waitExposed(win)
            win.resize(2400, 800)
            qtbot.wait(50)

            status = win.statusBar()
            assert status is not None
            image = status.grab().toImage()
            measured = 0
            offenders: list[str] = []
            for child in status.children():
                if not isinstance(child, QWidget) or not child.isVisible():
                    continue
                rect = child.geometry()
                if not self._rect_inside(rect, image):
                    continue
                measured += 1
                fraction = self._white_fraction(image, rect)
                if fraction > self.MAX_WHITE_AREA_FRACTION:
                    label = child.text() if isinstance(child, QLabel) else ""
                    offenders.append(f"{type(child).__name__}({label!r}): {fraction:.0%}")

            assert measured, "kein Statusbar-Widget konnte gemessen werden"
            assert not offenders, (
                f"Statusbar-Widgets rendern reinweiss auf der #F4F4F4-Flaeche: {offenders}"
            )
            qtbot.wait(50)
        finally:
            app.setStyleSheet(previous_stylesheet)


class TestPanelVisibility:
    """Sprint 9.4: Dashboard- und AuditTrail-Tab via Settings togglebar."""

    def test_default_zeigt_beide_tabs(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        # Initial sind beide Tabs aktiv (Controller-Default).
        win.apply_panel_visibility(show_dashboard=True, show_audit_trail=True)
        assert win._lower_tabs.indexOf(win._dashboard_view) != -1
        assert win._lower_tabs.indexOf(win._audit_trail_view) != -1

    def test_nur_dashboard(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.apply_panel_visibility(show_dashboard=True, show_audit_trail=False)
        assert win._lower_tabs.indexOf(win._dashboard_view) != -1
        assert win._lower_tabs.indexOf(win._audit_trail_view) == -1

    def test_nur_audit_trail(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.apply_panel_visibility(show_dashboard=False, show_audit_trail=True)
        assert win._lower_tabs.indexOf(win._dashboard_view) == -1
        assert win._lower_tabs.indexOf(win._audit_trail_view) != -1

    def test_beide_aus_versteckt_tabwidget(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        win.apply_panel_visibility(show_dashboard=False, show_audit_trail=False)
        # `isVisible` ist False, weil das Widget explizit versteckt wurde.
        assert win._lower_tabs.isVisible() is False
        # Beide Tabs sind weg
        assert win._lower_tabs.count() == 0

    def test_beide_aus_cacht_splitter_sizes(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        # Aktuellen Splitter-Zustand merken.
        before = win._workspace_splitter.sizes()
        assert sum(before) > 0  # sanity: Splitter hat Größen
        win.apply_panel_visibility(show_dashboard=False, show_audit_trail=False)
        assert win._cached_splitter_sizes == before
        # Untere Hälfte ist auf 0 kollabiert, Datentabelle nutzt die volle Höhe.
        sizes_now = win._workspace_splitter.sizes()
        assert sizes_now[1] == 0
        assert sizes_now[0] == sum(before)

    def test_roundtrip_restored_splitter_sizes(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        before = win._workspace_splitter.sizes()
        win.apply_panel_visibility(show_dashboard=False, show_audit_trail=False)
        win.apply_panel_visibility(show_dashboard=True, show_audit_trail=True)
        assert win._cached_splitter_sizes is None
        assert win._workspace_splitter.sizes() == before

    def test_toggle_einzeln_aendert_splitter_nicht(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        before = win._workspace_splitter.sizes()
        win.apply_panel_visibility(show_dashboard=True, show_audit_trail=False)
        # Splitter bleibt unverändert, Cache leer (kein Collapse).
        assert win._cached_splitter_sizes is None
        assert win._workspace_splitter.sizes() == before

    def test_save_workspace_state_nutzt_cached_sizes(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        before = win._workspace_splitter.sizes()
        win.apply_panel_visibility(show_dashboard=False, show_audit_trail=False)
        # In dem Moment ist der Splitter auf [total, 0] kollabiert.
        win._save_workspace_state()
        # Save hat den Cache temporär gesetzt → Splitter hat echte Größen.
        assert win._workspace_splitter.sizes() == before


class TestWindowStateController:
    """Sprint 19 / F-006: QSettings-/Panel-State im WindowStateController."""

    def test_apply_panel_visibility_hides_both_panels(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        win._window_state.apply_panel_visibility(show_dashboard=False, show_audit_trail=False)
        assert win._lower_tabs.isVisible() is False
        assert win._lower_tabs.count() == 0

    def test_splitter_sizes_cached_and_restored_on_collapse(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        before = win._workspace_splitter.sizes()
        win._window_state.apply_panel_visibility(show_dashboard=False, show_audit_trail=False)
        assert win._window_state._cached_splitter_sizes == before
        win._window_state.apply_panel_visibility(show_dashboard=True, show_audit_trail=True)
        assert win._window_state._cached_splitter_sizes is None
        assert win._workspace_splitter.sizes() == before

    def test_restore_falls_back_to_default_tab_on_garbage(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win._settings.setValue("workspace/lower_tab", "kein-int")
        win._window_state.restore()
        assert win._lower_tabs.currentIndex() == 0


class TestMainWindowComposition:
    """Sprint 19 / F-006: MainWindow bleibt dünner Compositor, API unverändert."""

    def test_public_api_attributes_present(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        for name in (
            "_file_menu",
            "_help_menu",
            "_recent_menu",
            "_toolbar",
            "_action_new",
            "_action_settings",
            "_action_bug_report",
            "_action_switch_engagement",
        ):
            assert hasattr(win, name), name
        assert win.data_table() is not None
        assert win.workspace_splitter() is not None
        assert win.lower_tabs() is not None

    def test_helper_modules_qt_importable(self) -> None:
        from sampling_tool.ui import (
            _window_layout,
            _window_menu,
            _window_state,
            _window_toolbar,
        )

        assert callable(_window_layout.build_workspace)
        assert callable(_window_menu.build_menu)
        assert callable(_window_menu.rebuild_recent_menu)
        assert callable(_window_toolbar.build_toolbar)
        assert _window_state.WindowStateController is not None

    def test_sidebar_is_resizable(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        sidebar = win.sidebar()
        assert sidebar.minimumWidth() < sidebar.maximumWidth()


class TestResetSamplingToolbar:
    """Sprint 20: Toolbar-Button „Sampling zurücksetzen"."""

    def test_toolbar_contains_reset_sampling_action(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        assert hasattr(win, "_action_reset_sampling")
        assert win._action_reset_sampling in win._toolbar.actions()

    def test_reset_sampling_action_adjacent_to_new_sample(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        actions = win._toolbar.actions()
        i_new = actions.index(win._action_new_sample)
        i_reset = actions.index(win._action_reset_sampling)
        assert i_reset == i_new + 1

    def test_reset_sampling_action_emits_signal(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.set_reset_enabled(True)
        with qtbot.waitSignal(win.reset_sampling_requested, timeout=1000):
            win._action_reset_sampling.trigger()

    def test_set_reset_enabled_toggles_toolbar_and_menu_actions(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.set_reset_enabled(True)
        assert win._action_reset_sampling.isEnabled() is True
        assert win._action_reset_sample.isEnabled() is True
        win.set_reset_enabled(False)
        assert win._action_reset_sampling.isEnabled() is False
        assert win._action_reset_sample.isEnabled() is False

    def test_reset_sampling_disabled_on_welcome(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        win.set_reset_enabled(True)
        win.show_welcome()
        assert win._action_reset_sampling.isEnabled() is False


class TestWindowGeometryFitsScreen:
    """Sprint 67 / Teil A: Startgröße passt in den verfügbaren Bildschirmbereich."""

    @pytest.fixture(autouse=True)
    def _isolated_qsettings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Schiebt `QSettings`-IO in einen tmp-Pfad, damit echte Prefs unangetastet
        bleiben (gleiches Muster wie `test_feature_toggles`/`test_settings_store`).

        Zusatz (Code-Review-Nachtrag zu Sprint 67 Task 2): `QSettings(org, app)`
        ist laut Qt-Doku fest auf `NativeFormat`/`UserScope` verdrahtet und
        ignoriert `setDefaultFormat`/`setPath` (siehe ausführlicher Kommentar in
        `TestWindowGeometryPersistence._isolated_qsettings`). Seit Task 2 liest
        `restore()` echte `window/*`-Werte – ohne diesen Patch würde dieser Test
        von zufällig echten (auf diesem Rechner bereits gespeicherten) Prefs
        abhängen und könnte je nach Ausführungsreihenfolge/Vorlauf flackern.
        """
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        monkeypatch.setattr(
            "sampling_tool.ui.main_window.QSettings",
            lambda organization, application: QSettings(
                QSettings.Format.IniFormat, QSettings.Scope.UserScope, organization, application
            ),
        )

    def test_initial_geometry_fits_available_screen(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        screen = win.screen()
        assert screen is not None
        assert screen.availableGeometry().contains(win.geometry())


class TestWindowGeometryPersistence:
    """Sprint 67 / Teil A: Fenstergeometrie (Größe/Position/Maximiert) überlebt einen Neustart."""

    @pytest.fixture(autouse=True)
    def _isolated_qsettings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Schiebt `QSettings`-IO in einen tmp-Pfad, damit echte Prefs unangetastet
        bleiben (gleiches Muster wie `test_feature_toggles`/`test_settings_store`).

        Zusatz (Code-Review-Nachtrag): der 2-Arg-Konstruktor `QSettings(org, app)`
        ist laut Qt-Doku fest auf `NativeFormat`/`UserScope` verdrahtet und
        ignoriert `setDefaultFormat`/`setPath` – verifiziert via `fileName()`,
        das trotz obigem `setPath` weiterhin auf die echte
        `~/Library/Preferences/…plist` zeigte. `MainWindow.__init__` nutzt genau
        diesen Konstruktor fest verdrahtet (kein überschreibbares Factory wie
        `settings_store._qsettings`) – deshalb hier zusätzlich `main_window.
        QSettings` patchen, analog zum Muster in `test_settings_store.py`.
        """
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        monkeypatch.setattr(
            "sampling_tool.ui.main_window.QSettings",
            lambda organization, application: QSettings(
                QSettings.Format.IniFormat, QSettings.Scope.UserScope, organization, application
            ),
        )

    def test_geometry_roundtrip(self, qtbot: QtBot) -> None:
        """Größe/Position/Maximiert überleben einen Save/Restore-Zyklus."""
        win1 = MainWindow()
        qtbot.addWidget(win1)
        win1.show()
        qtbot.waitExposed(win1)
        # 1000×650 statt eines kleineren Werts: `MainWindow` hat (unabhängig von
        # Sprint 67) über Sidebar + AuditTrail-Filterzeile eine echte Layout-
        # Mindestbreite von ca. 810–870px – ein kleinerer Zielwert würde beim
        # `setGeometry` auf einem bereits `show()`n Fenster von Qt sofort auf
        # die Mindestgröße hochgeklemmt und damit den Roundtrip verfälschen.
        win1.setGeometry(20, 20, 1000, 650)
        win1._window_state.save()

        win2 = MainWindow()
        qtbot.addWidget(win2)
        win2.show()
        qtbot.waitExposed(win2)
        assert win2.geometry() == QRect(20, 20, 1000, 650)

        win3 = MainWindow()
        qtbot.addWidget(win3)
        win3.show()
        qtbot.waitExposed(win3)
        win3.setWindowState(win3.windowState() | Qt.WindowState.WindowMaximized)
        win3._window_state.save()

        win4 = MainWindow()
        qtbot.addWidget(win4)
        win4.show()
        qtbot.waitExposed(win4)
        assert bool(win4.windowState() & Qt.WindowState.WindowMaximized) is True

    def test_invalid_geometry_falls_back(self, qtbot: QtBot) -> None:
        """Eine außerhalb aller Screens liegende gespeicherte Geometrie wird verworfen."""
        # Explizites Format/Scope statt `QSettings(APP_ORG, APP_NAME)`: der
        # 2-Arg-Konstruktor ignoriert `setPath`/`setDefaultFormat` (siehe
        # `_isolated_qsettings`) – ohne dies würde hier in die echten,
        # ungeschützten Prefs geschrieben statt in den isolierten tmp-Pfad.
        settings = QSettings(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG, APP_NAME
        )
        settings.setValue("window/x", 50_000)
        settings.setValue("window/y", 50_000)
        settings.setValue("window/width", 700)
        settings.setValue("window/height", 500)

        win = MainWindow()
        qtbot.addWidget(win)

        screen = win.screen()
        assert screen is not None
        expected = fit_to_available(
            QSize(_DESIRED_WIDTH, _DESIRED_HEIGHT), screen.availableGeometry()
        )
        assert win.geometry() == expected

    def test_partial_geometry_falls_back(self, qtbot: QtBot) -> None:
        """Nur x/y ohne width/height gesetzt → `_read_saved_rect` verwirft, Fallback greift."""
        # Siehe Kommentar in `test_invalid_geometry_falls_back`: explizites
        # Format/Scope statt des isolierungslosen 2-Arg-Konstruktors.
        settings = QSettings(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG, APP_NAME
        )
        settings.setValue("window/x", 100)
        settings.setValue("window/y", 100)
        # width/height bewusst NICHT gesetzt.

        win = MainWindow()
        qtbot.addWidget(win)

        screen = win.screen()
        assert screen is not None
        expected = fit_to_available(
            QSize(_DESIRED_WIDTH, _DESIRED_HEIGHT), screen.availableGeometry()
        )
        assert win.geometry() == expected

    def test_non_positive_size_falls_back(self, qtbot: QtBot) -> None:
        """width=0 (alle 4 Werte vorhanden, aber kaputt) → `_read_saved_rect` verwirft.

        Andere Fehlerart als `test_partial_geometry_falls_back` (dort fehlen
        Werte komplett) – deckt den separaten `width <= 0 or height <= 0`-Zweig
        in `_read_saved_rect` ab.
        """
        settings = QSettings(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG, APP_NAME
        )
        settings.setValue("window/x", 100)
        settings.setValue("window/y", 100)
        settings.setValue("window/width", 0)
        settings.setValue("window/height", 500)

        win = MainWindow()
        qtbot.addWidget(win)

        screen = win.screen()
        assert screen is not None
        expected = fit_to_available(
            QSize(_DESIRED_WIDTH, _DESIRED_HEIGHT), screen.availableGeometry()
        )
        assert win.geometry() == expected


class TestIntOrNone:
    """Sprint 67 / Teil A: `_int_or_none` – QSettings liefert str (Windows/INI) oder nativen Typ."""

    def test_rejects_bool_despite_bool_being_an_int_subtype(self) -> None:
        assert _int_or_none(True) is None
        assert _int_or_none(False) is None

    def test_accepts_native_int(self) -> None:
        assert _int_or_none(42) == 42

    def test_parses_numeric_string(self) -> None:
        assert _int_or_none("42") == 42

    def test_rejects_malformed_string(self) -> None:
        assert _int_or_none("not-a-number") is None

    def test_rejects_none_and_other_types(self) -> None:
        assert _int_or_none(None) is None
        assert _int_or_none(3.5) is None


class TestOuterSplitterPersistence:
    """Sprint 67 / Teil A: Sidebar-Breite (äußerer Splitter) überlebt einen Neustart."""

    @pytest.fixture(autouse=True)
    def _isolated_qsettings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Schiebt `QSettings`-IO in einen tmp-Pfad, damit echte Prefs unangetastet
        bleiben. Siehe `TestWindowGeometryPersistence._isolated_qsettings` für den
        vollständigen Hintergrund (QSettings(org, app) ignoriert setPath/setDefaultFormat,
        `main_window.QSettings` muss deshalb zusätzlich gepatcht werden)."""
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        monkeypatch.setattr(
            "sampling_tool.ui.main_window.QSettings",
            lambda organization, application: QSettings(
                QSettings.Format.IniFormat, QSettings.Scope.UserScope, organization, application
            ),
        )

    def test_outer_splitter_persisted(self, qtbot: QtBot) -> None:
        # Verarbeitet zuerst liegengebliebene `deleteLater()`-Events aus
        # vorangegangenen Tests dieser Datei (viele kurzlebige `MainWindow`-
        # Instanzen mit je einer `DataTableView`). Dieser Test ist der erste
        # mit zwei parallel sichtbaren Workspace-Fenstern – ohne den Wait
        # traf ein längst geplantes, aber noch nicht zugestelltes Paint-Event
        # empirisch reproduzierbar auf ein inzwischen C++-seitig gelöschtes
        # Widget und crashte den Prozess mit einem Segfault (nicht nur einen
        # Testfehler). `qtbot.wait(0)` reichte nicht, um den Rückstau aus
        # ~60 vorangehenden Tests zu leeren; 200 ms taten es zuverlässig
        # (7 Wiederholungen ohne Crash). Zusätzlich abgesichert durch den
        # `sip.isdeleted`-Check + das `except RuntimeError` in
        # `DataTableView.paintEvent` – die eigentliche, verlässliche
        # Fehlerbehebung ist aber dieser Wait, nicht der Guard dort.
        qtbot.wait(200)
        win1 = MainWindow()
        qtbot.addWidget(win1)
        win1.show()
        qtbot.waitExposed(win1)
        # Der äußere Splitter liegt auf der Workspace-Seite des Welcome/
        # Workspace-`QStackedWidget`, die anfangs NICHT die aktuelle Seite ist
        # (siehe `show_welcome()` am Ende von `MainWindow.__init__`). Eine
        # nicht-aktuelle Stack-Seite bekommt von Qt keine reale Layout-Größe
        # zugewiesen – jede `setSizes`-Anfrage würde sonst wirkungslos auf die
        # winzige Default-Größe zurückfallen, weshalb hier zuerst auf den
        # Workspace umgeschaltet wird. Zusätzlich braucht das Fenster genug
        # reale Breite oberhalb seiner Layout-Mindestbreite: 1000px reichte
        # auf macOS/Ubuntu-CI, schlug auf Windows-CI aber fehl (Sidebar
        # landete bei genau `_SIDEBAR_MIN_WIDTH` statt 300) – vermutlich
        # weil Windows' Default-Schriftmetriken den Workspace-Bereich
        # (AuditTrail/Dashboard/Tabelle) breiter machen als auf macOS/Linux,
        # sodass bei 1000px zu wenig Spielraum für eine 300px-Sidebar bleibt.
        # 1600px lässt auf allen drei OS reichlich Puffer.
        win1.show_workspace()
        win1.setGeometry(20, 20, 1600, 800)
        win1.outer_splitter().setSizes([300, 400])
        win1._window_state.save()

        win2 = MainWindow()
        qtbot.addWidget(win2)
        win2.show()
        qtbot.waitExposed(win2)
        win2.show_workspace()
        win2.setGeometry(20, 20, 1600, 800)
        assert win2.outer_splitter().sizes()[0] == 300


class TestMainWindowMinimumSize:
    """Sprint 67 / Teil A: Mindestgröße passt auf 1280×720 (13-Zoll-Zielgerät)."""

    def test_minimum_size_fits_target_device(self, qtbot: QtBot) -> None:
        win = MainWindow()
        qtbot.addWidget(win)
        assert 0 < win.minimumWidth() <= 1280
        assert 0 < win.minimumHeight() <= 720


class TestUiScaleApplication:
    """Sprint 68 / Teil B1: Toolbar-Icon-Größe + Tabellen-Zeilenhöhe folgen dem Faktor."""

    def test_derived_sizes_scale(self, qtbot: QtBot) -> None:
        from sampling_tool.ui._window_toolbar import _TOOLBAR_ICON_SIZE
        from sampling_tool.ui.widgets.data_table import _DEFAULT_ROW_HEIGHT

        win = MainWindow()
        qtbot.addWidget(win)

        win.apply_ui_scale(1.0)
        assert win._toolbar.iconSize() == QSize(_TOOLBAR_ICON_SIZE, _TOOLBAR_ICON_SIZE)
        v_header = win.data_table().verticalHeader()
        assert v_header is not None
        assert v_header.defaultSectionSize() == _DEFAULT_ROW_HEIGHT

        win.apply_ui_scale(1.15)
        assert win._toolbar.iconSize().width() > _TOOLBAR_ICON_SIZE
        v_header = win.data_table().verticalHeader()
        assert v_header is not None
        assert v_header.defaultSectionSize() > _DEFAULT_ROW_HEIGHT

    def test_apply_ui_scale_triggers_data_table_column_resize(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sprint 69 / Bug 4: `MainWindow.apply_ui_scale` muss die Spalten-
        breiten-Anpassung am Data-Table anstoßen – vorher wurden nur Icon-
        Größe + Zeilenhöhe skaliert, wodurch Zellenwerte bei „Groß" visuell
        abgeschnitten wurden (Tabellenwerte-Cutoff-Bug). Der eigentliche
        Clamp-/Breiten-Effekt wird ausführlich in
        `tests/ui/test_data_table.py::TestDataTableView::test_columns_resize_on_ui_scale_change`
        getestet – hier wird nur die Verdrahtung MainWindow → DataTableView
        abgesichert.
        """
        win = MainWindow()
        qtbot.addWidget(win)

        calls: list[float] = []
        original = win.data_table().apply_ui_scale

        def spy(factor: float) -> None:
            calls.append(factor)
            original(factor)

        monkeypatch.setattr(win.data_table(), "apply_ui_scale", spy)

        win.apply_ui_scale(1.15)

        assert calls == [1.15]
