"""Representative fresh-session synthetic recovery checks (not gate closure)."""
import sqlite3
from types import SimpleNamespace

import pytest

from sawopt.studies.stage5a2.arm import ArmSession
from sawopt.studies.stage5a2.codec import encode_typed
from sawopt.studies.stage5a2.journal import JournalError, SQLiteJournal
from sawopt.studies.stage5a2.initialization import canonical_key_tokens
from sawopt.studies.stage5a2.live_state import snapshot
from sawopt.studies.stage5a2.pair import prepare_pair
from .q1bc_fixture import fixture, candidate


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
    evaluate = lambda v, o: candidate(v, o, pair=pair)
    reference = arms[role]
    assert reference.step() and reference.step()
    kinds = {"RNG_DRAW_STARTED", "RNG_DRAW_COMMITTED", "PROPOSAL_ATTEMPT",
             "DUPLICATE_DETECTED", "EVALUATION_INTENT", "EVALUATION_RESULT_COMMITTED"}
    def scientific_events(arm):
        return [(e.event_type, encode_typed(e.payload)) for e in arm.journal.events() if e.event_type in kinds]
    def top16(arm):
        return [(r["rank"], r["ordinal"], r["key"]) for r in
                sorted(arm.trace, key=lambda r: (r["rank"], r["ordinal"]))[:16]]
    expected = (scientific_events(reference), snapshot(reference.backend), encode_typed(reference.trace),
                reference.best_rank, reference.best_key, top16(reference))
    # Restore an isolated baseline to the same identity-bound journal paths.
    # Capture all reference data first; no old session is used after reset.
    _, _, _, _, _, restarted_arms = _q1_initialized_baseline()
    def open_restart():
        return prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                            geometry_valid=lambda v: True, evaluators=(evaluate, evaluate))[1][role]
    interrupted = restarted_arms[role]
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
