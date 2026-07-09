"""Sprint 23 – `SamplingPreset`-Modell + JSON-Serialisierung.

Pure-Core-Tests (kein Qt, keine I/O): das Preset bündelt die
„wie-wird-gesampelt"-Felder eines `SampleConfig` OHNE Seed/Daten und
ist verlustfrei über stdlib-JSON persistierbar. Die Reproduzierbarkeit
wird am Sampler nachgewiesen: ein aus dem Preset rekonstruiertes
`SampleConfig` zieht bit-identisch zur manuellen Konfiguration.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, time

import pytest

from sampling_tool.core.models import (
    DatasetRow,
    FilterOperator,
    SampleConfig,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.core.presets import (
    SamplingPreset,
    deserialize_presets,
    serialize_presets,
)
from sampling_tool.core.sampling import create_sampler

pytestmark = pytest.mark.unit


def _full_config(seed: int = 99) -> SampleConfig:
    """SampleConfig, das jedes optionale Feld nutzt (worst case fürs Mapping)."""
    return SampleConfig(
        method=SamplingMethod.STRATIFIED,
        size=7,
        seed=seed,
        stratum_field="Land",
        stratify_mode=StratifyMode.EQUAL,
        filter_field="Status",
        filter_value="offen",
    )


class TestSamplingPresetModel:
    def test_from_config_drops_seed(self) -> None:
        preset = SamplingPreset.from_config("Standard", _full_config(seed=12345))
        # Das Preset trägt KEINEN Seed (ziehungs-spezifisch, kein Template-Feld).
        assert not hasattr(preset, "seed")

    def test_from_config_keeps_all_sampling_fields(self) -> None:
        preset = SamplingPreset.from_config("Standard", _full_config())
        assert preset.name == "Standard"
        assert preset.method == SamplingMethod.STRATIFIED
        assert preset.size == 7
        assert preset.stratum_field == "Land"
        assert preset.stratify_mode == StratifyMode.EQUAL
        assert preset.filter_field == "Status"
        assert preset.filter_value == "offen"

    def test_to_config_injects_seed_and_reconstructs(self) -> None:
        original = _full_config(seed=4242)
        preset = SamplingPreset.from_config("Standard", original)
        rebuilt = preset.to_config(seed=4242)
        # Bis auf die ggf. abweichende Beschreibung ist das Config identisch.
        assert rebuilt == replace(original, description=rebuilt.description)

    def test_to_config_uses_given_seed(self) -> None:
        preset = SamplingPreset.from_config("Standard", _full_config(seed=1))
        assert preset.to_config(seed=2024).seed == 2024


class TestPresetSerialization:
    def test_json_roundtrip_preserves_all_fields(self) -> None:
        preset = SamplingPreset.from_config("Vorlage A", _full_config())
        restored = deserialize_presets(serialize_presets([preset]))
        assert restored == [preset]

    def test_json_roundtrip_preserves_enums_as_native_types(self) -> None:
        preset = SamplingPreset.from_config("Vorlage A", _full_config())
        restored = deserialize_presets(serialize_presets([preset]))[0]
        assert isinstance(restored.method, SamplingMethod)
        assert isinstance(restored.stratify_mode, StratifyMode)

    def test_json_roundtrip_preserves_int_filter_value(self) -> None:
        cfg = SampleConfig(
            method=SamplingMethod.SIMPLE, size=3, seed=1, filter_field="Betrag", filter_value=500
        )
        preset = SamplingPreset.from_config("Beträge", cfg)
        restored = deserialize_presets(serialize_presets([preset]))[0]
        assert restored.filter_value == 500
        assert isinstance(restored.filter_value, int)

    def test_json_roundtrip_preserves_datetime_filter_value(self) -> None:
        # Filter-Werte stammen aus distinct_values – auf Datums-Spalten sind
        # das echte datetime-Objekte. Tagged-Encoding muss sie roundtrippen.
        when = datetime(2026, 3, 1, 12, 30, 0)
        cfg = SampleConfig(
            method=SamplingMethod.SIMPLE,
            size=3,
            seed=1,
            filter_field="Buchungsdatum",
            filter_value=when,
        )
        preset = SamplingPreset.from_config("Stichtag", cfg)
        restored = deserialize_presets(serialize_presets([preset]))[0]
        assert restored.filter_value == when

    def test_json_roundtrip_preserves_date_filter_value(self) -> None:
        day = date(2026, 3, 1)
        cfg = SampleConfig(
            method=SamplingMethod.SIMPLE,
            size=3,
            seed=1,
            filter_field="Tag",
            filter_value=day,
        )
        preset = SamplingPreset.from_config("Tag", cfg)
        restored = deserialize_presets(serialize_presets([preset]))[0]
        assert restored.filter_value == day

    def test_json_roundtrip_preserves_time_filter_value(self) -> None:
        moment = time(9, 30, 0)
        cfg = SampleConfig(
            method=SamplingMethod.SIMPLE,
            size=3,
            seed=1,
            filter_field="Uhrzeit",
            filter_value=moment,
        )
        preset = SamplingPreset.from_config("Uhrzeit", cfg)
        restored = deserialize_presets(serialize_presets([preset]))[0]
        assert restored.filter_value == moment

    def test_deserialize_empty_string_yields_empty_list(self) -> None:
        assert deserialize_presets("") == []

    def test_deserialize_non_list_json_yields_empty_list(self) -> None:
        # Defensiv: korruptes/fremdes JSON (kein Array) → leere Liste, kein Crash.
        assert deserialize_presets("{}") == []
        assert deserialize_presets("42") == []

    def test_deserialize_invalid_json_syntax_yields_empty_list(self) -> None:
        # Korrupte QSettings (Hand-Edit, Teil-Write) → leere Liste statt Crash.
        assert deserialize_presets("[invalid") == []
        assert deserialize_presets("{kein json") == []
        assert deserialize_presets("überhaupt kein json") == []

    def test_deserialize_skips_malformed_items(self) -> None:
        # Einzelne kaputte Einträge (fehlende Felder, unbekanntes Enum, kein
        # Dict) werden übersprungen – gültige Presets laden trotzdem.
        good = SamplingPreset.from_config("ok", _full_config())
        raw = json.dumps(
            [
                json.loads(serialize_presets([good]))[0],
                {"name": "ohne_methode", "size": 3},  # KeyError: method fehlt
                {"method": "simple", "size": 3},  # KeyError: name fehlt
                {"name": "boeses_enum", "method": "bogus", "size": 3},  # ValueError
                "kein dict",
            ]
        )
        restored = deserialize_presets(raw)
        assert [p.name for p in restored] == ["ok"]


class TestPresetSamplingNeutrality:
    """Pflicht (Sprint 23 §5): ein Preset ändert die Ziehung nicht – es
    rekonstruiert exakt die manuelle Konfiguration."""

    @staticmethod
    def _rows() -> list[DatasetRow]:
        return [
            DatasetRow(row_id=i, values={"Land": "AUT" if i % 2 else "DEU", "Betrag": i * 10})
            for i in range(1, 21)
        ]

    def test_preset_then_draw_equals_manual_then_draw(self) -> None:
        rows = self._rows()
        manual = SampleConfig(
            method=SamplingMethod.SIMPLE,
            size=4,
            seed=777,
            filter_field="Land",
            filter_value="AUT",
        )
        preset = SamplingPreset.from_config("AUT-Stichprobe", manual)
        from_preset = preset.to_config(seed=777)

        manual_result = create_sampler(manual).sample(list(rows), population_size=len(rows))
        preset_result = create_sampler(from_preset).sample(list(rows), population_size=len(rows))

        assert manual_result.selected_row_ids == preset_result.selected_row_ids


class TestFilterOperatorPresetRoundtrip:
    """Sprint 36 (T3): das Preset trägt den Filter-Operator; alte JSON ohne
    den Key lädt rückwärtskompatibel als `EQ`."""

    @staticmethod
    def _config_with_gt() -> SampleConfig:
        return SampleConfig(
            method=SamplingMethod.SIMPLE,
            size=3,
            seed=1,
            filter_field="Betrag",
            filter_value=500,
            filter_operator=FilterOperator.GT,
        )

    def test_serialization_roundtrip_preserves_operator(self) -> None:
        preset = SamplingPreset.from_config("Beträge > 500", self._config_with_gt())
        restored = deserialize_presets(serialize_presets([preset]))[0]
        assert restored.filter_operator == FilterOperator.GT
        assert restored.filter_field == "Betrag"
        assert restored.filter_value == 500
        assert restored == preset

    def test_old_json_without_operator_key_loads_as_eq(self) -> None:
        # Kritische Garantie: bereits gespeicherte Presets (JSON ohne den
        # `filter_operator`-Key) müssen weiterhin laden – als Default `EQ`.
        raw = json.dumps(
            [
                {
                    "name": "alt",
                    "method": SamplingMethod.SIMPLE.value,
                    "size": 5,
                    "cluster_field": None,
                    "stratum_field": None,
                    "stratify_mode": StratifyMode.PROPORTIONAL.value,
                    "filter_field": "Status",
                    "filter_value": "offen",
                }
            ]
        )
        restored = deserialize_presets(raw)
        assert len(restored) == 1
        assert restored[0].filter_operator == FilterOperator.EQ
        assert restored[0].filter_field == "Status"
        assert restored[0].filter_value == "offen"

    def test_from_config_carries_operator(self) -> None:
        preset = SamplingPreset.from_config("x", self._config_with_gt())
        assert preset.filter_operator == FilterOperator.GT

    def test_to_config_passthrough_operator(self) -> None:
        preset = SamplingPreset.from_config("x", self._config_with_gt())
        assert preset.to_config(seed=7).filter_operator == preset.filter_operator
