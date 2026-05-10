"""Stichprobenverfahren: Simple, Cluster, Stratified.

Drei Sampler erben von `BaseSampler`. Alle nutzen `make_rng(seed)` +
`fisher_yates_shuffle` aus `core.rng` – damit ist jede Ziehung bei gleichem
Seed und gleichem Eingabe-Datensatz bit-genau reproduzierbar.

Public API:
    SamplingError      – einheitliche Fehlerklasse
    BaseSampler        – abstrakte Basis
    SimpleSampler      – einfache Zufallsauswahl ohne Zurücklegen
    ClusterSampler     – ganze Cluster auswählen
    StratifiedSampler  – proportional/equal pro Schicht
    create_sampler()   – Factory: SamplingMethod → konkreter Sampler
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from sampling_tool.core.models import (
    Dataset,
    DatasetRow,
    SampleConfig,
    SampleResult,
    SamplingMethod,
    StratifyMode,
)
from sampling_tool.core.rng import fisher_yates_shuffle, make_rng


class SamplingError(ValueError):
    """Fachlicher Fehler bei der Stichprobenziehung (für Auditoren-UI)."""


# ---------------------------------------------------------------------------
# Basis
# ---------------------------------------------------------------------------


class BaseSampler(ABC):
    """Abstrakte Basis aller Sampler.

    Jeder konkrete Sampler implementiert `_select(...)` und liefert die
    gezogenen `row_id`s zurück. Die Basisklasse kümmert sich um:
    - Validierung der Konfiguration
    - Optionalen Vorfilter (`filter_field`/`filter_value`)
    - Deterministische Sortierung nach `row_id` vor der Ziehung
    - Verpacken in ein `SampleResult`
    """

    def __init__(self, config: SampleConfig) -> None:
        self.config = config
        self._validate_config()

    # ---- öffentliche API ------------------------------------------------

    def sample(self, dataset: Dataset) -> SampleResult:
        """Führt die Ziehung auf `dataset` aus und gibt ein `SampleResult` zurück."""
        pool = self._apply_filter(dataset.rows)
        if not pool:
            raise SamplingError("Nach Anwendung des Filters sind keine Datensätze mehr verfügbar.")

        # Stabile Sortierung – garantiert: gleicher Datensatz → gleicher Pool-Order
        # → gleicher Shuffle-Output bei gleichem Seed.
        pool_sorted = sorted(pool, key=lambda r: r.row_id)

        selected_ids = self._select(pool_sorted)

        return SampleResult(
            config=self.config,
            selected_row_ids=tuple(sorted(selected_ids)),
            population_size=len(dataset),
        )

    # ---- vor-/nachgelagerte Hilfen --------------------------------------

    def _apply_filter(self, rows: Iterable[DatasetRow]) -> list[DatasetRow]:
        """Wendet `filter_field == filter_value` an, falls konfiguriert."""
        if self.config.filter_field is None:
            return list(rows)
        field = self.config.filter_field
        value = self.config.filter_value
        return [r for r in rows if r.get(field) == value]

    # ---- Hooks für Subklassen ------------------------------------------

    @abstractmethod
    def _select(self, pool: list[DatasetRow]) -> list[int]:
        """Wählt aus `pool` (bereits gefiltert + sortiert) die Zeilen aus."""

    def _validate_config(self) -> None:
        """Basisvalidierung. Subklassen erweitern via super()._validate_config()."""
        if self.config.size < 1:
            raise SamplingError(f"Stichprobengröße muss >= 1 sein, bekommen: {self.config.size}")
        if self.config.seed < 0:
            raise SamplingError(f"Seed muss nicht-negativ sein, bekommen: {self.config.seed}")


# ---------------------------------------------------------------------------
# Simple Random Sampling
# ---------------------------------------------------------------------------


class SimpleSampler(BaseSampler):
    """Einfache Zufallsauswahl ohne Zurücklegen via Fisher-Yates."""

    def _select(self, pool: list[DatasetRow]) -> list[int]:
        n = self.config.size
        if n > len(pool):
            raise SamplingError(
                f"Stichprobengröße ({n}) ist größer als die verfügbare Population "
                f"({len(pool)}). Bitte Größe reduzieren oder Filter anpassen."
            )
        rng = make_rng(self.config.seed)
        shuffled = fisher_yates_shuffle(list(pool), rng)
        return [row.row_id for row in shuffled[:n]]


# ---------------------------------------------------------------------------
# Cluster Sampling
# ---------------------------------------------------------------------------


class ClusterSampler(BaseSampler):
    """Wählt komplette Cluster (Gruppen) aus.

    `config.size` bezeichnet hier die Anzahl der zu ziehenden Cluster, nicht
    die Anzahl der Zeilen. Die tatsächliche Zeilenzahl im Ergebnis kann größer
    sein und steht in `SampleResult.actual_size`.
    """

    def _validate_config(self) -> None:
        super()._validate_config()
        if not self.config.cluster_field:
            raise SamplingError(
                "Cluster-Sampling erfordert die Angabe eines Cluster-Feldes "
                "(SampleConfig.cluster_field)."
            )

    def _select(self, pool: list[DatasetRow]) -> list[int]:
        cluster_field = self.config.cluster_field
        assert cluster_field is not None  # durch _validate_config garantiert

        # Cluster aufbauen – Reihenfolge der Keys ist deterministisch (sorted),
        # damit das Mischen reproduzierbar wird.
        clusters: dict[Any, list[DatasetRow]] = defaultdict(list)
        for row in pool:
            clusters[row.get(cluster_field)].append(row)

        cluster_keys = sorted(clusters.keys(), key=_sort_key)

        n_clusters_requested = self.config.size
        if n_clusters_requested > len(cluster_keys):
            raise SamplingError(
                f"Es wurden {n_clusters_requested} Cluster angefordert, "
                f"aber nur {len(cluster_keys)} sind im Datensatz vorhanden."
            )

        rng = make_rng(self.config.seed)
        shuffled_keys = fisher_yates_shuffle(list(cluster_keys), rng)
        chosen_keys = shuffled_keys[:n_clusters_requested]

        return [row.row_id for key in chosen_keys for row in clusters[key]]


# ---------------------------------------------------------------------------
# Stratified Sampling
# ---------------------------------------------------------------------------


class StratifiedSampler(BaseSampler):
    """Geschichtete Zufallsauswahl, proportional ODER equal pro Schicht.

    Die Verteilung der Stichprobengröße auf die Schichten erfolgt über die
    **Largest-Remainder-Methode** (Hare-Quote). Das löst den Bug aus dem
    VBA-Vorgänger, bei dem ungerade Verteilungen oft 1–2 Stichproben "verloren"
    gegangen sind.
    """

    def _validate_config(self) -> None:
        super()._validate_config()
        if not self.config.stratum_field:
            raise SamplingError(
                "Stratified-Sampling erfordert die Angabe eines Schicht-Feldes "
                "(SampleConfig.stratum_field)."
            )

    def _select(self, pool: list[DatasetRow]) -> list[int]:
        stratum_field = self.config.stratum_field
        assert stratum_field is not None

        strata: dict[Any, list[DatasetRow]] = defaultdict(list)
        for row in pool:
            strata[row.get(stratum_field)].append(row)

        stratum_keys = sorted(strata.keys(), key=_sort_key)

        total_size = self.config.size
        if total_size < len(stratum_keys):
            raise SamplingError(
                f"Stichprobengröße ({total_size}) ist kleiner als die Anzahl der "
                f"Schichten ({len(stratum_keys)}). Pro Schicht muss mindestens "
                f"ein Element gezogen werden können."
            )

        sizes_per_stratum = self._compute_sizes(strata, stratum_keys, total_size)

        # Pro Schicht prüfen, dass genug Elemente da sind – sonst klare Fehlermeldung.
        for key, target in zip(stratum_keys, sizes_per_stratum, strict=True):
            available = len(strata[key])
            if target > available:
                raise SamplingError(
                    f"Schicht '{key}' hat nur {available} Elemente, "
                    f"benötigt werden aber {target}. Bitte Methode oder Größe anpassen."
                )

        rng = make_rng(self.config.seed)
        selected: list[int] = []
        for key, target in zip(stratum_keys, sizes_per_stratum, strict=True):
            shuffled = fisher_yates_shuffle(list(strata[key]), rng)
            selected.extend(row.row_id for row in shuffled[:target])
        return selected

    # ---- Größenverteilung ------------------------------------------------

    def _compute_sizes(
        self,
        strata: dict[Any, list[DatasetRow]],
        keys: list[Any],
        total_size: int,
    ) -> list[int]:
        """Verteilt `total_size` per Largest-Remainder auf die Schichten."""
        match self.config.stratify_mode:
            case StratifyMode.PROPORTIONAL:
                weights = [len(strata[k]) for k in keys]
            case StratifyMode.EQUAL:
                weights = [1 for _ in keys]
        return _largest_remainder(weights, total_size)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_sampler(config: SampleConfig) -> BaseSampler:
    """Liefert den passenden Sampler-Subtyp zur konfigurierten Methode."""
    match config.method:
        case SamplingMethod.SIMPLE:
            return SimpleSampler(config)
        case SamplingMethod.CLUSTER:
            return ClusterSampler(config)
        case SamplingMethod.STRATIFIED:
            return StratifiedSampler(config)


# ---------------------------------------------------------------------------
# Hilfen (modul-privat)
# ---------------------------------------------------------------------------


def _sort_key(value: Any) -> tuple[int, str]:
    """Robuster Sort-Key für gemischte Cluster-/Stratum-Werte (auch None).

    Ergebnis ist ein Tupel `(typ_rang, str_repr)` – verhindert TypeError bei
    `sorted()` über heterogene Schlüssel und bleibt deterministisch.
    """
    if value is None:
        return (0, "")
    return (1, str(value))


def _largest_remainder(weights: list[int], total: int) -> list[int]:
    """Largest-Remainder-Methode (Hare-Quote).

    Verteilt `total` so auf die `weights`, dass die Summe exakt `total` ist
    und größere Reste bevorzugt aufgerundet werden. Stabil bei Gleichstand
    (frühere Indizes gewinnen) → reproduzierbar.
    """
    weight_sum = sum(weights)
    if weight_sum == 0:
        # Sollte durch _validate_config nicht erreichbar sein, aber defensiv:
        raise SamplingError("Gewichts-Summe ist 0 – Verteilung nicht möglich.")

    quotas = [w * total / weight_sum for w in weights]
    floors = [int(q) for q in quotas]
    remainder = total - sum(floors)

    if remainder > 0:
        # Indizes nach absteigendem Bruchteil sortieren; bei Gleichstand
        # gewinnt der kleinere Index (stable sort).
        order = sorted(
            range(len(weights)),
            key=lambda i: (-(quotas[i] - floors[i]), i),
        )
        for i in order[:remainder]:
            floors[i] += 1

    return floors
