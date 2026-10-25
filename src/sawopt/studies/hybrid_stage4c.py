"""Frozen Stage 4C protocol contract and evidence helpers.

This module validates the protected Stage 4A inputs and retains the frozen
Stage 4C matrix/manifest semantics for historical report and audit consumers.
The legacy Stage 4C production execution entrypoint is retired.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .hybrid import stage4a_load_context


STUDY_TYPE = "hybrid_stage4c_confirmatory"
PROTOCOL_REVISION = "stage4c_confirmatory_v1"
TOPOLOGIES = ("P_D", "D_P")
SEEDS = (20261007, 20261008, 20261009, 20261010, 20261011)
STAGE4B_SEEDS = (20261002, 20261003, 20261004, 20261005, 20261006)
BUDGET = 96000
CHECKPOINTS = (8000, 16000, 24000, 32000, 48000, 64000, 80000, 96000)
INITIAL_POPULATION_MULTIPLIER = 18
FINALIST_COUNT = 16
PRODUCTION_TOTAL_EVALUATIONS = len(TOPOLOGIES) * len(SEEDS) * BUDGET
SEARCH_GRID_SHA256 = "212dd2b0b71ddeffb7a8865937d132ee596870f25c989ac7d90c5dab6fd7faa0"
COMMON_GRID_ID = "2e24c4ce3f96c38baba44dc83bc60f95954a6b677cb2a37d63078e78c4cea42f"
COMMON_GRID_SHA256 = "54c1daf67dd2bb9242f95e638d7bd801db536acc2c7d6f00c1f62a788bead554"
PRODUCTION_RUN_ROOT = "C:/Users/sub/Documents/ChatGPT/saw-com-optimizer-runs/production"
QUALIFICATION_RUN_ROOT = "C:/Users/sub/Documents/ChatGPT/saw-com-optimizer-runs/qualification/stage4c"
NETWORK_CONVENTION = "Stage 4A; exp(+jωt), left-to-right, power-normalized acoustic waves"
MATURITY_CRITERIA = {
    "convergence_evidence_complete": True,
    "grid_converged": True,
    "recovery_pending_confirmation": False,
    "historical_bound_hit_alone_blocks_maturity": False,
    "hard_bound_unresolved": False,
    "boundary_pending_confirmation": False,
    "significant_improvement_80k_to_96k": False,
    "fraction_of_budget_at_last_significant_improvement_max": 0.80,
}
CLOSEOUT_CRITERIA = {
    "primary_comparator": "feasibility_first_lexicographic",
    "comparator_fields": ["feasible", "max_violation", "sum_violation", "worst_il_db"],
    "no_weighted_scalar_score": True,
    "model_level_materiality": {
        "primary_metric": "max_normalized_violation",
        "absolute_difference_threshold": 0.02,
        "meaning": "internal_computational_interpretation_threshold",
        "manufacturing_or_measurement_tolerance": False,
    },
    "clear_winner": {
        "minimum_matched_seed_wins": 4,
        "late_checkpoints": [64000, 80000, 96000],
        "same_seed_wins_required_at_each_late_checkpoint": 4,
        "require_all_cells_mature": True,
        "terminal_winner_pairs_required": 4,
        "material_pair_rule": (
            "feasibility_differs_in_favor_of_winner OR both_infeasible_and_abs_delta_max_violation_at_least_0.02"
        ),
        "require_no_convergence_or_boundary_caveat": True,
    },
    "practically_equivalent": {
        "require_all_cells_mature": True,
        "require_no_stable_four_of_five_late_preference": True,
        "require_matched_feasibility_status_for_every_seed": True,
        "all_five_terminal_abs_delta_max_violation_strictly_below": 0.02,
    },
    "otherwise": "STAGE4C_TOPOLOGY_SELECTION_UNRESOLVED",
}


def expected_matrix(
    *, seeds: Sequence[int] = SEEDS, budget: int = BUDGET,
    terminal_budget: int = BUDGET, checkpoints: Sequence[int] = CHECKPOINTS,
    topologies: Sequence[str] = TOPOLOGIES,
) -> list[dict[str, Any]]:
    """Return the complete, cold-started matched-seed cell matrix."""
    dimensions = {"P_D": 13, "D_P": 13}
    if set(topologies) != set(TOPOLOGIES) or len(topologies) != len(TOPOLOGIES):
        raise ValueError("Stage 4C topology set must be exactly P_D and D_P")
    return [{
        "topology": topology,
        "seed": int(seed),
        "dimension": dimensions[topology],
        "initial_population": INITIAL_POPULATION_MULTIPLIER * dimensions[topology],
        "budget": int(budget),
        "population_schedule_terminal_budget": int(terminal_budget),
        "checkpoints": [int(value) for value in checkpoints],
        "cold_start": True,
        "warm_start": False,
        "parent_transfer": False,
        "topology_transfer": False,
        "historical_population_injection": False,
    } for topology in topologies for seed in seeds]



def _require_equal(label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        raise ValueError(f"Stage 4C protected/frozen input mismatch: {label}")


def validate_frozen_config(cfg: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed on protocol drift or any protected Stage 4B input change."""
    study = cfg.get("study", {})
    dms = cfg.get("dms_topology", {})
    hybrid = cfg.get("hybrid", {})
    stage = cfg.get("stage4c", {})
    storage = cfg.get("storage_contract", {})
    base_dms = baseline["dms_topology"]
    base_hybrid = baseline["hybrid"]
    _require_equal("study type", study.get("type"), STUDY_TYPE)
    _require_equal("protocol revision", study.get("revision"), PROTOCOL_REVISION)
    _require_equal("comparison topologies", tuple(hybrid.get("supported_topologies", ())), TOPOLOGIES)
    _require_equal("Stage 4C supported topologies", tuple(stage.get("supported_hybrid_topologies", ())), TOPOLOGIES)
    _require_equal("study topology declaration", tuple(study.get("topologies", ())), TOPOLOGIES)
    _require_equal("study seeds", tuple(study.get("seeds", ())), SEEDS)
    _require_equal("DMS seeds", tuple(dms.get("seeds", ())), SEEDS)
    _require_equal("Stage 4C seeds", tuple(stage.get("seeds", ())), SEEDS)
    if set(SEEDS) & set(STAGE4B_SEEDS):
        raise ValueError("Stage 4C production seeds overlap Stage 4B seeds")
    _require_equal("budget", int(dms.get("budget", -1)), BUDGET)
    _require_equal("study budget", int(study.get("budget_per_cell", -1)), BUDGET)
    _require_equal("Stage 4C budget", int(stage.get("budget_per_cell", -1)), BUDGET)
    _require_equal("terminal schedule budget", int(dms.get("population_schedule_terminal_budget", -1)), BUDGET)
    _require_equal("study terminal budget", int(study.get("population_schedule_terminal_budget", -1)), BUDGET)
    _require_equal("Stage 4C terminal budget", int(stage.get("population_schedule_terminal_budget", -1)), BUDGET)
    _require_equal("checkpoints", tuple(int(x) for x in dms.get("checkpoints", ())), CHECKPOINTS)
    _require_equal("study checkpoints", tuple(int(x) for x in study.get("checkpoints", ())), CHECKPOINTS)
    _require_equal("Stage 4C checkpoints", tuple(int(x) for x in stage.get("checkpoints", ())), CHECKPOINTS)
    _require_equal("initial population rule", dms.get("initial_population_per_dimension"), INITIAL_POPULATION_MULTIPLIER)
    _require_equal("cold start", dms.get("cold_start"), True)
    _require_equal("no explicit population override", dms.get("initial_population"), None)
    _require_equal("material", tuple(dms.get("selection", {}).get("materials", ())), ("MLIT",))
    _require_equal("DMS model", tuple(dms.get("selection", {}).get("topologies", ())), ("T1_SYMMETRIC_5IDT",))
    _require_equal("study material", stage.get("material"), "MLIT")
    _require_equal("study DMS topology", stage.get("dms_topology"), "T1_SYMMETRIC_5IDT")
    _require_equal("optimizer", stage.get("optimizer"), "L-SHADE")
    _require_equal("ports", (float(hybrid.get("source_impedance_ohm", 0)),
                              float(hybrid.get("load_impedance_ohm", 0)),
                              float(dms.get("impedance_ohm", 0))), (50.0, 50.0, 50.0))
    _require_equal("stage ports", (float(stage.get("source_impedance_ohm", 0)),
                                    float(stage.get("load_impedance_ohm", 0))), (50.0, 50.0))
    _require_equal("warm start", stage.get("warm_start"), False)
    _require_equal("parent transfer", stage.get("parent_transfer"), False)
    _require_equal("topology transfer", stage.get("topology_transfer"), False)
    _require_equal("historical population injection", stage.get("historical_population_injection"), False)
    _require_equal("production early stop", stage.get("production_early_stop"), False)
    _require_equal("production launch gate", stage.get("production_launch_authorized"), False)
    _require_equal("hybrid production launch gate", hybrid.get("production_launch_authorized"), False)
    _require_equal("production storage policy", storage.get("production_policy"), "external_persistent_v1")
    _require_equal("production persistent root", storage.get("production_root"), PRODUCTION_RUN_ROOT)
    _require_equal("qualification storage policy", storage.get("qualification_policy"), "external_qualification_v1")
    _require_equal("qualification persistent root", storage.get("qualification_root"), QUALIFICATION_RUN_ROOT)
    _require_equal("initial population rule declaration", stage.get("initial_population_rule"), "18 * topology_dimension")
    _require_equal("initial populations", stage.get("initial_populations"), {"P_D": 234, "D_P": 234})
    _require_equal("finalist count", hybrid.get("common_grid_finalists"), FINALIST_COUNT)
    _require_equal("stage finalist count", stage.get("common_grid_finalists"), FINALIST_COUNT)

    protected = stage.get("protected_inputs", {})
    _require_equal("protected specification", protected.get("specification"), baseline["spec"])
    _require_equal("protected geometry constraints", protected.get("geometry_constraints"), baseline["constraints"])
    _require_equal("protected MLIT profile config", protected.get("mlit_profile"), base_dms["materials"]["MLIT"])
    _require_equal("protected T1 active bounds", protected.get("t1_active_bounds"), baseline["_stage4c_t1_active_bounds"])
    _require_equal("protected T1 hard bounds", protected.get("t1_hard_bounds"), baseline["_stage4c_t1_hard_bounds"])
    for label, key, expected in (
        ("specification", "spec", baseline["spec"]),
        ("geometry constraints", "constraints", baseline["constraints"]),
        ("MLIT profile", "materials", base_dms["materials"]["MLIT"]),
        ("resonator wavelength/pair bounds", "resonator_bounds", base_hybrid["resonator_bounds"]),
        ("resonator aperture bounds", "resonator_aperture_bounds_um", base_hybrid["resonator_aperture_bounds_um"]),
        ("resonator model", "resonator_model", base_hybrid["resonator_model"]),
        ("layout", "layout", base_hybrid["layout"]),
    ):
        actual = cfg.get(key) if key in {"spec", "constraints"} else (
            dms.get("materials", {}).get("MLIT") if key == "materials" else hybrid.get(key)
        )
        _require_equal(label, actual, expected)
    _require_equal("protected resonator bounds", protected.get("resonator_bounds"), base_hybrid["resonator_bounds"])
    _require_equal("protected aperture bounds", protected.get("resonator_aperture_bounds_um"), base_hybrid["resonator_aperture_bounds_um"])
    _require_equal("T1 reflector electrodes", protected.get("t1_reflector_electrodes"), base_dms.get("t1_reflector_electrodes"))
    model = base_hybrid["resonator_model"]
    _require_equal("protected metallization ratio", protected.get("metallization_ratio"), model["metallization_ratio"])
    _require_equal("protected thickness/lambda", protected.get("thickness_over_lambda"), model["thickness_over_lambda"])
    _require_equal("protected resonator gap/lambda", protected.get("gap_lambda"), model["gap_lambda"])
    _require_equal("protected layout", protected.get("layout"), base_hybrid["layout"])
    _require_equal("search grid point count", protected.get("search_grid_points"), 1001)
    _require_equal("search grid SHA", protected.get("search_grid_sha256"), SEARCH_GRID_SHA256)
    _require_equal("common grid point count", protected.get("common_validation_grid_points"), 9113)
    _require_equal("common grid ID", protected.get("common_validation_grid_id"), COMMON_GRID_ID)
    _require_equal("common grid SHA", protected.get("common_validation_grid_sha256"), COMMON_GRID_SHA256)
    _require_equal("network convention", protected.get("network_convention"), NETWORK_CONVENTION)
    _require_equal("maturity criteria", stage.get("maturity_criteria"), MATURITY_CRITERIA)
    closeout = stage.get("closeout_criteria", {})
    _require_equal("closeout classification criteria", closeout, CLOSEOUT_CRITERIA)
    initializer = hybrid.get("initializer", {})
    _require_equal("initializer method", initializer.get("method"), "independent_uniform_rejection_v1")
    _require_equal("initializer attempt budget", initializer.get("max_attempts"), 10000)
    _require_equal("initializer historical-seed policy", initializer.get("include_historical_seed"), False)
    _require_equal("initializer derivation", initializer.get("seed_derivation"),
                   "sha256(stage4b-v1/seed/material/topology/initial_population)")
    _require_equal("stage initializer", stage.get("initializer"), initializer)
    _require_equal("layout model", hybrid.get("layout"), base_hybrid["layout"])
    return {
        "specification": cfg["spec"],
        "geometry_constraints": cfg["constraints"],
        "material_profile_config": dms["materials"]["MLIT"],
        "material": "MLIT",
        "dms_topology": "T1_SYMMETRIC_5IDT",
        "t1_active_bounds": baseline["_stage4c_t1_active_bounds"],
        "t1_hard_bounds": baseline["_stage4c_t1_hard_bounds"],
        "t1_reflector_electrodes": int(base_dms["t1_reflector_electrodes"]),
        "mlit_profile_metadata": baseline["_stage4c_profile_metadata"],
        "resonator_bounds": hybrid["resonator_bounds"],
        "resonator_aperture_bounds_um": hybrid["resonator_aperture_bounds_um"],
        "resonator_model": hybrid["resonator_model"],
        "layout": hybrid["layout"],
        "source_impedance_ohm": 50.0,
        "load_impedance_ohm": 50.0,
        "network_convention": NETWORK_CONVENTION,
        "search_grid_points": 1001,
        "search_grid_sha256": SEARCH_GRID_SHA256,
        "common_validation_grid_points": 9113,
        "common_validation_grid_id": COMMON_GRID_ID,
        "common_validation_grid_sha256": COMMON_GRID_SHA256,
    }


def load_stage4c_context(config_path: str | Path) -> dict[str, Any]:
    """Load Stage 4C over the qualified Stage 4A model and freeze its inputs."""
    from ..design.topology import RESONATOR_BOUNDS
    from ..io.config import load_experiment_config
    from ..io.provenance import build_fingerprint_metadata
    import yaml

    root = Path(__file__).resolve().parents[3]
    baseline_context = stage4a_load_context(root / "configs/studies/hybrid_stage4a_qualification.yaml")
    cfg_path = Path(config_path)
    if not cfg_path.is_absolute():
        cfg_path = root / cfg_path
    cfg_path = cfg_path.resolve()
    raw_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    _require_equal("base configuration", raw_cfg.get("base_config"), "dms_topology_screening.yaml")
    cfg = load_experiment_config(cfg_path)
    baseline = dict(baseline_context["cfg"])
    baseline["_stage4c_t1_active_bounds"] = baseline_context["contract"]["dms_active_bounds"]
    baseline["_stage4c_t1_hard_bounds"] = baseline_context["contract"]["dms_hard_bounds"]
    baseline["_stage4c_profile_metadata"] = baseline_context["profile_metadata"]
    protected = validate_frozen_config(cfg, baseline)
    _require_equal("qualified resonator bounds", cfg["hybrid"]["resonator_bounds"],
                   np.asarray(RESONATOR_BOUNDS, dtype=float).tolist())
    _require_equal("search grid identity", len(baseline_context["search_frequencies"]), 1001)
    _require_equal("computed search grid SHA", baseline_context["contract"]["search_frequency_sha256"], SEARCH_GRID_SHA256)
    _require_equal("common validation grid identity", len(baseline_context["common_frequencies"]), 9113)
    _require_equal("computed common grid ID", baseline_context["common_grid_id"], COMMON_GRID_ID)
    _require_equal("computed common grid SHA", baseline_context["grid_metadata"]["sha256"], COMMON_GRID_SHA256)
    if {name: baseline_context["spaces"][name].dimension for name in TOPOLOGIES} != {"P_D": 13, "D_P": 13}:
        raise ValueError("Stage 4C topology dimensions must both be 13")

    dimensions = {"P_D": 13, "D_P": 13}
    contract = {
        "study_type": STUDY_TYPE,
        "protocol_revision": PROTOCOL_REVISION,
        "optimizer": "L-SHADE",
        "material": "MLIT",
        "dms_topology": "T1_SYMMETRIC_5IDT",
        "topologies": list(TOPOLOGIES),
        "source_impedance_ohm": 50.0,
        "load_impedance_ohm": 50.0,
        "seeds": list(SEEDS),
        "budget_per_cell": BUDGET,
        "population_schedule_terminal_budget": BUDGET,
        "checkpoints": list(CHECKPOINTS),
        "initial_population_rule": "18 * topology_dimension",
        "initial_populations": {name: INITIAL_POPULATION_MULTIPLIER * dimension
                                 for name, dimension in dimensions.items()},
        "cold_start": True,
        "warm_start": False,
        "parent_transfer": False,
        "topology_transfer": False,
        "historical_population_injection": False,
        "production_early_stop": False,
        "storage_contract": cfg["storage_contract"],
        "finalist_count_per_checkpoint": FINALIST_COUNT,
        "search_frequency_count": 1001,
        "search_frequency_sha256": SEARCH_GRID_SHA256,
        "common_validation_grid_id": COMMON_GRID_ID,
        "common_validation_frequency_count": 9113,
        "common_validation_grid_sha256": COMMON_GRID_SHA256,
        "protected_scientific_inputs": protected,
        "com_provider": baseline_context["profile_metadata"],
        "matrix": expected_matrix(),
        "total_unique_evaluations": PRODUCTION_TOTAL_EVALUATIONS,
        "initializer_contract": cfg["stage4c"]["initializer"],
        "maturity_criteria": cfg["stage4c"]["maturity_criteria"],
        "closeout_criteria": cfg["stage4c"]["closeout_criteria"],
        "run_storage_policy": "external_persistent_v1",
    }
    config_relative = cfg_path.relative_to(root).as_posix()
    computation_paths = tuple(dict.fromkeys((*baseline_context["computation_paths"], config_relative,
                                              "src/sawopt/studies/hybrid_stage4c.py",
                                              "src/sawopt/studies/hybrid_stage4b.py",
                                              "src/sawopt/optimization/convergence_evidence.py")))
    reporting_paths = ("src/sawopt/reporting/hybrid_stage4c.py",)
    fingerprint = build_fingerprint_metadata(
        root, contract, computation_paths=computation_paths,
        reporting_paths=reporting_paths,
    )
    context = dict(baseline_context)
    context.update({
        "root": root,
        "config_path": cfg_path,
        "cfg": cfg,
        "contract": contract,
        "fingerprint": fingerprint,
        "matrix": expected_matrix(),
        "initial_populations": {"P_D": 234, "D_P": 234},
        "t1_hard_bounds": baseline_context["contract"]["dms_hard_bounds"],
        "protected_scientific_inputs": protected,
        "computation_paths": computation_paths,
        "reporting_paths": reporting_paths,
        "source_impedance_ohm": 50.0,
        "load_impedance_ohm": 50.0,
    })
    return context


def build_stage4c_run_manifest(
    context: Mapping[str, Any], *, run_id: str, source_commit_sha: str,
    run_storage_policy: str = "external_persistent_v1",
) -> dict[str, Any]:
    """Build the immutable Stage 4C production protocol manifest."""
    if not run_id or not source_commit_sha:
        raise ValueError("Stage 4C run manifest requires run_id and source_commit_sha")
    if run_storage_policy != "external_persistent_v1":
        raise ValueError("Stage 4C production requires storage policy external_persistent_v1")
    return {
        "schema_version": 1,
        "run_id": str(run_id),
        "mode": "production",
        "study_type": STUDY_TYPE,
        "protocol_revision": PROTOCOL_REVISION,
        "computation_fingerprint": context["fingerprint"]["computation_fingerprint"],
        "source_commit_sha": str(source_commit_sha),
        "topologies": list(TOPOLOGIES),
        "expected_cell_count": len(TOPOLOGIES) * len(SEEDS),
        "seeds": list(SEEDS),
        "budget_per_cell": BUDGET,
        "population_schedule_terminal_budget": BUDGET,
        "checkpoints": list(CHECKPOINTS),
        "initial_population_rule": "18 * topology_dimension",
        "initial_populations": {"P_D": 234, "D_P": 234},
        "production_early_stop": False,
        "search_grid_sha256": SEARCH_GRID_SHA256,
        "common_validation_grid_id": COMMON_GRID_ID,
        "common_validation_grid_sha256": COMMON_GRID_SHA256,
        "model_profile_provenance": context["profile_metadata"],
        "source_impedance_ohm": 50.0,
        "load_impedance_ohm": 50.0,
        "cold_start": True,
        "warm_start": False,
        "parent_transfer": False,
        "topology_transfer": False,
        "historical_population_injection": False,
        "run_storage_policy": run_storage_policy,
        "required_storage_root": PRODUCTION_RUN_ROOT,
        "ranking_eligible": True,
        "scientific_evidence": True,
        "matrix": expected_matrix(),
        "fingerprint_schema_version": context["fingerprint"]["fingerprint_schema_version"],
        "dependency_manifest": context["fingerprint"]["dependency_manifest"],
    }


def validate_stage4c_run_manifest(
    saved: Mapping[str, Any], expected: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate immutable protocol fields while preserving the original creation time."""
    if not isinstance(saved, Mapping):
        raise RuntimeError("existing Stage 4C run manifest is not an object")
    for key, value in expected.items():
        if saved.get(key) != value:
            raise RuntimeError(f"Stage 4C immutable run manifest mismatch: {key}")
    created_at = saved.get("created_at_utc")
    if not isinstance(created_at, str) or not created_at.strip():
        raise RuntimeError("Stage 4C immutable run manifest mismatch: created_at_utc")
    validated = dict(expected)
    validated["created_at_utc"] = created_at
    return validated


def ensure_stage4c_run_manifest(
    manifest_path: str | Path, expected: Mapping[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Create the manifest once or validate its immutable contract on resume."""
    path = Path(manifest_path)
    if path.is_file():
        saved = json.loads(path.read_text(encoding="utf-8"))
        return validate_stage4c_run_manifest(saved, expected), False
    if path.exists():
        raise RuntimeError("Stage 4C run manifest path exists but is not a file")
    value = {
        **dict(expected),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_json(path, value)
    return value, True


def _atomic_json(path: Path, value: Any) -> None:
    from .hybrid import stage4a_clean
    from .hybrid_stage4b import write_atomic_json as _atomic

    # Keep the same finite-number normalization and atomic write convention as Stage 4B.
    _atomic(path, stage4a_clean(value))


__all__ = [
    "BUDGET", "CHECKPOINTS", "COMMON_GRID_ID", "COMMON_GRID_SHA256",
    "FINALIST_COUNT", "INITIAL_POPULATION_MULTIPLIER", "PROTOCOL_REVISION",
    "PRODUCTION_TOTAL_EVALUATIONS", "SEARCH_GRID_SHA256", "SEEDS",
    "STAGE4B_SEEDS", "STUDY_TYPE", "TOPOLOGIES", "PRODUCTION_RUN_ROOT",
    "QUALIFICATION_RUN_ROOT", "build_stage4c_run_manifest", "expected_matrix",
    "load_stage4c_context", "validate_frozen_config",
    "ensure_stage4c_run_manifest", "validate_stage4c_run_manifest",
]
