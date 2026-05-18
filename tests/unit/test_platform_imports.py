"""Cross-Platform-Import-Schutz.

Pass-4 T-006: CLAUDE.md-Stolperfalle "pywin32 ist Windows-only – auf
macOS NICHT importieren auf Modul-Ebene; Late-Imports innerhalb von
Funktionen". Wenn jemand versehentlich ein Top-Level `import pywin32`
o. ä. einfügt, crasht die App beim Start auf macOS / Linux. CI auf
Linux/Mac würde grün bleiben, wenn dieser Test fehlt – pywin32 ist
gar nicht installiert, der ImportError taucht erst beim App-Start auf.
"""

from __future__ import annotations

import importlib
import sys

import pytest

WIN32_PREFIXES: tuple[str, ...] = ("win32", "pywin32")


@pytest.mark.skipif(sys.platform == "win32", reason="Test ist macOS/Linux-spezifisch")
class TestNoWin32ModulesOnNonWindows:
    """Verifiziert, dass sampling_tool auf macOS/Linux ohne pywin32 läuft."""

    def test_top_level_package_loads_without_win32(self) -> None:
        # Pre-State: keine win32-Module aus früheren Tests im Cache.
        for name in [n for n in sys.modules if n.startswith(WIN32_PREFIXES)]:
            del sys.modules[name]

        # Frischer Re-Import des Pakets darf keine win32-Module ziehen.
        importlib.import_module("sampling_tool")
        importlib.import_module("sampling_tool.io")
        importlib.import_module("sampling_tool.persistence")
        importlib.import_module("sampling_tool.core")
        importlib.import_module("sampling_tool.audit")

        loaded_win32 = [n for n in sys.modules if n.startswith(WIN32_PREFIXES)]
        assert not loaded_win32, (
            f"win32-Module wurden geladen, das crasht auf macOS/Linux: {loaded_win32}"
        )

    def test_main_module_loads_without_win32(self) -> None:
        """Das `__main__`-Modul (App-Startpunkt) darf auch keine
        pywin32-Imports auf Modul-Ebene haben – die `import pywin32`-
        Stellen müssen alle hinter einem `sys.platform == 'win32'`-
        Check liegen oder Late-Imports in Funktionen sein."""
        for name in [n for n in sys.modules if n.startswith(WIN32_PREFIXES)]:
            del sys.modules[name]

        # `sampling_tool.__main__` importiert nur Bootstrap-Logik –
        # ein Modul-Reload reicht für die Verifikation.
        importlib.import_module("sampling_tool.__main__")
        loaded_win32 = [n for n in sys.modules if n.startswith(WIN32_PREFIXES)]
        assert not loaded_win32, f"win32-Module aus __main__: {loaded_win32}"
