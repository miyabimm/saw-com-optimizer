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
from .live_state import inspect_snapshot, restore, snapshot
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
        durable_keys = set()
        rng_commits = 0
        rng_state = self.rng.service.initial_state
        invalid_seen = False
        previous_commit = None
        pending_step = None
        next_step = 0
        checkpoint_sequence = 0
        attachment = None
        intents = {}
        for event in journal.iter_events():
            if event.event_type == "POPULATION_ATTACHMENT_ATTACHED":
                if attachment is not None:
                    raise ValueError("duplicate population attachment")
                attachment = event.payload
            elif event.event_type == "RNG_DRAW_COMMITTED":
                rng_commits += 1
                rng_state = event.payload["post_state"]
            elif event.event_type in {"OPTIMIZER_STEP_STARTED", "OPTIMIZER_STEP_COMMITTED"}:
                state, state_rng = inspect_snapshot(backend, event.payload["state"])
                if state["unique_evaluations"] != len(durable_keys):
                    raise ValueError("optimizer snapshot FE differs from journal prefix ledger")
                cache = state["_cache_frequency_versions"] if cell.role == "lshade" else state["cache"]
                if {canonical_key_tokens(key) for key in cache} != durable_keys:
                    raise ValueError("optimizer snapshot cache differs from journal prefix ledger")
                # A matching key set alone does not prove that the restored
                # optimizer will use the committed result for each candidate.
                records = list(state.get("_cache", {}).items()) + list(state.get("cache", {}).items())
                for name in ("_population", "population", "parents", "pending"):
                    records.extend((member.key, member.result) for member in state.get(name, []))
                for key, result in records:
                    durable = self.results.get(canonical_key_tokens(key))
                    if durable is None or encode_typed(result) != encode_typed(durable["result"]):
                        raise ValueError("optimizer snapshot result differs from journal prefix ledger")
                if event.payload["rng_ordinal"] != rng_commits or state_rng != rng_state:
                    raise ValueError("optimizer snapshot RNG differs from journal prefix tape")
                step_id = "initialization" if previous_commit is None else f"step:{next_step}"
                expected_id = f"{event.event_type}:{cell.identity_id}:{step_id}"
                if event.event_id != expected_id:
                    raise ValueError("optimizer step sequence differs from journal prefix")
                if event.event_type == "OPTIMIZER_STEP_STARTED":
                    if pending_step is not None:
                        raise ValueError("optimizer step has overlapping pre-states")
                    if previous_commit is not None and any(
                        event.payload[name] != previous_commit[name]
                        for name in ("state", "rng_ordinal", "no_progress")
                    ):
                        raise ValueError("optimizer step pre-state differs from committed prefix")
                    pending_step = step_id
                else:
                    if pending_step != step_id:
                        raise ValueError("optimizer step commit has no matching pre-state")
                    pending_step = None
                    previous_commit = event.payload
                    if step_id != "initialization":
                        next_step += 1
            elif event.event_type == "CHECKPOINT_SNAPSHOT":
                payload = event.payload
                if (type(payload) is not dict or payload.get("journal_sequence") != event.sequence - 1
                        or payload.get("journal_head_hash") != event.previous_hash):
                    raise ValueError("checkpoint journal prefix mismatch")
                if (attachment is None or previous_commit is None or pending_step is not None
                        or event.event_id != f"CHECKPOINT_SNAPSHOT:{cell.identity_id}:{checkpoint_sequence}"):
                    raise ValueError("checkpoint sequence or state boundary mismatch")
                expected = {
                    "schema": "stage5a2_checkpoint_v1", "checkpoint_sequence": checkpoint_sequence,
                    "pair_identity_id": pair.identity_id, "cell_identity_id": cell.identity_id,
                    "population_sha256": attachment["population_sha256"],
                    "representation_sha256": attachment["representation_sha256"],
                    "journal_sequence": event.sequence - 1, "journal_head_hash": event.previous_hash,
                    "state": previous_commit["state"],
                    "state_sha256": hashlib.sha256(previous_commit["state"]).hexdigest(),
                    "rng_ordinal": previous_commit["rng_ordinal"], "no_progress": previous_commit["no_progress"],
                }
                if payload != expected:
                    raise ValueError("checkpoint identity or state differs from journal prefix")
                checkpoint_sequence += 1
            elif event.event_type == "EVALUATION_INTENT":
                payload = event.payload
                key = payload["key"]
                suffix = hashlib.sha256(encode_typed(key)).hexdigest()
                if (key in intents or key in self.results or payload["step_id"] != pending_step
                        or pending_step is None or payload["ordinal"] != len(self.trace) + 1
                        or canonical_key_tokens(payload["physical"]) != key
                        or event.event_id != f"EVALUATION_INTENT:{cell.identity_id}:{suffix}"):
                    raise ValueError("evaluation intent differs from pending journal transition")
                intents[key] = payload
            elif event.event_type == "EVALUATOR_ATTEMPT_STARTED":
                payload = event.payload
                key = payload["key"]
                attempt = self.attempts.get(key, 0)
                suffix = hashlib.sha256(encode_typed(key)).hexdigest()
                if (key not in intents or key in self.results or payload["attempt"] != attempt
                        or event.event_id != f"EVALUATOR_ATTEMPT_STARTED:{cell.identity_id}:{suffix}:{attempt}"):
                    raise ValueError("evaluator attempt differs from pending intent")
                self.attempts[key] = attempt + 1
            elif event.event_type == "EVALUATION_RESULT_COMMITTED":
                payload = event.payload
                if (invalid_seen or payload["key"] in self.results
                        or payload["ordinal"] != len(self.trace) + 1
                        or canonical_key_tokens(payload["physical"]) != payload["key"]):
                    raise ValueError("invalid, duplicate or gapped durable FE ledger")
                if payload["status"] == "INVALID_RECORD":
                    invalid_seen = True
                    if payload["rank"] is not None:
                        raise ValueError("invalid result has rank in FE ledger")
                else:
                    validate_candidate(payload["result"], vector=payload["physical"], ordinal=payload["ordinal"],
                                       topology=pair.topology, grid_sha256=pair.grid_sha256)
                    rank = GeometryFirstComparator().rank_key(payload["result"])
                    if payload["status"] != payload["result"]["evaluation_status"] or payload["rank"] != rank:
                        raise ValueError("result rank/status differs from FE ledger")
                    if self.best_rank is None or rank < self.best_rank:
                        self.best_rank, self.best_key = rank, payload["key"]
                if payload["best_rank"] != self.best_rank or payload["best_key"] != self.best_key:
                    raise ValueError("best rank/key differs from FE ledger")
                intent = intents.get(payload["key"])
                suffix = hashlib.sha256(encode_typed(payload["key"])).hexdigest()
                if (intent is None or not self.attempts.get(payload["key"])
                        or payload["step_id"] != pending_step
                        or event.event_id != f"EVALUATION_RESULT_COMMITTED:{cell.identity_id}:{suffix}"
                        or any(encode_typed(payload[name]) != encode_typed(intent[name])
                               for name in ("key", "physical", "ordinal", "step_id", "proposal_index"))):
                    raise ValueError("evaluation result differs from pending intent/attempt")
                self.results[payload["key"]] = payload
                durable_keys.add(payload["key"])
                self.trace.append(payload)
        self.checkpoint_sequence = checkpoint_sequence

    def checkpoint(self):
        """Atomically record a snapshot of the current committed step prefix."""
        if self.initializing:
            raise ValueError("checkpoint requires committed initialization")
        starts = commits = 0
        commit = tail = attachment = None
        for event in self.journal.iter_events():
            tail = event
            if event.event_type == "OPTIMIZER_STEP_STARTED":
                starts += 1
            elif event.event_type == "OPTIMIZER_STEP_COMMITTED":
                commits += 1
                commit = event.payload
            elif event.event_type == "POPULATION_ATTACHMENT_ATTACHED":
                if attachment is not None:
                    raise ValueError("checkpoint requires one population attachment")
                attachment = event.payload
        if commit is None or starts != commits:
            raise ValueError("checkpoint requires a committed optimizer boundary")
        if (snapshot(self.backend) != commit["state"] or self.rng.ordinal != commit["rng_ordinal"]
                or self.no_progress != commit["no_progress"]):
            raise ValueError("checkpoint state differs from committed optimizer boundary")
        if attachment is None or tail is None:
            raise ValueError("checkpoint requires one population attachment")
        payload = {
            "schema": "stage5a2_checkpoint_v1", "checkpoint_sequence": self.checkpoint_sequence,
            "pair_identity_id": self.pair.identity_id, "cell_identity_id": self.cell.identity_id,
            "population_sha256": attachment["population_sha256"],
            "representation_sha256": attachment["representation_sha256"],
            "journal_sequence": tail.sequence, "journal_head_hash": tail.event_hash,
            "state": commit["state"], "state_sha256": hashlib.sha256(commit["state"]).hexdigest(),
            "rng_ordinal": self.rng.ordinal, "no_progress": self.no_progress,
        }
        self._event(str(self.checkpoint_sequence), "CHECKPOINT_SNAPSHOT", payload)
        self.checkpoint_sequence += 1
        return payload

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

    def hydrate_committed_steps(self):
        """Restore the contiguous durable post-initialization step prefix.

        A pending step is deliberately left for source-control-flow replay.
        """
        if self.initializing:
            raise ValueError("initialization must be restored first")
        started = set()
        last_commit = None
        commit_count = 0
        terminal_status = None
        for event in self.journal.iter_events():
            if event.event_type == "OPTIMIZER_STEP_STARTED":
                started.add(event.event_id)
            elif (event.event_type == "OPTIMIZER_STEP_COMMITTED"
                  and event.event_id != f"OPTIMIZER_STEP_COMMITTED:{self.cell.identity_id}:initialization"):
                step_id = f"step:{commit_count}"
                if event.event_id != f"OPTIMIZER_STEP_COMMITTED:{self.cell.identity_id}:{step_id}":
                    raise ValueError("noncontiguous optimizer step commits")
                if f"OPTIMIZER_STEP_STARTED:{self.cell.identity_id}:{step_id}" not in started:
                    raise ValueError("optimizer step commit has no pre-state")
                last_commit = event.payload
                commit_count += 1
            elif event.event_type == "CELL_TERMINAL_STATUS_COMMITTED":
                terminal_status = event.payload["status"]
        if last_commit is not None:
            restore(self.backend, last_commit["state"])
            self.rng.ordinal = last_commit["rng_ordinal"]
            self.no_progress = last_commit["no_progress"]
            self.step_index = commit_count
        if terminal_status is not None:
            self.status = terminal_status
        elif last_commit is not None:
            # A crash can occur after the optimizer commit and before the
            # search-only terminal event. Reconcile without rerunning the step.
            status = "SEARCHING"
            if self.cell.role == "controlled_de" and self.backend.status != "SEARCHING":
                status = self.backend.status
            if self.no_progress >= 65536:
                status = "BUDGET_STALLED"
            if self.backend.unique_evaluations == 4096:
                status = "SEARCH_BUDGET_REACHED"
            if status != "SEARCHING":
                self._event(f"step:{self.step_index - 1}", "CELL_TERMINAL_STATUS_COMMITTED", {"status": status})
                self.status = status

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
        if self.no_progress >= 65536:
            self.status = "BUDGET_STALLED"
        if self.backend.unique_evaluations == 4096:
            self.status = "SEARCH_BUDGET_REACHED"
        if self.status != "SEARCHING":
            self._event(self.rng.step_id, "CELL_TERMINAL_STATUS_COMMITTED", {"status": self.status})
        return result
