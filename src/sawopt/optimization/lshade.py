"""A resumable, evaluator-agnostic L-SHADE style backend.

The implementation keeps search vectors in normalized coordinates and delegates
canonical mixed-integer decoding to ``canonicalizer``.  It intentionally does
not know anything about COM physics; all physical validity and metrics come
from the supplied evaluator.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from .base import OptimizerBackend
from .selection import DEFAULT_COMPARATOR, FeasibilityFirstComparator


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return {"__ndarray__": _jsonable(value.tolist()), "dtype": str(value.dtype)}
    if isinstance(value, np.integer) or isinstance(value, np.bool_):
        return value.item()
    if isinstance(value, np.floating):
        value = float(value)
        return value if np.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _from_jsonable(value: Any) -> Any:
    if isinstance(value, Mapping) and value.get("__ndarray__") is not None:
        return np.asarray(value["__ndarray__"], dtype=value.get("dtype"))
    if isinstance(value, Mapping):
        return {key: _from_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_from_jsonable(item) for item in value]
    return value


def validate_lshade_checkpoint_header(path: str | Path) -> None:
    """Reject unsupported L-SHADE state versions before parsing the payload."""
    with Path(path).open("rb") as stream:
        prefix = stream.read(512)
    match = re.search(rb'"state_version"\s*:\s*(\d+)', prefix)
    if match is None:
        raise ValueError("L-SHADE checkpoint state version header is missing")
    version = int(match.group(1))
    if version != 4:
        raise ValueError(
            f"L-SHADE checkpoint state version {version} is unsupported; expected 4"
        )


@dataclass
class _PopulationMember:
    x: np.ndarray
    physical: np.ndarray
    key: tuple
    result: Mapping[str, Any]


def parent_midpoint_repair(mutant: Sequence[float], parent: Sequence[float]):
    """Repair a normalized trial toward the violated bound and its parent.

    SHADE/L-SHADE reference implementations repair a violated component using
    the midpoint between the parent and the violated bound.  This avoids the
    artificial mass at exactly 0/1 produced by clipping.  The returned event
    data is intentionally small and deterministic so boundary pressure can be
    audited later.
    """
    trial = np.asarray(mutant, dtype=float).copy()
    parent = np.asarray(parent, dtype=float)
    if trial.shape != parent.shape:
        raise ValueError("mutant and parent must have the same shape")
    if trial.ndim != 1:
        raise ValueError("mutant and parent must be one-dimensional")
    lower, upper = [], []
    for index, value in enumerate(trial):
        if not np.isfinite(value):
            value = float(parent[index])
        if value < 0.0:
            trial[index] = 0.5 * float(parent[index])
            lower.append(index)
        elif value > 1.0:
            trial[index] = 0.5 * (1.0 + float(parent[index]))
            upper.append(index)
        else:
            trial[index] = value
    return np.clip(trial, 0.0, 1.0), {"lower": lower, "upper": upper}


def shade_success_memory(successful_f: Sequence[float], successful_cr: Sequence[float],
                         weights: Sequence[float], *, fallback_f=.5, fallback_cr=.5):
    """Return one canonical batch update for SHADE's ``M_F``/``M_CR``.

    Successful scale factors use the weighted Lehmer mean.  Successful
    crossover rates use the weighted arithmetic mean, the reference SHADE
    update.  Empty or non-positive batches leave the supplied memory values
    unchanged.  The helper is public so the formula has a direct fixture-level
    test instead of being hidden inside the optimizer loop.
    """
    f = np.asarray(successful_f, dtype=float)
    cr = np.asarray(successful_cr, dtype=float)
    weight = np.asarray(weights, dtype=float)
    if not (f.ndim == cr.ndim == weight.ndim == 1 and len(f) == len(cr) == len(weight)):
        raise ValueError("success samples and weights must be equal-length vectors")
    valid = np.isfinite(f) & np.isfinite(cr) & np.isfinite(weight) & (weight > 0.0)
    if not np.any(valid):
        return float(fallback_f), float(fallback_cr)
    f, cr, weight = f[valid], np.clip(cr[valid], 0.0, 1.0), weight[valid]
    f_denominator = float(np.sum(weight * f))
    weight_total = float(np.sum(weight))
    new_f = float(np.sum(weight * f * f) / f_denominator) if f_denominator > 0 else float(fallback_f)
    new_cr = float(np.sum(weight * cr) / weight_total) if weight_total > 0 else float(fallback_cr)
    return float(np.clip(new_f, 0.0, 1.0)), float(np.clip(new_cr, 0.0, 1.0))


class LShadeBackend(OptimizerBackend):
    """L-SHADE with exact NumPy RNG continuation and canonical caching."""

    name = "lshade"
    design_space_version = 1
    frequency_grid_version = 1
    population_schedule_identifier = "lshade_linear_population_v1"
    population_schedule_version = 1

    def __init__(self, bounds, *, seed: int = 0, config: Mapping[str, Any] | None = None,
                 integer_indices=(1, 2, 3), canonicalizer: Callable | None = None,
                 comparator: FeasibilityFirstComparator | None = None,
                 source_config_fingerprint: str | None = None, **options):
        self.bounds = np.asarray(bounds, dtype=float)
        if self.bounds.ndim != 2 or self.bounds.shape[1] != 2 or np.any(self.bounds[:, 1] <= self.bounds[:, 0]):
            raise ValueError("bounds must be a (D, 2) array with positive spans")
        self.dimension = int(len(self.bounds))
        self.config = dict(config or {})
        self.config.update(options)
        self.hard_bounds = np.asarray(self.config.get("hard_bounds", self.bounds), dtype=float)
        if (self.hard_bounds.shape != self.bounds.shape
                or np.any(self.hard_bounds[:, 1] <= self.hard_bounds[:, 0])
                or np.any(self.bounds[:, 0] < self.hard_bounds[:, 0])
                or np.any(self.bounds[:, 1] > self.hard_bounds[:, 1])):
            raise ValueError("hard_bounds must contain the active bounds")
        if canonicalizer is None:
            canonicalizer = self.config.pop("canonicalize", None)
        self.integer_indices = tuple(int(i) for i in integer_indices)
        self.canonicalizer = canonicalizer or self._default_canonicalizer
        self.comparator = comparator or DEFAULT_COMPARATOR
        self.source_config_fingerprint = source_config_fingerprint
        self.rng = np.random.default_rng(int(seed))
        self.initial_population_size = max(
            int(self.config.get("initial_population", self.config.get("initial_population_per_dimension", 18) * self.dimension)),
            int(self.config.get("min_population", 4)),
        )
        self.minimum_population_size = int(self.config.get("min_population", 4))
        if self.minimum_population_size < 4:
            raise ValueError("min_population must be at least four")
        self.history_size = int(self.config.get("history_size", 6))
        if self.history_size <= 0:
            raise ValueError("history_size must be positive")
        self.pbest_max_fraction = float(self.config.get(
            "pbest_max_fraction", self.config.get("pbest_fraction", .20)))
        self.archive_rate = float(self.config.get("archive_rate", 1.0))
        self.max_duplicate_retries = int(self.config.get("max_duplicate_retries", 5))
        self.total_budget = int(self.config.get("total_budget", self.config.get("max_unique_evaluations", 1)))
        self.hard_max_budget = int(self.config.get("hard_max_budget", self.total_budget))
        self.population_schedule_terminal_budget = int(self.config.get(
            "population_schedule_terminal_budget", self.hard_max_budget))
        if self.hard_max_budget <= 0 or self.population_schedule_terminal_budget <= 0:
            raise ValueError("hard_max_budget and population_schedule_terminal_budget must be positive")
        if self.population_schedule_terminal_budget > self.hard_max_budget:
            raise ValueError("population schedule horizon cannot exceed hard_max_budget")
        self.canonical_space_size = self.config.get("canonical_space_size")
        if self.canonical_space_size is not None:
            self.canonical_space_size = int(self.canonical_space_size)
            if self.canonical_space_size <= 0:
                raise ValueError("canonical_space_size must be positive")
        elif set(self.integer_indices) >= set(range(self.dimension)):
            # A fully integer normalized domain has a finite canonical space
            # under the default rounding policy.  This is a formal exhaustion
            # certificate; mixed/continuous spaces deliberately remain open.
            cardinality = 1
            for low, high in self.bounds:
                cardinality *= int(np.floor(high + .5) - np.ceil(low - .5) + 1)
            self.canonical_space_size = max(1, cardinality)
        self.compact_history_cache = bool(self.config.get("compact_history_cache", False))
        self.historical_finalist_count = int(self.config.get("historical_finalist_count", 16))
        if self.historical_finalist_count <= 0:
            raise ValueError("historical_finalist_count must be positive")
        self.exhaustion_duplicate_streak = self.config.get("exhaustion_duplicate_streak")
        if self.exhaustion_duplicate_streak is not None:
            self.exhaustion_duplicate_streak = int(self.exhaustion_duplicate_streak)
            if self.exhaustion_duplicate_streak <= 0:
                raise ValueError("exhaustion_duplicate_streak must be positive")
        self.memory_update_batch_size = int(self.config.get("memory_update_batch_size", 0))
        if self.memory_update_batch_size < 0:
            raise ValueError("memory_update_batch_size cannot be negative")
        self.initial_requested_budget = int(self.config.get("requested_unique_budget", self.total_budget))
        self._reset_state()

    def _reset_state(self):
        self.evaluator = None
        self._population: list[_PopulationMember] = []
        self._archive: list[np.ndarray] = []
        self._cache: dict[tuple, Mapping[str, Any]] = {}
        # A canonical design is counted once for the unique-design budget,
        # but its physics result is grid-versioned.  This prevents a result
        # from the pre-exchange grid being reused after an adaptive refresh.
        self._cache_frequency_versions: dict[tuple, int] = {}
        self._history_rank_index: dict[tuple, tuple[tuple[float, ...], tuple[float, ...], int]] = {}
        self._history_next_order = 0
        self._historical_finalist_keys: list[tuple] = []
        self._incumbent: Mapping[str, Any] | None = None
        self._incumbent_key = None
        self.m_f = np.full(self.history_size, .5, dtype=float)
        self.m_cr = np.full(self.history_size, .5, dtype=float)
        self.history_index = 0
        self.unique_evaluations = 0
        self.proposals_total = 0
        self.raw_offspring_count = 0
        self.duplicate_count = 0
        self.duplicate_by_group = {"integer": 0, "continuous": 0}
        self.cache_hits = 0
        self.generations = 0
        self.duplicate_streak = 0
        self.search_space_exhausted = False
        self.best_so_far_trace: list[dict[str, Any]] = []
        self.population_trace: list[dict[str, Any]] = []
        self.archive_trace: list[dict[str, Any]] = []
        self.active_frequency_grid = []
        self.frequency_grid_version = 1
        self.active_bounds = self.bounds.tolist()
        self.boundary_repair_counts = {
            "lower": [0 for _ in range(self.dimension)],
            "upper": [0 for _ in range(self.dimension)],
        }
        self._successful_f: list[float] = []
        self._successful_cr: list[float] = []
        self._successful_weights: list[float] = []
        self._memory_batch_proposals = 0
        self.convergence_state: dict[str, Any] = {}
        self._target_budget = max(self.initial_requested_budget, self.total_budget)

    def _default_canonicalizer(self, physical: np.ndarray):
        value = np.asarray(physical, dtype=float).copy()
        for index in self.integer_indices:
            if 0 <= index < len(value):
                value[index] = np.floor(value[index] + .5)
        value = np.clip(value, self.bounds[:, 0], self.bounds[:, 1])
        return value, tuple(float(item) for item in value)

    def _normalize(self, physical: np.ndarray) -> np.ndarray:
        low, high = self.bounds[:, 0], self.bounds[:, 1]
        return np.clip((np.asarray(physical, dtype=float) - low) / (high - low), 0.0, 1.0)

    def _physical(self, x: np.ndarray) -> np.ndarray:
        low, high = self.bounds[:, 0], self.bounds[:, 1]
        return low + np.clip(np.asarray(x, dtype=float), 0.0, 1.0) * (high - low)

    def _canonical(self, x: np.ndarray):
        physical = self._physical(x)
        returned = self.canonicalizer(physical)
        if isinstance(returned, tuple) and len(returned) == 2:
            canonical, key = returned
        else:
            canonical = returned
            key = tuple(float(item) for item in np.asarray(canonical, dtype=float))
        canonical = np.asarray(canonical, dtype=float)
        if canonical.shape != (self.dimension,) or not np.isfinite(canonical).all():
            raise ValueError("canonicalizer must return a finite vector with the optimizer dimension")
        if np.any(canonical < self.hard_bounds[:, 0]) or np.any(canonical > self.hard_bounds[:, 1]):
            raise ValueError("canonicalizer returned a design outside immutable hard bounds")
        return canonical, tuple(key)

    def _observe_q1(self, event, **data):
        """Inert opt-in observation; no arithmetic/state/RNG changes when absent."""
        observer = getattr(self, "_q1_observer", None)
        if observer is not None:
            observer(event, data)

    def _evaluate(self, x: np.ndarray):
        self.proposals_total += 1
        canonical, key = self._canonical(x)
        is_new_design = key not in self._cache_frequency_versions
        if not is_new_design:
            cached_version = self._cache_frequency_versions.get(key)
            if cached_version == int(self.frequency_grid_version):
                self.cache_hits += 1
                return canonical, key, self._cache.get(key), True
            # The design remains a known unique design, but its result is
            # stale for the active frequency grid.  Refresh it without
            # charging the unique-design budget a second time.
        if self.evaluator is None:
            raise RuntimeError("Backend is not initialized")
        result = self.evaluator(canonical.copy())
        if not isinstance(result, Mapping):
            raise TypeError("evaluator must return a mapping")
        result = copy.deepcopy(dict(result))
        self._cache_frequency_versions[key] = int(self.frequency_grid_version)
        if self.compact_history_cache:
            self._update_compact_history(key, canonical, result)
        else:
            self._cache[key] = result
        if is_new_design:
            self.unique_evaluations += 1
        return canonical, key, result, False

    def initialize(self, evaluator, *, population=None, comparator=None):
        if comparator is not None:
            self.comparator = comparator
        self.evaluator = evaluator
        if population is None:
            size = min(self.initial_population_size, max(self.minimum_population_size, self._target_budget))
            population = self.rng.uniform(0.0, 1.0, size=(size, self.dimension))
        raw = np.asarray(population, dtype=float)
        if raw.ndim != 2 or raw.shape[1] != self.dimension:
            raise ValueError("population must be a (n, D) array")
        self._population = []
        seen = set()
        for row in raw:
            member = self._make_member(np.clip(row, 0.0, 1.0))
            if member is None:
                self.duplicate_count += 1
                self.duplicate_streak += 1
                continue
            if member.key in seen:
                self.duplicate_count += 1
                self.duplicate_streak += 1
                continue
            self._population.append(member)
            seen.add(member.key)
            self._observe_q1("initial_member", index=len(self._population) - 1)
        if len(self._population) < self.minimum_population_size:
            raise ValueError("initial population does not contain enough canonical designs")
        self.initial_population_size = len(self._population)
        if self.memory_update_batch_size == 0:
            self.memory_update_batch_size = self.initial_population_size
        self._target_budget = max(self._target_budget, self.unique_evaluations)
        self._check_search_space_exhausted()
        self._update_incumbent()
        self._record_trace()

    def set_evaluator(self, evaluator):
        """Attach a process-local evaluator after loading a checkpoint."""
        self.evaluator = evaluator

    def _make_member(self, x):
        return self._make_member_result(x, allow_cached=True)

    def _make_member_result(self, x, *, allow_cached: bool):
        canonical, key, result, cached = self._evaluate(x)
        if cached and (not allow_cached or result is None):
            return None
        return _PopulationMember(np.asarray(x, dtype=float).copy(), canonical, key, result)

    def _update_compact_history(self, key, canonical, result):
        """Update the small all-design rank/vector index and bounded payload cache."""
        previous = self._history_rank_index.get(key)
        order = previous[2] if previous is not None else self._history_next_order
        if previous is None:
            self._history_next_order += 1
        try:
            vector = np.asarray(result.get("candidate_vector", canonical), dtype=float)
            if vector.ndim != 1 or not np.isfinite(vector).all():
                vector = np.asarray(canonical, dtype=float)
        except (TypeError, ValueError):
            vector = np.asarray(canonical, dtype=float)
        rank_key = tuple(float(value) for value in self.comparator.rank_key(result))
        self._history_rank_index[key] = (rank_key, tuple(float(v) for v in vector), order)

        was_finalist = key in self._historical_finalist_keys
        if was_finalist:
            candidates = self._history_rank_index.keys()
        else:
            candidates = [*self._historical_finalist_keys, key]
        ranked = sorted(
            candidates,
            key=lambda item: (self._history_rank_index[item][0], self._history_rank_index[item][2]),
        )
        self._historical_finalist_keys = list(ranked[:self.historical_finalist_count])

        # Keep full records only for the bounded shortlist. Population and
        # incumbent records have their own owners in optimizer state.
        finalists = set(self._historical_finalist_keys)
        for cached_key in tuple(self._cache):
            if cached_key not in finalists:
                del self._cache[cached_key]
        if key in finalists:
            self._cache[key] = result

    def historical_finalists(self, count: int | None = None) -> list[dict[str, Any]]:
        """Return exact stable-order best historical candidates for this grid state."""
        limit = self.historical_finalist_count if count is None else max(0, int(count))
        if not self.compact_history_cache:
            return [dict(value) for value in sorted(
                self._cache.values(), key=self.comparator.rank_key,
            )[:limit]]
        keys = self._historical_finalist_keys[:limit]
        return [
            {
                "candidate_vector": list(self._history_rank_index[key][1]),
                "history_rank_key": list(self._history_rank_index[key][0]),
            }
            for key in keys
        ]

    def _update_incumbent(self):
        if not self._population:
            return
        best = min(self._population, key=lambda item: self.comparator.rank_key(item.result))
        if self._incumbent is None or self.comparator.better(best.result, self._incumbent):
            self._incumbent = copy.deepcopy(dict(best.result))
            self._incumbent_key = best.key

    def _record_trace(self):
        self._update_incumbent()
        if self._incumbent is None:
            return
        primary_metric = getattr(self.comparator, "primary_metric", None)
        row = {
            "unique_evaluation": int(self.unique_evaluations),
            "population_size": len(self._population),
            "frequency_grid_version": int(self.frequency_grid_version),
            "comparator": type(self.comparator).__name__,
            "rank_key": list(self.comparator.rank_key(self._incumbent)),
            "primary_metric": (
                primary_metric(self._incumbent) if callable(primary_metric) else None
            ),
            "primary_metric_feasible": (
                bool(self._incumbent["feasible"])
                if isinstance(self._incumbent.get("feasible"), (bool, np.bool_))
                else None
            ),
        }
        previous_key = tuple(np.inf if value is None else value
                             for value in (self.best_so_far_trace[-1]["rank_key"]
                                           if self.best_so_far_trace else ()))
        previous_version = (
            self.best_so_far_trace[-1].get("frequency_grid_version")
            if self.best_so_far_trace else None
        )
        if (not self.best_so_far_trace
                or previous_version is None
                or int(previous_version) != int(self.frequency_grid_version)
                or tuple(row["rank_key"]) < previous_key):
            self.best_so_far_trace.append(row)
        self.population_trace.append({
            "unique_evaluation": int(self.unique_evaluations),
            "population_size": len(self._population),
            "frequency_grid_version": int(self.frequency_grid_version),
        })
        self.archive_trace.append({
            "unique_evaluation": int(self.unique_evaluations),
            "archive_size": len(self._archive),
            "frequency_grid_version": int(self.frequency_grid_version),
        })

    def _ordered_indices(self):
        return sorted(range(len(self._population)), key=lambda i: self.comparator.rank_key(self._population[i].result))

    def _sample_parameters(self, memory_index):
        f = 0.0
        for _ in range(100):
            f = self.rng.standard_cauchy() * .1 + self.m_f[memory_index]
            if np.isfinite(f) and f > 0:
                break
        if not np.isfinite(f) or f <= 0:
            f = float(self.m_f[memory_index])
        f = float(np.clip(f, np.finfo(float).eps, 1.0))
        cr = float(np.clip(self.rng.normal(self.m_cr[memory_index], .1), 0.0, 1.0))
        return f, cr

    def _resize_population(self, consumed):
        # Observation checkpoints never change the L-SHADE horizon.  The
        # horizon is fixed at construction time for deterministic continuation.
        target = self.population_size_for_budget(consumed)
        target = max(self.minimum_population_size, min(len(self._population), target))
        if target < len(self._population):
            keep = self._ordered_indices()[:target]
            self._population = [self._population[index] for index in keep]
            self._trim_archive(target)

    def population_size_for_budget(self, unique_evaluations: int) -> int:
        """Return the deterministic L-SHADE population schedule value."""
        horizon = max(int(self.population_schedule_terminal_budget), 1)
        fraction = min(1.0, max(0.0, float(unique_evaluations) / float(horizon)))
        return int(round(
            self.initial_population_size
            - fraction * (self.initial_population_size - self.minimum_population_size)
        ))

    def _archive_key(self, vector):
        return tuple(float(value) for value in np.asarray(vector, dtype=float))

    def _trim_archive(self, limit=None):
        limit = max(1, int(limit if limit is not None else len(self._population)))
        # Keep the archive duplicate-free and use random removal only when its
        # canonical L-SHADE capacity is exceeded.
        unique = []
        seen = set()
        for vector in self._archive:
            key = self._archive_key(vector)
            if key not in seen:
                unique.append(np.asarray(vector, dtype=float).copy())
                seen.add(key)
        self._archive = unique
        while len(self._archive) > limit:
            del self._archive[int(self.rng.integers(0, len(self._archive)))]

    def _archive_insert(self, vector):
        key = self._archive_key(vector)
        if key not in {self._archive_key(value) for value in self._archive}:
            self._archive.append(np.asarray(vector, dtype=float).copy())
        self._trim_archive(len(self._population))

    def _repair_boundary(self, mutant, parent):
        repaired, events = parent_midpoint_repair(mutant, parent)
        for direction, indices in events.items():
            for index in indices:
                self.boundary_repair_counts[direction][index] += 1
        return repaired

    def _check_search_space_exhausted(self):
        if self.canonical_space_size is not None and self.unique_evaluations >= self.canonical_space_size:
            self.search_space_exhausted = True
        if (self.exhaustion_duplicate_streak is not None
                and self.duplicate_streak >= self.exhaustion_duplicate_streak):
            # This secondary path is opt-in and is treated as a formal policy
            # supplied by the caller for a known finite/collapsed space.
            self.search_space_exhausted = True

    def _unseen_proposal(self):
        """Find a fresh point for a known finite canonical space.

        Mixed continuous spaces keep the normal mutation path.  For a fully
        integer finite space, deterministic enumeration is used when the space
        is small enough; otherwise bounded random retries are sufficient.  The
        fallback prevents canonical quantization from starving the exact
        budget without changing the normal L-SHADE trajectory in large spaces.
        """
        seen = set(self._cache_frequency_versions)
        if (self.canonical_space_size is not None
                and set(self.integer_indices) >= set(range(self.dimension))
                and self.canonical_space_size <= 100_000):
            import itertools
            ranges = [range(int(np.ceil(low)), int(np.floor(high)) + 1)
                      for low, high in self.bounds]
            for values in itertools.product(*ranges):
                physical = np.asarray(values, dtype=float)
                _canonical, key = self._canonical(self._normalize(physical))
                if key not in seen:
                    return self._normalize(physical)
        self._observe_q1("fallback_invoked")
        for _ in range(256):
            self._observe_q1("before_proposal", phase="fallback", attempt=_)
            proposal = self.rng.uniform(0.0, 1.0, self.dimension)
            _canonical, key = self._canonical(proposal)
            self._observe_q1("proposal", phase="fallback", attempt=_, x=proposal,
                             physical=_canonical, key=key, duplicate=key in seen)
            if key not in seen:
                return proposal
        return None

    def _flush_success_memory(self):
        if not self._successful_f:
            self._memory_batch_proposals = 0
            return
        memory_index = int(self.history_index)
        self.m_f[memory_index], self.m_cr[memory_index] = shade_success_memory(
            self._successful_f, self._successful_cr, self._successful_weights,
            fallback_f=self.m_f[memory_index], fallback_cr=self.m_cr[memory_index],
        )
        self.history_index = (self.history_index + 1) % self.history_size
        self._successful_f.clear()
        self._successful_cr.clear()
        self._successful_weights.clear()
        self._memory_batch_proposals = 0

    def _record_success(self, f, cr, weight):
        self._successful_f.append(float(f))
        self._successful_cr.append(float(cr))
        self._successful_weights.append(float(max(weight, np.finfo(float).eps)))

    def _maybe_flush_success_memory(self):
        if self._memory_batch_proposals >= max(1, self.memory_update_batch_size):
            self._flush_success_memory()

    def _sample_indices(self, target_index, pbest_count):
        n = len(self._population)
        pbest_pool = self._ordered_indices()[:max(2, min(pbest_count, n))]
        pbest = int(self.rng.choice([index for index in pbest_pool if index != target_index] or pbest_pool))
        first_candidates = [index for index in range(n) if index != target_index and index != pbest]
        r1_index = int(self.rng.choice(first_candidates)) if first_candidates else target_index
        union = [self._population[index].x for index in range(n) if index not in (target_index, r1_index)]
        union.extend(self._archive)
        if not union:
            union = [self._population[r1_index].x]
        r2 = np.asarray(union[int(self.rng.integers(0, len(union)))], dtype=float)
        return pbest, r1_index, r2

    def _generation(self, target_budget):
        """Advance by one offspring.

        Treating one offspring as the resumable quantum makes a checkpoint at
        any unique-design budget identical to the same uninterrupted trajectory
        continued to that budget.  Success memories are updated with the
        standard weighted Lehmer means using the successful parameter pair.
        """
        if self.unique_evaluations >= target_budget or self.search_space_exhausted:
            return False
        target_index = int(self.generations % len(self._population))
        target = self._population[target_index]
        self._observe_q1("parameters", target=target_index)
        memory_index = int(self.rng.integers(0, self.history_size))
        f, cr = self._sample_parameters(memory_index)
        pbest_count = max(2, int(np.ceil(self.pbest_max_fraction * len(self._population))))
        trial_member = None
        accepted = False
        attempts = max(0, self.max_duplicate_retries) + 1 + 64
        for _attempt in range(attempts):
            if _attempt > self.max_duplicate_retries:
                trial = self._unseen_proposal()
                if trial is None:
                    self._check_search_space_exhausted()
                    break
            else:
                self._observe_q1("before_proposal", phase="normal", attempt=_attempt)
                pbest, r1, r2 = self._sample_indices(target_index, pbest_count)
                mutant = target.x + f * (self._population[pbest].x - target.x) + f * (self._population[r1].x - r2)
                mutant = self._repair_boundary(mutant, target.x)
                forced = int(self.rng.integers(0, self.dimension))
                mask = self.rng.random(self.dimension) < cr
                mask[forced] = True
                trial = np.where(mask, mutant, target.x)
                # Canonicalization is pure; opt-in only, and the evaluator still
                # runs its original path below. No returned value is substituted.
                if getattr(self, "_q1_observer", None) is not None:
                    observed_physical, observed_key = self._canonical(trial)
                    self._observe_q1("proposal", phase="normal", attempt=_attempt, x=trial,
                                     physical=observed_physical, key=observed_key,
                                     duplicate=observed_key in self._cache_frequency_versions)
            self.raw_offspring_count += 1
            candidate, key, result, cached = self._evaluate(trial)
            duplicate = bool(cached or key == target.key
                             or any(key == item.key for item in self._population if item is not target))
            if duplicate:
                self.duplicate_count += 1
                self.duplicate_streak += 1
                if self.integer_indices:
                    self.duplicate_by_group["integer"] += 1
                if len(self.integer_indices) < self.dimension:
                    self.duplicate_by_group["continuous"] += 1
                self._check_search_space_exhausted()
                if self.search_space_exhausted:
                    break
                # A cached canonical design is a proposal only.  Never put it
                # back into the active population; draw another proposal.
                continue
            self.duplicate_streak = 0
            trial_member = _PopulationMember(np.asarray(trial, dtype=float).copy(), candidate, key, result)
            accepted = True
            break
        if accepted and trial_member is not None and self.comparator.better(trial_member.result, target.result):
            self._archive_insert(target.x)
            self._population[target_index] = trial_member
            self._record_success(f, cr, self.comparator.improvement(target.result, trial_member.result))
        self._memory_batch_proposals += 1
        self._maybe_flush_success_memory()
        self.generations += 1
        if self.unique_evaluations > 0:
            self._resize_population(self.unique_evaluations)
            self._record_trace()
        return accepted

    def advance_to_unique_budget(self, target_unique_evals: int, evaluator=None, **_kwargs):
        target = int(target_unique_evals)
        if target < 1:
            raise ValueError("target_unique_evals must be positive")
        if evaluator is not None:
            self.evaluator = evaluator
        if target > self.hard_max_budget:
            raise ValueError("target_unique_evals exceeds hard_max_budget")
        self._target_budget = max(self._target_budget, target)
        self.initial_requested_budget = max(self.initial_requested_budget, target)
        if not self._population:
            raise RuntimeError("initialize must be called before advance_to_unique_budget")
        while self.unique_evaluations < target and not self.search_space_exhausted:
            self._generation(target)
        return self.summary()

    def set_frequency_grid(self, frequencies_hz, version: int | None = None):
        self.active_frequency_grid = np.asarray(frequencies_hz, dtype=float).tolist()
        self.frequency_grid_version = int(version if version is not None else self.frequency_grid_version + 1)

    def exchange_frequency_grid(self, frequencies_hz, evaluator=None, version: int | None = None):
        """Reevaluate the active population after adding frequencies.

        The canonical cache identity is unchanged, so this refresh does not
        charge unique designs.  The caller's evaluator should use the supplied
        grid; this method only coordinates population refresh and ranking.
        """
        if evaluator is not None:
            self.evaluator = evaluator
        if self.evaluator is None:
            raise RuntimeError("Backend is not initialized")
        # Change the active version before re-evaluation so refreshed cache
        # entries are tagged correctly.  The unique-design counter remains
        # unchanged because these are validation refreshes, not new designs.
        self.set_frequency_grid(frequencies_hz, version=version)
        for index, member in enumerate(self._population):
            result = self.evaluator(member.physical.copy())
            if not isinstance(result, Mapping):
                raise TypeError("evaluator must return a mapping")
            result = copy.deepcopy(dict(result))
            self._cache_frequency_versions[member.key] = int(self.frequency_grid_version)
            if self.compact_history_cache:
                self._update_compact_history(member.key, member.physical, result)
            else:
                self._cache[member.key] = result
            self._population[index] = _PopulationMember(member.x, member.physical, member.key, result)
        # An incumbent from the old frequency grid is not a valid candidate
        # on the new grid.  Always rebuild it from the refreshed population.
        self._incumbent = None
        self._incumbent_key = None
        self._update_incumbent()
        self._record_trace()

    def update_bounds(self, bounds, *, design_space_version: int | None = None,
                      inject_fraction: float = .20, rng: np.random.Generator | None = None):
        """Re-normalize survivors after a soft-bound expansion.

        The archive is cleared by policy, memories are preserved, and a small
        new-region slice is sampled.  The caller remains responsible for
        deciding whether expansion is justified.
        """
        old_bounds = self.bounds.copy()
        new_bounds = np.asarray(bounds, dtype=float)
        if (new_bounds.shape != old_bounds.shape or np.any(new_bounds[:, 1] <= new_bounds[:, 0])
                or np.any(new_bounds[:, 0] < self.hard_bounds[:, 0])
                or np.any(new_bounds[:, 1] > self.hard_bounds[:, 1])
                or np.any(new_bounds[:, 0] > old_bounds[:, 0])
                or np.any(new_bounds[:, 1] < old_bounds[:, 1])):
            raise ValueError("invalid expanded bounds")
        survivors = list(self._population)
        self.bounds = new_bounds
        self.active_bounds = new_bounds.tolist()
        self._population = []
        for survivor in survivors:
            normalized = self._normalize(survivor.physical)
            canonical, key, result, cached = self._evaluate(normalized)
            if cached and result is None:
                result = survivor.result
            self._population.append(_PopulationMember(
                normalized, canonical, key, result,
            ))
        count = max(0, int(np.ceil(len(self._population) * float(inject_fraction))))
        generator = rng or self.rng
        occupied = {item.key for item in self._population}
        for index in range(count):
            for _attempt in range(100):
                candidate = self._make_member_result(
                    generator.uniform(0.0, 1.0, self.dimension),
                    allow_cached=not self.compact_history_cache,
                )
                if candidate is None:
                    continue
                if candidate.key not in occupied:
                    occupied.add(candidate.key)
                    self._population[-1 - index] = candidate
                    break
        self._archive.clear()
        self.design_space_version = int(design_space_version or self.design_space_version + 1)
        self.convergence_state = {}
        self._check_search_space_exhausted()
        self._record_trace()

    def population(self):
        return np.asarray([item.x for item in self._population], dtype=float)

    def incumbent(self):
        return copy.deepcopy(self._incumbent)

    def summary(self):
        return {
            "backend": self.name,
            "unique_evaluations": int(self.unique_evaluations),
            "requested_unique_budget": int(self.initial_requested_budget),
            "actual_unique_budget": int(self.unique_evaluations),
            "proposals_total": int(self.proposals_total),
            "raw_offspring_count": int(self.raw_offspring_count),
            "duplicate_count": int(self.duplicate_count),
            "duplicate_rate": float(self.duplicate_count / max(self.proposals_total, 1)),
            "duplicate_rate_by_group": {
                key: float(value / max(self.raw_offspring_count, 1))
                for key, value in self.duplicate_by_group.items()
            },
            "cache_hits": int(self.cache_hits),
            "cache_hit_rate": float(self.cache_hits / max(self.proposals_total, 1)),
            "population_size": len(self._population),
            "current_budget": int(self.unique_evaluations),
            "terminal_budget": int(self.population_schedule_terminal_budget),
            "initial_population": int(self.initial_population_size),
            "current_population": int(len(self._population)),
            "population_schedule_identifier": self.population_schedule_identifier,
            "population_schedule_version": int(self.population_schedule_version),
            "generations": int(self.generations),
            "search_space_exhausted": bool(self.search_space_exhausted),
            "population_schedule_terminal_budget": int(self.population_schedule_terminal_budget),
            "terminal_budget": int(self.population_schedule_terminal_budget),
            "current_budget": int(self.unique_evaluations),
            "initial_population": int(self.initial_population_size),
            "current_population": int(len(self._population)),
            "population_schedule_identifier": self.population_schedule_identifier,
            "population_schedule_version": int(self.population_schedule_version),
            "hard_max_budget": int(self.hard_max_budget),
            "boundary_repair_counts": copy.deepcopy(self.boundary_repair_counts),
            "archive_size": len(self._archive),
            "m_f": self.m_f.tolist(), "m_cr": self.m_cr.tolist(),
            "incumbent": self.incumbent(),
            "best_so_far_trace": copy.deepcopy(self.best_so_far_trace),
            "population_trace": copy.deepcopy(self.population_trace),
            "archive_trace": copy.deepcopy(self.archive_trace),
        }

    def state_dict(self) -> dict[str, Any]:
        return {
            "state_version": 4,
            "backend": self.name,
            "compact_history_cache": bool(self.compact_history_cache),
            "historical_finalist_count": int(self.historical_finalist_count),
            "bounds": self.bounds.tolist(),
            "hard_bounds": self.hard_bounds.tolist(),
            "active_bounds": copy.deepcopy(self.active_bounds),
            "population": [{"x": item.x.tolist(), "physical": item.physical.tolist(),
                            "key": list(item.key), "result": _jsonable(item.result)} for item in self._population],
            "archive": [item.tolist() for item in self._archive],
            "cache": ([] if self.compact_history_cache else [
                [list(key), _jsonable(value)] for key, value in self._cache.items()
            ]),
            "retained_results": ([
                [list(key), _jsonable(value)] for key, value in self._cache.items()
            ] if self.compact_history_cache else []),
            "cache_frequency_versions": ([] if self.compact_history_cache else [
                [list(key), int(version)]
                for key, version in self._cache_frequency_versions.items()
            ]),
            "compact_history_index": ([
                [list(key), int(self._cache_frequency_versions[key]), _jsonable(rank_key),
                 list(candidate_vector), int(order)]
                for key, (rank_key, candidate_vector, order) in self._history_rank_index.items()
            ] if self.compact_history_cache else []),
            "m_f": self.m_f.tolist(), "m_cr": self.m_cr.tolist(),
            "history_index": int(self.history_index),
            "current_population_size": len(self._population),
            "rng_state": _jsonable(self.rng.bit_generator.state),
            "initial_population_size": int(self.initial_population_size),
            "minimum_population_size": int(self.minimum_population_size),
            "memory_update_batch_size": int(self.memory_update_batch_size),
            "memory_batch_proposals": int(self._memory_batch_proposals),
            "successful_f": _jsonable(self._successful_f),
            "successful_cr": _jsonable(self._successful_cr),
            "successful_weights": _jsonable(self._successful_weights),
            "unique_evaluations": int(self.unique_evaluations),
            "requested_unique_budget": int(self.initial_requested_budget),
            "actual_unique_budget": int(self.unique_evaluations),
            "proposals_total": int(self.proposals_total),
            "raw_offspring_count": int(self.raw_offspring_count),
            "duplicate_count": int(self.duplicate_count), "cache_hits": int(self.cache_hits),
            "duplicate_by_group": copy.deepcopy(self.duplicate_by_group),
            "generations": int(self.generations),
            "duplicate_streak": int(self.duplicate_streak),
            "search_space_exhausted": bool(self.search_space_exhausted),
            "boundary_repair_counts": copy.deepcopy(self.boundary_repair_counts),
            "incumbent": _jsonable(self._incumbent), "incumbent_key": list(self._incumbent_key) if self._incumbent_key is not None else None,
            "best_so_far_trace": _jsonable(self.best_so_far_trace),
            "population_trace": _jsonable(self.population_trace),
            "archive_trace": _jsonable(self.archive_trace),
            "design_space_version": int(self.design_space_version),
            "frequency_grid_version": int(self.frequency_grid_version),
            "active_frequency_grid": _jsonable(getattr(self, "active_frequency_grid", [])),
            "convergence_state": _jsonable(self.convergence_state),
            "population_schedule_terminal_budget": int(self.population_schedule_terminal_budget),
            "hard_max_budget": int(self.hard_max_budget),
            "total_budget": int(self._target_budget),
            "canonical_space_size": self.canonical_space_size,
            "source_config_fingerprint": self.source_config_fingerprint,
        }

    def load_state_dict(self, state: Mapping[str, Any]) -> None:
        state_version = int(state.get("state_version", -1))
        if state_version != 4:
            raise ValueError(
                f"L-SHADE checkpoint state version {state_version} is unsupported; expected 4"
            )
        if state.get("backend") not in (None, self.name):
            raise ValueError("checkpoint backend mismatch")
        saved_compact = bool(state.get("compact_history_cache", False))
        if saved_compact != self.compact_history_cache:
            raise ValueError("checkpoint compact-history mode mismatch")
        saved_finalist_count = int(state.get("historical_finalist_count", 16))
        if saved_finalist_count != self.historical_finalist_count:
            raise ValueError("checkpoint historical finalist count mismatch")
        saved_terminal = state.get(
            "terminal_budget", state.get("population_schedule_terminal_budget")
        )
        if (saved_terminal is not None
                and int(saved_terminal) != int(self.population_schedule_terminal_budget)):
            raise ValueError(
                "L-SHADE checkpoint terminal horizon mismatch; cold start is required"
            )
        checkpoint_fingerprint = state.get("source_config_fingerprint")
        if (self.source_config_fingerprint is not None and checkpoint_fingerprint is not None
                and checkpoint_fingerprint != self.source_config_fingerprint):
            raise ValueError("checkpoint source/config fingerprint mismatch")
        self.bounds = np.asarray(state["bounds"], dtype=float)
        self.hard_bounds = np.asarray(state.get("hard_bounds", self.hard_bounds), dtype=float)
        self.dimension = int(len(self.bounds))
        self.active_bounds = copy.deepcopy(state.get("active_bounds", self.bounds.tolist()))
        self._population = []
        for item in state.get("population", []):
            self._population.append(_PopulationMember(
                np.asarray(item["x"], dtype=float), np.asarray(item["physical"], dtype=float),
                tuple(item["key"]), _from_jsonable(item["result"])))
        self._archive = [np.asarray(item, dtype=float) for item in state.get("archive", [])]
        if self.compact_history_cache:
            self._cache = {
                tuple(key): _from_jsonable(value)
                for key, value in state.get("retained_results", [])
            }
            self._cache_frequency_versions = {}
            self._history_rank_index = {}
            for key, version, rank_key, candidate_vector, order in state.get(
                    "compact_history_index", []):
                self._cache_frequency_versions[tuple(key)] = int(version)
                self._history_rank_index[tuple(key)] = (
                    tuple(float("inf") if value is None else float(value)
                          for value in rank_key),
                    tuple(float(value) for value in candidate_vector),
                    int(order),
                )
            self._history_next_order = max(
                (entry[2] for entry in self._history_rank_index.values()), default=-1,
            ) + 1
            self._historical_finalist_keys = sorted(
                self._history_rank_index,
                key=lambda key: (
                    self._history_rank_index[key][0],
                    self._history_rank_index[key][2],
                ),
            )[:self.historical_finalist_count]
        else:
            self._cache = {tuple(key): _from_jsonable(value) for key, value in state.get("cache", [])}
            self._cache_frequency_versions = {
                tuple(key): int(version)
                for key, version in state.get("cache_frequency_versions", [])
            }
        self.m_f = np.asarray(state["m_f"], dtype=float)
        self.m_cr = np.asarray(state["m_cr"], dtype=float)
        self.history_index = int(state["history_index"])
        self.rng.bit_generator.state = _from_jsonable(state["rng_state"])
        self.initial_population_size = int(state.get("initial_population_size", len(self._population)))
        self.minimum_population_size = int(state.get("minimum_population_size", self.minimum_population_size))
        self.memory_update_batch_size = int(state.get(
            "memory_update_batch_size", max(1, self.initial_population_size)))
        self._memory_batch_proposals = int(state.get("memory_batch_proposals", 0))
        self._successful_f = [float(value) for value in _from_jsonable(state.get("successful_f", []))]
        self._successful_cr = [float(value) for value in _from_jsonable(state.get("successful_cr", []))]
        self._successful_weights = [float(value) for value in _from_jsonable(state.get("successful_weights", []))]
        self.unique_evaluations = int(state.get(
            "unique_evaluations", len(self._cache_frequency_versions)))
        self.initial_requested_budget = int(state.get(
            "requested_unique_budget", state.get("total_budget", self.total_budget)))
        self.proposals_total = int(state.get(
            "proposals_total", state.get("raw_offspring_count", 0)))
        self.raw_offspring_count = int(state.get("raw_offspring_count", 0))
        self.duplicate_count = int(state.get("duplicate_count", 0))
        self.duplicate_by_group = {str(key): int(value) for key, value in state.get("duplicate_by_group", {}).items()}
        self.duplicate_by_group.setdefault("integer", 0)
        self.duplicate_by_group.setdefault("continuous", 0)
        self.cache_hits = int(state.get("cache_hits", 0))
        self.generations = int(state.get("generations", 0))
        self._incumbent = _from_jsonable(state.get("incumbent"))
        incumbent_key = state.get("incumbent_key")
        self._incumbent_key = tuple(incumbent_key) if incumbent_key is not None else None
        self.best_so_far_trace = _from_jsonable(state.get("best_so_far_trace", []))
        self.population_trace = _from_jsonable(state.get("population_trace", []))
        self.archive_trace = _from_jsonable(state.get("archive_trace", []))
        self.design_space_version = int(state.get("design_space_version", 1))
        self.frequency_grid_version = int(state.get("frequency_grid_version", 1))
        self.active_frequency_grid = _from_jsonable(state.get("active_frequency_grid", []))
        self.convergence_state = _from_jsonable(state.get("convergence_state", {}))
        self.duplicate_streak = int(state.get("duplicate_streak", 0))
        self.search_space_exhausted = bool(state.get("search_space_exhausted", False))
        saved_repairs = state.get("boundary_repair_counts", {})
        self.boundary_repair_counts = {
            direction: [int(value) for value in saved_repairs.get(
                direction, [0] * self.dimension
            )]
            for direction in ("lower", "upper")
        }
        self.population_schedule_terminal_budget = int(state.get(
            "population_schedule_terminal_budget", self.population_schedule_terminal_budget))
        self.hard_max_budget = int(state.get("hard_max_budget", self.hard_max_budget))
        self.canonical_space_size = state.get("canonical_space_size", self.canonical_space_size)
        self._target_budget = int(state.get("total_budget", self.total_budget))

    # Explicit aliases make the checkpoint contract discoverable without
    # requiring callers to know the historical ``*_dict`` naming.
    def save_state(self):
        return copy.deepcopy(self.state_dict())

    def load_state(self, state):
        self.load_state_dict(state)

    def save_checkpoint(self, path):
        path = str(path)
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(self.state_dict(), stream, indent=2, ensure_ascii=False, allow_nan=False)

    def load_checkpoint(self, path):
        validate_lshade_checkpoint_header(path)
        with open(path, encoding="utf-8") as stream:
            self.load_state_dict(json.load(stream))


class FixedDEReferenceBackend(LShadeBackend):
    """Small in-house DE/rand/1/bin reference for strategy isolation tests."""

    name = "fixed_de_reference"

    def _generation(self, target_budget):
        # The L-SHADE state machinery remains shared; only mutation strategy is
        # replaced so evaluator/cache/comparator effects stay controlled.
        original = self.pbest_max_fraction
        self.pbest_max_fraction = 1.0
        try:
            super()._generation(target_budget)
        finally:
            self.pbest_max_fraction = original
