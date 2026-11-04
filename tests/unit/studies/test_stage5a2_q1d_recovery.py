"""Representative fresh-session synthetic recovery checks (not gate closure)."""
import hashlib
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest

from sawopt.studies.stage5a2.arm import ArmSession
from sawopt.studies.stage5a2.codec import encode_typed
from sawopt.studies.stage5a2.journal import JournalError, SQLiteJournal
from sawopt.studies.stage5a2.initialization import canonical_key_tokens
from sawopt.studies.stage5a2.identity import GenesisError
from sawopt.studies.stage5a2.live_state import snapshot
from sawopt.studies.stage5a2.pair import prepare_pair
from .q1bc_fixture import fixture, candidate


def test_interrupted_initialization_reuses_committed_members_in_fresh_session(tmp_path):
    metadata, pair, genesis, _ = fixture(tmp_path)
    calls = [[], []]
    def evaluate(role, vector, ordinal):
        calls[role].append((ordinal, vector.tobytes()))
        if role == 0 and ordinal == 10 and sum(o == 10 for o, _ in calls[0]) == 1:
            raise RuntimeError("initialization evaluator interrupted")
        return candidate(vector, ordinal, pair=pair)
    evaluators = tuple(lambda v, o, role=role: evaluate(role, v, o) for role in range(2))
    with pytest.raises(RuntimeError, match="initialization evaluator interrupted"):
        prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                     geometry_valid=lambda v: True, evaluators=evaluators)
    assert [ordinal for ordinal, _ in calls[0]] == list(range(1, 11))
    assert not calls[1]
    seal, arms = prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                              geometry_valid=lambda v: pytest.fail("sealed sampler reentered"),
                              evaluators=evaluators)
    assert [ordinal for ordinal, _ in calls[0]] == list(range(1, 11)) + list(range(10, 235))
    assert calls[0][9] == calls[0][10]
    assert [ordinal for ordinal, _ in calls[1]] == list(range(1, 235))
    expected = [member.sealed_physical_le_f64 for member in seal.members]
    assert [value for _, value in calls[0][:9] + calls[0][10:]] == expected
    assert [value for _, value in calls[1]] == expected
    for arm in arms:
        assert len(arm.results) == len(arm.trace) == arm.backend.unique_evaluations == 234
        assert sum(event.event_type == "EVALUATION_RESULT_COMMITTED" for event in arm.journal.events()) == 234


@pytest.mark.parametrize("role", [0, 1])
def test_new_session_hydrates_committed_steps_and_replays_pending(initialized_pair, role):
    metadata, pair, genesis, _, _, arms = initialized_pair
    evaluate = lambda v, o: candidate(v, o, pair=pair)
    def open_pair():
        return prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                            geometry_valid=lambda v: True, evaluators=(evaluate, evaluate))
    arm = arms[role]
    arm.step()
    original = arm._event
    def interrupt(suffix, kind, payload):
        if kind == "OPTIMIZER_STEP_COMMITTED":
            raise RuntimeError("crash before step commit")
        return original(suffix, kind, payload)
    arm._event = interrupt
    with pytest.raises(RuntimeError, match="crash before"):
        arm.step()
    expected = snapshot(arm.backend)
    _, fresh = open_pair()
    resumed = fresh[role]
    assert resumed.step_index == 1
    resumed.evaluator = lambda *args: pytest.fail("committed result redriven")
    assert resumed.step()
    actual = snapshot(resumed.backend)
    if actual != expected:
        index = next(i for i, (a, b) in enumerate(zip(actual, expected)) if a != b)
        pytest.fail(f"state mismatch at {index}: {actual[index-120:index+120]!r} != {expected[index-120:index+120]!r}")
    assert len(resumed.trace) == len(resumed.results) == resumed.backend.unique_evaluations == 236


@pytest.mark.parametrize("role", [0, 1])
def test_uninterrupted_and_fresh_session_scientific_trajectory_match(initialized_pair, _q1_initialized_baseline, role):
    metadata, pair, genesis, _, _, arms = initialized_pair
    # Force successful L-SHADE offspring after the common initialization so
    # the parity check covers archive and in-progress adaptation as well as shrink.
    evaluate = lambda v, o: candidate(v, o, pair=pair, score=0. if role == 0 else None)
    reference = arms[role]
    reference.evaluator = evaluate
    assert reference.step() and reference.step()
    if role == 0:
        assert len(reference.backend._population) < 234
        assert reference.backend._archive and reference.backend._successful_f
        assert reference.backend._memory_batch_proposals == 2
    kinds = {"RNG_DRAW_STARTED", "RNG_DRAW_COMMITTED", "PROPOSAL_ATTEMPT",
             "DUPLICATE_DETECTED", "EVALUATION_INTENT", "EVALUATION_RESULT_COMMITTED"}
    def scientific_events(arm):
        return [(e.event_type, encode_typed(e.payload)) for e in arm.journal.events() if e.event_type in kinds]
    def top16(arm):
        return [(r["rank"], r["ordinal"], r["key"]) for r in
                sorted(arm.trace, key=lambda r: (r["rank"], r["ordinal"]))[:16]]
    expected = (scientific_events(reference), snapshot(reference.backend), encode_typed(reference.trace),
                reference.best_rank, reference.best_key, top16(reference))
    event_types = [kind for kind, _ in expected[0]]
    rng_calls = event_types.count("RNG_DRAW_STARTED")
    assert rng_calls == event_types.count("RNG_DRAW_COMMITTED")
    assert event_types.count("EVALUATION_RESULT_COMMITTED") == len(reference.trace) == 236
    print(f"Q1-D role={role} digest={hashlib.sha256(encode_typed(expected)).hexdigest()} "
          f"RNG={rng_calls} proposals={event_types.count('PROPOSAL_ATTEMPT')} FE=236 trace=236")
    # Restore an isolated baseline to the same identity-bound journal paths.
    # Capture all reference data first; no old session is used after reset.
    _, _, _, _, _, restarted_arms = _q1_initialized_baseline()
    def open_restart():
        return prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                            geometry_valid=lambda v: True, evaluators=(evaluate, evaluate))[1][role]
    interrupted = restarted_arms[role]
    interrupted.evaluator = evaluate
    assert interrupted.step()
    event = interrupted._event
    def crash(suffix, kind, payload):
        if kind == "OPTIMIZER_STEP_COMMITTED":
            raise RuntimeError("crash")
        return event(suffix, kind, payload)
    interrupted._event = crash
    with pytest.raises(RuntimeError, match="crash"):
        interrupted.step()
    recovered = open_restart()
    recovered.evaluator = lambda *args: pytest.fail("committed result redriven")
    assert recovered.step()

    # Complete ordered logical scientific event payloads exclude physical
    # attempts and time; typed encoding compares IEEE-754 bits losslessly.
    assert (scientific_events(recovered), snapshot(recovered.backend), encode_typed(recovered.trace),
            recovered.best_rank, recovered.best_key, top16(recovered)) == expected
    assert len(recovered.trace) == recovered.backend.unique_evaluations == 236


def test_recovery_seals_terminal_after_step_commit_before_status(tmp_path, monkeypatch):
    # Minimal transition fixture: this tests the durable boundary, not a
    # 4096-FE scientific trajectory or its ledger reconciliation.
    journal = SQLiteJournal(tmp_path / "arm.sqlite", "test", "controlled_de")
    arm = ArmSession.__new__(ArmSession)
    arm.cell = SimpleNamespace(identity_id="cell", role="controlled_de")
    arm.journal = journal
    arm.backend = SimpleNamespace(unique_evaluations=0, status="SEARCHING")
    arm.rng = SimpleNamespace(ordinal=0, step_id="")
    arm.initializing = False
    arm.step_index = 0
    arm.no_progress = 0
    arm.status = "SEARCHING"
    monkeypatch.setattr("sawopt.studies.stage5a2.arm.restore",
                        lambda backend, state: setattr(backend, "unique_evaluations", state))
    arm._event("step:0", "OPTIMIZER_STEP_STARTED", {"state": 4095})
    arm._event("step:0", "OPTIMIZER_STEP_COMMITTED",
               {"state": 4096, "rng_ordinal": 7, "no_progress": 0})
    arm.hydrate_committed_steps()
    assert arm.status == "SEARCH_BUDGET_REACHED"
    assert not arm.step()
    terminals = [e for e in journal.events() if e.event_type == "CELL_TERMINAL_STATUS_COMMITTED"]
    assert len(terminals) == 1
    assert terminals[0].payload == {"status": "SEARCH_BUDGET_REACHED"}
    assert arm.rng.ordinal == 7 and arm.backend.unique_evaluations == 4096
    arm.hydrate_committed_steps()
    assert len([e for e in journal.events() if e.event_type == "CELL_TERMINAL_STATUS_COMMITTED"]) == 1


def test_de_duplicate_transaction_replays_in_fresh_session(initialized_pair, monkeypatch):
    from sawopt.optimization.controlled_de import de_trial
    metadata, pair, genesis, _, _, arms = initialized_pair
    arm = arms[1]
    def force_first_duplicate(parents, target, rng):
        if rng.cursor == (0, 0, 0):  # sorted generation, retry, target
            return parents[target].copy(), {}
        return de_trial(parents, target, rng)
    monkeypatch.setattr("sawopt.optimization.controlled_de.de_trial", force_first_duplicate)
    commit = arm.journal.commit_records
    def crash_after_duplicate(records, events):
        result = commit(records, events)
        if any(kind == "DUPLICATE_DETECTED" for _, kind, _ in events):
            raise RuntimeError("duplicate committed")
        return result
    monkeypatch.setattr(arm.journal, "commit_records", crash_after_duplicate)
    with pytest.raises(RuntimeError, match="duplicate committed"):
        arm.step()
    assert len(arm.trace) == 234
    evaluate = lambda v, o: candidate(v, o, pair=pair)
    _, resumed = prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                              geometry_valid=lambda v: pytest.fail("sampler reentered"),
                              evaluators=(evaluate, evaluate))
    arm = resumed[1]
    assert arm.step()
    assert arm.backend.duplicate_count == 1 and arm.backend.proposals_total == 2
    assert arm.backend.target == 1 and arm.backend.retry == 0 and len(arm.backend.pending) == 1
    assert len(arm.trace) == arm.backend.unique_evaluations == 235
    events = arm.journal.events()
    proposals = [event.payload for event in events if event.event_type == "PROPOSAL_ATTEMPT"]
    assert [proposal["duplicate"] for proposal in proposals] == [True, False]
    assert [proposal["retry"] for proposal in proposals] == [0, 1]
    assert sum(event.event_type == "DUPLICATE_DETECTED" for event in events) == 1


def test_lshade_zero_fe_fallback_replays_in_fresh_session(initialized_pair, monkeypatch):
    metadata, pair, genesis, _, _, arms = initialized_pair
    arm = arms[0]
    frozen = arm.backend._population[0].physical.copy()
    arm.backend.canonicalizer = lambda v: (frozen.copy(), tuple(frozen))
    original = arm._event
    def crash(suffix, kind, payload):
        if kind == "OPTIMIZER_STEP_COMMITTED":
            raise RuntimeError("zero-FE step interrupted")
        return original(suffix, kind, payload)
    arm._event = crash
    with pytest.raises(RuntimeError, match="zero-FE step interrupted"):
        arm.step()
    expected = snapshot(arm.backend)
    before = arm.journal.events()
    assert sum(event.event_type == "PROPOSAL_ATTEMPT" for event in before) == 262
    assert sum(event.event_type == "FALLBACK_INVOKED" for event in before) == 1
    evaluate = lambda v, o: candidate(v, o, pair=pair)
    _, resumed = prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                              geometry_valid=lambda v: pytest.fail("sampler reentered"),
                              evaluators=(evaluate, evaluate))
    arm = resumed[0]
    arm.backend.canonicalizer = lambda v: (frozen.copy(), tuple(frozen))
    arm.evaluator = lambda *args: pytest.fail("duplicate caused evaluator dispatch")
    monkeypatch.setattr(arm.rng.service, "_invoke", lambda *args: pytest.fail("committed RNG redrawn"))
    assert arm.step()
    assert snapshot(arm.backend) == expected
    assert arm.backend.unique_evaluations == len(arm.trace) == 234
    events = arm.journal.events()
    assert sum(event.event_type == "PROPOSAL_ATTEMPT" for event in events) == 262
    assert sum(event.event_type == "FALLBACK_INVOKED" for event in events) == 1
    assert sum(event.event_type == "OPTIMIZER_STEP_COMMITTED" for event in events) == 2
    arm.step_index -= 1  # reread the already committed step, not a new proposal
    assert arm.step()
    assert snapshot(arm.backend) == expected
    assert arm.journal.events()[-1].event_hash == events[-1].event_hash


def test_pending_evaluator_retry_in_new_session_is_not_a_physics_failure(initialized_pair):
    metadata, pair, genesis, _, _, arms = initialized_pair
    calls = []
    def evaluator(v, ordinal):
        calls.append((ordinal, v.tobytes()))
        if ordinal == 235 and sum(o == 235 for o, _ in calls) == 1:
            raise RuntimeError("infrastructure interruption")
        return candidate(v, ordinal, pair=pair)
    def open_pair():
        return prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                            geometry_valid=lambda v: True, evaluators=(evaluator, evaluator))
    arms[1].evaluator = evaluator
    with pytest.raises(RuntimeError, match="infrastructure interruption"):
        arms[1].step()
    assert len(arms[1].trace) == 234
    _, arms = open_pair()
    assert arms[1].step()
    retries = [row for row in calls if row[0] == 235]
    assert len(retries) == 2 and retries[0] == retries[1]
    assert len(arms[1].trace) == arms[1].backend.unique_evaluations == 235
    assert arms[1].trace[-1]["status"] == "PHYSICS_EVALUATED"
    events = arms[1].journal.events()
    assert sum(e.event_type == "INFRASTRUCTURE_INTERRUPTED" for e in events) == 1
    assert sum(e.event_type == "EVALUATOR_ATTEMPT_STARTED" for e in events) == 236


@pytest.mark.parametrize("after_draw", [False, True])
def test_pending_rng_call_restarts_from_durable_pre_state(initialized_pair, after_draw):
    metadata, pair, genesis, _, _, arms = initialized_pair
    evaluator = lambda v, o: candidate(v, o, pair=pair)
    def open_pair():
        return prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                            geometry_valid=lambda v: True, evaluators=(evaluator, evaluator))
    arm = arms[1]
    invoke = arm.rng.service._invoke
    def crash(method, args, kwargs):
        if after_draw:
            invoke(method, args, kwargs)
        raise RuntimeError("RNG call interrupted")
    arm.rng.service._invoke = crash
    with pytest.raises(RuntimeError, match="RNG call interrupted"):
        arm.step()
    events = arm.journal.events()
    starts = [e for e in events if e.event_type == "RNG_DRAW_STARTED"]
    assert len(starts) == 1
    assert not any(e.event_type == "RNG_DRAW_COMMITTED" for e in events)
    _, resumed = open_pair()
    assert resumed[1].step()
    events = resumed[1].journal.events()
    assert sum(e.event_type == "RNG_DRAW_STARTED" and e.event_id == starts[0].event_id for e in events) == 1
    assert sum(e.event_type == "RNG_DRAW_COMMITTED" and e.payload["call_id"] == starts[0].payload["call_id"] for e in events) == 1
    assert resumed[1].backend.unique_evaluations == len(resumed[1].trace) == 235


def test_proposal_before_intent_resumes_without_redrawing(initialized_pair, monkeypatch):
    metadata, pair, genesis, _, _, arms = initialized_pair
    arm = arms[1]
    original = arm._event
    def crash(suffix, kind, payload):
        if kind == "EVALUATION_INTENT":
            raise RuntimeError("crash before intent")
        return original(suffix, kind, payload)
    arm._event = crash
    with pytest.raises(RuntimeError, match="crash before intent"):
        arm.step()
    events = arm.journal.events()
    proposal = [event for event in events if event.event_type == "PROPOSAL_ATTEMPT"][-1]
    assert len(arm.trace) == 234
    evaluate = lambda v, o: candidate(v, o, pair=pair)
    _, resumed = prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                              geometry_valid=lambda v: True, evaluators=(evaluate, evaluate))
    monkeypatch.setattr(resumed[1].rng.service, "_invoke", lambda *args: pytest.fail("committed RNG redrawn"))
    assert resumed[1].step()
    intents = [event for event in resumed[1].journal.events() if event.event_type == "EVALUATION_INTENT"]
    assert intents[-1].payload["physical"].tobytes() == proposal.payload["physical"].tobytes()
    assert len(resumed[1].trace) == resumed[1].backend.unique_evaluations == 235


def test_foreign_pair_identity_fails_before_hydration(initialized_pair, monkeypatch):
    metadata, pair, genesis, _, _, _ = initialized_pair
    foreign = replace(pair, config_sha256="f" * 64)
    monkeypatch.setattr("sawopt.studies.stage5a2.arm.restore",
                        lambda *args: pytest.fail("hydration with foreign identity"))
    with pytest.raises(GenesisError, match="identity|roster"):
        prepare_pair(pair=foreign, genesis=genesis, metadata=metadata,
                     geometry_valid=lambda v: pytest.fail("sampler reentered"),
                     evaluators=(lambda *args: pytest.fail("evaluator dispatched"),) * 2)


def test_hash_valid_snapshot_fe_mismatch_fails_before_hydration(initialized_pair, monkeypatch):
    metadata, pair, genesis, _, _, arms = initialized_pair
    arm = arms[1]
    arm.backend.unique_evaluations = 235  # forged post-state; ledger still has 234
    forged = snapshot(arm.backend)
    arm._event("step:0", "OPTIMIZER_STEP_STARTED", {"state": forged, "rng_ordinal": 0, "no_progress": 0})
    arm._event("step:0", "OPTIMIZER_STEP_COMMITTED", {"state": forged, "rng_ordinal": 0, "no_progress": 0})
    monkeypatch.setattr("sawopt.studies.stage5a2.arm.restore",
                        lambda *args: pytest.fail("hydration before ledger validation"))
    with pytest.raises(ValueError, match="FE.*ledger"):
        prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                     geometry_valid=lambda v: pytest.fail("sampler reentered"),
                     evaluators=(lambda *args: pytest.fail("evaluator dispatched"),) * 2)


def test_hash_valid_pending_step_prestate_mismatch_fails_before_hydration(initialized_pair, monkeypatch):
    metadata, pair, genesis, _, _, arms = initialized_pair
    arm = arms[1]
    # All members, caches, FE and RNG remain valid but this is not the
    # immediately preceding committed initialization state.
    arm.backend.population[0], arm.backend.population[1] = arm.backend.population[1], arm.backend.population[0]
    arm._event("step:0", "OPTIMIZER_STEP_STARTED", {
        "state": snapshot(arm.backend), "rng_ordinal": 0, "no_progress": 0,
    })
    monkeypatch.setattr("sawopt.studies.stage5a2.arm.restore",
                        lambda *args: pytest.fail("hydration before pre-state validation"))
    with pytest.raises(ValueError, match="step.*pre-state.*prefix"):
        prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                     geometry_valid=lambda v: pytest.fail("sampler reentered"),
                     evaluators=(lambda *args: pytest.fail("evaluator dispatched"),) * 2)


@pytest.mark.parametrize("role", [0, 1])
def test_hash_valid_snapshot_cache_result_mismatch_fails_before_hydration(initialized_pair, monkeypatch, role):
    metadata, pair, genesis, _, _, arms = initialized_pair
    arm = arms[role]
    cache = arm.backend._cache if role == 0 else arm.backend.cache
    key = next(iter(cache))
    cache[key]["metrics"]["worst_il_db"] += 1.0
    forged = snapshot(arm.backend)
    arm._event("step:0", "OPTIMIZER_STEP_STARTED", {"state": forged, "rng_ordinal": 0, "no_progress": 0})
    monkeypatch.setattr("sawopt.studies.stage5a2.arm.restore",
                        lambda *args: pytest.fail("hydration before result validation"))
    with pytest.raises(ValueError, match="snapshot.*result.*ledger"):
        prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                     geometry_valid=lambda v: pytest.fail("sampler reentered"),
                     evaluators=(lambda *args: pytest.fail("evaluator dispatched"),) * 2)


def test_hash_valid_result_rank_mismatch_fails_before_hydration(initialized_pair, monkeypatch):
    metadata, pair, genesis, _, _, arms = initialized_pair
    arm = arms[1]
    physical = arm.backend.population[0].physical.copy()
    physical[0] += 0.001
    key = canonical_key_tokens(physical)
    result = candidate(physical, 235, pair=pair)
    arm._event("forged", "EVALUATION_RESULT_COMMITTED", {
        "key": key, "physical": physical, "ordinal": 235, "step_id": "step:0",
        "proposal_index": 0, "result": result, "status": "PHYSICS_EVALUATED",
        "rank": (9.,) * 7, "best_rank": arm.best_rank, "best_key": arm.best_key,
        "pending_target": None,
    })
    monkeypatch.setattr("sawopt.studies.stage5a2.arm.restore",
                        lambda *args: pytest.fail("hydration before rank validation"))
    with pytest.raises(ValueError, match="rank.*ledger"):
        prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                     geometry_valid=lambda v: pytest.fail("sampler reentered"),
                     evaluators=(lambda *args: pytest.fail("evaluator dispatched"),) * 2)


def test_corrupt_arm_journal_fails_before_recovery_evaluator(initialized_pair):
    metadata, pair, genesis, _, _, _ = initialized_pair
    with sqlite3.connect(genesis.cell_paths[1]) as connection:
        connection.execute("UPDATE events SET payload=? WHERE sequence=1", (b"corrupt",))
    def forbidden(*args):
        pytest.fail("evaluation must not occur on a corrupted journal")
    with pytest.raises(JournalError):
        prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                     geometry_valid=forbidden, evaluators=(forbidden, forbidden))
