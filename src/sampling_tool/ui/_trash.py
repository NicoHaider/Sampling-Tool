"""Papierkorb-Anbindung für aufgeräumte Sicherungskopien (Sprint 88 / A3).

Eigenes Modul, damit `persistence/` Qt-frei bleibt (der Version-Manager
bekommt die Funktion hereingereicht) und die Tests sie an EINER Stelle
ersetzen können – kein Test darf den echten Papierkorb berühren
(`tests/conftest.py`).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QFile


def move_to_trash(path: Path) -> bool:
    """Verschiebt `path` in den Papierkorb des Systems; `False`, wenn das nicht geht.

    Kein Fallback auf Löschen – ohne Papierkorb bleibt die Datei liegen.
    """
    moved, _path_in_trash = QFile.moveToTrash(str(path))
    return bool(moved)
