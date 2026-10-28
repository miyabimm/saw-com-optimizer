"""Local Q0 invariants only: Q1-D/E and all official gates remain pending."""
import copy
from dataclasses import replace
import subprocess
import sys

import numpy as np
import pytest

from sawopt.optimization.controlled_de import ControlledDEBackend
from sawopt.optimization.lshade import LShadeBackend
from sawopt.optimization.selection import GeometryFirstComparator
from sawopt.studies.stage5a2.arm import BudgetStalled, InvalidRecord
from sawopt.studies.stage5a2.candidates import InvalidCandidate, validate_candidate
from sawopt.studies.stage5a2.codec import encode_typed
from sawopt.studies.stage5a2.live_state import restore, snapshot
from sawopt.studies.stage5a2.pair import LSHADE_CONFIG, prepare_pair
from .q1bc_fixture import fixture, candidate


def _simple(v, score=None):
    return {"evaluation_status": "PHYSICS_EVALUATED", "feasible": True,
            "metrics": {"worst_il_db": float(v.sum()) if score is None else score}}


def _de(seed=4):
    backend = ControlledDEBackend([[0., 1.]] * 13, canonicalizer=lambda v: (v.copy(), tuple(v)), seed=seed)
    backend.initialize(_simple, population=np.random.Generator(np.random.PCG64(5)).random((234, 13)))
    return backend


def test_de_exact_4096_fe_including_initial_and_final_partial():
    backend = _de()
    while backend.status == "SEARCHING":
        backend.step()
    assert backend.unique_evaluations == 4096
    assert backend.proposals_total == 3862 and backend.duplicate_count == 0
    assert backend.generation_sizes == [234] * 16 + [118]
    state = snapshot(backend)
    assert backend.step() is False
    assert snapshot(backend) == state  # terminal boundary has no draw/state change


def test_de_synchronous_donors_parent_tie_and_pending_trials(monkeypatch):
    backend = _de()
    original = copy.deepcopy(backend.population)
    seen = []
    def trial(parents, target, rng):
        np.testing.assert_array_equal(parents, [m.x for m in original])
        seen.append(target)
        return np.full(13, .1 + target / 1000.), {}
    monkeypatch.setattr("sawopt.optimization.controlled_de.de_trial", trial)
    backend.evaluator = lambda v: _simple(v, -1.)
    backend.step()
    assert backend.target == 1 and len(backend.pending) == 1
    np.testing.assert_array_equal(backend.population[0].x, original[0].x)
    # An exact tuple tie keeps the original second parent on generation commit.
    backend.evaluator = lambda v: copy.deepcopy(original[backend.target].result)
    for _ in range(233):
        backend.step()
    assert seen == list(range(234))
    np.testing.assert_array_equal(backend.population[0].physical, np.full(13, .1))
    for actual, expected in zip(backend.population[1:], original[1:]):
        np.testing.assert_array_equal(actual.x, expected.x)


def test_de_duplicate_cap_stops_without_4097th_proposal_or_draw(monkeypatch):
    backend = _de()
    calls = []
    def duplicate(parents, target, rng):
        calls.append(target)
        return parents[target].copy(), {}
    monkeypatch.setattr("sawopt.optimization.controlled_de.de_trial", duplicate)
    backend.step()
    assert backend.status == "BUDGET_STALLED"
    assert len(calls) == backend.proposals_total == backend.duplicate_count == 4096
    assert backend.unique_evaluations == 234 and backend.target == 0
    assert backend.generation_sizes == [] and backend.parents
    backend.step()
    assert len(calls) == 4096


def test_de_aggregate_watchdog_before_extra_draw(monkeypatch):
    backend = _de()
    backend.no_progress = 65535
    calls = []
    monkeypatch.setattr("sawopt.optimization.controlled_de.de_trial",
                        lambda parents, target, rng: (calls.append(1) or parents[target].copy(), {}))
    backend.step()
    assert backend.status == "BUDGET_STALLED" and backend.no_progress == 65536
    assert len(calls) == 1 and backend.unique_evaluations == 234


def _pair(tmp_path, evaluator=None):
    metadata, pair, genesis, canonicalize = fixture(tmp_path)
    evaluator = evaluator or (lambda v, o: candidate(v, o, pair=pair))
    seal, arms = prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                              geometry_valid=lambda v: True, evaluators=(evaluator, evaluator))
    return metadata, pair, genesis, canonicalize, seal, arms


def test_actual_234_member_boundary_two_certificates_before_fe_and_private_ledgers(tmp_path):
    metadata, pair, genesis, canonicalize = fixture(tmp_path)
    calls = [[], []]
    def evaluate(role, v, ordinal):
        if not calls[role]:
            for path, name in zip(genesis.cell_paths, ("lshade", "controlled_de")):
                from sawopt.studies.stage5a2.journal import SQLiteJournal
                journal = SQLiteJournal(path, dict(pair.cell_journal_uuids)[name], name, create=False)
                assert sum(e.event_type == "INITIALIZATION_PREFLIGHT_CERTIFICATE" for e in journal.events()) == 1
        calls[role].append(v.tobytes())
        return candidate(v, ordinal, pair=pair)
    seal, arms = prepare_pair(pair=pair, genesis=genesis, metadata=metadata, geometry_valid=lambda v: True,
                              evaluators=(lambda v, o: evaluate(0, v, o), lambda v, o: evaluate(1, v, o)))
    assert calls[0] == calls[1] == [m.sealed_physical_le_f64 for m in seal.members]
    for arm in arms:
        assert arm.backend.unique_evaluations == len(arm.results) == len(arm.trace) == 234
    assert arms[0].results is not arms[1].results
    assert arms[0].backend._cache_frequency_versions is not arms[1].backend.cache
    arms[0].step()
    assert len(arms[0].trace) == 235 and len(arms[1].trace) == 234
    # A fresh attachment loads the seal/results; neither sampler/geometry nor
    # committed initialization/search results may be dispatched again.
    def forbidden(*args):
        pytest.fail("sealed population or durable result redriven")
    loaded_seal, resumed = prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                                        geometry_valid=forbidden, evaluators=(forbidden, forbidden))
    assert loaded_seal == seal
    assert resumed[0].step_index == 1
    assert len(resumed[0].trace) == resumed[0].backend.unique_evaluations == 235


def test_pair_actual_preflight_mismatch_stops_both_before_any_fe(tmp_path, monkeypatch):
    metadata, pair, genesis, canonicalize = fixture(tmp_path)
    original = ControlledDEBackend.initial_input
    def changed(self, v):
        actual, key = original(self, v)
        actual[0] = np.nextafter(actual[0], np.inf)
        return actual, tuple(actual)
    monkeypatch.setattr(ControlledDEBackend, "initial_input", changed)
    calls = []
    with pytest.raises(Exception, match="REPRESENTATION_MISMATCH"):
        prepare_pair(pair=pair, genesis=genesis, metadata=metadata, geometry_valid=lambda v: True,
                     evaluators=(lambda v, o: calls.append(v),) * 2)
    assert not calls


def test_lshade_hooked_unhooked_bitwise_parity_and_frozen_settings(tmp_path):
    metadata, pair, _, canonicalize, seal, arms = _pair(tmp_path)
    hooked = arms[0]
    seed = hooked.rng.service.synthetic_test_seed
    baseline = LShadeBackend(metadata.bounds_array(), seed=seed, config=LSHADE_CONFIG,
                             integer_indices=metadata.integer_indices, canonicalizer=canonicalize,
                             comparator=GeometryFirstComparator(), source_config_fingerprint=pair.config_sha256)
    baseline.initialize(lambda v: candidate(v, baseline.unique_evaluations + 1, pair=pair),
                        population=np.asarray([np.frombuffer(m.lshade_input_genotype_le_f64, dtype="<f8") for m in seal.members]))
    assert snapshot(baseline) == snapshot(hooked.backend)
    for _ in range(8):
        baseline._generation(4096)
        hooked.step()
        assert snapshot(baseline) == snapshot(hooked.backend)
    assert baseline.initial_population_size == baseline.memory_update_batch_size == 234
    assert baseline.population_schedule_terminal_budget == baseline.hard_max_budget == baseline.total_budget == 4096
    assert baseline.minimum_population_size == 4 and baseline.history_size == 6
    assert baseline.max_duplicate_retries == 5 and baseline.pbest_max_fraction == .20
    assert baseline.archive_rate == 1. and baseline.exhaustion_duplicate_streak is None
    foreign = LShadeBackend(metadata.bounds_array(), config=dict(LSHADE_CONFIG, population_schedule_terminal_budget=96000, hard_max_budget=96000))
    with pytest.raises(ValueError, match="identity mismatch"):
        restore(foreign, snapshot(baseline))


def test_lossless_live_roundtrip_infinity_and_no_v4_serializer(tmp_path, monkeypatch):
    _, pair, _, _, _, arms = _pair(tmp_path)
    backend = arms[0].backend
    backend._population[0].result = candidate(backend._population[0].physical, 1, pair=pair, status="PHYSICS_FAILED")
    backend._history_rank_index[backend._population[0].key] = (GeometryFirstComparator().rank_key(backend._population[0].result), tuple(backend._population[0].physical), 0)
    backend._population[0].x[0] = -0.
    monkeypatch.setattr(LShadeBackend, "state_dict", lambda self: pytest.fail("lossy v4 serializer used"))
    raw = snapshot(backend)
    backend.m_f[0] = .7
    restore(backend, raw)
    assert snapshot(backend) == raw
    assert np.signbit(backend._population[0].x[0])
    with pytest.raises(ValueError):
        restore(backend, encode_typed({"state_version": 4, "rank": [None]}))
    backend.m_f[0] = np.nan
    with pytest.raises(ValueError, match="numeric live field"):
        snapshot(backend)


@pytest.mark.parametrize("role", [0, 1])
def test_pre_step_result_before_update_replay_does_not_recommit_fe_or_redraw(tmp_path, monkeypatch, role):
    _, _, _, _, _, arms = _pair(tmp_path)
    arm = arms[role]
    original = arm._event
    def crash(suffix, kind, payload):
        if kind == "OPTIMIZER_STEP_COMMITTED":
            raise RuntimeError("result-before-update crash")
        return original(suffix, kind, payload)
    arm._event = crash
    with pytest.raises(RuntimeError, match="result-before-update"):
        arm.step()
    assert len(arm.trace) == 235
    end_state = snapshot(arm.backend)
    arm._event = original
    monkeypatch.setattr(arm.rng.service, "_invoke", lambda *a, **k: pytest.fail("committed RNG redrawn"))
    arm.evaluator = lambda *a: pytest.fail("durable result reevaluated")
    arm.step()
    assert snapshot(arm.backend) == end_state
    assert len(arm.trace) == len(arm.results) == arm.backend.unique_evaluations == 235
    events = arm.journal.events()
    assert sum(e.event_type == "EVALUATION_RESULT_COMMITTED" for e in events) == 235
    # Loading an already committed transition must not run its source twice.
    arm.step_index -= 1
    committed_state = snapshot(arm.backend)
    arm.step()
    assert snapshot(arm.backend) == committed_state
    # Also interrupt immediately AFTER the journal result, BEFORE _evaluate
    # can populate the backend cache or perform survivor/adaptation updates.
    baseline = copy.copy(arm.backend)
    baseline.rng = np.random.Generator(np.random.PCG64())
    if role == 0:
        del baseline._q1_observer
    else:
        baseline.observe = None
    restore(baseline, snapshot(arm.backend))
    baseline.evaluator = lambda v: candidate(v, baseline.unique_evaluations + 1, pair=arm.pair)
    baseline._generation(4096) if role == 0 else baseline.step()
    expected = snapshot(baseline)
    monkeypatch.undo()
    real_evaluate = arm.evaluate
    arm.evaluator = lambda v, o: candidate(v, o, pair=arm.pair)
    def after_result(v):
        real_evaluate(v)
        raise RuntimeError("immediate result boundary")
    arm.backend.evaluator = after_result
    with pytest.raises(RuntimeError, match="immediate result boundary"):
        arm.step()
    assert len(arm.trace) == 236 and arm.backend.unique_evaluations == 235
    arm.backend.evaluator = arm.evaluate
    monkeypatch.setattr(arm.rng.service, "_invoke", lambda *a, **k: pytest.fail("redraw"))
    arm.evaluator = lambda *a: pytest.fail("reevaluate")
    arm.step()
    assert snapshot(arm.backend) == expected
    assert len(arm.trace) == arm.backend.unique_evaluations == 236


@pytest.mark.parametrize("initial_streak", [0, 65536 - 262])
def test_lshade_six_normal_attempts_one_256_candidate_fallback_first_none_zero_fe(tmp_path, initial_streak):
    _, _, _, _, _, arms = _pair(tmp_path)
    arm = arms[0]
    backend = arm.backend
    original_canonicalizer = backend.canonicalizer
    frozen = backend._population[0].physical.copy()
    backend.canonicalizer = lambda v: (frozen.copy(), tuple(frozen))
    arm.no_progress = initial_streak
    before_fe = backend.unique_evaluations
    before_events = len(arm.journal.events())
    arm.step()
    new = arm.journal.events()[before_events:]
    proposals = [e.payload for e in new if e.event_type == "PROPOSAL_ATTEMPT"]
    assert [p["phase"] for p in proposals] == ["normal"] * 6 + ["fallback"] * 256
    assert sum(e.event_type == "FALLBACK_INVOKED" for e in new) == 1
    assert sum(e.event_type == "OPTIMIZER_STEP_COMMITTED" for e in new) == 1
    assert backend.unique_evaluations == before_fe == len(arm.trace)
    assert backend.generations == 1 and backend._memory_batch_proposals == 1
    assert arm.no_progress == initial_streak + 262
    if initial_streak:
        assert arm.status == "BUDGET_STALLED"
        terminal = [e for e in new if e.event_type == "CELL_TERMINAL_STATUS_COMMITTED"]
        assert len(terminal) == 1 and "pending_step" not in terminal[0].payload
        head = arm.journal.events()[-1].event_hash
        assert arm.step() is False
        assert arm.journal.events()[-1].event_hash == head
        return
    # At the common cutoff, finish no further proposal or random call. The
    # interrupted source transition remains pending instead of being invented.
    arm.no_progress = 65535
    assert arm.step() is False
    assert arm.status == "BUDGET_STALLED" and arm.no_progress == 65536
    events = arm.journal.events()
    last_proposal = max(e.sequence for e in events if e.event_type == "PROPOSAL_ATTEMPT")
    assert not any(e.event_type.startswith("RNG_DRAW") for e in events if e.sequence > last_proposal)
    assert backend.unique_evaluations == before_fe
    backend.canonicalizer = original_canonicalizer


@pytest.mark.parametrize("status", ["GEOMETRY_REJECTED", "PHYSICS_FAILED"])
def test_search_reject_or_modeled_failure_charges_one_fe_no_duplicate_retry(tmp_path, status):
    _, pair, _, _, _, arms = _pair(tmp_path)
    for arm in arms:
        arm.evaluator = lambda v, o: candidate(v, o, pair=pair, status=status)
        arm.step()
        assert len(arm.trace) == arm.backend.unique_evaluations == 235
        assert arm.trace[-1]["status"] == status
        assert arm.trace[-1]["rank"] == GeometryFirstComparator().rank_key(arm.trace[-1]["result"])


def test_invalid_record_counted_quarantined_not_ranked_and_infrastructure_not_failed(tmp_path):
    _, _, _, _, _, arms = _pair(tmp_path)
    arm = arms[0]
    arm.evaluator = lambda v, o: {"evaluation_status": "UNKNOWN"}
    with pytest.raises(InvalidRecord):
        arm.step()
    assert len(arm.trace) == 235 and arm.trace[-1]["rank"] is None
    assert arm.status == "INVALID_RECORD"
    assert arm.step() is False
    other = arms[1]
    def raises(v, o):
        raise ValueError("infrastructure fixture, not a typed modeled failure")
    other.evaluator = raises
    with pytest.raises(ValueError, match="infrastructure fixture"):
        other.step()
    assert len(other.trace) == 234 and other.status == "INFRASTRUCTURE_INTERRUPTED"


@pytest.mark.parametrize("mutate", [
    lambda r: r.pop("metrics"), lambda r: r.update(extra=True),
    lambda r: r.update(feasible="true"), lambda r: r.update(max_violation=1001.),
    lambda r: r.update(evaluation_status="UNKNOWN"), lambda r: r.update(first_evaluation_ordinal=True),
    lambda r: r["metrics"].update(worst_il_db=np.inf),
])
def test_strict_schema_rejects_before_comparator(tmp_path, mutate):
    _, pair, _, _ = fixture(tmp_path)
    v = np.ones(13)
    record = candidate(v, 1, pair=pair)
    mutate(record)
    with pytest.raises((InvalidCandidate, ValueError)):
        validate_candidate(record, vector=v, ordinal=1, topology=pair.topology, grid_sha256=pair.grid_sha256)


def test_synthetic_execution_in_fresh_process_import_call_guard(tmp_path):
    script = r'''
import sys
class Guard:
    def find_spec(self, fullname, *args):
        if fullname.startswith(("sawopt.physics", "sawopt.problem", "sawopt.evaluation", "sawopt.io", "sawopt.reporting")):
            raise AssertionError("forbidden synthetic import: " + fullname)
sys.meta_path.insert(0, Guard())
from pathlib import Path
from tests.unit.studies.q1bc_fixture import fixture, candidate
from sawopt.studies.stage5a2.pair import prepare_pair
m,p,g,_=fixture(Path(sys.argv[1]))
s,arms=prepare_pair(pair=p,genesis=g,metadata=m,geometry_valid=lambda v:True,evaluators=(lambda v,o:candidate(v,o,pair=p),)*2)
for arm in arms: arm.step()
assert [len(a.trace) for a in arms] == [235,235]
assert not any(k.startswith(("sawopt.physics", "sawopt.problem", "sawopt.evaluation")) for k in sys.modules)
'''
    subprocess.run([sys.executable, "-c", script, str(tmp_path)], check=True)
