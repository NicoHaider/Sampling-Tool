"""Gemeinsame stdout-/stderr-Behandlung für die Skripte unter `scripts/`.

Windows-CI leitet stdout jedes Steps und jedes `subprocess.run(capture_output=True)`
über eine Pipe um. Für eine Pipe wählt CPython 3.13 nicht UTF-8, sondern die
ANSI-Codepage (cp1252) – ein einziges Zeichen außerhalb davon lässt `print()` mit
`UnicodeEncodeError` sterben. In Sprint 74 hat das den Windows-Release-Build
gekillt: `build_app.py` druckte `✓` (U+2713) NACH erfolgreichem PyInstaller-Lauf,
der Step fiel, das Artefakt entstand nicht.

Der Guard sitzt deshalb an der Wurzel und nicht am Zeichen: einzelne Glyphen zu
entfernen behebt genau einen Fall und lädt den nächsten wieder ein.
"""

from __future__ import annotations

import sys


def force_utf8_stdout() -> None:
    """Schaltet `sys.stdout`/`sys.stderr` auf UTF-8 mit `errors="replace"`.

    `errors="replace"` statt `strict`: der Guard darf unter keinen Umständen
    selbst zur Fehlerquelle werden – ein nicht darstellbares Zeichen wird zu `?`,
    statt einen fertigen Build zu verwerfen.

    Streams ohne `reconfigure` (`io.StringIO`, diverse Test-Capture-Wrapper)
    werden übersprungen statt zu werfen; sonst wäre der Guard die Regression.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # Detached/geschlossener Stream – hier gibt es nichts zu retten,
            # und ein Fehler beim Absichern der Ausgabe darf den Lauf nicht
            # abbrechen.
            continue
