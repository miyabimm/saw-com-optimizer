"""Backend contracts shared by Stage 3.3 optimizer implementations."""
from __future__ import annotations

from typing import Any, Callable, Mapping

import numpy as np
from scipy.optimize import differential_evolution


class ScipyDELegacyBackend:
    """Standalone SciPy-DE strategy, retained separately from study execution.

    It deliberately retains SciPy's generation semantics and is not advertised
    as exactly resumable. The current synthetic CLI uses :class:`LShadeBackend`;
    this backend remains an available strategy, not a COM/FE runner.
    """

    name = "scipy_de_legacy"

    def __init__(self, bounds, *, seed=0, config=None, canonicalizer=None, comparator=None):
        self.bounds = np.asarray(bounds, dtype=float)
        self.seed = int(seed)
        self.config = dict(config or {})
        self.canonicalizer = canonicalizer
        self.comparator = comparator
        self.evaluator = None
        self._cache = {}
        self._best = None
        self.unique_evaluations = 0
        self.objective_calls = 0

    def _canonical(self, x):
        value = np.asarray(x, dtype=float)
        if self.canonicalizer is not None:
            result = self.canonicalizer(value)
            if isinstance(result, tuple):
                return np.asarray(result[0], dtype=float), tuple(result[1])
            value = np.asarray(result, dtype=float)
        return value, tuple(float(item) for item in value)

    def initialize(self, evaluator, *, population=None, comparator=None):
        del population
        self.evaluator = evaluator
        if comparator is not None:
            self.comparator = comparator

    def advance_to_unique_budget(self, target_unique_evals):
        if self.evaluator is None:
            raise RuntimeError("initialize must be called before advance_to_unique_budget")
        target = int(target_unique_evals)
        if target <= 0:
            raise ValueError("target_unique_evals must be positive")
        cache = self._cache

        def objective(x):
            self.objective_calls += 1
            physical, key = self._canonical(x)
            if key in cache:
                result = cache[key]
            else:
                if self.unique_evaluations >= target:
                    return 1e100
                result = dict(self.evaluator(physical))
                cache[key] = result
                self.unique_evaluations += 1
            rank = self.comparator.rank_key(result) if self.comparator is not None else (
                float(not result.get("feasible", False)), float(result.get("max_violation", 1e100)),
                float(result.get("metrics", {}).get("worst_il_db", 1e100)))
            scalar = 0.0
            for item in rank:
                scalar = scalar * 1e3 + min(float(item), 1e100)
            if self._best is None or (self.comparator is not None and self.comparator.better(result, self._best)):
                self._best = result
            return scalar

        population = max(4, int(self.config.get("population", 14)))
        dimensions = max(1, len(self.bounds))
        iterations = max(1, int(np.ceil(target / max(population, 1))))
        differential_evolution(
            objective, [tuple(row) for row in self.bounds], seed=self.seed,
            popsize=max(1, int(np.ceil(population / dimensions))), maxiter=iterations,
            polish=False, tol=0.0, atol=0.0, workers=1,
            updating="immediate",
        )
        return self.summary()

    def summary(self):
        return {"backend": self.name, "unique_evaluations": self.unique_evaluations,
                "objective_calls": self.objective_calls, "incumbent": self._best}

    def state_dict(self):
        return {"backend": self.name, "seed": self.seed, "unique_evaluations": self.unique_evaluations,
                "objective_calls": self.objective_calls, "incumbent": self._best}

    def load_state_dict(self, state):
        if state.get("backend") not in (None, self.name):
            raise ValueError("checkpoint backend mismatch")
        self.unique_evaluations = int(state.get("unique_evaluations", 0))
        self.objective_calls = int(state.get("objective_calls", 0))
        self._best = state.get("incumbent")

    def population(self):
        return np.empty((0, len(self.bounds)), dtype=float)

    def incumbent(self):
        return self._best
