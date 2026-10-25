from sawopt.optimization import convergence_evidence as canonical
from sawopt.optimization.selection import FeasibilityFirstComparator, GeometryFirstComparator


def test_explicit_checkpoint_evidence_and_budget_overrides_have_fixed_output():
    record = {
        "requested_unique_design_budget": 8000,
        "terminal_budget": 16000,
        "grid_converged": False,
        "recovery_pending_confirmation": True,
        "boundary_pending_confirmation": False,
        "hard_bound_unresolved": False,
        "micro_polish_improvement": 0.0,
        "fraction_of_budget_at_last_significant_improvement": 0.75,
    }

    result = canonical.derive_checkpoint_evidence(
        record, current_budget=4000, terminal_budget=16000,
    )

    assert result == {
        "grid_converged": False,
        "recovery_pending_confirmation": True,
        "boundary_pending_confirmation": False,
        "hard_bound_unresolved": False,
        "micro_polish_improvement": 0.0,
        "fraction_of_budget_at_last_significant_improvement": 0.75,
        "current_budget": 4000,
        "terminal_budget": 16000,
        "missing_fields": [],
        "complete": True,
    }


def test_checkpoint_events_and_trace_fallback_have_fixed_output():
    record = {
        "requested_unique_design_budget": 100,
        "terminal_budget": 200,
        "frequency_grid_events": [
            {"checkpoint_budget": 50, "added_count": 1},
            {"checkpoint_budget": 100, "added_count": 0},
        ],
        "recovery_events": [{"budget": 50, "event": "recovery"}],
        "boundary_events": [
            {"budget": 50, "event": "boundary_pressure"},
            {"budget": 100, "event": "hard_bound_limited"},
        ],
        "hard_bound_reached_by_variable": {"reflector_pitch": True},
        "best_candidate_polish": {"improvement": 0.125},
        "best_so_far_trace": [
            {"unique_evaluation": 10, "primary_metric": 2.0,
             "primary_metric_feasible": False},
            {"unique_evaluation": 100, "primary_metric": 1.97,
             "primary_metric_feasible": False},
        ],
    }

    result = canonical.derive_checkpoint_evidence(record, current_budget=50)

    assert result == {
        "grid_converged": False,
        "recovery_pending_confirmation": True,
        "boundary_pending_confirmation": True,
        "hard_bound_unresolved": True,
        "micro_polish_improvement": 0.125,
        "fraction_of_budget_at_last_significant_improvement": 2.0,
        "current_budget": 50,
        "terminal_budget": 200,
        "missing_fields": [],
        "complete": True,
    }


def test_missing_telemetry_stays_unknown_and_missing_field_order_is_stable():
    result = canonical.derive_checkpoint_evidence({
        "requested_unique_design_budget": 64,
        "terminal_budget": 128,
    })

    assert result == {
        "grid_converged": None,
        "recovery_pending_confirmation": None,
        "boundary_pending_confirmation": None,
        "hard_bound_unresolved": None,
        "micro_polish_improvement": None,
        "fraction_of_budget_at_last_significant_improvement": None,
        "current_budget": 64,
        "terminal_budget": 128,
        "missing_fields": list(canonical.EVIDENCE_FIELDS),
        "complete": False,
    }


def test_applied_evidence_augments_record_without_dropping_source_fields():
    source = {
        "source_id": "fixture-17",
        "requested_unique_design_budget": 8,
        "terminal_budget": 16,
        "frequency_grid_events": [{"checkpoint_budget": 8, "grid_fixed": True}],
        "recovery_events": [],
        "boundary_events": [],
        "hard_bound_reached_by_variable": {},
        "micro_polish_improvement": 0.0,
        "fraction_of_budget_at_last_significant_improvement": 1.0,
    }

    result = canonical.apply_checkpoint_evidence(source, current_budget=8)

    assert result["source_id"] == "fixture-17"
    assert result["grid_converged"] is True
    assert result["recovery_pending_confirmation"] is False
    assert result["boundary_pending_confirmation"] is False
    assert result["hard_bound_unresolved"] is False
    assert result["micro_polish_improvement"] == 0.0
    assert result["fraction_of_budget_at_last_significant_improvement"] == 1.0
    assert result["convergence_evidence_complete"] is True
    assert result["convergence_evidence_missing_fields"] == []


def _infeasible_trace_record(max_violation):
    return {
        "evaluation_status": "PHYSICS_EVALUATED",
        "feasible": False,
        "max_violation": max_violation,
        "sum_violation": max_violation,
        "metrics": {"worst_il_db": 8.0, "ripple_db": 2.0},
        "violations": {"filter": max_violation},
    }


def _feasible_trace_record(worst_il=7.0):
    return {
        "evaluation_status": "PHYSICS_EVALUATED",
        "feasible": True,
        "max_violation": 0.0,
        "sum_violation": 0.0,
        "metrics": {"worst_il_db": worst_il, "ripple_db": 2.0},
        "violations": {"filter": 0.0},
    }


def _trace_row(record, comparator, unique_evaluation):
    return {
        "unique_evaluation": unique_evaluation,
        "rank_key": list(comparator.rank_key(record)),
        "comparator": type(comparator).__name__,
        "primary_metric": comparator.primary_metric(record),
        "primary_metric_feasible": bool(record["feasible"]),
    }


def test_geometry_first_primary_metric_handles_evaluation_and_geometry_states():
    comparator = GeometryFirstComparator()
    feasible = _feasible_trace_record()
    infeasible = _infeasible_trace_record(0.4)
    rejected = {
        "evaluation_status": "GEOMETRY_REJECTED",
        "geometry_violations": {"max_total_length": 0.1},
    }
    failed = {"evaluation_status": "PHYSICS_FAILED"}

    assert comparator.rank_key(feasible) == (0.0, 0.0, 0.0, 7.0, 2.0, 0.0, 0.0)
    assert comparator.primary_metric(feasible) == 7.0
    assert comparator.primary_metric(infeasible) == 0.4
    assert comparator.primary_metric(rejected) is None
    assert comparator.primary_metric(failed) is None
    assert comparator.rank_key(rejected) == (1.0, 0.0, 0.1, 0.1, 0.0, 0.0, 0.0)
    assert comparator.rank_key(failed) == (
        0.0, 1.0, float("inf"), float("inf"), float("inf"), float("inf"), float("inf")
    )
    assert comparator.better(feasible, rejected)
    assert comparator.better(failed, rejected)
    assert canonical._trace_primary({
        "comparator": "GeometryFirstComparator",
        "rank_key": list(comparator.rank_key(rejected)),
        "primary_metric": comparator.primary_metric(rejected),
    }) is None
    assert canonical._trace_primary({
        "comparator": "GeometryFirstComparator",
        "rank_key": list(comparator.rank_key(failed)),
        "primary_metric": comparator.primary_metric(failed),
    }) is None


def test_feasibility_transition_and_within_regime_thresholds_for_current_traces():
    infeasible = _infeasible_trace_record(0.4)
    feasible_8 = _feasible_trace_record(8.0)
    feasible_799 = _feasible_trace_record(7.99)
    feasible_797 = _feasible_trace_record(7.97)
    feasible_789 = _feasible_trace_record(7.89)

    for comparator in (FeasibilityFirstComparator(), GeometryFirstComparator()):
        trace = [
            _trace_row(infeasible, comparator, 100),
            _trace_row(feasible_8, comparator, 200),
            _trace_row(feasible_799, comparator, 300),
            _trace_row(feasible_797, comparator, 400),
            _trace_row(feasible_789, comparator, 800),
        ]

        # Infeasible -> feasible is significant despite a numerically larger
        # scalar; a sub-threshold same-regime change is not.
        assert canonical._last_significant_fraction(trace[:2], 1000) == 0.2
        assert canonical._last_significant_fraction(trace[:3], 1000) == 0.2
        # Same-regime absolute (0.03) and relative (>1%) improvements continue
        # to use the existing thresholds.
        assert canonical._last_significant_fraction(trace[:4], 1000) == 0.4
        assert canonical._last_significant_fraction(trace, 1000) == 0.8
