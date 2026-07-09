"""Core-Domain: Modelle + Sampling-Algorithmen + RNG.

Re-Export aller öffentlichen Symbole, damit Konsumenten kurz importieren können:

    from sampling_tool.core import SimpleSampler, SampleConfig, SamplingMethod
"""

from __future__ import annotations

from sampling_tool.core.models import (
    AuditEvent,
    Dataset,
    DatasetRow,
    Engagement,
    FilterOperator,
    SampleConfig,
    SampleResult,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.core.presets import SamplingPreset
from sampling_tool.core.rng import fisher_yates_shuffle, make_rng
from sampling_tool.core.sampling import (
    BaseSampler,
    ClusterSampler,
    SamplingError,
    SimpleSampler,
    StratifiedSampler,
    create_sampler,
    matches_filter,
)

__all__ = [
    "AuditEvent",
    "BaseSampler",
    "ClusterSampler",
    "Dataset",
    "DatasetRow",
    "Engagement",
    "FilterOperator",
    "SampleConfig",
    "SampleResult",
    "SamplingError",
    "SamplingMethod",
    "SamplingPreset",
    "SimpleSampler",
    "StratifiedSampler",
    "StratifyMode",
    "create_sampler",
    "fisher_yates_shuffle",
    "make_rng",
    "matches_filter",
]
