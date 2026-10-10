"""Unit-Tests für `core.provenance` – kanonisches SamplingProvenance-Modell
(Sprint 43 / S1.5b, A-001)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from sampling_tool.core.models import (
    AuditEvent,
    FilterCondition,
    FilterOperator,
    ParentRelation,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.core.provenance import SamplingProvenance, format_event_details


def _cluster_sample() -> SampleResult:
    """Cluster-Sample: `size_requested` (5) bewusst != `size_actual` (7)."""
    cfg = SampleConfig(
        method=SamplingMethod.CLUSTER,
        size=5,
        seed=99,
        cluster_field="Land",
        filters=(FilterCondition("Betrag", FilterOperator.GTE, 100),),
    )
    return SampleResult(
        config=cfg,
        selected_row_ids=(1, 2, 3, 4, 5, 6, 7),
        population_size=10,
        parent_sample_id=17,
        created_by="anna",
        drawn_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        id=3,
    )


class TestFromSampleResult:
    def test_size_requested_differs_from_actual_for_cluster(self) -> None:
        provenance = SamplingProvenance.from_sample_result(
            _cluster_sample(), dataset_id=1, app_version="0.8.0"
        )
        assert provenance.size_requested == 5
        assert provenance.size_actual == 7

    def test_dataset_id_none_is_allowed_not_guessed(self) -> None:
        provenance = SamplingProvenance.from_sample_result(
            _cluster_sample(), dataset_id=None, app_version="0.8.0"
        )
        assert provenance.dataset_id is None


class TestFilterOperatorSymbol:
    def test_known_operators_map_to_symbols(self) -> None:
        for operator, symbol in (
            (FilterOperator.EQ, "="),
            (FilterOperator.NE, "≠"),
            (FilterOperator.GT, ">"),
            (FilterOperator.GTE, "≥"),
            (FilterOperator.LT, "<"),
            (FilterOperator.LTE, "≤"),
        ):
            result = SampleResult(
                config=SampleConfig(
                    method=SamplingMethod.SIMPLE,
                    size=1,
                    seed=1,
                    filters=(FilterCondition("A", operator, 5),),
                ),
                selected_row_ids=(1,),
                population_size=1,
            )
            provenance = SamplingProvenance.from_sample_result(
                result, dataset_id=None, app_version="0.8.0"
            )
            assert provenance.filter_text == f"A {symbol} 5"


class TestToOrderedFields:
    def test_contains_all_reproduction_fields(self) -> None:
        provenance = SamplingProvenance.from_sample_result(
            _cluster_sample(), dataset_id=1, app_version="0.8.0"
        )
        fields = dict(provenance.to_ordered_fields())
        assert fields["Dataset-ID"] == "1"
        assert fields["Sampling-Methode"] == "Cluster"
        assert fields["Angeforderte Größe"] == "5"
        assert fields["Tatsächliche Größe"] == "7"
        assert fields["Population (Zeilen)"] == "10"
        assert fields["Seed"] == "99"
        assert fields["Filter"] == "Betrag ≥ 100"
        assert "Filter-Feld" not in fields
        assert fields["Cluster-Feld"] == "Land"
        assert fields["Schicht-Feld"] == "—"
        # Sprint 85 / E1: Cluster ist nicht geschichtet – kein Schichtungsmodus.
        assert "Schichtungsmodus" not in fields
        assert fields["Übergeordnete Stichprobe"] == "17"
        assert fields["Algorithmus-Version"] == "bdo-v1"
        assert fields["App-Version"] == "0.8.0"
        assert fields["Erstellt von"] == "anna"
        assert "Gezogen am" in fields

    def test_missing_optional_values_render_as_dash_not_estimated(self) -> None:
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=3, seed=1)
        result = SampleResult(config=cfg, selected_row_ids=(1, 2, 3), population_size=3)
        provenance = SamplingProvenance.from_sample_result(
            result, dataset_id=None, app_version="0.8.0"
        )
        fields = dict(provenance.to_ordered_fields())
        assert fields["Dataset-ID"] == "—"
        assert fields["Übergeordnete Stichprobe"] == "—"
        assert fields["Filter"] == "—"
        assert fields["Cluster-Feld"] == "—"
        assert fields["Schicht-Feld"] == "—"


class TestOrderedFieldsOmitIrrelevant:
    """Sprint 85 / E1: kein Schichtungsmodus außerhalb von „Geschichtet";
    seit Sprint 92 trägt die eine Zeile „Filter" den Operator mit."""

    def _labels(self, cfg: SampleConfig) -> list[str]:
        result = SampleResult(config=cfg, selected_row_ids=(1,), population_size=3)
        provenance = SamplingProvenance.from_sample_result(result, dataset_id=1, app_version="x")
        return [label for label, _ in provenance.to_ordered_fields()]

    def test_simple_without_filter_has_neither(self) -> None:
        labels = self._labels(SampleConfig(method=SamplingMethod.SIMPLE, size=1, seed=1))
        assert "Filter-Operator" not in labels
        assert "Schichtungsmodus" not in labels
        assert "Filter" in labels

    def test_stratified_with_filter_has_both(self) -> None:
        cfg = SampleConfig(
            method=SamplingMethod.STRATIFIED,
            size=1,
            seed=1,
            stratum_field="Land",
            filters=(FilterCondition("Betrag", FilterOperator.EQ, 1),),
        )
        labels = self._labels(cfg)
        assert "Filter" in labels
        assert "Schichtungsmodus" in labels


class TestToAuditDetails:
    def test_contains_all_keys_needed_for_audit_event(self) -> None:
        provenance = SamplingProvenance.from_sample_result(
            _cluster_sample(), dataset_id=1, app_version="0.8.0"
        )
        details = provenance.to_audit_details()
        assert details["dataset_id"] == 1
        assert details["method"] == "cluster"
        assert details["size_requested"] == 5
        assert details["filters"] == [{"field": "Betrag", "operator": "gte", "value": 100}]
        assert details["filter_field"] == "Betrag"
        assert details["filter_value"] == 100
        assert details["filter_operator"] == "gte"
        assert details["cluster_field"] == "Land"
        assert details["stratum_field"] is None
        assert details["stratify_mode"] == "proportional"
        assert details["parent_sample_id"] == 17
        assert details["algorithm_version"] == "bdo-v1"
        assert details["app_version"] == "0.8.0"
        assert details["created_by"] == "anna"

    def test_raw_values_not_pre_formatted_strings(self) -> None:
        """`to_audit_details` feeds `details_json` – values must stay native
        types (int/None), unlike `to_ordered_fields`'s display strings."""
        provenance = SamplingProvenance.from_sample_result(
            _cluster_sample(), dataset_id=1, app_version="0.8.0"
        )
        details = provenance.to_audit_details()
        assert isinstance(details["parent_sample_id"], int)
        assert isinstance(details["size_requested"], int)


class TestParentRelation:
    """Sprint 83 / A: Einschränkung und Nachstichprobe sind unterscheidbar;
    Bestandssamples ohne erfasste Ableitung werden als solche benannt, nie geraten."""

    @pytest.mark.parametrize(
        ("relation", "expected"),
        [
            (ParentRelation.RESTRICT, "Eingeschränkt auf Stichprobe #17"),
            (ParentRelation.SUPPLEMENT, "Nachstichprobe zu #17 (ohne Dubletten)"),
            (None, "Ableitung zu #17 nicht erfasst (älterer Stand)"),
        ],
    )
    def test_derivation_text_with_parent(
        self, relation: ParentRelation | None, expected: str
    ) -> None:
        sample = replace(_cluster_sample(), parent_relation=relation)
        provenance = SamplingProvenance.from_sample_result(
            sample, dataset_id=1, app_version="0.8.0"
        )
        assert dict(provenance.to_ordered_fields())["Ableitung"] == expected

    def test_without_parent_shows_placeholder(self) -> None:
        sample = replace(_cluster_sample(), parent_sample_id=None)
        provenance = SamplingProvenance.from_sample_result(
            sample, dataset_id=1, app_version="0.8.0"
        )
        assert dict(provenance.to_ordered_fields())["Ableitung"] == "—"

    def test_derivation_row_follows_parent_sample_id(self) -> None:
        provenance = SamplingProvenance.from_sample_result(
            _cluster_sample(), dataset_id=1, app_version="0.8.0"
        )
        labels = [label for label, _value in provenance.to_ordered_fields()]
        assert labels[labels.index("Übergeordnete Stichprobe") + 1] == "Ableitung"

    @pytest.mark.parametrize("relation", [ParentRelation.RESTRICT, ParentRelation.SUPPLEMENT])
    def test_audit_details_carry_raw_relation(self, relation: ParentRelation) -> None:
        sample = replace(_cluster_sample(), parent_relation=relation)
        details = SamplingProvenance.from_sample_result(
            sample, dataset_id=1, app_version="0.8.0"
        ).to_audit_details()
        assert details["parent_relation"] == relation.value

    def test_audit_details_relation_none_when_unrecorded(self) -> None:
        details = SamplingProvenance.from_sample_result(
            _cluster_sample(), dataset_id=1, app_version="0.8.0"
        ).to_audit_details()
        assert "parent_relation" in details
        assert details["parent_relation"] is None


def _provenance(*filters: FilterCondition) -> SamplingProvenance:
    cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=1, seed=1, filters=filters)
    result = SampleResult(config=cfg, selected_row_ids=(1,), population_size=5)
    return SamplingProvenance.from_sample_result(result, dataset_id=1, app_version="x")


class TestProvenanceFilters:
    """Sprint 92 / A5: mehrere Filter in Event, Metadaten und Anzeige."""

    _A = FilterCondition("Kostenstelle", FilterOperator.EQ, "Vertrieb")
    _B = FilterCondition("Betrag", FilterOperator.GTE, 1000)

    def test_new_event_carries_filter_list(self) -> None:
        details = _provenance(self._A, self._B).to_audit_details()
        assert details["filters"] == [
            {"field": "Kostenstelle", "operator": "eq", "value": "Vertrieb"},
            {"field": "Betrag", "operator": "gte", "value": 1000},
        ]
        # Mehrere Filter: keine Einzelschlüssel – ein alter Leser sähe sonst nur einen.
        assert "filter_field" not in details

    def test_without_filter_empty_list_and_no_legacy_keys(self) -> None:
        details = _provenance().to_audit_details()
        assert details["filters"] == []
        assert "filter_field" not in details

    def test_display_joins_with_und(self) -> None:
        provenance = _provenance(self._A, self._B)
        assert provenance.filter_text == "Kostenstelle = Vertrieb UND Betrag ≥ 1.000"
        assert dict(provenance.to_ordered_fields())["Filter"] == provenance.filter_text

    def test_new_event_details_line(self) -> None:
        details = _provenance(self._A, self._B).to_audit_details()
        event = AuditEvent(event_type="sampling", total_count=5, details=details)
        text = format_event_details(event)
        assert "Filter: Kostenstelle = Vertrieb UND Betrag ≥ 1.000" in text
        assert "Filter-Feld" not in text

    def test_single_filter_event_shows_one_filter_entry(self) -> None:
        details = _provenance(self._B).to_audit_details()
        event = AuditEvent(event_type="sampling", total_count=5, details=details)
        text = format_event_details(event)
        assert text.count("Filter:") == 1
        assert "Filter-" not in text
        assert "Filter: Betrag ≥ 1.000" in text

    def test_legacy_event_with_single_keys(self) -> None:
        """Bestandsevents (vor Sprint 92, append-only) tragen nur die Einzelschlüssel."""
        details = {
            "method": "simple",
            "filter_field": "Kostenstelle",
            "filter_value": "Vertrieb",
            "filter_operator": "eq",
            "population_basis": "filtered",
        }
        event = AuditEvent(event_type="sampling", total_count=5, details=details)
        assert format_event_details(event) == (
            "Population: 5 · Methode: Einfach · Filter: Kostenstelle = Vertrieb"
        )

    def test_legacy_event_before_sprint_89_keeps_population_note(self) -> None:
        details = {"filter_field": "Kostenstelle", "filter_value": "V", "filter_operator": "eq"}
        event = AuditEvent(event_type="sampling", total_count=5, details=details)
        assert "Filter nicht eingerechnet" in format_event_details(event)

    def test_legacy_population_note_for_old_sample_metadata(self) -> None:
        cfg = SampleConfig(method=SamplingMethod.SIMPLE, size=1, seed=1, filters=(self._A,))
        result = SampleResult(config=cfg, selected_row_ids=(1,), population_size=500)
        provenance = SamplingProvenance.from_sample_result(
            result, dataset_id=1, app_version="x", population_predates_basis=True
        )
        assert "Filter nicht eingerechnet" in provenance.population_text
