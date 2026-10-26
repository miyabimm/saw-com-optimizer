"""Reusable SAW filter and dense frequency-grid evaluation."""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
import hashlib
from numbers import Real
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Callable, Mapping

import numpy as np

from ..design.space import canonical_design
from ..evaluation import evaluate_design, evaluate_response, feasibility_objective, measure, validation_grid
from ..optimization.selection import FeasibilityFirstComparator
from ..physics.com import SimulationResult
from ..optimization.adaptive_frequency import critical_frequencies, new_frequency_points
from ..optimization.cache import IncrementalFrequencyCache


class SnapshotValidationError(ValueError):
    """A resolved scientific declaration is incomplete, changed, or unsupported."""


class CandidateInputError(ValueError):
    """A physical proposal or evaluation phase is outside the adapter contract."""


class CandidateEvaluationError(RuntimeError):
    """The existing configured evaluation path failed; no result was fabricated."""

    def __init__(self, phase: str, cause: Exception):
        self.phase = phase
        self.cause_type = type(cause).__name__
        super().__init__(f"{phase} evaluation failed ({self.cause_type}): {cause}")


@dataclass(frozen=True)
class ConfiguredEvaluationContext:
    """Detached v1 fields consumed by the existing single-filter evaluator."""

    experiment_id: str
    schema_id: str
    effective_config_sha256: str
    input_sha256: Mapping[str, str]
    declared_source_commit_sha: str
    declared_environment_sha256: str
    topology: str
    decoder: str
    variable_names: tuple[str, ...]
    variable_units: tuple[str, ...]
    active_bounds: tuple[tuple[float, float], ...]
    hard_bounds: tuple[tuple[float, float], ...]
    fixed_values: Mapping[str, float]
    center: str
    wiring: str
    ports_unit: str
    source_impedance_ohm: float
    load_impedance_ohm: float
    specification_frequency_unit: str
    frequency_unit: str
    feasibility_tolerance: float
    search_frequencies_hz: tuple[float, ...]
    validation_frequencies_hz: tuple[float, ...]
    search_grid_sha256: str
    validation_grid_sha256: str
    evaluation_config: Mapping[str, Any]


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _verified_effective_config(snapshot: Any) -> tuple[dict[str, Any], dict[str, str], str]:
    """Verify the resolved envelope and revalidate its exact normalized payload."""
    from ..io.scientific_config import SCHEMA_ID, canonical_bytes, resolve_scientific_config

    required = {
        "status", "schema_valid", "schema_id", "experiment_id", "qualification",
        "run_authorized", "scientific_run_implemented", "effective_config",
        "effective_config_sha256", "config_file_sha256", "input_sha256", "references",
    }
    try:
        if not isinstance(snapshot, Mapping) or set(snapshot) != required:
            raise SnapshotValidationError("resolved snapshot envelope fields do not match v1")
        detached = copy.deepcopy(dict(snapshot))
        if (detached["status"] != "VALID" or detached["schema_valid"] is not True
                or detached["schema_id"] != SCHEMA_ID
                or detached["qualification"] != "NOT_EVALUATED"
                or detached["run_authorized"] is not False
                or detached["scientific_run_implemented"] is not False):
            raise SnapshotValidationError("resolved snapshot status/schema/authorization is unsupported")
        if not isinstance(detached["effective_config"], dict):
            raise SnapshotValidationError("effective_config must be an object")
        for name in ("effective_config_sha256", "config_file_sha256"):
            if (not isinstance(detached[name], str)
                    or re.fullmatch(r"[0-9a-f]{64}", detached[name]) is None):
                raise SnapshotValidationError(f"{name} must be a lowercase SHA-256")
        if not isinstance(detached["references"], dict):
            raise SnapshotValidationError("references must be an object")

        effective = detached["effective_config"]
        effective_bytes = canonical_bytes(effective)
        if _sha256(effective_bytes) != detached["effective_config_sha256"]:
            raise SnapshotValidationError("effective_config_sha256 mismatch")
        if (detached["experiment_id"] != effective.get("experiment_id")
                or detached["schema_id"] != effective.get("schema_id")):
            raise SnapshotValidationError("resolved envelope identity differs from effective_config")

        input_hashes = detached["input_sha256"]
        input_names = {"model", "search_grid", "validation_grid"}
        if not isinstance(input_hashes, dict) or set(input_hashes) != input_names:
            raise SnapshotValidationError("input_sha256 must identify model and both exact grids")
        payloads = {
            "model": effective["model"]["parameters"],
            "search_grid": effective["grids"]["search"],
            "validation_grid": effective["grids"]["validation"],
        }
        for name, payload in payloads.items():
            digest = input_hashes[name]
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise SnapshotValidationError(f"input_sha256.{name} must be a lowercase SHA-256")
            if _sha256(canonical_bytes(payload)) != digest:
                raise SnapshotValidationError(f"input_sha256.{name} mismatch")

        # Revalidate the effective declaration through the existing v1 schema
        # owner. Convert only the three already-resolved payloads to inline
        # wrappers; no config or referenced file is read here.
        raw = copy.deepcopy(effective)
        raw["model"]["parameters"] = {"inline": raw["model"]["parameters"]}
        raw["grids"] = {
            role: {"inline": raw["grids"][role]}
            for role in ("search", "validation")
        }
        verified = resolve_scientific_config(
            raw, config_path=Path("resolved-snapshot.yaml"), config_bytes=b"",
        )
        if canonical_bytes(verified["effective_config"]) != effective_bytes:
            raise SnapshotValidationError("effective_config is not the exact normalized v1 snapshot")
        if verified["effective_config_sha256"] != detached["effective_config_sha256"]:
            raise SnapshotValidationError("revalidated effective identity differs")
        if verified["input_sha256"] != input_hashes:
            raise SnapshotValidationError("revalidated input identities differ")
        return effective, dict(input_hashes), detached["effective_config_sha256"]
    except SnapshotValidationError:
        raise
    except Exception as exc:
        raise SnapshotValidationError(f"resolved snapshot validation failed: {exc}") from exc


def _evaluation_context(snapshot: Any) -> ConfiguredEvaluationContext:
    effective, input_hashes, effective_config_sha256 = _verified_effective_config(snapshot)
    design = effective["design"]
    spec = effective["specification"]
    variables = design["variables"]
    evaluation_spec = {
        "passband": list(spec["passband"]),
        "stopbands": copy.deepcopy(spec["stopbands"]),
        "il": spec["il_db"],
        "ripple": spec["ripple_db"],
        "vswr": spec["vswr"],
    }
    evaluation_config = _freeze({
        "com": effective["model"]["parameters"],
        "center": design["center"],
        "spec": evaluation_spec,
        "constraints": design["geometry"],
    })
    return ConfiguredEvaluationContext(
        experiment_id=effective["experiment_id"],
        schema_id=effective["schema_id"],
        effective_config_sha256=effective_config_sha256,
        input_sha256=MappingProxyType(input_hashes),
        declared_source_commit_sha=effective["resources"]["source_commit_sha"],
        declared_environment_sha256=effective["resources"]["environment_sha256"],
        topology=design["topology"],
        decoder=design["decoder"],
        variable_names=tuple(variable["name"] for variable in variables),
        variable_units=tuple(variable["unit"] for variable in variables),
        active_bounds=tuple(tuple(variable["bounds"]) for variable in variables),
        hard_bounds=tuple(tuple(variable["hard_bounds"]) for variable in variables),
        fixed_values=_freeze(design["fixed"]),
        center=design["center"],
        wiring=design["wiring"],
        ports_unit=effective["ports"]["unit"],
        source_impedance_ohm=effective["ports"]["source"],
        load_impedance_ohm=effective["ports"]["load"],
        specification_frequency_unit=spec["frequency_unit"],
        frequency_unit=effective["grids"]["search"]["unit"],
        feasibility_tolerance=spec["feasibility_tolerance"],
        search_frequencies_hz=tuple(effective["grids"]["search"]["points"]),
        validation_frequencies_hz=tuple(effective["grids"]["validation"]["points"]),
        search_grid_sha256=input_hashes["search_grid"],
        validation_grid_sha256=input_hashes["validation_grid"],
        evaluation_config=evaluation_config,
    )


def _physical_proposal(vector: Any, context: ConfiguredEvaluationContext) -> np.ndarray:
    try:
        values = list(vector)
    except (TypeError, ValueError) as exc:
        raise CandidateInputError("physical proposal must be a seven-coordinate sequence") from exc
    if len(values) != 7:
        raise CandidateInputError("physical proposal must have exactly seven coordinates")
    proposal = np.empty(7, dtype=np.float64)
    for index, value in enumerate(values):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
            raise CandidateInputError(f"physical proposal coordinate {index} must be a real number")
        try:
            proposal[index] = float(value)
        except (OverflowError, TypeError, ValueError) as exc:
            raise CandidateInputError(f"physical proposal coordinate {index} is not binary64") from exc
    if not np.isfinite(proposal).all():
        raise CandidateInputError("physical proposal coordinates must be finite")
    for index, value in enumerate(proposal):
        for label, bounds in (("active", context.active_bounds[index]),
                              ("hard", context.hard_bounds[index])):
            if value < bounds[0] or value > bounds[1]:
                raise CandidateInputError(
                    f"physical proposal coordinate {index} is outside declared {label} bounds {bounds}"
                )
    return proposal


def _validate_measure_record(record: Mapping[str, Any], context: ConfiguredEvaluationContext) -> None:
    required = {
        "metrics", "violations", "feasible", "max_violation", "objective",
        "search_scalar_objective", "objective_parts", "diagnostics",
    }
    if not required.issubset(record):
        raise TypeError(f"evaluation record is missing fields: {sorted(required - set(record))}")
    metrics = record["metrics"]
    violations = record["violations"]
    if not isinstance(metrics, Mapping) or not isinstance(violations, Mapping):
        raise TypeError("evaluation metrics and violations must be mappings")
    expected_violations = {"il", "ripple", "input_vswr", "output_vswr", "geometry"}
    expected_violations.update(f"stop_{index}" for index in range(
        len(context.evaluation_config["spec"]["stopbands"])
    ))
    if set(violations) != expected_violations:
        raise ValueError("evaluation violation names do not match the v1 measure contract")
    for name, value in violations.items():
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
            raise TypeError(f"evaluation violation {name} is not numeric")
        if not np.isfinite(float(value)) or value < 0:
            raise ValueError(f"evaluation violation {name} is nonfinite or negative")
    if type(record["feasible"]) is not bool:
        raise TypeError("evaluation feasible flag must be boolean")
    max_violation = record["max_violation"]
    if isinstance(max_violation, (bool, np.bool_)) or not isinstance(max_violation, Real):
        raise TypeError("evaluation max_violation must be numeric")
    if float(max_violation) != max(float(value) for value in violations.values()):
        raise ValueError("evaluation max_violation disagrees with named violations")
    if record["feasible"] is not (float(max_violation) <= context.feasibility_tolerance):
        raise ValueError("evaluation feasible flag disagrees with declared tolerance")
    for name in ("objective", "search_scalar_objective"):
        value = record[name]
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) or not np.isfinite(float(value)):
            raise ValueError(f"evaluation {name} must be finite and numeric")
    if record["objective"] != record["search_scalar_objective"]:
        raise ValueError("evaluation scalar surrogate fields disagree")
    if not isinstance(record["objective_parts"], Mapping) or not isinstance(record["diagnostics"], Mapping):
        raise TypeError("evaluation objective_parts and diagnostics must be mappings")
    expected_objective, expected_parts = feasibility_objective(metrics, violations)
    if (record["objective"] != expected_objective
            or record["search_scalar_objective"] != expected_objective):
        raise ValueError("evaluation scalar surrogate disagrees with feasibility_objective")
    if dict(record["objective_parts"]) != expected_parts:
        raise ValueError("evaluation objective_parts disagree with feasibility_objective")
    if "sum_violation" in record:
        sum_violation = record["sum_violation"]
        if (isinstance(sum_violation, (bool, np.bool_))
                or not isinstance(sum_violation, Real)
                or not np.isfinite(float(sum_violation)) or sum_violation < 0):
            raise ValueError("evaluation sum_violation must be finite and nonnegative")
        expected_sum = sum(float(value) for value in violations.values())
        if float(sum_violation) != expected_sum:
            raise ValueError("evaluation sum_violation disagrees with the ordered named violations")
    required_metrics = {
        "worst_il_db", "ripple_db", "input_vswr", "output_vswr",
        "source_return_loss_db_min", "load_return_loss_db_min", "stop_attenuation_db",
        "length_um", "width_um", "electrodes",
    }
    if not required_metrics.issubset(metrics):
        raise TypeError(f"evaluation metrics are missing fields: {sorted(required_metrics - set(metrics))}")
    for name in ("worst_il_db", "ripple_db", "input_vswr", "output_vswr",
                 "length_um", "width_um", "electrodes"):
        if isinstance(metrics[name], (bool, np.bool_)) or not isinstance(metrics[name], Real):
            raise TypeError(f"evaluation metric {name} is not numeric")
        if not np.isfinite(float(metrics[name])):
            raise ValueError(f"evaluation metric {name} is nonfinite")
    for name in ("source_return_loss_db_min", "load_return_loss_db_min"):
        if isinstance(metrics[name], (bool, np.bool_)) or not isinstance(metrics[name], Real):
            raise TypeError(f"evaluation metric {name} is not numeric")
        if np.isnan(float(metrics[name])):
            raise ValueError(f"evaluation metric {name} is NaN")
    stops = metrics["stop_attenuation_db"]
    if (not isinstance(stops, (list, tuple))
            or len(stops) != len(context.evaluation_config["spec"]["stopbands"])
            or any(not isinstance(value, Real) or not np.isfinite(float(value)) for value in stops)):
        raise ValueError("evaluation stop attenuation metrics do not match declared stopbands")


class ConfiguredCandidateEvaluator:
    """Evaluate one v1 seven-coordinate physical candidate on an explicit grid.

    The verified snapshot and all consumed fields are detached at construction.
    The callable is suitable for future injected optimizer/R5 orchestration but
    does not initialize an optimizer, charge FEs, validate dense grids, or write
    storage.
    """

    def __init__(self, resolved_snapshot: Mapping[str, Any], *,
                 evaluate_design_fn: Callable | None = None):
        self.context = _evaluation_context(resolved_snapshot)
        if evaluate_design_fn is not None and not callable(evaluate_design_fn):
            raise TypeError("evaluate_design_fn must be callable")
        self._evaluate_design_fn = evaluate_design if evaluate_design_fn is None else evaluate_design_fn
        self._comparator = FeasibilityFirstComparator()

    def __call__(self, physical_vector: Any, *, phase: str) -> dict[str, Any]:
        if not isinstance(phase, str) or phase not in ("SEARCH", "VALIDATION"):
            raise CandidateInputError("phase must be exactly SEARCH or VALIDATION")
        proposal = _physical_proposal(physical_vector, self.context)
        try:
            design, canonical, key = canonical_design(proposal)
            decoded_record = asdict(design)
            if (canonical.shape != (7,) or not np.isfinite(canonical).all()
                    or len(key) != 7):
                raise ValueError("canonical decoder returned an invalid seven-coordinate design")
            for index, value in enumerate(canonical):
                for bounds in (self.context.active_bounds[index], self.context.hard_bounds[index]):
                    if value < bounds[0] or value > bounds[1]:
                        raise ValueError(f"canonical coordinate {index} is outside declared bounds")
            frequencies = np.asarray(
                self.context.search_frequencies_hz if phase == "SEARCH"
                else self.context.validation_frequencies_hz,
                dtype=np.float64,
            ).copy()
            record, _network, _simulation = self._evaluate_design_fn(
                copy.deepcopy(design), _thaw(self.context.evaluation_config), frequencies,
                self.context.source_impedance_ohm, self.context.load_impedance_ohm,
                wiring=self.context.wiring,
            )
            if not isinstance(record, Mapping):
                raise TypeError("evaluate_design_fn must return an evaluation record mapping")
            result = copy.deepcopy(dict(record))
            _validate_measure_record(result, self.context)
            result.update({
                "evaluation_phase": phase,
                "effective_config_sha256": self.context.effective_config_sha256,
                "model_sha256": self.context.input_sha256["model"],
                "proposal_vector": proposal.tolist(),
                "design": decoded_record,
                "canonical_vector": canonical.tolist(),
                "canonical_key": key,
                "source_impedance_ohm": self.context.source_impedance_ohm,
                "load_impedance_ohm": self.context.load_impedance_ohm,
                "grid_sha256": (self.context.search_grid_sha256 if phase == "SEARCH"
                                else self.context.validation_grid_sha256),
                "grid_point_count": len(frequencies),
            })
            result["rank_key"] = self._comparator.rank_key(result)
            return result
        except CandidateInputError:
            raise
        except Exception as exc:
            raise CandidateEvaluationError(phase, exc) from exc


def dense(d, cfg, rs, rl, wiring="outer_ports", counters=None, *,
         base_grid=None, passes=None, validation=False):
    """Dense-evaluate one fixed design with exact incremental frequency caching."""
    f = validation_grid(cfg["spec"], cfg) if base_grid is None else np.unique(np.asarray(base_grid, dtype=float))
    passes = int(cfg.get("validation", {}).get("dense_refinement_passes",
                       cfg.get("dense_refinement_passes", 2))) if passes is None else int(passes)
    slope = float(cfg.get("dense_slope_threshold_db", .5))
    tolerance = float(cfg.get("validation", {}).get(
        "adaptive_frequency_tolerance_hz",
        cfg.get("adaptive_frequency_tolerance_hz", 1e3),
    ))

    def point_evaluate(points):
        net, sim = evaluate_response(d, cfg, points, rs, rl, wiring=wiring)
        payload = dict(net)
        payload["y_parameters"] = sim.y_parameters
        payload["_diagnostics"] = sim.diagnostics
        return payload

    cache = IncrementalFrequencyCache(point_evaluate)

    def cached_evaluate(points):
        nonlocal solved_seen
        payload = cache.evaluate(points)
        solved_delta = cache.solved_points - solved_seen
        solved_seen = cache.solved_points
        if counters is not None:
            counters.add_solved(solved_delta, validation=validation)
            counters.add_evaluation_time(cache.last_evaluation_wall_time_s, validation=validation)
        net = {key: value for key, value in payload.items()
               if key not in ("frequencies_hz", "y_parameters", "_diagnostics")}
        evaluated_frequencies = np.asarray(payload["frequencies_hz"], dtype=float)
        sim = SimulationResult(
            frequencies_hz=evaluated_frequencies,
            y_parameters=np.asarray(payload["y_parameters"]),
            diagnostics=payload.get("_diagnostics", {}),
        )
        result = measure(evaluated_frequencies, net, d, cfg)
        result["diagnostics"] = sim.diagnostics
        return result, net, sim

    solved_seen = 0
    for _ in range(max(0, passes)):
        result, net, sim = cached_evaluate(f)
        critical = critical_frequencies(
            f, net, cfg["spec"], slope_threshold_db=slope,
            max_points=int(cfg.get("adaptive_max_points_per_round",
                                   cfg.get("validation", {}).get("adaptive_max_points_per_round", 64))),
        )
        added = new_frequency_points(f, critical, tolerance)
        if len(added) == 0:
            break
        f = np.unique(np.r_[f, added])
    return f, cached_evaluate(f)


__all__ = [
    "CandidateEvaluationError", "CandidateInputError", "ConfiguredCandidateEvaluator",
    "ConfiguredEvaluationContext", "SnapshotValidationError", "dense",
]
