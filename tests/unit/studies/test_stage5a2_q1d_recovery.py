"""Representative fresh-session synthetic recovery checks (not gate closure)."""
from types import SimpleNamespace

import pytest

from sawopt.studies.stage5a2.arm import ArmSession
from sawopt.studies.stage5a2.codec import encode_typed
from sawopt.studies.stage5a2.journal import SQLiteJournal
from sawopt.studies.stage5a2.live_state import snapshot
from sawopt.studies.stage5a2.pair import prepare_pair
from .q1bc_fixture import fixture, candidate


@pytest.mark.parametrize("role", [0, 1])
def test_new_session_hydrates_committed_steps_and_replays_pending(tmp_path, role):
    metadata, pair, genesis, _ = fixture(tmp_path)
    evaluate = lambda v, o: candidate(v, o, pair=pair)
    def open_pair():
        return prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                            geometry_valid=lambda v: True, evaluators=(evaluate, evaluate))
    _, arms = open_pair()
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
def test_uninterrupted_and_fresh_session_scientific_trajectory_match(tmp_path, role):
    original = tmp_path / "original"
    original.mkdir()
    metadata, pair, genesis, _ = fixture(original)
    evaluate = lambda v, o: candidate(v, o, pair=pair)
    _, arms = prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                           geometry_valid=lambda v: True, evaluators=(evaluate, evaluate))
    reference = arms[role]
    assert reference.step() and reference.step()

    # Independent deterministic genesis: roster locators bind each journal
    # to its own directory, so copying a pair database would be invalid.
    clone = tmp_path / "restart"
    clone.mkdir()
    _, _, restart_genesis, _ = fixture(clone)
    def open_restart():
        return prepare_pair(pair=pair, genesis=restart_genesis, metadata=metadata,
                            geometry_valid=lambda v: True, evaluators=(evaluate, evaluate))[1][role]
    interrupted = open_restart()
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
    kinds = {"RNG_DRAW_STARTED", "RNG_DRAW_COMMITTED", "PROPOSAL_ATTEMPT",
             "DUPLICATE_DETECTED", "EVALUATION_INTENT", "EVALUATION_RESULT_COMMITTED"}
    def scientific_events(arm):
        return [(e.event_type, encode_typed(e.payload)) for e in arm.journal.events() if e.event_type in kinds]
    assert scientific_events(recovered) == scientific_events(reference)
    assert snapshot(recovered.backend) == snapshot(reference.backend)
    assert encode_typed(recovered.trace) == encode_typed(reference.trace)
    assert (recovered.best_rank, recovered.best_key) == (reference.best_rank, reference.best_key)
    def top16(arm):
        return [(r["rank"], r["ordinal"], r["key"]) for r in
                sorted(arm.trace, key=lambda r: (r["rank"], r["ordinal"]))[:16]]
    assert top16(recovered) == top16(reference)
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
