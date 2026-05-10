"""Reproduzierbare Zufallszahlen + Fisher-Yates-Shuffle.

Zentrale Stelle für jede Form von Zufall im Tool. **Niemals `random` aus der
stdlib verwenden** – nur `numpy.random.default_rng(seed)`. Damit ist jede
Stichprobe bei gleichem Seed bit-genau rekonstruierbar (ISAE-3402-Pflicht).
"""

from __future__ import annotations

from typing import TypeVar

import numpy as np
from numpy.random import Generator

T = TypeVar("T")


def make_rng(seed: int) -> Generator:
    """Erzeugt einen deterministischen NumPy-Generator.

    Args:
        seed: Nicht-negativer Integer (siehe `config.SEED_MIN`/`SEED_MAX`).

    Raises:
        ValueError: Wenn `seed` negativ ist.
    """
    if seed < 0:
        raise ValueError(f"Seed muss nicht-negativ sein, bekommen: {seed}")
    return np.random.default_rng(seed)


def fisher_yates_shuffle(items: list[T], rng: Generator) -> list[T]:
    """In-place Fisher-Yates-Shuffle über den übergebenen RNG.

    Implementiert den klassischen Knuth-Algorithmus (rückwärts iterierend)
    statt `rng.shuffle()`, weil wir damit Determinismus über NumPy-Versionen
    hinweg garantieren – `rng.shuffle` darf intern optimiert werden, der
    Index-Tausch ist spezifiziert.

    Args:
        items: Liste, die gemischt wird (in-place, wird zusätzlich zurückgegeben).
        rng:   `numpy.random.Generator` – muss für Reproduzierbarkeit aus
               `make_rng(seed)` stammen.

    Returns:
        Dieselbe Liste, jetzt gemischt.
    """
    n = len(items)
    for i in range(n - 1, 0, -1):
        # rng.integers(0, i+1) → diskret-gleichverteilter Index in [0, i]
        j = int(rng.integers(0, i + 1))
        items[i], items[j] = items[j], items[i]
    return items
