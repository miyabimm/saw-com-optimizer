"""Library-only L-SHADE orchestration for one resolved scientific v1 request.

This module requires explicit role-specific evaluator callbacks. It never
creates a scientific CLI route, checkpoint, or R5 run.
"""
from __future__ import annotations

import copy
from dataclasses import asdict
import math
from numbers import Real
from typing import Any, Callable, Mapping

import numpy as np

from ..design.space import canonical_design
from ..problem.evaluator import (
    ConfiguredEvaluationContext,
    _physical_proposal,
    _validate_measure_record,
    configured_evaluation_context,
)
from .lshade import LShadeBackend
from .selection import FeasibilityFirstComparator


class ConfiguredSearchInputError(ValueError):
    """The validated declaration or explicit orchestration inputs are unsupported."""


class _OrchestrationFailure(Exception):
    def __init__(self, phase: str, category: str, cause: Exception):
        self.phase = phase
        self.category = category
        self.cause = cause
        super().__init__(str(cause))


_SETTING_KEYS = (
    "initial_population", "min_population", "history_size", "pbest_max_fraction",
    "archive_rate", "max_duplicate_retries", "total_budget", "hard_max_budget",
    "population_schedule_terminal_budget", "requested_unique_budget",
    "canonical_space_size", "compact_history_cache", "historical_finalist_count",
    "exhaustion_duplicate_streak", "memory_update_batch_size",
)
_METRIC_KEYS = (
    "worst_il_db", "ripple_db", "input_vswr", "output_vswr",
    "source_return_loss_db_min", "load_return_loss_db_min", "stop_attenuation_db",
    "length_um", "width_um", "electrodes",
)


def _input_snapshot(snapshot: Any) -> tuple[dict[str, Any], ConfiguredEvaluationContext]:
    if not isinstance(snapshot, Mapping):
        raise ConfiguredSearchInputError("resolved snapshot must be a mapping")
    try:
        detached = copy.deepcopy(dict(snapshot))
        context = configured_evaluation_context(detached)
    except Exception as exc:
        raise ConfiguredSearchInputError(f"resolved v1 snapshot verification failed: {exc}") from exc
    effective = detached["effective_config"]
    optimizer = effective["optimizer"]
    design = effective["design"]
    specification = effective["specification"]
    expected_cells = effective["storage"]["expected_cells"]
    if (context.schema_id != "sawopt.scientific_config/1"
            or design["topology"] != "filter_design"
            or design["decoder"] != "sawopt.design.space.decode"
            or design["integer_indices"] != [1, 2, 3]
            or optimizer["name"] != "lshade"
            or optimizer["rng"] != "numpy.random.default_rng/PCG64"
            or optimizer["proposal_policy"] != "backend"
            or optimizer["checkpoint_policy"] != "disabled"
            or specification["comparator"] != "sawopt.optimization.selection.FeasibilityFirstComparator"
            or optimizer["comparator"] != specification["comparator"]
            or len(expected_cells) != 1
            or expected_cells[0]["topology"] != "filter_design"
            or expected_cells[0]["method"] != "lshade"
            or expected_cells[0]["seed"] != optimizer["seed"]):
        raise ConfiguredSearchInputError("only the declared one-cell filter_design/lshade v1 mode is supported")
    settings = optimizer["settings"]
    if not isinstance(settings, Mapping) or set(settings) != set(_SETTING_KEYS):
        raise ConfiguredSearchInputError("optimizer.settings do not match the exact supported v1 fields")
    if optimizer["search_fe_limit"] != settings["hard_max_budget"]:
        raise ConfiguredSearchInputError("search FE limit and hard backend budget disagree")
    return detached, context


def _canonicalize_physical(physical: np.ndarray):
    _design, canonical, key = canonical_design(physical)
    return canonical, key


def _record_vector(value: Any, name: str) -> np.ndarray:
    try:
        values = list(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"evaluation {name} must be a seven-coordinate vector") from exc
    if len(values) != 7:
        raise ValueError(f"evaluation {name} must have seven coordinates")
    converted = np.empty(7, dtype=np.float64)
    for index, item in enumerate(values):
        if isinstance(item, (bool, np.bool_)) or not isinstance(item, Real):
            raise ValueError(f"evaluation {name}[{index}] must be a real number")
        converted[index] = float(item)
    if not np.isfinite(converted).all():
        raise ValueError(f"evaluation {name} must be finite")
    return converted


def _validated_record(
    raw: Any,
    physical: np.ndarray,
    phase: str,
    snapshot: Mapping[str, Any],
    context: ConfiguredEvaluationContext,
    comparator: FeasibilityFirstComparator,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError("injected evaluator must return a mapping")
    record = copy.deepcopy(dict(raw))
    proposal = _record_vector(record.get("proposal_vector"), "proposal_vector")
    canonical = _record_vector(record.get("canonical_vector"), "canonical_vector")
    decoded_design, expected_canonical, expected_key = canonical_design(physical)
    if proposal.tobytes() != physical.tobytes():
        raise ValueError("evaluation proposal_vector differs from the backend-supplied physical design")
    if canonical.tobytes() != expected_canonical.tobytes():
        raise ValueError("evaluation canonical_vector differs from design.space.canonical_design")
    if physical.tobytes() != expected_canonical.tobytes():
        raise ValueError("backend evaluator input is not already the declared canonical physical vector")
    key = _record_vector(record.get("canonical_key"), "canonical_key")
    expected_key_array = np.asarray(expected_key, dtype=np.float64)
    if key.tobytes() != expected_key_array.tobytes():
        raise ValueError("evaluation canonical_key differs from design.space.canonical_design")
    if record.get("design") != asdict(decoded_design):
        raise ValueError("evaluation decoded design differs from canonical_design")
    if record.get("evaluation_phase") != phase:
        raise ValueError(f"evaluation phase must be exactly {phase}")
    if record.get("effective_config_sha256") != context.effective_config_sha256:
        raise ValueError("evaluation effective-config identity mismatch")
    if record.get("model_sha256") != context.input_sha256["model"]:
        raise ValueError("evaluation model identity mismatch")
    grid_name = "search_grid" if phase == "SEARCH" else "validation_grid"
    grid_points = (context.search_frequencies_hz if phase == "SEARCH"
                   else context.validation_frequencies_hz)
    if record.get("grid_sha256") != context.input_sha256[grid_name]:
        raise ValueError(f"evaluation {phase.lower()} grid identity mismatch")
    point_count = record.get("grid_point_count")
    if (isinstance(point_count, (bool, np.bool_)) or not isinstance(point_count, int)
            or point_count != len(grid_points)):
        raise ValueError(f"evaluation {phase.lower()} grid point count mismatch")

    _validate_measure_record(record, context)
    rank_key = record.get("rank_key")
    try:
        rank_values = list(rank_key)
    except (TypeError, ValueError) as exc:
        raise ValueError("evaluation rank_key must be a sequence") from exc
    expected_rank = comparator.rank_key(record)
    if (len(rank_values) != len(expected_rank)
            or any(isinstance(value, (bool, np.bool_)) or not isinstance(value, Real)
                   or math.isnan(float(value)) for value in rank_values)
            or tuple(float(value) for value in rank_values) != expected_rank):
        raise ValueError("evaluation rank_key disagrees with FeasibilityFirstComparator")

    if "candidate_vector" in record:
        candidate = _record_vector(record["candidate_vector"], "candidate_vector")
        if candidate.tobytes() != expected_canonical.tobytes():
            raise ValueError("evaluation candidate_vector differs from the canonical physical vector")
    else:
        record["candidate_vector"] = expected_canonical.tolist()
    return record


def _record_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    """Project one validated record into bounded, response-free result fields."""
    summary = {
        "evaluation_phase": record["evaluation_phase"],
        "effective_config_sha256": record["effective_config_sha256"],
        "model_sha256": record["model_sha256"],
        "grid_sha256": record["grid_sha256"],
        "grid_point_count": int(record["grid_point_count"]),
        "proposal_vector": list(record["proposal_vector"]),
        "design": copy.deepcopy(dict(record["design"])),
        "canonical_vector": list(record["canonical_vector"]),
        "canonical_key": list(record["canonical_key"]),
        "candidate_vector": list(record["candidate_vector"]),
        "metrics": {name: copy.deepcopy(record["metrics"][name]) for name in _METRIC_KEYS},
        "violations": copy.deepcopy(dict(record["violations"])),
        "feasible": record["feasible"],
        "max_violation": record["max_violation"],
        "objective": record["objective"],
        "search_scalar_objective": record["search_scalar_objective"],
        "objective_parts": copy.deepcopy(dict(record["objective_parts"])),
        "rank_key": list(record["rank_key"]),
    }
    if "sum_violation" in record:
        summary["sum_violation"] = record["sum_violation"]
    return summary


def _failure(phase: str, category: str, error: Exception) -> dict[str, str]:
    message = str(error).replace("\n", " ")[:400]
    return {
        "phase": phase,
        "category": category,
        "error_type": type(error).__name__,
        "message": message,
    }


def _backend_summary(backend: LShadeBackend | None, invocations: Mapping[str, Mapping[str, int]]):
    if backend is None:
        counters = {
            "unique_evaluations": 0, "proposals_total": 0, "raw_offspring_count": 0,
            "duplicate_count": 0, "cache_hits": 0,
        }
        summary = None
        incumbent = None
    else:
        counters = {
            "unique_evaluations": int(backend.unique_evaluations),
            "proposals_total": int(backend.proposals_total),
            "raw_offspring_count": int(backend.raw_offspring_count),
            "duplicate_count": int(backend.duplicate_count),
            "cache_hits": int(backend.cache_hits),
        }
        summary = {
            "backend": backend.name,
            "initial_population": int(backend.initial_population_size),
            "current_population": len(backend.population()),
            "generations": int(backend.generations),
            "population_schedule_identifier": backend.population_schedule_identifier,
            "population_schedule_version": int(backend.population_schedule_version),
            "population_schedule_terminal_budget": int(backend.population_schedule_terminal_budget),
            "hard_max_budget": int(backend.hard_max_budget),
            "search_space_exhausted": bool(backend.search_space_exhausted),
            "boundary_repair_counts": copy.deepcopy(backend.boundary_repair_counts),
        }
        incumbent = backend.incumbent()
    search_calls = invocations["SEARCH"]
    validation_calls = invocations["VALIDATION"]
    counters.update({
        "search_evaluator_attempts": search_calls["attempts"],
        "search_evaluator_records_returned": search_calls["records_returned"],
        "failed_search_evaluator_attempts": search_calls["failed_attempts"],
        "search_grid_points_requested": search_calls["grid_points_requested"],
        "validation_evaluator_attempts": validation_calls["attempts"],
        "validation_evaluator_records_returned": validation_calls["records_returned"],
        "failed_validation_evaluator_attempts": validation_calls["failed_attempts"],
    })
    residual = (counters["proposals_total"] - counters["unique_evaluations"]
                - counters["cache_hits"] - counters["failed_search_evaluator_attempts"])
    counters["unclassified_search_proposals"] = residual
    return counters, summary, incumbent


def run_configured_lshade(
    resolved_snapshot: Mapping[str, Any],
    *,
    search_evaluator: Callable,
    validation_evaluator: Callable,
) -> dict[str, Any]:
    """Run one configured L-SHADE search and validate its search incumbent.

    Evaluators receive ``(physical_canonical_vector, phase=...)`` and must
    return the verified S2-A record envelope. Both role-specific callbacks
    are mandatory; validation is outside all backend budget/cache counters.
    """
    if not callable(search_evaluator) or not callable(validation_evaluator):
        raise ConfiguredSearchInputError("explicit SEARCH and VALIDATION evaluators are required")
    detached, context = _input_snapshot(resolved_snapshot)
    effective = detached["effective_config"]
    optimizer = effective["optimizer"]
    settings = optimizer["settings"]
    design = effective["design"]
    comparator = FeasibilityFirstComparator()
    search_grid_count = len(context.search_frequencies_hz)
    validation_grid_count = len(context.validation_frequencies_hz)
    invocations = {
        phase: {"attempts": 0, "records_returned": 0, "failed_attempts": 0,
                "grid_points_requested": 0}
        for phase in ("SEARCH", "VALIDATION")
    }
    backend: LShadeBackend | None = None
    search_record: dict[str, Any] | None = None
    validation_record: dict[str, Any] | None = None
    search_status = "NOT_STARTED"
    validation_status = "NOT_RUN"
    failure: dict[str, str] | None = None
    terminal_status = "FAILED"

    def invoke_evaluator(vector: Any, *, phase: str) -> dict[str, Any]:
        counters = invocations[phase]
        try:
            physical = _physical_proposal(vector, context)
            decoded, canonical, _key = canonical_design(physical)
            del decoded
            if physical.tobytes() != canonical.tobytes():
                raise ValueError("evaluator input is not canonical in physical coordinates")
        except Exception as exc:
            raise _OrchestrationFailure(phase, "RECONCILIATION", exc) from exc

        counters["attempts"] += 1
        counters["grid_points_requested"] += (
            search_grid_count if phase == "SEARCH" else validation_grid_count
        )
        callback_vector = physical.copy()
        original_bytes = callback_vector.tobytes()
        try:
            raw_record = (search_evaluator if phase == "SEARCH" else validation_evaluator)(
                callback_vector, phase=phase,
            )
        except Exception as exc:
            counters["failed_attempts"] += 1
            category = "EVALUATION" if phase == "SEARCH" else "VALIDATION"
            raise _OrchestrationFailure(phase, category, exc) from exc
        try:
            if callback_vector.tobytes() != original_bytes:
                raise ValueError("injected evaluator mutated its physical input vector")
            record = _validated_record(
                raw_record, physical, phase, detached, context, comparator,
            )
        except Exception as exc:
            counters["failed_attempts"] += 1
            category = "RECONCILIATION" if phase == "SEARCH" else "VALIDATION"
            raise _OrchestrationFailure(phase, category, exc) from exc
        counters["records_returned"] += 1
        return record

    try:
        bounds = [list(variable["bounds"]) for variable in design["variables"]]
        hard_bounds = [list(variable["hard_bounds"]) for variable in design["variables"]]
        backend_config = {key: settings[key] for key in _SETTING_KEYS}
        backend_config["hard_bounds"] = hard_bounds
        backend = LShadeBackend(
            bounds,
            seed=optimizer["seed"],
            config=backend_config,
            integer_indices=(1, 2, 3),
            canonicalizer=_canonicalize_physical,
            comparator=comparator,
        )
        backend.initialize(
            lambda vector: invoke_evaluator(vector, phase="SEARCH"),
            comparator=comparator,
        )
        backend.advance_to_unique_budget(optimizer["search_fe_limit"])
    except _OrchestrationFailure as exc:
        failure = _failure(exc.phase, exc.category, exc.cause)
        search_status = "FAILED"
    except Exception as exc:
        failure = _failure("SEARCH", "OPTIMIZER", exc)
        search_status = "FAILED"

    counters, backend_summary, incumbent = _backend_summary(backend, invocations)
    if failure is None:
        if counters["unclassified_search_proposals"] != 0:
            error = ValueError(
                "backend proposals do not reconcile to committed unique evaluations, "
                "cache hits, and observed failed evaluator attempts"
            )
            failure = _failure("SEARCH", "RECONCILIATION", error)
            search_status = "FAILED"
        elif backend is None or incumbent is None:
            error = RuntimeError("L-SHADE produced no search incumbent")
            failure = _failure("SEARCH", "OPTIMIZER", error)
            search_status = "FAILED"
        elif backend.unique_evaluations >= optimizer["search_fe_limit"]:
            search_status = "BUDGET_REACHED"
        elif backend.search_space_exhausted:
            search_status = "EXHAUSTED"
        else:
            error = RuntimeError("L-SHADE stopped before budget without an exhaustion disposition")
            failure = _failure("SEARCH", "OPTIMIZER", error)
            search_status = "INCOMPLETE"

    if incumbent is not None:
        try:
            search_record = _record_summary(incumbent)
        except Exception as exc:
            if failure is None:
                failure = _failure("SEARCH", "RECONCILIATION", exc)
                search_status = "FAILED"

    if failure is None and search_status in ("BUDGET_REACHED", "EXHAUSTED"):
        validation_status = "RUNNING"
        try:
            validation_record = _record_summary(invoke_evaluator(
                np.asarray(incumbent["canonical_vector"], dtype=np.float64),
                phase="VALIDATION",
            ))
            validation_status = "VALIDATED"
            terminal_status = "COMPLETED" if search_status == "BUDGET_REACHED" else "EXHAUSTED"
        except _OrchestrationFailure as exc:
            validation_status = "FAILED"
            failure = _failure(exc.phase, "VALIDATION", exc.cause)
            terminal_status = "VALIDATION_FAILED"
    elif failure is not None:
        terminal_status = "FAILED"
    else:
        terminal_status = "INCOMPLETE"

    # Search grid points are per-call requests, not unique candidate FEs.
    counters["search_grid_points_per_call"] = search_grid_count
    counters["validation_grid_points_per_call"] = validation_grid_count
    validation = {
        "status": validation_status,
        "grid_sha256": context.validation_grid_sha256,
        "grid_point_count": validation_grid_count,
        "evaluator_calls": invocations["VALIDATION"]["attempts"],
        "requested_grid_points": invocations["VALIDATION"]["grid_points_requested"],
        "record": validation_record,
    }
    search = {
        "status": search_status,
        "grid_sha256": context.search_grid_sha256,
        "grid_point_count": search_grid_count,
        "counters": counters,
        "summary": backend_summary,
        "incumbent": search_record,
    }
    return {
        "schema_id": "sawopt.configured_lshade_result/1",
        "status": terminal_status,
        "failure": failure,
        "identity": {
            "schema_id": context.schema_id,
            "experiment_id": context.experiment_id,
            "effective_config_sha256": context.effective_config_sha256,
            "input_sha256": dict(context.input_sha256),
            "declared_source_commit_sha": context.declared_source_commit_sha,
            "declared_environment_sha256": context.declared_environment_sha256,
            "topology": context.topology,
            "method": optimizer["name"],
            "optimizer_version": optimizer["version"],
            "optimizer_settings": copy.deepcopy(dict(settings)),
            "seed": int(optimizer["seed"]),
            "rng": optimizer["rng"],
            "comparator": optimizer["comparator"],
            "integer_indices": [1, 2, 3],
            "active_bounds": [list(bounds) for bounds in context.active_bounds],
            "hard_bounds": [list(bounds) for bounds in context.hard_bounds],
            "search_fe_limit": int(optimizer["search_fe_limit"]),
            "expected_cells": copy.deepcopy(effective["storage"]["expected_cells"]),
            "ports": {
                "unit": context.ports_unit,
                "source_ohm": context.source_impedance_ohm,
                "load_ohm": context.load_impedance_ohm,
            },
            "declared_resources": {
                name: effective["resources"][name]
                for name in (
                    "workers", "processes", "threads", "memory_bytes",
                    "wall_time_seconds", "stop_policy",
                )
            },
        },
        "accounting": {
            "unique_evaluations_source": "LShadeBackend.unique_evaluations",
            "failed_attempt_policy": (
                "L-SHADE counts unique_evaluations only after an evaluator returns and the "
                "backend accepts the record; attempted failures are reported separately and "
                "are not silently charged or retried. Failed-model FE policy requires a future "
                "explicit qualification/owner decision."
            ),
            "duplicate_count_overlaps_cache_hits": True,
            "validation_outside_search_budget": True,
        },
        "search": search,
        "validation": validation,
    }


__all__ = ["ConfiguredSearchInputError", "run_configured_lshade"]
