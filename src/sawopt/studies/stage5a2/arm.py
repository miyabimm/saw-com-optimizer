"""Thin synthetic-only arm transactions on Q1-A journal and PCG64 services.

A committed result store is deliberately NOT installed into the backend cache.
An uncommitted optimizer step is replayed from its live pre-state instead.
Q1-D owns exhaustive crash/restart certification of these boundaries.
"""
from __future__ import annotations

import copy
import hashlib

import numpy as np

from sawopt.optimization.selection import GeometryFirstComparator

from .candidates import InvalidCandidate, validate_candidate
from .codec import encode_typed
from .initialization import canonical_key_tokens
from .live_state import restore, snapshot
from .rng import RNGCallIdentity, RNGCallService


class BudgetStalled(RuntimeError):
    pass


class InvalidRecord(RuntimeError):
    pass


class TapedGenerator:
    def __init__(self, service, cell):
        self.service = service
        self.cell = cell
        self.generator = service.generator
        self.ordinal = 0
        self.step_id = "initialization"
        self.cursor = ("initialization",)
        self.slot = 0
        self.before_draw = lambda: None

    def __getattr__(self, method):
        if method not in {"integers", "choice", "random", "normal", "standard_cauchy", "uniform", "permutation"}:
            raise AttributeError(method)
        def call(*args, **kwargs):
            self.before_draw()
            identity = RNGCallIdentity(
                self.cell.identity_id, self.cell.role, self.step_id,
                self.cursor + (method, self.slot), self.ordinal,
            )
            value = self.service.call(identity, method, *args, **kwargs)
            self.ordinal += 1
            self.slot += 1
            return value
        return call


class ArmSession:
    """One arm with private durable result/FE/trace ledger and replay seam.

    Evaluators are explicitly injected ``(physical_copy, first_ordinal)``
    synthetic callables. No evaluator resolution, provider or run dispatch.
    Construct through the two-arm boundary in ``pair.prepare_pair``.
    """
    def __init__(self, backend, *, cell, pair, journal, evaluator, seed):
        if pair.identity_scope != "synthetic_test":
            raise ValueError("Q1-BC executes synthetic-only identities")
        if journal.get_immutable_record("cell_identity", cell.identity_id) != cell.canonical_bytes:
            raise ValueError("arm lacks its immutable cell identity")
        self.backend, self.cell, self.pair, self.journal = backend, cell, pair, journal
        self.evaluator = evaluator
        self.rng = TapedGenerator(RNGCallService(
            backend.rng, journal, pair_identity=pair, synthetic_test=True, synthetic_test_seed=seed,
        ), cell)
        backend.rng = self.rng
        if cell.role == "lshade":
            backend._q1_observer = self.observe
        else:
            backend.observe = self.observe
        backend.evaluator = self.evaluate
        self.results = {}
        self.attempts = {}
        self.trace = []
        self.best_rank = None
        self.best_key = None
        self.no_progress = 0
        self.proposal_index = 0
        self.step_index = 0
        self.initializing = True
        self.expected_initial_inputs = None
        self.status = "NOT_INITIALIZED"
        self.rng.before_draw = self._before_draw
        for event in journal.events():
            if event.event_type == "EVALUATION_RESULT_COMMITTED":
                payload = event.payload
                if payload["key"] in self.results or payload["ordinal"] != len(self.trace) + 1:
                    raise ValueError("duplicate/gapped durable FE ledger")
                self.results[payload["key"]] = payload
                self.trace.append(payload)
                if payload["rank"] is not None:
                    self.best_rank = payload["best_rank"]
                    self.best_key = payload["best_key"]
            elif event.event_type == "EVALUATOR_ATTEMPT_STARTED":
                self.attempts[event.payload["key"]] = event.payload["attempt"] + 1

    def _before_draw(self):
        if self.no_progress >= 65536:
            raise BudgetStalled("common no-progress watchdog before any further draw")

    def _event(self, suffix, kind, payload):
        return self.journal.append_event(f"{kind}:{self.cell.identity_id}:{suffix}", kind, payload)

    def observe(self, event, data):
        if event == "generation_snapshot":
            self._event(str(data["generation"]), "GENERATION_SNAPSHOT_COMMITTED", {"state": snapshot(self.backend)})
        elif event == "initial_member":
            self._event(str(data["index"]), "INITIALIZATION_MEMBER_COMMITTED", {
                "index": data["index"], "next_member": data["index"] + 1,
                "unique_evaluations": self.backend.unique_evaluations,
            })
        elif event == "parameters":
            if self.no_progress >= 65536:
                raise BudgetStalled("common no-progress watchdog")
            self.rng.cursor = ("parameters", data["target"])
            self.rng.slot = 0
        elif event == "before_proposal":
            if self.no_progress >= 65536:
                raise BudgetStalled("common no-progress watchdog")
            self.rng.cursor = tuple(data[k] for k in sorted(data))
            self.rng.slot = 0
        elif event == "fallback_invoked":
            self._event(f"{self.rng.step_id}:{self.proposal_index}", "FALLBACK_INVOKED", data)
        elif event == "proposal":
            self.no_progress += 1
            payload = copy.deepcopy(data)
            payload.update(proposal_index=self.proposal_index, no_progress=self.no_progress,
                           rng_ordinal=self.rng.ordinal, next_retry=data.get("retry", data.get("attempt", 0)) + 1)
            # One transaction owns proposal classification, duplicate, retry,
            # watchdog and cursor projection. Replay verifies identical bytes.
            suffix = f"{self.rng.step_id}:{self.proposal_index}"
            events = [(f"PROPOSAL_ATTEMPT:{self.cell.identity_id}:{suffix}", "PROPOSAL_ATTEMPT", payload)]
            if data["duplicate"]:
                events.append((f"DUPLICATE_DETECTED:{self.cell.identity_id}:{suffix}",
                               "DUPLICATE_DETECTED", {"next_retry": payload["next_retry"],
                                                      "no_progress": self.no_progress}))
            self.journal.commit_records((), events)
            self.proposal_index += 1

    def evaluate(self, physical):
        key = canonical_key_tokens(physical)
        # Local pre-step FE ordinal, NOT the journal's (possibly later) FE count.
        ordinal = self.backend.unique_evaluations + 1
        if self.initializing and (self.expected_initial_inputs is None or not 1 <= ordinal <= 234
                                  or physical.tobytes() != self.expected_initial_inputs[ordinal - 1]):
            raise ValueError("actual initialization evaluator argument differs from the two-arm seal")
        existing = self.results.get(key)
        if existing is not None:
            if (existing["ordinal"] != ordinal or existing["physical"].tobytes() != physical.tobytes()
                    or existing["step_id"] != self.rng.step_id):
                raise ValueError("result replay identity differs from backend pre-step")
            self.no_progress = 0
            if existing["status"] == "INVALID_RECORD":
                raise InvalidRecord("replayed invalid returned record")
            return copy.deepcopy(existing["result"])
        if len(self.results) >= 4096:
            raise RuntimeError("Q0 FE ceiling reached before dispatch")
        payload = {"key": key, "physical": physical.copy(), "ordinal": ordinal,
                   "step_id": self.rng.step_id, "proposal_index": self.proposal_index}
        suffix = hashlib.sha256(encode_typed(key)).hexdigest()
        self._event(suffix, "EVALUATION_INTENT", payload)
        attempt = self.attempts.get(key, 0)
        self._event(f"{suffix}:{attempt}", "EVALUATOR_ATTEMPT_STARTED", {"key": key, "attempt": attempt})
        self.attempts[key] = attempt + 1
        try:
            result = self.evaluator(physical.copy(), ordinal)
        except Exception as exc:
            # No arbitrary exception-to-PHYSICS_FAILED conversion.
            self._event(f"{suffix}:{attempt}", "INFRASTRUCTURE_INTERRUPTED", {"exception_type": type(exc).__name__})
            self.status = "INFRASTRUCTURE_INTERRUPTED"
            raise
        rank = None
        status = "INVALID_RECORD"
        try:
            validate_candidate(result, vector=physical, ordinal=ordinal,
                               topology=self.pair.topology, grid_sha256=self.pair.grid_sha256)
            rank = GeometryFirstComparator().rank_key(result)
            status = result["evaluation_status"]
        except (InvalidCandidate, TypeError, ValueError, KeyError):
            pass
        try:
            encode_typed(result)
            quarantined = result
        except (TypeError, ValueError):
            quarantined = {"unsupported_return_type": type(result).__name__}
        improves = rank is not None and (self.best_rank is None or rank < self.best_rank)
        best = rank if improves else self.best_rank
        best_key = key if improves else self.best_key
        pending_target = None
        if not self.initializing and self.cell.role == "controlled_de":
            pending_target = {"generation": self.backend.generation, "target": self.backend.target,
                              "next_target": self.backend.target + 1,
                              "phenotype_genotype": self.backend._normalize(physical)}
        committed = dict(payload, result=quarantined, status=status, rank=rank, best_rank=best,
                         pending_target=pending_target, best_key=best_key)
        self._event(suffix, "EVALUATION_RESULT_COMMITTED", committed)
        self.results[key] = committed
        self.trace.append(committed)
        self.best_rank = best
        self.best_key = best_key
        self.no_progress = 0
        if status == "INVALID_RECORD":
            self.status = status
            self._event(suffix, "CELL_TERMINAL_STATUS_COMMITTED", {"status": status, "ordinal": ordinal})
            raise InvalidRecord("returned record quarantined and charged once; never ranked")
        return copy.deepcopy(result)

    def transition(self, operation):
        """Commit a complete source transition; reuse results/tape on replay.

        ``initialization`` uses the same pre-state replay mechanism. Member rows
        are observational durable cursors; no partial source locals are guessed.
        """
        step_id = "initialization" if self.initializing else f"step:{self.step_index}"
        self.rng.step_id = step_id
        started_id = f"OPTIMIZER_STEP_STARTED:{self.cell.identity_id}:{step_id}"
        committed_id = f"OPTIMIZER_STEP_COMMITTED:{self.cell.identity_id}:{step_id}"
        started = self.journal.get_event(started_id)
        committed = self.journal.get_event(committed_id)
        if committed is not None:
            restore(self.backend, committed["payload"]["state"])
            self.rng.ordinal = committed["payload"]["rng_ordinal"]
            self.no_progress = committed["payload"]["no_progress"]
        else:
            if started is None:
                self._event(step_id, "OPTIMIZER_STEP_STARTED", {
                    "state": snapshot(self.backend), "rng_ordinal": self.rng.ordinal,
                    "no_progress": self.no_progress,
                })
            else:
                restore(self.backend, started["payload"]["state"])
                self.rng.ordinal = started["payload"]["rng_ordinal"]
                self.no_progress = started["payload"]["no_progress"]
            self.proposal_index = 0
            self.rng.slot = 0
            self.rng.cursor = ("initialization",) if self.initializing else ("step", self.step_index)
            try:
                operation()
            except BudgetStalled:
                self.status = "BUDGET_STALLED"
                self._event(step_id, "CELL_TERMINAL_STATUS_COMMITTED", {"status": self.status, "pending_step": step_id})
                return False
            self._event(step_id, "OPTIMIZER_STEP_COMMITTED", {
                "state": snapshot(self.backend), "rng_ordinal": self.rng.ordinal,
                "no_progress": self.no_progress,
            })
        if self.initializing:
            self.initializing = False
            self.status = "SEARCHING"
        else:
            self.step_index += 1
            self.status = "SEARCHING"
        return True

    def step(self):
        if self.initializing or self.status != "SEARCHING":
            return False
        if self.backend.unique_evaluations >= 4096:
            self.status = "SEARCH_BUDGET_REACHED"
            return False
        operation = (lambda: self.backend._generation(4096)) if self.cell.role == "lshade" else self.backend.step
        result = self.transition(operation)
        if not result:
            return False  # transition already committed the pending-step stop
        if self.cell.role == "controlled_de" and self.backend.status != "SEARCHING":
            self.status = self.backend.status
        if self.backend.unique_evaluations == 4096:
            self.status = "SEARCH_BUDGET_REACHED"
        if self.status != "SEARCHING":
            self._event(self.rng.step_id, "CELL_TERMINAL_STATUS_COMMITTED", {"status": self.status})
        return result
