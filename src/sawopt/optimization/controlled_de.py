"""Controlled Q0 DE/rand/1/bin, not a SciPy DE configuration.

Parents are canonical-phenotype genotypes. The caller owns durable transactions;
``observe`` is an optional, draw-free boundary used by the Q1 study adapter.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np

from .selection import GeometryFirstComparator


def de_trial(parents, target, rng):
    eligible = [i for i in range(len(parents)) if i != target]
    donors = tuple(int(i) for i in rng.permutation(eligible)[:3])
    r1, r2, r3 = donors
    mutant = parents[r1] + .5 * (parents[r2] - parents[r3])
    forced = int(rng.integers(0, parents.shape[1]))
    mask = rng.random(parents.shape[1]) < .9
    mask[forced] = True
    before = np.where(mask, mutant, parents[target])
    # Q0 explicitly leaves in-range words unchanged (avoid cancellation in
    # 1-abs(z-1) for in-range binary64 z).
    reflected = before.copy()
    outside = (before < 0.) | (before > 1.)
    reflected[outside] = 1. - np.abs(np.mod(before[outside], 2.) - 1.)
    return reflected, {"donors": donors, "forced": forced, "mask": mask,
                       "before_reflection": before}


@dataclass
class DEMember:
    x: np.ndarray
    physical: np.ndarray
    key: tuple
    result: dict


class ControlledDEBackend:
    """Fixed N=234, F=.5, CR=.9, synchronous generations, parent-on-tie.

    ``step`` completes one target (including duplicate retries). Pending trials
    never enter the donor pool. Only a full generation or terminal FE boundary
    commits survivors; a stalled generation remains explicitly pending.
    """
    name = "controlled_de"
    population_size = 234
    budget = 4096
    target_proposal_limit = 4096
    no_progress_limit = 65536

    def __init__(self, bounds, *, canonicalizer, seed=0, observe=None):
        self.bounds = np.asarray(bounds, dtype=float)
        if (self.bounds.shape != (13, 2) or not np.isfinite(self.bounds).all()
                or np.any(self.bounds[:, 1] <= self.bounds[:, 0])):
            raise ValueError("Q0 requires finite 13-coordinate increasing bounds")
        self.canonicalizer = canonicalizer
        self.rng = np.random.Generator(np.random.PCG64(seed))
        self.comparator = GeometryFirstComparator()
        self.observe = observe
        self.evaluator = None
        self.population = []
        self.parents = []
        self.pending = []
        self.cache = {}
        self.unique_evaluations = 0
        self.proposals_total = 0
        self.duplicate_count = 0
        self.no_progress = 0
        self.generation = 0
        self.target = 0
        self.retry = 0
        self.status = "NOT_INITIALIZED"
        self.generation_sizes = []

    def _observe(self, event, **data):
        if self.observe is not None:
            self.observe(event, data)

    def _normalize(self, physical):
        low, high = self.bounds.T
        return np.clip((np.asarray(physical) - low) / (high - low), 0., 1.)

    def initial_input(self, physical):
        canonical, key = self.canonicalizer(np.asarray(physical, dtype=float).copy())
        return np.asarray(canonical, dtype=float).copy(), tuple(key)

    def _member(self, physical, key):
        if self.unique_evaluations >= self.budget:
            raise RuntimeError("no evaluation beyond Q0 FE ceiling")
        result = copy.deepcopy(self.evaluator(physical.copy()))
        self.cache[key] = result
        self.unique_evaluations += 1
        self.no_progress = 0
        return DEMember(self._normalize(physical), physical.copy(), key, result)

    def initialize(self, evaluator, *, population):
        if self.status != "NOT_INITIALIZED":
            raise RuntimeError("DE initialization is a cold transition")
        raw = np.asarray(population, dtype=float)
        if raw.shape != (234, 13):
            raise ValueError("Q0 requires 234 ordered physical initial members")
        self.evaluator = evaluator
        for index, row in enumerate(raw):
            physical, key = self.initial_input(row)
            if key in self.cache:
                raise ValueError("initial population has duplicate canonical keys")
            self.population.append(self._member(physical, key))
            self._observe("initial_member", index=index)
        self.status = "SEARCHING"

    def _commit_survivors(self):
        survivors = list(self.parents)
        for index, trial in enumerate(self.pending):
            if self.comparator.better(trial.result, self.parents[index].result):
                survivors[index] = trial
        self.population = survivors
        self.generation_sizes.append(len(self.pending))
        self.generation += 1
        self.parents = []
        self.pending = []
        self.target = self.retry = 0

    def step(self):
        if self.status != "SEARCHING":
            return False
        if not self.parents:
            self.parents = copy.deepcopy(self.population)
            self._observe("generation_snapshot", generation=self.generation)
        while True:
            if self.retry >= self.target_proposal_limit or self.no_progress >= self.no_progress_limit:
                self.status = "BUDGET_STALLED"
                return False
            self._observe("before_proposal", generation=self.generation, target=self.target, retry=self.retry)
            raw, evidence = de_trial(np.asarray([m.x for m in self.parents]), self.target, self.rng)
            low, high = self.bounds.T
            physical, key = self.initial_input(low + raw * (high - low))
            duplicate = key in self.cache
            self._observe("proposal", x=raw, physical=physical, key=key, duplicate=duplicate,
                          generation=self.generation, target=self.target, retry=self.retry, **evidence)
            self.proposals_total += 1
            self.no_progress += 1
            self.retry += 1
            if duplicate:
                self.duplicate_count += 1
                continue
            member = self._member(physical, key)
            self.pending.append(member)
            self.target += 1
            self.retry = 0
            if self.target == self.population_size or self.unique_evaluations == self.budget:
                self._commit_survivors()
            if self.unique_evaluations == self.budget:
                # Validation belongs to Q1-E; do not claim overall COMPLETED.
                self.status = "SEARCH_BUDGET_REACHED"
            return True
