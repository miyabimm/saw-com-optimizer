from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
import yaml

from sawopt.design.space import canonical_design
from sawopt.evaluation import feasibility_objective
from sawopt.io.scientific_config import resolve_scientific_config
from sawopt.optimization.lshade import LShadeBackend
from sawopt.optimization.selection import FeasibilityFirstComparator

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "configs/examples/scientific_validation_only.yaml"


def make_snapshot(*, budget=12, initial_population=4, compact=False,
                 exhaustion_duplicate_streak=None, narrow=False):
    declaration = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    effective = declaration
    effective["model"]["parameters"] = {
        "inline": effective["model"]["parameters"]["inline"]
    }
    for role in ("search", "validation"):
        effective["grids"][role] = {"inline": effective["grids"][role]["inline"]}
    settings = effective["optimizer"]["settings"]
    effective["optimizer"]["search_fe_limit"] = budget
    for key in (
        "total_budget", "hard_max_budget", "population_schedule_terminal_budget",
        "requested_unique_budget",
    ):
        settings[key] = budget
    settings["initial_population"] = initial_population
    settings["min_population"] = 4
    settings["compact_history_cache"] = compact
    settings["exhaustion_duplicate_streak"] = exhaustion_duplicate_streak
    if narrow:
        variables = effective["design"]["variables"]
        integer_bounds = ((20, 21), (10, 11), (40, 41))
        for variable, bounds in zip(variables[1:4], integer_bounds, strict=True):
            variable["bounds"] = list(bounds)
        for index, value in ((0, 5.0), (4, 0.5), (5, 0.5), (6, 80.0)):
            variables[index]["bounds"] = [value, float(np.nextafter(value, np.inf))]
    return resolve_scientific_config(
        effective, config_path=Path("test-owned.yaml"), config_bytes=b"test-owned",
    )


def synthetic_evaluator(snapshot, calls=None, *, fail_at=None, mutation=False,
                        corrupt=None):
    effective = snapshot["effective_config"]
    comparator = FeasibilityFirstComparator()
    invocation = {"count": 0}

    def evaluate(vector, *, phase):
        invocation["count"] += 1
        ordinal = invocation["count"]
        candidate = np.asarray(vector, dtype=np.float64)
        if mutation:
            vector[0] = float(vector[0]) + 1.0
        design, canonical, key = canonical_design(candidate)
        if calls is not None:
            calls.append((phase, candidate.tobytes(), key))
        if fail_at == ordinal:
            raise ArithmeticError(f"synthetic {phase.lower()} failure {ordinal}")
        score = 1.0 + float(np.sum((canonical - np.asarray(
            [5.0, 40.0, 30.0, 70.0, 1.0, 1.0, 80.0], dtype=np.float64,
        )) ** 2)) * 1e-5
        metrics = {
            "worst_il_db": score,
            "ripple_db": 0.25,
            "input_vswr": 1.2,
            "output_vswr": 1.3,
            "source_return_loss_db_min": 10.0,
            "load_return_loss_db_min": 11.0,
            "stop_attenuation_db": [40.0, 41.0],
            "length_um": 100.0,
            "width_um": 80.0,
            "electrodes": 200.0,
        }
        violations = {
            "il": 0.0, "ripple": 0.0, "input_vswr": 0.0,
            "output_vswr": 0.0, "stop_0": 0.0, "stop_1": 0.0,
            "geometry": 0.0,
        }
        objective, parts = feasibility_objective(metrics, violations)
        grid_name = "search_grid" if phase == "SEARCH" else "validation_grid"
        grid = effective["grids"]["search" if phase == "SEARCH" else "validation"]
        result = {
            "evaluation_phase": phase,
            "effective_config_sha256": snapshot["effective_config_sha256"],
            "model_sha256": snapshot["input_sha256"]["model"],
            "proposal_vector": candidate.tolist(),
            "design": vars(design),
            "canonical_vector": canonical.tolist(),
            "canonical_key": key,
            "candidate_vector": canonical.tolist(),
            "grid_sha256": snapshot["input_sha256"][grid_name],
            "grid_point_count": len(grid["points"]),
            "metrics": metrics,
            "violations": violations,
            "feasible": True,
            "max_violation": 0.0,
            "sum_violation": 0.0,
            "objective": objective,
            "search_scalar_objective": objective,
            "objective_parts": parts,
            "diagnostics": {"fixture": True},
        }
        result["rank_key"] = comparator.rank_key(result)
        if corrupt == "rank":
            result["rank_key"] = (999.0,)
        elif corrupt == "objective":
            result["objective"] += 1.0
            result["search_scalar_objective"] = result["objective"]
        elif corrupt == "canonical":
            result["canonical_vector"][0] += 0.01
        elif corrupt == "vector":
            result["canonical_vector"] = result["canonical_vector"][:-1]
        elif corrupt == "phase":
            result["evaluation_phase"] = "VALIDATION"
        elif corrupt == "grid":
            result["grid_sha256"] = "0" * 64
        return result

    return evaluate


def run(snapshot, search, validation=None):
    from sawopt.optimization.configured_search import run_configured_lshade

    return run_configured_lshade(
        snapshot, search_evaluator=search,
        validation_evaluator=search if validation is None else validation,
    )


def test_configured_search_matches_direct_lshade_and_separates_validation(monkeypatch):
    snapshot = make_snapshot(budget=12, initial_population=4, compact=True)
    import sawopt.optimization.configured_search as configured_search

    original_backend = configured_search.LShadeBackend
    captured_backends = []

    class CapturingBackend(original_backend):
        def initialize(self, evaluator, *, population=None, comparator=None):
            super().initialize(evaluator, population=population, comparator=comparator)
            self.initial_members = [(member.physical.tobytes(), member.key) for member in self._population]
            self.initial_rng_state = copy.deepcopy(self.rng.bit_generator.state)
            captured_backends.append(self)

    monkeypatch.setattr(configured_search, "LShadeBackend", CapturingBackend)
    orchestrated_calls = []
    search = synthetic_evaluator(snapshot, orchestrated_calls)
    validation_calls = []
    validation = synthetic_evaluator(snapshot, validation_calls)
    result = run(snapshot, search, validation)

    orchestrated_sequence = list(orchestrated_calls)
    orchestrated_calls.clear()
    effective = snapshot["effective_config"]
    settings = effective["optimizer"]["settings"]
    bounds = [variable["bounds"] for variable in effective["design"]["variables"]]
    hard_bounds = [variable["hard_bounds"] for variable in effective["design"]["variables"]]

    def canonicalizer(vector):
        _design, canonical, key = canonical_design(vector)
        return canonical, key

    def direct_evaluator(vector):
        return search(vector, phase="SEARCH")

    direct = LShadeBackend(
        bounds, seed=effective["optimizer"]["seed"],
        config={**settings, "hard_bounds": hard_bounds}, integer_indices=(1, 2, 3),
        canonicalizer=canonicalizer, comparator=FeasibilityFirstComparator(),
    )
    direct.initialize(direct_evaluator)
    direct_initial_members = [(member.physical.tobytes(), member.key) for member in direct._population]
    direct_initial_rng_state = copy.deepcopy(direct.rng.bit_generator.state)
    direct.advance_to_unique_budget(effective["optimizer"]["search_fe_limit"])
    orchestrated_backend = captured_backends[0]

    assert orchestrated_backend.initial_members == direct_initial_members
    assert json.dumps(orchestrated_backend.initial_rng_state, sort_keys=True, separators=(",", ":")) == json.dumps(
        direct_initial_rng_state, sort_keys=True, separators=(",", ":"),
    )
    assert orchestrated_backend.population().tobytes() == direct.population().tobytes()
    assert [member.key for member in orchestrated_backend._population] == [
        member.key for member in direct._population
    ]
    assert [(vector_bytes, key) for phase, vector_bytes, key in orchestrated_sequence[:4]] == (
        orchestrated_backend.initial_members
    )
    assert result["status"] == "COMPLETED"
    assert result["identity"]["effective_config_sha256"] == snapshot["effective_config_sha256"]
    assert result["identity"]["input_sha256"] == snapshot["input_sha256"]
    assert result["identity"]["expected_cells"] == effective["storage"]["expected_cells"]
    assert result["identity"]["seed"] == effective["optimizer"]["seed"]
    assert result["search"]["status"] == "BUDGET_REACHED"
    counters = result["search"]["counters"]
    assert counters["unique_evaluations"] == direct.unique_evaluations == 12
    assert counters["proposals_total"] == direct.proposals_total
    assert counters["duplicate_count"] == direct.duplicate_count
    assert counters["cache_hits"] == direct.cache_hits
    assert counters["search_evaluator_attempts"] == counters["search_evaluator_records_returned"] == 12
    assert counters["proposals_total"] == counters["unique_evaluations"] + counters["cache_hits"]
    assert counters["search_grid_points_requested"] == (
        counters["search_evaluator_attempts"] * counters["search_grid_points_per_call"]
    )
    assert counters["raw_offspring_count"] <= counters["proposals_total"]
    assert result["search"]["incumbent"]["rank_key"] == list(
        FeasibilityFirstComparator().rank_key(direct.incumbent())
    )
    assert result["search"]["incumbent"]["canonical_vector"] == direct.incumbent()["canonical_vector"]
    assert result["search"]["summary"]["generations"] == direct.generations
    assert result["search"]["summary"]["population_schedule_identifier"] == direct.population_schedule_identifier
    assert result["search"]["summary"]["population_schedule_version"] == direct.population_schedule_version
    assert result["search"]["summary"]["population_schedule_terminal_budget"] == direct.population_schedule_terminal_budget
    assert len(orchestrated_calls) == counters["search_evaluator_attempts"]
    assert orchestrated_calls == orchestrated_sequence
    assert all(phase == "SEARCH" for phase, _vector_bytes, _key in orchestrated_calls)

    validation_result = result["validation"]
    assert validation_result["status"] == "VALIDATED"
    assert validation_result["grid_sha256"] == snapshot["input_sha256"]["validation_grid"]
    assert validation_result["grid_point_count"] == len(effective["grids"]["validation"]["points"])
    assert validation_result["requested_grid_points"] == len(effective["grids"]["validation"]["points"])
    assert validation_result["evaluator_calls"] == 1
    assert validation_result["record"]["canonical_vector"] == result["search"]["incumbent"]["canonical_vector"]
    assert len(validation_calls) == 1 and validation_calls[0][0] == "VALIDATION"
    assert not any(phase == "VALIDATION" for phase, _vector_bytes, _key in orchestrated_calls)


def test_initialization_evaluator_failure_is_attempted_but_not_a_committed_unique_fe():
    snapshot = make_snapshot(budget=8, initial_population=4)
    result = run(snapshot, synthetic_evaluator(snapshot, fail_at=1))
    assert result["status"] == "FAILED"
    assert result["failure"]["phase"] == "SEARCH"
    assert result["failure"]["category"] == "EVALUATION"
    counters = result["search"]["counters"]
    assert counters["search_evaluator_attempts"] == 1
    assert counters["search_evaluator_records_returned"] == 0
    assert counters["unique_evaluations"] == 0
    assert counters["proposals_total"] == 1
    assert counters["failed_search_evaluator_attempts"] == 1
    assert result["validation"]["status"] == "NOT_RUN"


def test_search_attempts_and_backend_committed_unique_fes_are_distinct_on_callback_failure():
    snapshot = make_snapshot(budget=8, initial_population=4)
    search = synthetic_evaluator(snapshot, fail_at=5)
    result = run(snapshot, search)

    assert result["status"] == "FAILED"
    assert result["failure"]["phase"] == "SEARCH"
    assert result["failure"]["category"] == "EVALUATION"
    counters = result["search"]["counters"]
    assert counters["search_evaluator_attempts"] == 5
    assert counters["search_evaluator_records_returned"] == 4
    assert counters["unique_evaluations"] == 4
    assert counters["proposals_total"] == 5
    assert counters["failed_search_evaluator_attempts"] == 1
    assert counters["unclassified_search_proposals"] == 0
    assert result["validation"]["status"] == "NOT_RUN"
    assert "FE" in result["accounting"]["failed_attempt_policy"]


def test_generation_evaluator_failure_is_fail_closed_without_retries():
    snapshot = make_snapshot(budget=12, initial_population=4)
    calls = []
    result = run(snapshot, synthetic_evaluator(snapshot, calls, fail_at=5))
    counters = result["search"]["counters"]
    assert result["failure"]["phase"] == "SEARCH"
    assert counters["search_evaluator_attempts"] == 5
    assert counters["failed_search_evaluator_attempts"] == 1
    assert counters["proposals_total"] == 5
    assert len(calls) == 5


def test_duplicate_heavy_run_reconciles_backend_counter_semantics_and_exhaustion():
    snapshot = make_snapshot(
        budget=40, initial_population=4, compact=True,
        exhaustion_duplicate_streak=1, narrow=True,
    )
    result = run(snapshot, synthetic_evaluator(snapshot))
    counters = result["search"]["counters"]
    assert result["search"]["status"] == "EXHAUSTED"
    assert counters["duplicate_count"] > 0
    assert counters["cache_hits"] >= counters["duplicate_count"]
    assert counters["proposals_total"] == counters["unique_evaluations"] + counters["cache_hits"]
    assert counters["unclassified_search_proposals"] == 0
    assert counters["unique_evaluations"] < 40
    assert result["validation"]["status"] == "VALIDATED"
    assert result["search"]["incumbent"]["candidate_vector"] == result["search"]["incumbent"]["canonical_vector"]
    assert result["validation"]["record"]["canonical_vector"] == result["search"]["incumbent"]["canonical_vector"]


def test_validation_failure_preserves_search_incumbent_and_is_not_completed():
    snapshot = make_snapshot(budget=8, initial_population=4)
    search_calls = []
    validation_calls = []
    search = synthetic_evaluator(snapshot, search_calls)
    validation = synthetic_evaluator(snapshot, validation_calls, fail_at=1)
    result = run(snapshot, search, validation)
    assert result["status"] == "VALIDATION_FAILED"
    assert result["search"]["status"] == "BUDGET_REACHED"
    assert result["search"]["incumbent"] is not None
    assert result["validation"]["status"] == "FAILED"
    assert result["validation"]["evaluator_calls"] == 1
    assert result["validation"]["requested_grid_points"] == len(
        snapshot["effective_config"]["grids"]["validation"]["points"]
    )
    assert result["failure"]["phase"] == "VALIDATION"
    assert result["failure"]["category"] == "VALIDATION"
    assert len(search_calls) == result["search"]["counters"]["unique_evaluations"]
    assert len(validation_calls) == 1


@pytest.mark.parametrize("damage", [
    "hash", "seed", "settings", "bounds", "roster", "optimizer",
    "comparator", "grid", "schema",
])
def test_mutated_or_inconsistent_snapshot_rejects_before_any_evaluator(damage):
    snapshot = make_snapshot()
    damaged = copy.deepcopy(snapshot)
    if damage == "hash":
        damaged["effective_config_sha256"] = "0" * 64
    elif damage == "seed":
        damaged["effective_config"]["optimizer"]["seed"] += 1
    elif damage == "settings":
        damaged["effective_config"]["optimizer"]["settings"]["max_duplicate_retries"] += 1
    elif damage == "bounds":
        damaged["effective_config"]["design"]["variables"][0]["bounds"][0] += 0.01
    elif damage == "roster":
        damaged["effective_config"]["storage"]["expected_cells"][0]["cell_id"] = "other-cell"
    elif damage == "optimizer":
        damaged["effective_config"]["optimizer"]["name"] = "controlled_de"
    elif damage == "comparator":
        damaged["effective_config"]["optimizer"]["comparator"] = "unsupported"
    elif damage == "grid":
        damaged["effective_config"]["grids"]["search"]["points"][0] += 1.0
    else:
        damaged["schema_id"] = "sawopt.scientific_config/2"
    calls = []
    search = synthetic_evaluator(snapshot, calls)
    with pytest.raises((ValueError, TypeError)):
        run(damaged, search)
    assert calls == []


def test_unsupported_or_missing_callbacks_fail_before_evaluation():
    from sawopt.optimization.configured_search import ConfiguredSearchInputError, run_configured_lshade

    snapshot = make_snapshot()
    calls = []
    evaluator = synthetic_evaluator(snapshot, calls)
    with pytest.raises((ConfiguredSearchInputError, TypeError)):
        run_configured_lshade(snapshot, search_evaluator=None, validation_evaluator=evaluator)
    with pytest.raises((ConfiguredSearchInputError, TypeError)):
        run_configured_lshade(snapshot, search_evaluator=evaluator, validation_evaluator=None)
    assert calls == []


def test_injected_record_rank_objective_and_canonical_identity_are_reconciled():
    snapshot = make_snapshot(budget=8, initial_population=4)
    for corruption in ("rank", "objective", "canonical", "vector", "phase", "grid"):
        result = run(snapshot, synthetic_evaluator(snapshot, corrupt=corruption))
        assert result["status"] == "FAILED"
        assert result["failure"]["phase"] == "SEARCH"
        assert result["failure"]["category"] == "RECONCILIATION"
        assert result["search"]["counters"]["unique_evaluations"] == 0
        assert result["search"]["counters"]["search_evaluator_attempts"] == 1
        assert result["search"]["counters"]["search_evaluator_records_returned"] == 0


def test_callback_cannot_mutate_backend_physical_vector():
    snapshot = make_snapshot(budget=8, initial_population=4)
    result = run(snapshot, synthetic_evaluator(snapshot, mutation=True))
    assert result["status"] == "FAILED"
    assert result["failure"]["category"] == "RECONCILIATION"
    assert result["search"]["counters"]["unique_evaluations"] == 0
    assert result["search"]["counters"]["search_evaluator_attempts"] == 1


def test_canonicalizer_retains_duplicate_integer_ties_and_signed_zero():
    from sawopt.optimization.configured_search import _canonicalize_physical

    lower_tie, lower_key = _canonicalize_physical(
        np.asarray([5.0, 24.5, 16.5, 40.5, -0.0, 0.25, 80.0]),
    )
    upper_tie, upper_key = _canonicalize_physical(
        np.asarray([5.0, 24.9, 16.9, 40.9, -0.0, 0.25, 80.0]),
    )
    assert lower_tie[1:4].tolist() == [25.0, 17.0, 41.0]
    assert lower_tie.tobytes() == upper_tie.tobytes()
    assert lower_key == upper_key
    assert np.signbit(lower_tie[4])
    assert np.signbit(lower_key[4])
    snapshot = make_snapshot(budget=8, initial_population=4)
    result = run(snapshot, synthetic_evaluator(snapshot))
    assert result["search"]["counters"]["unique_evaluations"] <= snapshot["effective_config"]["optimizer"]["search_fe_limit"]
    assert result["search"]["incumbent"]["candidate_vector"] == result["search"]["incumbent"]["canonical_vector"]


def test_explicit_configured_search_does_not_change_scientific_cli_surface_or_write_storage(tmp_path):
    guard = r'''
import sys

def audit(event, args):
    if event == "open":
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (1 | 2 | 64 | 512 | 1024)):
            raise AssertionError("filesystem write")
    if event in ("os.mkdir", "os.remove", "os.rename", "os.rmdir", "subprocess.Popen"):
        raise AssertionError("side effect: " + event)
sys.addaudithook(audit)
from sawopt.optimization.configured_search import run_configured_lshade
assert callable(run_configured_lshade)
assert "sawopt.io.experiment_store" not in sys.modules
'''
    env = {**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.run([sys.executable, "-B", "-c", guard], cwd=tmp_path, env=env, check=True)


def test_scientific_cli_validate_and_rejected_run_keep_import_and_side_effect_boundary(tmp_path):
    guard = r'''
import sys
from pathlib import Path

def audit(event, args):
    if event == "open":
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (1 | 2 | 64 | 512 | 1024)):
            raise AssertionError("filesystem write")
    if event in ("os.mkdir", "os.remove", "os.rename", "os.rmdir", "subprocess.Popen"):
        raise AssertionError("side effect: " + event)
sys.addaudithook(audit)
from sawopt.cli import main
config = Path(sys.argv[1])
assert main(["validate", "--config", str(config)]) == 0
assert main(["run", "--config", str(config)]) == 2
for module in ("sawopt.physics.com", "sawopt.optimization.lshade", "sawopt.io.experiment_store"):
    assert module not in sys.modules, module
'''
    env = {**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.run(
        [sys.executable, "-B", "-c", guard, str(EXAMPLE)],
        cwd=tmp_path, env=env, check=True,
    )
