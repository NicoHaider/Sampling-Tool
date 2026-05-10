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
    SampleConfig,
    SampleResult,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.core.rng import fisher_yates_shuffle, make_rng
from sampling_tool.core.sampling import (
    BaseSampler,
    ClusterSampler,
    SamplingError,
    SimpleSampler,
    StratifiedSampler,
    create_sampler,
)

__all__ = [
    "AuditEvent",
    "BaseSampler",
    "ClusterSampler",
    "Dataset",
    "DatasetRow",
    "Engagement",
    "SampleConfig",
    "SampleResult",
    "SamplingError",
    "SamplingMethod",
    "SimpleSampler",
    "StratifiedSampler",
    "StratifyMode",
    "create_sampler",
    "fisher_yates_shuffle",
    "make_rng",
]
