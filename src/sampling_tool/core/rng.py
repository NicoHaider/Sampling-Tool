"""Reproduzierbare Zufallszahlen + Fisher-Yates-Shuffle.

Zentrale Stelle für jede Form von Zufall im Tool. **Niemals `random` aus der
stdlib verwenden** – nur `make_rng(seed)` (expliziter `PCG64`-BitGenerator).
Bit-genau reproduzierbar für einen gegebenen `SAMPLING_ALGORITHM_VERSION` bei
gepinnter numpy-Range (`numpy>=2.0,<3`, siehe `pyproject.toml`); abgesichert
durch Golden-Vektoren auf Windows+macOS (`tests/unit/test_golden_vectors.py`).
"""

from __future__ import annotations

from typing import Final, TypeVar

from numpy.random import PCG64, Generator

T = TypeVar("T")

SAMPLING_ALGORITHM_VERSION: Final[str] = "bdo-v1"
"""Version des Ziehungs-Algorithmus – pro Sample persistiert (Sprint 39 / R-001).

Ändert sich nur, wenn sich der tatsächliche Ziehungs-Output ändert (neuer
BitGenerator-Rohstream, andere Shuffle-Logik, andere Verteilungsmethode).
`bdo-v1` deckt den seit Sprint 1 unveränderten Fisher-Yates-Kern ab.
"""


def make_rng(seed: int) -> Generator:
    """Erzeugt einen deterministischen NumPy-Generator (expliziter `PCG64`-Kern).

    Args:
        seed: Nicht-negativer Integer (siehe `config.SEED_MIN`/`SEED_MAX`).

    Raises:
        ValueError: Wenn `seed` negativ ist.
    """
    if seed < 0:
        raise ValueError(f"Seed muss nicht-negativ sein, bekommen: {seed}")
    return Generator(PCG64(seed))


def fisher_yates_shuffle(items: list[T], rng: Generator) -> list[T]:
    """In-place Fisher-Yates-Shuffle über den übergebenen RNG.

    Implementiert den klassischen Knuth-Algorithmus (rückwärts iterierend)
    statt `rng.shuffle()`, weil dessen interne Swap-Reihenfolge nicht
    spezifiziert ist und sich ändern darf – `rng.integers(0, i+1)` ist es.
    Zusammen mit der gepinnten numpy-Range (`>=2.0,<3`) und den Golden-
    Vektoren (`tests/unit/test_golden_vectors.py`, Win+macOS) bleibt der
    Output für `SAMPLING_ALGORITHM_VERSION` bit-genau reproduzierbar.

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
