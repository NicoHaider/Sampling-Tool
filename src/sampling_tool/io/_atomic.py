"""Gemeinsamer atomarer Schreibpfad für alle Exporter (S2.5 / A-004, N-010-PDF-Write).

Vereinheitlicht die bisher pro Exporter unterschiedlich robusten `.tmp`→
`os.replace`-Muster: `exporter.py` schrieb sauber atomar, `multi_report_
exporter.py` hatte den finalen `os.replace` außerhalb von try/except/finally
(kein Cleanup bei Fehlschlag), `html_report.py`/`pdf_report.py` schrieben
direkt aufs Ziel (ein Absturz mittendrin hinterließ eine halbe/korrupte
Datei). Alle vier nutzen jetzt `atomic_output` statt eigener Tmp-Logik.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class AtomicReplaceError(OSError):
    """`os.replace()` ist beim finalen atomaren Swap fehlgeschlagen – z. B. weil
    die Zieldatei unter Windows in einer anderen Anwendung geöffnet ist.

    Bewusst von einem Fehler beim Schreiben der Tempdatei selbst unterscheidbar
    (der propagiert unverändert als sein ursprünglicher Typ), damit Aufrufer
    gezielt eine fachliche Meldung geben können (N-004: „möglicherweise in
    Excel geöffnet").
    """


@contextmanager
def atomic_output(target: Path) -> Iterator[Path]:
    """Kontextmanager für atomares Schreiben nach `target`.

    Legt den Zielordner an und erzeugt darin exklusiv (`tempfile.mkstemp`,
    unvorhersagbarer Name – kein Kollisions-/Symlink-Race in gemeinsam
    beschreibbaren Ordnern) eine Tempdatei; liefert deren Pfad. Schreibt der
    Aufrufer im `with`-Block erfolgreich, wird die Tempdatei per `os.replace`
    atomar auf `target` verschoben (gleiches Filesystem). Wirft der Aufrufer
    selbst ODER schlägt der abschließende `os.replace` fehl, wird die
    Tempdatei aufgeräumt und die Exception weitergereicht (`os.replace`-Fehler
    als `AtomicReplaceError`, alles andere unverändert) – `target` bleibt in
    jedem Fehlerfall unangetastet, nie eine halbe Datei.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    os.close(fd)  # nur den Pfad brauchen; der Writer überschreibt die exklusiv erzeugte Datei
    tmp = Path(tmp_name)
    try:
        yield tmp
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    try:
        os.replace(tmp, target)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise AtomicReplaceError(str(exc)) from exc
