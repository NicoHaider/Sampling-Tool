"""Tausenderpunkte für deutsche Locale bei Anzeige-Zahlen (Sprint 91 / C).

War bislang privat in `sampling_dialog.py` dupliziert; die Statusleiste
(„500000 Zeilen" statt „500.000 Zeilen") zeigte Zeilenzahlen ohne diese
Formatierung. Ein Ort für beide Aufrufer.
"""

from __future__ import annotations

# Sprint 92: die Funktion lebt in `core.formatting`, weil auch die Filteranzeige
# in Berichten (Core/IO, Qt-frei) Tausenderpunkte braucht.
from sampling_tool.core.formatting import format_int

__all__ = ["format_int"]
