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
    # Sprint 26 – Fast-Path: orjson serialisiert das Werte-Dict direkt in C und
    # ruft `_encode_value` (als `default`) NUR für tatsächliche datetime/date/
    # time-Werte zurück (OPT_PASSTHROUGH_DATETIME schickt genau diese Typen an
    # `default`). Das spart den früheren Per-Zellen-Dict-Comp + isinstance-Pass
    # über Nicht-Temporal-Werte (Massendaten sind ganz überwiegend nicht-
    # temporal). Die erzeugten Bytes sind byte-identisch zum vorherigen
    # `{k: _encode_value(v) ...}`-Aufbau (Tag-Shape + Key-Reihenfolge gleich) –
    # siehe Oracle-Test `test_tagged_encoding_roundtrip_unchanged`.
    # Kontrakt: `values` enthält nur flache Skalare (so liefert es der Importer-
    # `_coerce_value`; Nicht-Skalare werden dort zu str). Bei verschachtelten
    # Temporal-Werten in Containern würde `OPT_PASSTHROUGH_DATETIME` – anders als
    # der alte Top-Level-Dict-Comp – rekursiv taggen; dieser Fall ist im
    # Import-Pfad nicht erreichbar.
    return orjson.dumps(
        values, default=_encode_value, option=orjson.OPT_PASSTHROUGH_DATETIME
    ).decode("utf-8")


def _values_from_json(text: str) -> dict[str, Any]:
    raw = _json_loads(text)
    return {k: _decode_value(v) for k, v in raw.items()}
