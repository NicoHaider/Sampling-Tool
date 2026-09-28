"""Tausenderpunkte für deutsche Locale bei Anzeige-Zahlen (Sprint 91 / C).

War bislang privat in `sampling_dialog.py` dupliziert; die Statusleiste
(„500000 Zeilen" statt „500.000 Zeilen") zeigte Zeilenzahlen ohne diese
Formatierung. Ein Ort für beide Aufrufer.
"""

from __future__ import annotations


def format_int(value: int) -> str:
    """Tausenderpunkte für deutsche Locale (12345 → '12.345')."""
    return f"{value:,}".replace(",", ".")
