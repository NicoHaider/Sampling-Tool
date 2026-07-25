"""Sprint 28 – Menü „Vorlagen verwalten…" + Verwaltungs-Einstiegspunkt.

Der Menüeintrag öffnet das `TemplateManagerDialog` über genau **einen** klar
definierten Einstiegspunkt (`HelpController.handle_manage_templates`), damit
später ein Passwort-Gate davor ergänzt werden kann. Die Action ist app-weit
erreichbar (auch ohne offenes Projekt), weil Vorlagen app-weit liegen.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from sampling_tool.config import APP_NAME, APP_ORG
from sampling_tool.ui.controllers.main_controller import MainController
from sampling_tool.ui.main_window import MainWindow
from sampling_tool.ui.preset_store import PresetStore
from sampling_tool.ui.recent import RecentEngagementsStore

pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    monkeypatch.setattr(
        "sampling_tool.ui.settings_store._qsettings",
        lambda: QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG, APP_NAME),
    )


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    return win


class TestManageTemplatesMenu:
    def test_action_in_sample_menu(self, window: MainWindow) -> None:
        assert window._action_manage_templates in window._sample_menu.actions()
        assert window._action_manage_templates.text() == "Vorlagen verwalten…"

    def test_action_always_enabled_at_welcome(self, window: MainWindow) -> None:
        # Vorlagen sind app-weit – die Action bleibt auch ohne offenes Projekt
        # (Welcome-State) bedienbar, anders als die workspace-only Aktionen.
        assert window._action_manage_templates.isEnabled() is True

    def test_action_emits_signal(self, qtbot: QtBot, window: MainWindow) -> None:
        with qtbot.waitSignal(window.manage_templates_requested, timeout=500):
            window._action_manage_templates.trigger()


class TestManageTemplatesEntryPoint:
    def test_handle_manage_templates_opens_dialog(
        self, qtbot: QtBot, window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        controller = MainController(
            window, recent_store=RecentEngagementsStore(path=tmp_path / "recent.json")
        )
        opened: dict[str, object] = {}

        class _FakeDialog:
            def __init__(self, store: object, parent: object = None) -> None:
                opened["store"] = store
                opened["parent"] = parent

            def exec(self) -> int:
                opened["exec"] = True
                return 0

        monkeypatch.setattr(
            "sampling_tool.ui.controllers.help_controller.TemplateManagerDialog",
            _FakeDialog,
        )
        controller.help.handle_manage_templates()
        # Genau ein Einstiegspunkt öffnet das Verwaltungsfenster …
        assert opened.get("exec") is True
        # … mit der app-weiten PresetStore-Schicht (Sprint 23).
        assert isinstance(opened["store"], PresetStore)

    def test_menu_action_opens_dialog_end_to_end(
        self, qtbot: QtBot, window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Patch VOR dem Controller-Bau, damit die Signal-Verdrahtung den
        # gepatchten Dialog erfasst (Action → Signal → Handler → Dialog).
        opened: list[bool] = []

        class _FakeDialog:
            def __init__(self, store: object, parent: object = None) -> None:
                pass

            def exec(self) -> int:
                opened.append(True)
                return 0

        monkeypatch.setattr(
            "sampling_tool.ui.controllers.help_controller.TemplateManagerDialog",
            _FakeDialog,
        )
        # Referenz halten – sonst sammelt der GC den Controller ein und die
        # Bound-Method-Signal-Verbindung stirbt vor dem trigger().
        controller = MainController(
            window, recent_store=RecentEngagementsStore(path=tmp_path / "recent.json")
        )
        window._action_manage_templates.trigger()
        assert opened == [True]
        assert controller is not None
