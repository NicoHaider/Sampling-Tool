"""Sampling-Presets: benannte, wiederverwendbare Stichproben-Konfigurationen.

Ein `SamplingPreset` bündelt genau die Felder, die *beschreiben, wie*
gesampelt wird (Methode, Größe, Filter, Cluster-/Schicht-Konfiguration) –
ein Template über Engagements hinweg. Bewusst NICHT enthalten:

- der **Seed** (ziehungs-spezifischer Parameter; über verschiedene
  Populationen hinweg sinnlos – Reproduzierbarkeit hängt an Seed + Population,
  nicht am Konfig-Template, ISAE-3402),
- die **Population/Daten** und **Ergebnisse** (gehören nicht ins Template).

Das Modell ist reine Domain-Logik: kein Qt, keine SQL, keine Datei-I/O.
Persistiert werden Presets app-weit über `ui.preset_store.PresetStore`
(QSettings) – serialisiert mit den hiesigen stdlib-JSON-Helfern. Filter-Werte
können echte `datetime`/`date`/`time`-Objekte sein (aus Datums-Spalten via
`DatasetRepo.distinct_values`); ein Tagged-Encoder hält sie roundtrip-sicher,
analog zum Persistenz-Encoder in `persistence/_json.py` (hier aber stdlib statt
orjson, weil Core dependency-frei bleibt).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Final

from sampling_tool.core.models import (
    FilterOperator,
    SampleConfig,
    SamplingMethod,
    StratifyMode,
)


@dataclass(frozen=True, slots=True)
class SamplingPreset:
    """Benanntes Template einer Stichproben-Konfiguration (ohne Seed/Daten)."""

    name: str
    method: SamplingMethod
    size: int
    cluster_field: str | None = None
    stratum_field: str | None = None
    stratify_mode: StratifyMode = StratifyMode.PROPORTIONAL
    filter_field: str | None = None
    filter_value: Any = None
    filter_operator: FilterOperator = FilterOperator.EQ

    @classmethod
    def from_config(cls, name: str, config: SampleConfig) -> SamplingPreset:
        """Friert die „wie-wird-gesampelt"-Felder eines `SampleConfig` ein.

        Der Seed wird bewusst verworfen – er ist ziehungs-spezifisch und kein
        Bestandteil des wiederverwendbaren Templates.
        """
        return cls(
            name=name,
            method=config.method,
            size=config.size,
            cluster_field=config.cluster_field,
            stratum_field=config.stratum_field,
            stratify_mode=config.stratify_mode,
            filter_field=config.filter_field,
            filter_value=config.filter_value,
            filter_operator=config.filter_operator,
        )

    def to_config(self, seed: int) -> SampleConfig:
        """Rekonstruiert ein `SampleConfig` mit explizit übergebenem Seed.

        Der Seed kommt von außen (vom Sampling-Dialog), nie aus dem Preset –
        so bleibt die Reproduzierbarkeit an (Seed + Population) gebunden.
        """
        return SampleConfig(
            method=self.method,
            size=self.size,
            seed=seed,
            cluster_field=self.cluster_field,
            stratum_field=self.stratum_field,
            stratify_mode=self.stratify_mode,
            filter_field=self.filter_field,
            filter_value=self.filter_value,
            filter_operator=self.filter_operator,
        )


# ---------------------------------------------------------------------------
# JSON-Serialisierung (stdlib, dependency-frei)
#
# Tagged-Encoding für die Filter-Werte: skalare JSON-Typen (str/int/float/
# bool/None) gehen direkt durch, datetime/date/time werden mit `__type__`-
# Marker ISO-codiert. Spiegelt das Muster aus `persistence/_json.py`.
# ---------------------------------------------------------------------------

_TYPE_KEY: Final[str] = "__type__"
_VAL_KEY: Final[str] = "v"


def _encode_filter_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return {_TYPE_KEY: "datetime", _VAL_KEY: value.isoformat()}
    if isinstance(value, date):
        return {_TYPE_KEY: "date", _VAL_KEY: value.isoformat()}
    if isinstance(value, time):
        return {_TYPE_KEY: "time", _VAL_KEY: value.isoformat()}
    return value


def _decode_filter_value(value: Any) -> Any:
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


def _preset_to_dict(preset: SamplingPreset) -> dict[str, Any]:
    return {
        "name": preset.name,
        "method": preset.method.value,
        "size": preset.size,
        "cluster_field": preset.cluster_field,
        "stratum_field": preset.stratum_field,
        "stratify_mode": preset.stratify_mode.value,
        "filter_field": preset.filter_field,
        "filter_value": _encode_filter_value(preset.filter_value),
        "filter_operator": preset.filter_operator.value,
    }


def _preset_from_dict(data: dict[str, Any]) -> SamplingPreset:
    return SamplingPreset(
        name=str(data["name"]),
        method=SamplingMethod(data["method"]),
        size=int(data["size"]),
        cluster_field=data.get("cluster_field"),
        stratum_field=data.get("stratum_field"),
        stratify_mode=StratifyMode(data.get("stratify_mode", StratifyMode.PROPORTIONAL.value)),
        filter_field=data.get("filter_field"),
        filter_value=_decode_filter_value(data.get("filter_value")),
        filter_operator=FilterOperator(data.get("filter_operator", FilterOperator.EQ.value)),
    )


def serialize_presets(presets: list[SamplingPreset]) -> str:
    """Serialisiert eine Preset-Liste zu einem JSON-String (stdlib)."""
    return json.dumps([_preset_to_dict(p) for p in presets], ensure_ascii=False)


def deserialize_presets(raw: str) -> list[SamplingPreset]:
    """Deserialisiert einen JSON-String zu Presets; leerer String → [].

    Robust gegen korrupte Persistenz (Hand-Edit, Teil-Write, Versions-Drift):
    syntaktisch invalides JSON oder ein Nicht-Array liefert eine leere Liste;
    einzelne kaputte Einträge (fehlende Felder, unbekanntes Enum, kein Dict)
    werden übersprungen, gültige Presets laden trotzdem. Kein Crash – analog
    zur graceful degradation in `ui/recent.py` und beim Filter-Skip.
    """
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    presets: list[SamplingPreset] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            presets.append(_preset_from_dict(item))
        except (KeyError, ValueError, TypeError):
            continue
    return presets
