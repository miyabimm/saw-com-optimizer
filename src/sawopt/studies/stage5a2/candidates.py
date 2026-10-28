"""Strict Q0 candidate validation, physics-free and before comparator access."""
from __future__ import annotations

import math

import numpy as np

from .initialization import canonical_key_tokens

SCHEMA = "stage5a2_candidate_record_v1"
FIELDS = frozenset("""schema_id schema_version evaluation_phase evaluation_status topology
candidate_key candidate_vector first_evaluation_ordinal grid_sha256 geometry_valid
geometry_dimensions geometry_violations metrics violations filter_metrics_available
feasible max_violation sum_violation objective source_impedance_ohm load_impedance_ohm
failure_stage failure_code failure_message""".split())
METRICS = frozenset("""worst_il_db ripple_db input_vswr output_vswr
source_return_loss_db_min load_return_loss_db_min stop_attenuation_db""".split())
VIOLATIONS = frozenset(("il", "ripple", "input_vswr", "output_vswr", *(f"stop_{i}" for i in range(4))))


class InvalidCandidate(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise InvalidCandidate(message)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_candidate(record, *, vector, ordinal, topology, grid_sha256):
    _require(type(record) is dict, "candidate must be a plain mapping")
    _require(set(record) in (FIELDS, FIELDS | {"diagnostics"}), "candidate fields differ from Q0 schema")
    _require(record["schema_id"] == SCHEMA and type(record["schema_version"]) is int
             and record["schema_version"] == 1, "candidate schema/version mismatch")
    _require(record["evaluation_phase"] == "search", "search boundary rejects validation records")
    _require(record["topology"] == topology and record["grid_sha256"] == grid_sha256, "evaluation identity mismatch")
    _require(type(record["first_evaluation_ordinal"]) is int
             and record["first_evaluation_ordinal"] == ordinal, "first ordinal mismatch")
    candidate = np.asarray(record["candidate_vector"], dtype=float)
    _require(candidate.shape == (13,) and np.isfinite(candidate).all(), "invalid candidate vector")
    _require(candidate.tobytes() == np.asarray(vector, dtype=float).tobytes(), "candidate vector bits mismatch")
    _require(tuple(record["candidate_key"]) == canonical_key_tokens(candidate), "candidate key mismatch")
    for field in ("geometry_valid", "filter_metrics_available", "feasible"):
        _require(type(record[field]) is bool, f"{field} must be bool")
    for field in ("geometry_dimensions", "geometry_violations", "metrics", "violations"):
        _require(type(record[field]) is dict, f"{field} must be mapping")
    for field in ("geometry_dimensions", "geometry_violations"):
        _require(all(type(k) is str and _finite(v) for k, v in record[field].items()), f"{field} must be finite")
    _require(record["source_impedance_ohm"] == 50. and record["load_impedance_ohm"] == 50., "Q0 ports differ")
    status = record["evaluation_status"]
    _require(status in {"PHYSICS_EVALUATED", "PHYSICS_FAILED", "GEOMETRY_REJECTED"}, "unknown evaluation status")
    geometry = record["geometry_violations"]
    if status == "PHYSICS_EVALUATED":
        _require(record["geometry_valid"] and all(v <= 0. for v in geometry.values()), "evaluated geometry inconsistent")
        _require(record["filter_metrics_available"] and set(record["metrics"]) == METRICS, "metrics missing/unknown")
        metrics = record["metrics"]
        _require(all(_finite(v) for k, v in metrics.items() if k != "stop_attenuation_db"), "metrics nonfinite")
        stop = metrics["stop_attenuation_db"]
        _require(type(stop) in (list, tuple) and len(stop) == 4 and all(_finite(v) for v in stop), "stop metrics invalid")
        violations = record["violations"]
        _require(set(violations) == VIOLATIONS and all(_finite(v) for v in violations.values()), "violations invalid")
        positive = [max(0., v) for v in violations.values()]
        _require(all(_finite(record[k]) for k in ("max_violation", "sum_violation", "objective")), "summary nonfinite")
        _require(record["max_violation"] == max(positive) and record["sum_violation"] == sum(positive), "violation summary inconsistent")
        _require(record["feasible"] == (max(positive) <= 1e-10), "feasible inconsistent")
        _require(all(record[k] is None for k in ("failure_stage", "failure_code", "failure_message")), "success has failure")
    else:
        _require(not record["metrics"] and not record["violations"]
                 and not record["filter_metrics_available"] and not record["feasible"], "failure has filter data")
        _require(all(record[k] is None for k in ("max_violation", "sum_violation", "objective")), "failure numeric fields must be absent")
        _require(type(record["failure_code"]) is str and bool(record["failure_code"])
                 and type(record["failure_message"]) is str, "failure code/message required")
        if status == "GEOMETRY_REJECTED":
            _require(not record["geometry_valid"] and max(geometry.values(), default=0.) > 0.
                     and record["failure_stage"] == "geometry", "geometry rejection inconsistent")
        else:
            _require(record["failure_code"] in {"NONFINITE_GAIN", "NONPASSIVE_GAIN", "NONFINITE_METRICS",
                                                "INCOMPLETE_METRICS", "LINALG_ERROR", "FLOATING_POINT_ERROR", "OVERFLOW_ERROR"},
                     "unrecognized modeled numerical failure code")
            _require(record["geometry_valid"] and all(v <= 0. for v in geometry.values())
                     and record["failure_stage"] == "physics", "modeled failure geometry/stage inconsistent")
    if "diagnostics" in record:
        _require(type(record["diagnostics"]) is dict and record["diagnostics"].get("schema_version") == 1,
                 "diagnostics must be versioned")
    return record
