"""Bounded software tests for the v1 configured single-filter adapter."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
import yaml

from sawopt.design.space import canonical_design
from sawopt.evaluation import evaluate_design
from sawopt.io.cli_config import load_cli_config
from sawopt.io.scientific_config import canonical_bytes
from sawopt.optimization.selection import FeasibilityFirstComparator

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "configs/examples/scientific_validation_only.yaml"


def resolved_snapshot():
    return load_cli_config(EXAMPLE)


def expected_evaluation_config(effective):
    specification = effective["specification"]
    return {
        "com": copy.deepcopy(effective["model"]["parameters"]),
        "center": effective["design"]["center"],
        "spec": {
            "passband": list(specification["passband"]),
            "stopbands": copy.deepcopy(specification["stopbands"]),
            "il": specification["il_db"],
            "ripple": specification["ripple_db"],
            "vswr": specification["vswr"],
        },
        "constraints": copy.deepcopy(effective["design"]["geometry"]),
    }


def test_adapter_maps_the_complete_v1_evaluation_contract_and_matches_direct_path():
    from sawopt.problem.evaluator import ConfiguredCandidateEvaluator

    snapshot = resolved_snapshot()
    effective = snapshot["effective_config"]
    seen = []

    def capture(design, cfg, frequencies, rs, rl, *, wiring):
        result = evaluate_design(design, cfg, frequencies, rs, rl, wiring=wiring)
        _record, network, simulation = result
        seen.append((copy.deepcopy(cfg), np.asarray(frequencies).copy(), rs, rl, wiring,
                     copy.deepcopy(network), simulation.y_parameters.copy()))
        return result

    evaluator = ConfiguredCandidateEvaluator(snapshot, evaluate_design_fn=capture)
    from sawopt.problem.evaluator import _thaw
    assert _thaw(evaluator.context.evaluation_config) == expected_evaluation_config(effective)
    assert evaluator.context.variable_names == tuple(v["name"] for v in effective["design"]["variables"])
    assert evaluator.context.variable_units == tuple(v["unit"] for v in effective["design"]["variables"])
    assert evaluator.context.active_bounds == tuple(tuple(v["bounds"]) for v in effective["design"]["variables"])
    assert evaluator.context.hard_bounds == tuple(tuple(v["hard_bounds"]) for v in effective["design"]["variables"])
    assert evaluator.context.fixed_values == effective["design"]["fixed"]
    assert evaluator.context.feasibility_tolerance == 1.0e-10
    assert evaluator.context.source_impedance_ohm == effective["ports"]["source"]
    assert evaluator.context.load_impedance_ohm == effective["ports"]["load"]

    # Integer half-up ties are retained by the canonical design API. These
    # are small test-owned fixed-input regressions, not an optimization study.
    proposal = [5.0, 24.5, 16.5, 40.5, 0.5, 0.25, 80.0]
    for phase, role in (("SEARCH", "search"), ("VALIDATION", "validation")):
        output = evaluator(proposal, phase=phase)
        grid = effective["grids"][role]["points"]
        cfg = expected_evaluation_config(effective)
        from sawopt.design.space import decode
        design = decode(proposal)
        direct, _network, simulation = evaluate_design(
            design, cfg, np.asarray(grid, dtype=np.float64),
            effective["ports"]["source"], effective["ports"]["load"],
            wiring=effective["design"]["wiring"],
        )
        _decoded, canonical, key = canonical_design(proposal)

        assert output["evaluation_phase"] == phase
        assert output["effective_config_sha256"] == snapshot["effective_config_sha256"]
        assert output["model_sha256"] == snapshot["input_sha256"]["model"]
        assert output["proposal_vector"] == proposal
        assert output["design"] == vars(design)
        assert output["design"]["metallization_ratio"] == 0.5
        assert output["design"]["thickness_over_lambda"] == 0.04
        assert output["canonical_vector"] == canonical.tolist()
        assert output["canonical_key"] == key
        assert output["grid_point_count"] == len(grid)
        assert output["grid_sha256"] == snapshot["input_sha256"][role + "_grid"]
        assert output["metrics"] == direct["metrics"]
        assert output["violations"] == direct["violations"]
        assert output["feasible"] is direct["feasible"]
        assert output["max_violation"] == direct["max_violation"]
        assert output["objective"] == direct["objective"]
        assert output["search_scalar_objective"] == direct["search_scalar_objective"]
        assert output["objective_parts"] == direct["objective_parts"]
        assert output["diagnostics"] == simulation.diagnostics
        assert output["rank_key"] == FeasibilityFirstComparator().rank_key(direct)

    assert len(seen) == 2
    for observed, role in zip(seen, ("search", "validation"), strict=True):
        cfg, grid, rs, rl, wiring, network, y_parameters = observed
        assert cfg == expected_evaluation_config(effective)
        direct_network, direct_simulation = evaluate_design(
            canonical_design(proposal)[0], cfg, grid, rs, rl, wiring=wiring,
        )[1:]
        assert np.array_equal(y_parameters, direct_simulation.y_parameters)
        assert np.ascontiguousarray(y_parameters).tobytes() == np.ascontiguousarray(
            direct_simulation.y_parameters
        ).tobytes()
        for name in ("gt", "il", "s", "vswr"):
            assert np.array_equal(network[name], direct_network[name])
            assert np.ascontiguousarray(network[name]).tobytes() == np.ascontiguousarray(
                direct_network[name]
            ).tobytes()
        assert np.array_equal(grid, np.asarray(effective["grids"][role]["points"], dtype=np.float64))
        assert rs == effective["ports"]["source"]
        assert rl == effective["ports"]["load"]
        assert wiring == effective["design"]["wiring"]


def test_exact_grid_roles_do_not_call_default_grid_or_dense_paths(monkeypatch):
    import sawopt.evaluation as evaluation_module
    import sawopt.problem.evaluator as evaluator_module
    from sawopt.problem.evaluator import ConfiguredCandidateEvaluator

    def forbidden(*_args, **_kwargs):
        raise AssertionError("implicit grid/adaptive evaluation was called")

    monkeypatch.setattr(evaluation_module, "search_grid", forbidden)
    monkeypatch.setattr(evaluation_module, "validation_grid", forbidden)
    monkeypatch.setattr(evaluator_module, "validation_grid", forbidden)
    seen = []

    def record_only(design, cfg, frequencies, rs, rl, *, wiring):
        seen.append((np.asarray(frequencies).copy(), wiring))
        return evaluate_design(design, cfg, frequencies, rs, rl, wiring=wiring)

    snapshot = resolved_snapshot()
    evaluator = ConfiguredCandidateEvaluator(snapshot, evaluate_design_fn=record_only)
    evaluator([5.0, 24, 16, 40, 0.5, 0.5, 80], phase="SEARCH")
    evaluator([5.0, 24, 16, 40, 0.5, 0.5, 80], phase="VALIDATION")
    assert [grid.tolist() for grid, _ in seen] == [
        snapshot["effective_config"]["grids"]["search"]["points"],
        snapshot["effective_config"]["grids"]["validation"]["points"],
    ]


@pytest.mark.parametrize("damage", [
    "status", "schema", "schema_id", "qualification", "authorized", "implemented",
    "effective_hash", "input_model_hash", "input_search_grid_hash",
    "input_validation_grid_hash", "missing_input_hash", "config_hash", "effective_field",
    "unknown_effective_field", "unsupported_topology", "non_normalized_real",
])
def test_snapshot_is_verified_and_revalidated_before_evaluation(damage):
    from sawopt.problem.evaluator import ConfiguredCandidateEvaluator, SnapshotValidationError

    snapshot = resolved_snapshot()
    changed = copy.deepcopy(snapshot)
    if damage == "status":
        changed["status"] = "INVALID"
    elif damage == "schema":
        changed["schema_id"] = "sawopt.scientific_config/2"
    elif damage == "schema_id":
        changed["effective_config"]["schema_id"] = "sawopt.scientific_config/2"
    elif damage == "qualification":
        changed["qualification"] = "QUALIFIED"
    elif damage == "authorized":
        changed["run_authorized"] = True
    elif damage == "implemented":
        changed["scientific_run_implemented"] = True
    elif damage == "effective_hash":
        changed["effective_config_sha256"] = "0" * 64
    elif damage.startswith("input_") and damage.endswith("_hash"):
        name = damage[len("input_"):-len("_hash")]
        changed["input_sha256"][name] = "0" * 64
    elif damage == "missing_input_hash":
        changed["input_sha256"].pop("validation_grid")
    elif damage == "config_hash":
        changed["config_file_sha256"] = "not-a-digest"
    elif damage == "effective_field":
        changed["effective_config"]["ports"]["source"] = 51.0
    elif damage == "unknown_effective_field":
        changed["effective_config"]["design"]["unexpected"] = True
    elif damage == "unsupported_topology":
        changed["effective_config"]["design"]["topology"] = "P_D"
    elif damage == "non_normalized_real":
        changed["effective_config"]["ports"]["source"] = 50
        changed["effective_config_sha256"] = hashlib.sha256(
            canonical_bytes(changed["effective_config"])
        ).hexdigest()

    with pytest.raises(SnapshotValidationError):
        ConfiguredCandidateEvaluator(changed)


def test_snapshot_and_per_call_inputs_are_defensively_detached():
    from sawopt.problem.evaluator import ConfiguredCandidateEvaluator

    snapshot = resolved_snapshot()
    baseline = ConfiguredCandidateEvaluator(snapshot)
    expected = baseline([5.0, 24, 16, 40, 0.5, 0.5, 80], phase="SEARCH")
    guarded_snapshot = resolved_snapshot()
    evaluator = ConfiguredCandidateEvaluator(guarded_snapshot)
    guarded_snapshot["effective_config"]["model"]["parameters"]["idt"]["velocity_m_s"] = 123.0
    guarded_snapshot["effective_config"]["grids"]["search"]["points"][0] = 1.0
    actual = evaluator([5.0, 24, 16, 40, 0.5, 0.5, 80], phase="SEARCH")
    assert actual == expected
    with pytest.raises(TypeError):
        evaluator.context.evaluation_config["com"]["idt"]["velocity_m_s"] = 1.0

    calls = 0

    def mutating_evaluate(design, cfg, frequencies, rs, rl, *, wiring):
        nonlocal calls
        calls += 1
        result = evaluate_design(design, cfg, frequencies, rs, rl, wiring=wiring)
        cfg["com"]["idt"]["velocity_m_s"] = 1.0
        frequencies[:] = 1.0
        design.wavelength_um = 100.0
        return result

    isolated = ConfiguredCandidateEvaluator(resolved_snapshot(), evaluate_design_fn=mutating_evaluate)
    first = isolated([5.0, 24, 16, 40, 0.5, 0.5, 80], phase="SEARCH")
    second = isolated([5.0, 24, 16, 40, 0.5, 0.5, 80], phase="SEARCH")
    assert calls == 2
    assert first["metrics"] == second["metrics"]
    assert second["design"]["wavelength_um"] == 5.0


@pytest.mark.parametrize("vector,phase", [
    ([5.0] * 6, "SEARCH"), ([5.0] * 8, "SEARCH"),
    ([5.0, 24, 16, 40, 0.5, 0.5, float("nan")], "SEARCH"),
    ([4.59, 24, 16, 40, 0.5, 0.5, 80], "SEARCH"),
    ([5.0, 24, 16, 40, 0.5, 0.5, 150.01], "SEARCH"),
    ([5.0, True, 16, 40, 0.5, 0.5, 80], "SEARCH"),
    ([5.0 + 0j, 24, 16, 40, 0.5, 0.5, 80], "SEARCH"),
    ([[5.0, 24, 16, 40, 0.5, 0.5, 80]], "SEARCH"),
    ([5.0, 24, 16, 40, 0.5, 0.5, 80], "DENSE"),
])
def test_bad_candidates_and_phases_fail_before_evaluation(vector, phase):
    from sawopt.problem.evaluator import CandidateInputError, ConfiguredCandidateEvaluator

    calls = []

    def must_not_evaluate(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("invalid proposal reached evaluation")

    evaluator = ConfiguredCandidateEvaluator(resolved_snapshot(), evaluate_design_fn=must_not_evaluate)
    with pytest.raises(CandidateInputError):
        evaluator(vector, phase=phase)
    assert calls == []


def test_signed_zero_and_integer_rounding_identity_are_preserved():
    import struct

    from sawopt.problem.evaluator import ConfiguredCandidateEvaluator

    proposal = [5.0, 24.5, 16.5, 40.5, -0.0, 0.25, 80.0]
    result = ConfiguredCandidateEvaluator(resolved_snapshot())(proposal, phase="SEARCH")
    assert result["design"]["io_idt_pairs"] == 25
    assert result["design"]["center_idt_pairs"] == 17
    assert result["design"]["reflector_electrodes"] == 41
    for value in (result["proposal_vector"][4], result["design"]["idt_gap_lambda"],
                  result["canonical_vector"][4], result["canonical_key"][4]):
        assert struct.pack(">d", value) == struct.pack(">d", -0.0)


def test_resolved_snapshot_is_sufficient_after_config_and_reference_files_are_removed(tmp_path):
    from sawopt.problem.evaluator import ConfiguredCandidateEvaluator

    declaration = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    payloads = {
        "model": declaration["model"]["parameters"].pop("inline"),
        "search_grid": declaration["grids"]["search"].pop("inline"),
        "validation_grid": declaration["grids"]["validation"].pop("inline"),
    }
    from sawopt.io.cli_config import load_cli_config
    for name, payload in payloads.items():
        reference = tmp_path / f"{name}.yaml"
        reference.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        digest = hashlib.sha256(reference.read_bytes()).hexdigest()
        if name == "model":
            declaration["model"]["parameters"].update(path=reference.name, sha256=digest)
        else:
            role = name.removesuffix("_grid")
            declaration["grids"][role].update(path=reference.name, sha256=digest)
    config_path = tmp_path / "declaration.yaml"
    config_path.write_text(yaml.safe_dump(declaration, sort_keys=False), encoding="utf-8")
    snapshot = load_cli_config(config_path)
    config_path.unlink()
    for name in payloads:
        (tmp_path / f"{name}.yaml").unlink()

    result = ConfiguredCandidateEvaluator(snapshot)(
        [5.0, 24, 16, 40, 0.5, 0.5, 80], phase="SEARCH",
    )
    assert result["evaluation_phase"] == "SEARCH"
    assert result["grid_sha256"] == snapshot["input_sha256"]["search_grid"]


def test_numerical_failure_is_typed_and_never_becomes_a_result():
    from sawopt.problem.evaluator import CandidateEvaluationError, ConfiguredCandidateEvaluator

    failure = ValueError("synthetic numerical failure")

    def fail(*_args, **_kwargs):
        raise failure

    evaluator = ConfiguredCandidateEvaluator(resolved_snapshot(), evaluate_design_fn=fail)
    with pytest.raises(CandidateEvaluationError, match="SEARCH") as captured:
        evaluator([5.0, 24, 16, 40, 0.5, 0.5, 80], phase="SEARCH")
    assert captured.value.phase == "SEARCH"
    assert captured.value.__cause__ is failure


@pytest.mark.parametrize("corruption", [
    "negative_sum", "wrong_sum", "false_scalar_pair", "false_objective_parts",
])
def test_rank_and_surrogate_fields_must_match_the_existing_contract(corruption):
    from sawopt.problem.evaluator import CandidateEvaluationError, ConfiguredCandidateEvaluator

    def corrupt_record(design, cfg, frequencies, rs, rl, *, wiring):
        record, network, simulation = evaluate_design(
            design, cfg, frequencies, rs, rl, wiring=wiring,
        )
        if corruption == "negative_sum":
            record["sum_violation"] = -1.0
        elif corruption == "wrong_sum":
            record["sum_violation"] = sum(record["violations"].values()) + 0.25
        elif corruption == "false_scalar_pair":
            record["objective"] = 123.0
            record["search_scalar_objective"] = 123.0
        elif corruption == "false_objective_parts":
            record["objective_parts"]["primary"] += 1.0
        return record, network, simulation

    evaluator = ConfiguredCandidateEvaluator(
        resolved_snapshot(), evaluate_design_fn=corrupt_record,
    )
    with pytest.raises(CandidateEvaluationError) as captured:
        evaluator([5.0, 24, 16, 40, 0.5, 0.5, 80], phase="SEARCH")
    assert captured.value.phase == "SEARCH"
    assert isinstance(captured.value.__cause__, ValueError)


def test_consistent_optional_sum_violation_preserves_existing_comparator_rank():
    from sawopt.problem.evaluator import ConfiguredCandidateEvaluator

    original_records = []

    def with_sum(design, cfg, frequencies, rs, rl, *, wiring):
        record, network, simulation = evaluate_design(
            design, cfg, frequencies, rs, rl, wiring=wiring,
        )
        record["sum_violation"] = sum(float(value) for value in record["violations"].values())
        original_records.append(copy.deepcopy(record))
        return record, network, simulation

    result = ConfiguredCandidateEvaluator(
        resolved_snapshot(), evaluate_design_fn=with_sum,
    )([5.0, 24, 16, 40, 0.5, 0.5, 80], phase="SEARCH")
    assert result["rank_key"] == FeasibilityFirstComparator().rank_key(original_records[0])


def test_malformed_evaluation_record_fails_closed_instead_of_defaulting_feasible():
    from sawopt.problem.evaluator import CandidateEvaluationError, ConfiguredCandidateEvaluator

    def incomplete(*_args, **_kwargs):
        return ({"feasible": True}, {}, None)

    evaluator = ConfiguredCandidateEvaluator(resolved_snapshot(), evaluate_design_fn=incomplete)
    with pytest.raises(CandidateEvaluationError, match="missing fields"):
        evaluator([5.0, 24, 16, 40, 0.5, 0.5, 80], phase="SEARCH")


def test_fresh_process_adapter_import_does_not_load_r5_or_write_data(tmp_path):
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
from sawopt.problem.evaluator import ConfiguredCandidateEvaluator
assert ConfiguredCandidateEvaluator
assert "sawopt.io.experiment_store" not in sys.modules
assert "sawopt.io.checkpoints" not in sys.modules
'''
    env = {**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.run([sys.executable, "-B", "-c", guard], cwd=tmp_path, env=env, check=True)
