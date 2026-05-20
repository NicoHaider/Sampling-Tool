"""JSON-Helfer der Persistenz-Schicht (Sprint 19 / F-007).

orjson-Wrapper + tagged Encoder für datetime/date/time. Vorher in
repositories.py – herausgezogen, damit die Repo-Einzelmodule sie teilen.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Final

import orjson


def _json_dumps(value: Any) -> str:
    """orjson dump → str (SQLite-TEXT-Spalten brauchen str, nicht bytes)."""
    return orjson.dumps(value).decode("utf-8")


def _json_loads(text: str | bytes) -> Any:
    """orjson load – akzeptiert str und bytes."""
    return orjson.loads(text)


def _json_or_none(value: Any) -> str | None:
    """Serialisiert primitive Werte zu JSON, gibt None bei None zurück."""
    return None if value is None else _json_dumps(value)


def _json_or_none_load(text: str | None) -> Any:
    """Deserialisiert JSON oder gibt None zurück; tolerant gegenüber Plain-Strings."""
    if text is None:
        return None
    try:
        return _json_loads(text)
    except (TypeError, orjson.JSONDecodeError):
        return text


# ---------------------------------------------------------------------------
# Datetime-aware JSON für `dataset_rows.values_json`
#
# Die Importer-Schicht (Sprint 3) liefert echte datetime/date/time-Objekte in
# `DatasetRow.values`. Der eingebaute `json.dumps` kann das nicht, daher
# tagged-Encoding mit `__type__`-Marker und Round-Trip-sicherer Decode.
# ---------------------------------------------------------------------------

_TYPE_KEY: Final[str] = "__type__"
_VAL_KEY: Final[str] = "v"


def _encode_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return {_TYPE_KEY: "datetime", _VAL_KEY: value.isoformat()}
    if isinstance(value, date):
        return {_TYPE_KEY: "date", _VAL_KEY: value.isoformat()}
    if isinstance(value, time):
        return {_TYPE_KEY: "time", _VAL_KEY: value.isoformat()}
    return value


def _decode_value(value: Any) -> Any:
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


def _values_to_json(values: dict[str, Any]) -> str:
    return _json_dumps({k: _encode_value(v) for k, v in values.items()})


def _values_from_json(text: str) -> dict[str, Any]:
    raw = _json_loads(text)
    return {k: _decode_value(v) for k, v in raw.items()}
