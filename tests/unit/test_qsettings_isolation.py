"""Wächter: kein Test schreibt in die echten App-Einstellungen (Sprint 84 / A).

Die autouse-Fixture `_isolate_qsettings` in `tests/conftest.py` biegt für jeden
Test `settings_store._qsettings` auf eine INI unter `tmp_path` um. Dieser Test
belegt, dass `save_settings` dort landet – und bricht VOR dem Schreiben ab,
wenn der Handle nicht isoliert ist, damit ein Fehlschlag nie selbst die echten
Prefs beschädigt (Anlass: Sprint 82/83 setzten Auditor-Name und
`first_run_completed` auf Werks-Defaults zurück).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings

from sampling_tool.ui import settings_store
from sampling_tool.ui.settings_store import AppSettings, save_settings

_MARKER = "WÄCHTER"


def _save_marker_into_isolated_store(tmp_path: Path) -> Path:
    """Schreibt den Marker – aber nur, wenn der Handle unter `tmp_path` liegt."""
    ini = Path(settings_store.open_qsettings().fileName()).resolve()
    if not ini.is_relative_to(tmp_path.resolve()):
        raise AssertionError(f"QSettings nicht isoliert, Schreiben abgebrochen: {ini}")
    save_settings(replace(AppSettings.defaults(), default_auditor_name=_MARKER))
    return ini


class TestTestsNeverTouchRealPrefs:
    def test_save_settings_lands_in_tmp_ini(self, tmp_path: Path) -> None:
        ini = _save_marker_into_isolated_store(tmp_path)

        assert ini.is_file()
        stored = QSettings(str(ini), QSettings.Format.IniFormat)
        assert stored.value("settings/default_auditor_name") == _MARKER

    def test_every_handle_of_a_test_points_to_the_same_ini(self, tmp_path: Path) -> None:
        first = settings_store.open_qsettings().fileName()
        second = settings_store.open_qsettings().fileName()
        assert first == second
        assert Path(first).resolve().is_relative_to(tmp_path.resolve())


class TestGuardDetectsMissingIsolation:
    """Positiv-Kontrolle: ohne die autouse-Isolation muss der Wächter rot sein.

    Der Marker schaltet die Fixture für genau diesen Test ab; `_qsettings` ist
    dann der echte Produktions-Handle (plist/Registry/`~/.config`). Der Wächter
    darf dabei nicht schreiben – er muss vor `save_settings` abbrechen. Dass
    nichts geschrieben wurde, belegt der Spion: `save_settings` wird ersetzt
    und darf nie gerufen werden.
    """

    @pytest.mark.real_qsettings
    def test_guard_aborts_before_writing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[AppSettings] = []
        monkeypatch.setattr(f"{__name__}.save_settings", calls.append)

        with pytest.raises(AssertionError, match="nicht isoliert"):
            _save_marker_into_isolated_store(tmp_path)

        assert calls == []
