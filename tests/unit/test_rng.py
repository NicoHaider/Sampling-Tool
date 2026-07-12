"""Unit-Tests für `core/rng.py` – expliziter BitGenerator (Sprint 39 / S1.2, R-001)."""

from __future__ import annotations

import pytest
from numpy.random import PCG64

from sampling_tool.core.rng import SAMPLING_ALGORITHM_VERSION, make_rng


class TestMakeRng:
    def test_make_rng_uses_explicit_pcg64(self) -> None:
        rng = make_rng(42)
        assert isinstance(rng.bit_generator, PCG64)

    def test_negative_seed_raises(self) -> None:
        with pytest.raises(ValueError, match="nicht-negativ"):
            make_rng(-1)


class TestSamplingAlgorithmVersion:
    def test_is_bdo_v1(self) -> None:
        assert SAMPLING_ALGORITHM_VERSION == "bdo-v1"
