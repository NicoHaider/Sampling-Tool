"""Unit-Tests für `core.provenance` – kanonisches SamplingProvenance-Modell
(Sprint 43 / S1.5b, A-001)."""

from __future__ import annotations

from datetime import UTC, datetime

from sampling_tool.core.models import (
    FilterOperator,
    SampleConfig,
    SampleResult,
    SamplingMethod,
)
from sampling_tool.core.provenance import SamplingProvenance


def _cluster_sample() -> SampleResult:
    """Cluster-Sample: `size_requested` (5) bewusst != `size_actual` (7)."""
    cfg = SampleConfig(
        method=SamplingMethod.CLUSTER,
        size=5,
        seed=99,
        cluster_field="Land",
        filter_field="Betrag",
        filter_value=100,
        filter_operator=FilterOperator.GTE,
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
                    method=SamplingMethod.SIMPLE, size=1, seed=1, filter_operator=operator
                ),
                selected_row_ids=(1,),
                population_size=1,
            )
            provenance = SamplingProvenance.from_sample_result(
                result, dataset_id=None, app_version="0.8.0"
            )
            assert provenance.filter_operator_symbol == symbol


class TestToOrderedFields:
    def test_contains_all_reproduction_fields(self) -> None:
        provenance = SamplingProvenance.from_sample_result(
            _cluster_sample(), dataset_id=1, app_version="0.8.0"
        )
        fields = dict(provenance.to_ordered_fields())
        assert fields["Dataset-ID"] == "1"
        assert fields["Sampling-Methode"] == "cluster"
        assert fields["Angeforderte Größe"] == "5"
        assert fields["Tatsächliche Größe"] == "7"
        assert fields["Population (Zeilen)"] == "10"
        assert fields["Seed"] == "99"
        assert fields["Filter-Feld"] == "Betrag"
        assert fields["Filter-Operator"] == "≥"
        assert fields["Filter-Wert"] == "100"
        assert fields["Cluster-Feld"] == "Land"
        assert fields["Stratum-Feld"] == "—"
        assert fields["Stratify-Mode"] == "proportional"
        assert fields["Parent-Sample-ID"] == "17"
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
        assert fields["Parent-Sample-ID"] == "—"
        assert fields["Filter-Feld"] == "—"
        assert fields["Filter-Wert"] == "—"
        assert fields["Cluster-Feld"] == "—"
        assert fields["Stratum-Feld"] == "—"


class TestToAuditDetails:
    def test_contains_all_keys_needed_for_audit_event(self) -> None:
        provenance = SamplingProvenance.from_sample_result(
            _cluster_sample(), dataset_id=1, app_version="0.8.0"
        )
        details = provenance.to_audit_details()
        assert details["dataset_id"] == 1
        assert details["method"] == "cluster"
        assert details["size_requested"] == 5
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
