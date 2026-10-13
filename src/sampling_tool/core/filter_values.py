"""Typ-Tag für Filterwerte in JSON (Vorlagen, `samples.filters`, Event-`filters`).

JSON kennt kein Datum: ohne Tag käme ein `datetime`-Filterwert nach dem Speichern
als ISO-Text zurück – die Anzeige hielte ihn für Text, ein erneut angewendeter
Filter träfe keine Datumszelle mehr (Sprint 93). Gleiche Form wie der Tag der
Datensatz-Zellen in `persistence/_json.py`, damit es nur ein Format gibt.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Final

_TYPE_KEY: Final[str] = "__type__"
_VAL_KEY: Final[str] = "v"


def encode_filter_value(value: Any) -> Any:
    """`datetime`/`date`/`time` → `{"__type__": …, "v": ISO}`, alles andere unverändert."""
    if isinstance(value, datetime):
        return {_TYPE_KEY: "datetime", _VAL_KEY: value.isoformat()}
    if isinstance(value, date):
        return {_TYPE_KEY: "date", _VAL_KEY: value.isoformat()}
    if isinstance(value, time):
        return {_TYPE_KEY: "time", _VAL_KEY: value.isoformat()}
    return value


def decode_filter_value(value: Any) -> Any:
    """Umkehrung von `encode_filter_value`; ungetaggte Werte bleiben, wie sie sind."""
    if not (isinstance(value, dict) and _TYPE_KEY in value and _VAL_KEY in value):
        return value
    type_tag = value[_TYPE_KEY]
    raw = value[_VAL_KEY]
    if not isinstance(raw, str):
        return value
    if type_tag == "datetime":
        return datetime.fromisoformat(raw)
    if type_tag == "date":
        return date.fromisoformat(raw)
    if type_tag == "time":
        return time.fromisoformat(raw)
    return value
