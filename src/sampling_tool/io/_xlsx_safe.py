"""Gemeinsamer Safe-Writer für unvertrauenswürdigen Text in openpyxl-Exporten.

Schließt S-001 (Excel-/CSV-Formel-Injection, OWASP): importierte Fremddaten
(Zellwerte, Spaltennamen, Engagement-/Auditor-/Dateinamen, Filter-Werte, …)
landeten bisher ungefiltert in openpyxl-Zellen. Ein String, der mit `=`
beginnt, wird von openpyxl beim Speichern als **Formel** interpretiert
(`data_type == "f"`) – klassische Formel-Injection.

Neutralisierung passiert **ausschließlich hier, beim Export**. Der Import-/
Coercion-Pfad (`io/importer.py`) und die DB-Werte bleiben unverändert – die
gezogene Stichprobe darf durch einen Sicherheits-Fix nicht beeinflusst werden.

Mechanismus: die gefährliche Zelle wird zunächst ganz normal geschrieben und
danach auf `data_type = TYPE_STRING` gezwungen. Der Wert bleibt dabei
byte-identisch erhalten (keine Apostroph-Mutation nötig) – verifiziert gegen
openpyxl 3.1.5 (Reopen-Test: `data_type != "f"`, Wert unverändert).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Any, Final

from openpyxl.cell.cell import TYPE_STRING
from openpyxl.worksheet.worksheet import Worksheet

_DANGEROUS_PREFIXES: Final[tuple[str, ...]] = ("=", "+", "-", "@", "\t", "\r", "\n")


def is_dangerous(value: object) -> bool:
    """True, wenn `value` als Excel-/CSV-Formel interpretiert werden könnte.

    Policy (Review-Vorgabe, defense-in-depth über das hinaus, was openpyxl
    selbst als Formel erkennt): führendes `=`, `+`, `-`, `@`, Tab, CR oder LF,
    oder ein eingebettetes CR/LF an beliebiger Stelle.
    """
    if not isinstance(value, str) or not value:
        return False
    if value.startswith(_DANGEROUS_PREFIXES):
        return True
    return "\r" in value or "\n" in value


def safe_cell_value(value: Any) -> Any:
    """Typnormalisierung wie die früheren `_cell_value`/`_ensure_cell_value`.

    `datetime`/`date`/`bool`/`int`/`float`/`str` gehen unverändert durch,
    `None` bleibt `None`, alles andere wird `str(value)`. Neutralisiert
    gefährliche Strings **nicht** – das passiert erst beim Zell-Schreiben in
    `safe_row`, damit der Wert bis dahin exakt erhalten bleibt.
    """
    if value is None:
        return None
    if isinstance(value, datetime | date | bool | int | float | str):
        return value
    return str(value)


def safe_row(ws: Worksheet, values: Iterable[Any]) -> list[Any]:
    """Normalisiert `values`, hängt sie als Zeile an `ws` an und neutralisiert
    dabei gefährliche Strings (Formel-Injection, S-001).

    Gibt die normalisierte Liste zurück, damit Caller (z. B. für die
    Spaltenbreiten-Berechnung) nicht ein zweites Mal normalisieren müssen.
    """
    normalized = [safe_cell_value(v) for v in values]
    ws.append(normalized)
    row_idx = ws.max_row
    for col_idx, value in enumerate(normalized, start=1):
        if is_dangerous(value):
            ws.cell(row=row_idx, column=col_idx).data_type = TYPE_STRING
    return normalized
