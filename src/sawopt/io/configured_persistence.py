"""Test-only configured-result persistence planning; no scientific execution.

The plan builder is pure: it verifies detached in-memory inputs and does not
inspect the filesystem. R5 persistence is a separate explicit operation.
"""
from __future__ import annotations

import copy
import json
import os
from collections.abc import Mapping

from .experiment_store import (
    _validate_run_id, _validate_source_sha, create_experiment_run,
    read_experiment_manifest,
)
from ..optimization.configured_search import _input_snapshot, _validated_record
from ..optimization.selection import FeasibilityFirstComparator
from ..problem.evaluator import _physical_proposal


class PersistencePlanError(ValueError):
    """An untrusted configured result cannot be safely mapped to R5."""


_ACCOUNTING = {
    "unique_evaluations_source": "LShadeBackend.unique_evaluations",
    "failed_attempt_policy": (
        "L-SHADE counts unique_evaluations only after an evaluator returns and the "
        "backend accepts the record; attempted failures are reported separately and "
        "are not silently charged or retried. Failed-model FE policy requires a future "
        "explicit qualification/owner decision."
    ),
    "duplicate_count_overlaps_cache_hits": True,
    "validation_outside_search_budget": True,
}


def _raw_payload(result):
    try:
        return (json.dumps({"classification": "TEST_ONLY / NOT_SCIENTIFIC_EVIDENCE",
                            "configured_result": result}, sort_keys=True,
                           ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
    except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
        raise PersistencePlanError("R5_REPRESENTATION_GAP: result cannot be faithfully encoded as canonical JSON") from exc


def _equal(actual, expected, label):
    # JSON distinguishes booleans, integers, and floats and forbids NaN.
    try:
        a = json.dumps(actual, sort_keys=True, allow_nan=False, separators=(",", ":"))
        b = json.dumps(expected, sort_keys=True, allow_nan=False, separators=(",", ":"))
    except (ValueError, TypeError) as exc:
        raise PersistencePlanError(f"invalid {label}") from exc
    if a != b:
        raise PersistencePlanError(f"inconsistent {label}")


def _count(mapping, key):
    value = mapping[key]
    if type(value) is not int or value < 0:
        raise PersistencePlanError(f"invalid counter: {key}")
    return value


def _build(snapshot, result, run_id, execution_source_sha):
    _validate_run_id(run_id)
    _validate_source_sha(execution_source_sha)
    snapshot, context = _input_snapshot(snapshot)
    if not isinstance(result, Mapping):
        raise PersistencePlanError("result must be a mapping")
    result = copy.deepcopy(dict(result))
    config = snapshot["effective_config"]
    opt = config["optimizer"]
    _equal(result["schema_id"], "sawopt.configured_lshade_result/1", "result schema")
    _equal(result["accounting"], _ACCOUNTING, "accounting contract")
    expected_identity = {
        "schema_id": context.schema_id, "experiment_id": context.experiment_id,
        "effective_config_sha256": context.effective_config_sha256,
        "input_sha256": dict(context.input_sha256),
        "declared_source_commit_sha": context.declared_source_commit_sha,
        "declared_environment_sha256": context.declared_environment_sha256,
        "topology": context.topology, "method": opt["name"],
        "optimizer_version": opt["version"], "optimizer_settings": opt["settings"],
        "seed": opt["seed"], "rng": opt["rng"], "comparator": opt["comparator"],
        "integer_indices": [1, 2, 3],
        "active_bounds": [list(bounds) for bounds in context.active_bounds],
        "hard_bounds": [list(bounds) for bounds in context.hard_bounds],
        "search_fe_limit": opt["search_fe_limit"],
        "expected_cells": config["storage"]["expected_cells"],
        "ports": {"unit": context.ports_unit, "source_ohm": context.source_impedance_ohm,
                  "load_ohm": context.load_impedance_ohm},
        "declared_resources": {name: config["resources"][name] for name in (
            "workers", "processes", "threads", "memory_bytes", "wall_time_seconds", "stop_policy")},
    }
    _equal(result["identity"], expected_identity, "result identity")
    search, validation = result["search"], result["validation"]
    search_points, validation_points = len(context.search_frequencies_hz), len(context.validation_frequencies_hz)
    for section, sha, points in ((search, context.search_grid_sha256, search_points),
                                  (validation, context.validation_grid_sha256, validation_points)):
        _equal(section["grid_sha256"], sha, "grid hash")
        _equal(section["grid_point_count"], points, "grid count")
    counters = search["counters"]
    names = ("unique_evaluations", "proposals_total", "raw_offspring_count", "duplicate_count",
             "cache_hits", "search_evaluator_attempts", "search_evaluator_records_returned",
             "failed_search_evaluator_attempts", "search_grid_points_requested",
             "validation_evaluator_attempts", "validation_evaluator_records_returned",
             "failed_validation_evaluator_attempts", "unclassified_search_proposals",
             "search_grid_points_per_call", "validation_grid_points_per_call")
    _equal(sorted(counters), sorted(names), "counter fields")
    c = {name: _count(counters, name) for name in names}
    unique, attempts = c["unique_evaluations"], c["search_evaluator_attempts"]
    returned, failed = c["search_evaluator_records_returned"], c["failed_search_evaluator_attempts"]
    if (unique > opt["search_fe_limit"] or returned < unique or attempts > c["proposals_total"] or attempts != returned + failed
            or failed > 1 or c["search_grid_points_requested"] != attempts * search_points
            or c["search_grid_points_per_call"] != search_points
            or c["validation_grid_points_per_call"] != validation_points
            or c["duplicate_count"] > c["cache_hits"]
            or c["raw_offspring_count"] > c["proposals_total"]
            or c["proposals_total"] != unique + c["cache_hits"] + failed + c["unclassified_search_proposals"]):
        raise PersistencePlanError("inconsistent search accounting")
    # S2-B1 snapshots these fields before validation runs; they are not validation counts.
    if any(c[k] != 0 for k in ("validation_evaluator_attempts", "validation_evaluator_records_returned", "failed_validation_evaluator_attempts")):
        raise PersistencePlanError("unexpected pre-validation counter snapshot")
    summary = search["summary"]
    if summary is None:
        if unique or attempts or c["proposals_total"]:
            raise PersistencePlanError("missing backend summary")
    else:
        _equal(sorted(summary), sorted(("backend", "initial_population", "current_population", "generations",
            "population_schedule_identifier", "population_schedule_version", "population_schedule_terminal_budget",
            "hard_max_budget", "search_space_exhausted", "boundary_repair_counts")), "summary fields")
        _equal(summary["backend"], "lshade", "backend")
        _equal(summary["hard_max_budget"], opt["search_fe_limit"], "backend budget")
        _equal(summary["population_schedule_terminal_budget"], opt["search_fe_limit"], "schedule budget")
        _equal(summary["population_schedule_identifier"], "lshade_linear_population_v1", "schedule")
        _equal(summary["population_schedule_version"], 1, "schedule version")
        initial = _count(summary, "initial_population")
        current = _count(summary, "current_population")
        _count(summary, "generations")
        repairs = summary["boundary_repair_counts"]
        if not isinstance(repairs, Mapping) or set(repairs) != {"lower", "upper"}:
            raise PersistencePlanError("invalid boundary repairs")
        for values in repairs.values():
            if (not isinstance(values, list) or len(values) != len(context.active_bounds)
                    or any(type(value) is not int or value < 0 for value in values)):
                raise PersistencePlanError("invalid boundary repairs")
        if type(summary["search_space_exhausted"]) is not bool:
            raise PersistencePlanError("invalid exhaustion flag")
        maximum = opt["settings"]["initial_population"]
        if initial > maximum or current > initial or current > unique:
            raise PersistencePlanError("invalid current population")
        if search["status"] in ("BUDGET_REACHED", "EXHAUSTED"):
            if not (opt["settings"]["min_population"] <= current <= initial <= unique):
                raise PersistencePlanError("invalid initialized population")
        elif initial != maximum and initial < opt["settings"]["min_population"]:
            raise PersistencePlanError("invalid initial population")
    incumbent = search["incumbent"]
    record = validation["record"]
    comparator = FeasibilityFirstComparator()
    for item, phase in ((incumbent, "SEARCH"), (record, "VALIDATION")):
        if item is not None:
            vector = _physical_proposal(item["proposal_vector"], context)
            # S2-B1 deliberately strips diagnostics from bounded summaries. The
            # validator only checks that diagnostics is a mapping; this temporary
            # placeholder is not persisted or represented as an observation.
            checked = dict(item)
            checked["diagnostics"] = {}
            _validated_record(checked, vector, phase, snapshot, context, comparator)
    calls = _count(validation, "evaluator_calls")
    requests = _count(validation, "requested_grid_points")
    if calls > 1 or requests != calls * validation_points:
        raise PersistencePlanError("inconsistent validation requests")
    status, failure = result["status"], result["failure"]
    ss, vs = search["status"], validation["status"]
    if status in ("COMPLETED", "EXHAUSTED"):
        if (failure is not None or incumbent is None or record is None or vs != "VALIDATED"
                or calls != 1 or failed or returned != unique or c["unclassified_search_proposals"] != 0):
            raise PersistencePlanError("invalid successful outcome")
        if status == "COMPLETED" and (ss != "BUDGET_REACHED" or unique != opt["search_fe_limit"]):
            raise PersistencePlanError("invalid completion")
        if status == "EXHAUSTED" and (ss != "EXHAUSTED" or unique >= opt["search_fe_limit"] or not summary or not summary["search_space_exhausted"]):
            raise PersistencePlanError("invalid exhaustion")
        _equal(record["canonical_vector"], incumbent["canonical_vector"], "finalist")
        cell_status = "COMPLETED" if status == "COMPLETED" else "INCOMPLETE"
        reason = None if status == "COMPLETED" else "Search exhausted before budget"
        failure_class = None
        observed = validation_points
    elif status in ("FAILED", "VALIDATION_FAILED"):
        if not isinstance(failure, Mapping) or set(failure) != {"phase", "category", "error_type", "message"}:
            raise PersistencePlanError("invalid failure")
        if any(not isinstance(failure[k], str) or not failure[k] for k in failure):
            raise PersistencePlanError("invalid failure fields")
        if status == "VALIDATION_FAILED":
            if (ss not in ("BUDGET_REACHED", "EXHAUSTED") or vs != "FAILED" or calls != 1
                    or record is not None or incumbent is None or failure["phase"] != "VALIDATION"
                    or failure["category"] != "VALIDATION" or failed):
                raise PersistencePlanError("invalid validation failure")
            if ((ss == "BUDGET_REACHED" and unique != opt["search_fe_limit"])
                    or (ss == "EXHAUSTED" and (unique >= opt["search_fe_limit"]
                        or not summary or not summary["search_space_exhausted"]))
                    or c["unclassified_search_proposals"] != 0):
                raise PersistencePlanError("invalid search before validation failure")
            failure_class = "VALIDATION"
        else:
            if (ss != "FAILED" or vs != "NOT_RUN" or calls or record is not None
                    or failure["phase"] != "SEARCH" or failure["category"] not in ("EVALUATION", "RECONCILIATION", "OPTIMIZER")):
                raise PersistencePlanError("invalid search failure")
            if failure["category"] == "EVALUATION" and failed != 1:
                raise PersistencePlanError("evaluation failure without failed attempt")
            failure_class = {"EVALUATION": "MODEL", "RECONCILIATION": "VALIDATION", "OPTIMIZER": "UNKNOWN"}[failure["category"]]
        cell_status, reason, observed = "FAILED", failure["message"], 0
    else:
        raise PersistencePlanError("unsupported result status")
    _raw_payload(result)  # Validate the exact published bytes while planning is still pure.
    return {"snapshot": snapshot, "result": result, "run_id": run_id,
            "execution_source_sha": execution_source_sha, "cell_status": cell_status,
            "search_fes": unique, "validation_points": observed, "reason": reason,
            "failure_class": failure_class}


def build_persistence_plan(snapshot, result, *, run_id, execution_source_sha):
    """Build a detached, verified one-cell plan without filesystem access."""
    try:
        return _build(snapshot, result, run_id, execution_source_sha)
    except PersistencePlanError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise PersistencePlanError(f"invalid persistence inputs: {exc}") from exc


class ReviewEvidenceUnavailable(ValueError):
    """S2-B1 does not retain physical-response evidence for R5 review."""


def export_persistence_review(*, run_path, repository_root):
    """Refuse review export without inspecting or writing either path."""
    raise ReviewEvidenceUnavailable("VALIDATION_EVIDENCE_UNAVAILABLE: S2-B1 retains no physical response")


def _incident_classification(exc):
    # R5 may wrap a corrupt manifest's JSON/Unicode errors in RunStorageError.
    # Preserve that distinction from actual I/O failures through the cause chain.
    causes = []
    while exc is not None and exc not in causes:
        causes.append(exc)
        exc = exc.__cause__
    if any(isinstance(item, (ValueError, UnicodeError)) for item in causes):
        return "VALIDATION"
    if any(isinstance(item, OSError) for item in causes):
        return "IO"
    return "UNKNOWN"


def persist_persistence_plan(plan, *, data_root):
    """Persist a verified software fixture using the existing R5 transaction APIs.

    The caller must supply an isolated test-owned external root. A published
    incident is never deleted, repaired, retried, or promoted to success.
    """
    if not isinstance(plan, Mapping):
        raise PersistencePlanError("plan must be a mapping")
    try:
        verified = build_persistence_plan(plan["snapshot"], plan["result"],
                                          run_id=plan["run_id"],
                                          execution_source_sha=plan["execution_source_sha"])
        _equal(plan, verified, "persistence plan")
        if data_root is None or not os.path.isabs(os.fspath(data_root)):
            raise PersistencePlanError("an explicit absolute test-owned data root is required")
        # Fail closed on every existing root, including historical roots and
        # symlinks. Fixture callers must provide a fresh, isolated leaf.
        if os.path.lexists(data_root):
            raise FileExistsError("test-only data root already exists")
        payload = _raw_payload(verified["result"])
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, PersistencePlanError):
            raise
        raise PersistencePlanError(f"invalid persistence plan: {exc}") from exc
    snapshot = verified["snapshot"]
    effective = snapshot["effective_config"]
    storage = effective["storage"]
    cell = storage["expected_cells"][0]
    inputs = {"model": effective["model"]["parameters"],
              "search_grid": effective["grids"]["search"],
              "validation_grid": effective["grids"]["validation"]}
    run = create_experiment_run(
        effective["experiment_id"], effective_config=effective, scientific_inputs=inputs,
        expected_cells=storage["expected_cells"], source_sha=verified["execution_source_sha"],
        search_fe_limit=effective["optimizer"]["search_fe_limit"],
        validation_point_limit=len(inputs["validation_grid"]["points"]),
        review_context=effective["review_context"], run_id=verified["run_id"],
        data_root=data_root, required_free_bytes=storage["required_free_bytes"],
    )
    try:
        manifest = read_experiment_manifest(run.path)
        _equal(manifest["scientific_config_sha256"], snapshot["effective_config_sha256"], "R5 config hash")
        _equal(manifest["scientific_input_sha256"], snapshot["input_sha256"], "R5 input hashes")
        _equal(manifest["expected_cells"], storage["expected_cells"], "R5 roster")
        run.write_raw_artifact(f"cells/{cell['cell_id']}/configured_result.json", payload)
        if verified["cell_status"] == "FAILED":
            run.record_error(classification=verified["failure_class"], message=verified["reason"], cell_id=cell["cell_id"])
        counters = verified["result"]["search"]["counters"]
        run.record_cell(
            cell["cell_id"], status=verified["cell_status"],
            executed=bool(counters["search_evaluator_attempts"] or verified["search_fes"]),
            search_fes=verified["search_fes"], validation_points=verified["validation_points"],
            reason=verified["reason"], failure_class=verified["failure_class"],
            result={"classification": "TEST_ONLY / NOT_SCIENTIFIC_EVIDENCE",
                    "review_export": "VALIDATION_EVIDENCE_UNAVAILABLE"},
        )
        run.close(status=verified["cell_status"])
        return run.path
    except Exception as exc:
        try:
            run.record_error(classification=_incident_classification(exc), message=f"Test-only persistence incident: {type(exc).__name__}", cell_id=cell["cell_id"])
        except Exception as incident_exc:
            raise ExceptionGroup("persistence incident and failure recording incident", [exc, incident_exc]) from exc
        raise
