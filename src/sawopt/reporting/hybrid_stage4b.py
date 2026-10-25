"""Integrity checks and matched-seed summaries for Stage 4B."""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..studies.hybrid_stage4b import (
    AUTHORIZATION_SCOPE,
    BUDGET,
    CHECKPOINTS,
    FINALIST_COUNT,
    PROTOCOL_REVISION,
    SEEDS,
    TOPOLOGIES,
    _cell_paths,
    _expected_matrix,
)


def _metric(result: Mapping[str, Any] | None, name: str) -> float | None:
    if not isinstance(result, Mapping):
        return None
    value = result.get("metrics", {}).get(name)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def validate_production_matrix(run_directory: str | Path, context: Mapping[str, Any]) -> dict[str, Any]:
    """Check exact cell coverage, budgets, grids, fingerprints, and accounting."""
    run = Path(run_directory)
    batch_manifest_path = run / "metadata" / "stage4b_run_manifest.json"
    issues: list[str] = []
    if not batch_manifest_path.is_file():
        return {"status": "FAIL", "complete": False, "issues": ["missing Stage 4B run manifest"],
                "cells_present": 0, "cells_completed": 0, "cells": []}
    batch_manifest = json.loads(batch_manifest_path.read_text(encoding="utf-8"))
    if batch_manifest.get("protocol_revision") != PROTOCOL_REVISION:
        issues.append("protocol revision mismatch")
    if batch_manifest.get("mode") != "production":
        issues.append("run mode is not production")
    if batch_manifest.get("computation_fingerprint") != context["fingerprint"]["computation_fingerprint"]:
        issues.append("batch fingerprint mismatch")
    if batch_manifest.get("source_commit_sha") != _read_parent_source_sha(run):
        issues.append("batch/source manifest SHA mismatch")
    if batch_manifest.get("authorization_scope") != AUTHORIZATION_SCOPE:
        issues.append("authorization scope mismatch")
    if batch_manifest.get("user_authorized_production") is not True:
        issues.append("user authorization not recorded")
    if batch_manifest.get("codex_session_id") in (None, ""):
        issues.append("captured Codex session missing")
    if batch_manifest.get("callback_enabled") is not True or batch_manifest.get("review_after_completion") is not True:
        issues.append("completion callback flags mismatch")
    if batch_manifest.get("budget_per_cell") != BUDGET:
        issues.append("batch budget mismatch")
    if batch_manifest.get("population_schedule_terminal_budget") != BUDGET:
        issues.append("batch terminal horizon mismatch")
    if batch_manifest.get("checkpoints") != list(CHECKPOINTS):
        issues.append("batch checkpoint lattice mismatch")
    if batch_manifest.get("seeds") != list(SEEDS) or batch_manifest.get("topologies") != list(TOPOLOGIES):
        issues.append("batch seed/topology matrix mismatch")
    expected_matrix = _expected_matrix()
    if batch_manifest.get("matrix") != expected_matrix:
        issues.append("batch 20-cell matrix mismatch")

    rows: list[dict[str, Any]] = []
    present = completed = 0
    fingerprints: set[str] = set()
    grids: set[str] = set()
    seen_topologies: set[str] = set()
    seen_seeds: set[int] = set()
    for expected in expected_matrix:
        topology, seed = expected["topology"], int(expected["seed"])
        cell, cell_manifest_path, result_path = _cell_paths(run, topology, seed)
        if not result_path.is_file():
            issues.append(f"missing cell result {topology}/seed{seed}")
            continue
        present += 1
        result = json.loads(result_path.read_text(encoding="utf-8"))
        rows.append(result)
        if result.get("status") != "COMPLETED":
            issues.append(f"cell not completed: {topology}/seed{seed}")
            continue
        completed += 1
        seen_topologies.add(str(result.get("topology")))
        seen_seeds.add(int(result.get("seed", -1)))
        fingerprints.add(str(result.get("computation_fingerprint")))
        grids.add(str(result.get("common_validation_grid_id")))
        for key, value in expected.items():
            if result.get(key) != value:
                issues.append(f"cell contract mismatch {topology}/seed{seed}: {key}")
        if not cell_manifest_path.is_file():
            issues.append(f"missing cell manifest {topology}/seed{seed}")
        elif json.loads(cell_manifest_path.read_text(encoding="utf-8")) != {
            key: result.get(key) for key in json.loads(cell_manifest_path.read_text(encoding="utf-8"))
        }:
            issues.append(f"cell manifest/result mismatch {topology}/seed{seed}")
        if int(result.get("unique_evaluations", -1)) != BUDGET:
            issues.append(f"unique evaluation budget mismatch {topology}/seed{seed}")
        counters = result.get("counters", {})
        if int(counters.get("unique_decoded_evaluations", -1)) != BUDGET:
            issues.append(f"counter budget mismatch {topology}/seed{seed}")
        if int(counters.get("unique_decoded_evaluations", -1)) != (
            int(counters.get("geometry_rejections", 0)) + int(counters.get("geometry_valid_candidates", 0))
        ):
            issues.append(f"unique geometry accounting mismatch {topology}/seed{seed}")
        if int(counters.get("geometry_valid_candidates", -1)) != (
            int(counters.get("valid_physics_evaluations", 0)) + int(counters.get("physics_failures", 0))
        ):
            issues.append(f"geometry/physics accounting mismatch {topology}/seed{seed}")
        if int(counters.get("physics_attempted_evaluations", -1)) != (
            int(counters.get("valid_physics_evaluations", 0)) + int(counters.get("physics_failures", 0))
        ):
            issues.append(f"physics-attempt accounting mismatch {topology}/seed{seed}")
        if int(counters.get("search_frequency_points", -1)) != (
            int(counters.get("valid_physics_evaluations", 0)) * 1001
        ):
            issues.append(f"search-grid accounting mismatch {topology}/seed{seed}")
        if int(counters.get("validation_evaluations", -1)) != FINALIST_COUNT * len(CHECKPOINTS):
            issues.append(f"common-grid finalist count mismatch {topology}/seed{seed}")
        if int(counters.get("validation_frequency_points", -1)) != (
            int(counters.get("validation_evaluations", 0))
            - int(counters.get("validation_physics_failures", 0))
        ) * 9113:
            issues.append(f"common-grid frequency accounting mismatch {topology}/seed{seed}")
        if int(result.get("population_schedule_terminal_budget", -1)) != BUDGET:
            issues.append(f"cell terminal horizon mismatch {topology}/seed{seed}")
        if result.get("cold_start") is not True or any(
            result.get(key) is not False for key in (
                "warm_start", "parent_transfer", "topology_transfer", "historical_population_injection",
            )
        ):
            issues.append(f"warm/historical initialization detected {topology}/seed{seed}")
        if result.get("computation_fingerprint") != context["fingerprint"]["computation_fingerprint"]:
            issues.append(f"cell fingerprint mismatch {topology}/seed{seed}")
        if result.get("common_validation_grid_id") != context["common_grid_id"]:
            issues.append(f"cell common-grid identity mismatch {topology}/seed{seed}")
        if result.get("checkpoint_records") != list(CHECKPOINTS):
            issues.append(f"checkpoint disposition mismatch {topology}/seed{seed}")
        checkpoint_files = [cell / f"B{point}.json" for point in CHECKPOINTS]
        if not all(path.is_file() for path in checkpoint_files):
            issues.append(f"checkpoint summary missing {topology}/seed{seed}")
        else:
            for point, path in zip(CHECKPOINTS, checkpoint_files):
                item = json.loads(path.read_text(encoding="utf-8"))
                expected_validation = FINALIST_COUNT * (CHECKPOINTS.index(point) + 1)
                if (int(item.get("checkpoint_budget", -1)) != point
                        or item.get("computation_fingerprint") != context["fingerprint"]["computation_fingerprint"]
                        or int(item.get("counters", {}).get("unique_decoded_evaluations", -1)) != point
                        or int(item.get("counters", {}).get("validation_evaluations", -1)) != expected_validation):
                    issues.append(f"checkpoint evidence mismatch {topology}/seed{seed}/B{point}")

    if present != 20:
        issues.append(f"expected 20 cells present; found {present}")
    if completed != 20:
        issues.append(f"expected 20 completed cells; found {completed}")
    if seen_topologies != set(TOPOLOGIES) or seen_seeds != set(SEEDS):
        issues.append("topology or seed missing from completed matrix")
    if len(fingerprints) > 1 or (fingerprints and fingerprints != {context["fingerprint"]["computation_fingerprint"]}):
        issues.append("cell computation fingerprints are not identical")
    if len(grids) > 1 or (grids and grids != {context["common_grid_id"]}):
        issues.append("cell common-grid identities are not identical")
    return {
        "status": "PASS" if not issues else "FAIL",
        "complete": not issues and present == 20 and completed == 20,
        "cells_expected": 20,
        "cells_present": present,
        "cells_completed": completed,
        "topologies_present": sorted(seen_topologies),
        "seeds_present": sorted(seen_seeds),
        "computation_fingerprints": sorted(fingerprints),
        "common_grid_ids": sorted(grids),
        "issues": list(dict.fromkeys(issues)),
        "cells": rows,
    }


def _read_parent_source_sha(run: Path) -> str | None:
    parent_manifest = run / "metadata" / "orchestration_run_manifest.json"
    if not parent_manifest.is_file():
        return None
    try:
        metadata = json.loads(parent_manifest.read_text(encoding="utf-8")).get("experiment_metadata", {})
        return metadata.get("source_commit_sha")
    except (OSError, ValueError, TypeError):
        return None


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    return float(np.percentile(values, percentile)) if values else None


def summarize_topologies(cells: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for topology in TOPOLOGIES:
        group = [row for row in cells if row.get("topology") == topology]
        selected = [row.get("common_grid_selected_finalist") for row in group]
        valid = [row for row in selected if isinstance(row, Mapping)]
        scorable = []
        for row in valid:
            try:
                score = (float(row["max_violation"]), float(row["sum_violation"]),
                         float(row["metrics"]["worst_il_db"]))
            except (KeyError, TypeError, ValueError):
                continue
            if all(math.isfinite(value) for value in score):
                scorable.append((row, score))
        max_values = [score[0] for _, score in scorable]
        sum_values = [score[1] for _, score in scorable]
        il_values = [score[2] for _, score in scorable]
        ripple_values = [value for row in valid if (value := _metric(row, "ripple_db")) is not None]
        dominant = Counter()
        for row in valid:
            violations = row.get("violations", {})
            if violations:
                key, value = max(violations.items(), key=lambda item: float(item[1]))
                if float(value) > 0:
                    dominant[str(key)] += 1
        failures = sum(int(row.get("physics_failures", 0)) + int(row.get("validation_physics_failures", 0))
                       for row in group)
        geometry_rejections = sum(int(row.get("geometry_rejections", 0)) for row in group)
        cache_hits = sum(int(row.get("cache_statistics", {}).get("cache_hits", 0)) for row in group)
        feasible = sum(bool(row.get("feasible")) for row in valid)
        result.append({
            "topology": topology,
            "completed_seeds": sum(row.get("status") == "COMPLETED" for row in group),
            "valid_finalist_seeds": len(scorable),
            "feasible_seeds": feasible,
            "median_max_violation": float(np.median(max_values)) if max_values else None,
            "min_max_violation": min(max_values) if max_values else None,
            "max_max_violation": max(max_values) if max_values else None,
            "iqr_max_violation": (_percentile(max_values, 75) - _percentile(max_values, 25)) if max_values else None,
            "iqr_sum_violation": (_percentile(sum_values, 75) - _percentile(sum_values, 25)) if sum_values else None,
            "iqr_worst_il_db": (_percentile(il_values, 75) - _percentile(il_values, 25)) if il_values else None,
            "median_sum_violation": float(np.median(sum_values)) if sum_values else None,
            "median_worst_il_db": float(np.median(il_values)) if il_values else None,
            "median_ripple_db": float(np.median(ripple_values)) if ripple_values else None,
            "dominant_violations": json.dumps(dominant.most_common(), ensure_ascii=False),
            "physics_and_validation_failures": failures,
            "geometry_rejections": geometry_rejections,
            "cache_hits": cache_hits,
        })
    return result


def paired_comparisons(cells: Sequence[Mapping[str, Any]], *,
                       seed_labels: Sequence[int] = SEEDS) -> list[dict[str, Any]]:
    by_key = {(row.get("topology"), int(row.get("seed", -1))): row for row in cells}
    rows = []
    metrics = (
        ("max_violation", lambda cell: (cell or {}).get("max_violation")),
        ("sum_violation", lambda cell: (cell or {}).get("sum_violation")),
        ("worst_il_db", lambda cell: _metric(cell, "worst_il_db")),
        ("ripple_db", lambda cell: _metric(cell, "ripple_db")),
    )
    for left_index, left in enumerate(TOPOLOGIES):
        for right in TOPOLOGIES[left_index + 1:]:
            for seed in seed_labels:
                left_cell = by_key.get((left, seed), {}).get("common_grid_selected_finalist")
                right_cell = by_key.get((right, seed), {}).get("common_grid_selected_finalist")
                row: dict[str, Any] = {"topology_left": left, "topology_right": right, "seed": seed}
                for name, getter in metrics:
                    try:
                        a, b = getter(left_cell), getter(right_cell)
                        row[f"delta_{name}_left_minus_right"] = float(a) - float(b) if a is not None and b is not None else None
                    except (TypeError, ValueError):
                        row[f"delta_{name}_left_minus_right"] = None
                def lexicographic_score(cell):
                    if not isinstance(cell, Mapping):
                        return None
                    try:
                        score = (
                            float(cell["max_violation"]),
                            float(cell["sum_violation"]),
                            float(cell["metrics"]["worst_il_db"]),
                        )
                    except (KeyError, TypeError, ValueError):
                        return None
                    return score if all(math.isfinite(value) for value in score) else None
                left_score, right_score = lexicographic_score(left_cell), lexicographic_score(right_cell)
                row["lexicographic_winner"] = (
                    "INDETERMINATE" if left_score is None or right_score is None else
                    "TIE" if left_score == right_score else
                    left if left_score < right_score else right
                )
                rows.append(row)
    return rows


def convergence_rows(cells: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for cell in cells:
        for checkpoint in cell.get("checkpoint_summaries", ()):
            rows.append({
                "topology": cell.get("topology"), "seed": cell.get("seed"),
                **checkpoint,
                "computation_fingerprint": cell.get("computation_fingerprint"),
            })
    return rows


def bound_pressure_rows(cells: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str]] = Counter()
    for cell in cells:
        for row in cell.get("active_bound_diagnostics", ()):
            if row.get("at_lower_bound"):
                counts[(str(row.get("variable")), "lower")] += 1
            if row.get("at_upper_bound"):
                counts[(str(row.get("variable")), "upper")] += 1
    variables = sorted({variable for variable, _ in counts})
    return [{
        "variable": variable,
        "lower_bound_hits": counts[(variable, "lower")],
        "upper_bound_hits": counts[(variable, "upper")],
        "total_bound_hits": counts[(variable, "lower")] + counts[(variable, "upper")],
    } for variable in variables]


def runtime_rows(cells: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "topology": cell.get("topology"), "seed": cell.get("seed"),
        "unique_evaluations": cell.get("unique_evaluations"),
        "search_frequency_points": cell.get("counters", {}).get("search_frequency_points"),
        "validation_evaluations": cell.get("counters", {}).get("validation_evaluations"),
        "validation_frequency_points": cell.get("counters", {}).get("validation_frequency_points"),
        "geometry_rejections": cell.get("geometry_rejections"),
        "physics_failures": cell.get("physics_failures"),
        "validation_physics_failures": cell.get("validation_physics_failures"),
        "cache_hits": cell.get("cache_statistics", {}).get("cache_hits"),
        "search_evaluation_wall_time_s": cell.get("runtime", {}).get("search_evaluation_wall_time_s"),
        "common_validation_wall_time_s": cell.get("runtime", {}).get("common_validation_wall_time_s"),
        "cell_wall_time_s": cell.get("runtime", {}).get("cell_wall_time_s"),
    } for cell in cells]


def symmetry_sanity(cells: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_seed = {(row.get("topology"), int(row.get("seed", -1))): row for row in cells}
    pairs = []
    for seed in SEEDS:
        pd_cell = by_seed.get(("P_D", seed), {}).get("common_grid_selected_finalist")
        dp_cell = by_seed.get(("D_P", seed), {}).get("common_grid_selected_finalist")
        pd_il, dp_il = _metric(pd_cell, "worst_il_db"), _metric(dp_cell, "worst_il_db")
        pairs.append({
            "seed": seed,
            "p_d_worst_il_db": pd_il,
            "d_p_worst_il_db": dp_il,
            "delta_p_d_minus_d_p_db": None if pd_il is None or dp_il is None else pd_il - dp_il,
            "p_d_max_violation": None if not isinstance(pd_cell, Mapping) else pd_cell.get("max_violation"),
            "d_p_max_violation": None if not isinstance(dp_cell, Mapping) else dp_cell.get("max_violation"),
            "p_d_feasible": None if not isinstance(pd_cell, Mapping) else pd_cell.get("feasible"),
            "d_p_feasible": None if not isinstance(dp_cell, Mapping) else dp_cell.get("feasible"),
        })
    deltas = [row["delta_p_d_minus_d_p_db"] for row in pairs]
    pd_values = [row["p_d_worst_il_db"] for row in pairs]
    dp_values = [row["d_p_worst_il_db"] for row in pairs]
    if any(value is None for value in (*deltas, *pd_values, *dp_values)):
        status = "INDETERMINATE"
        warning = False
        rationale = "At least one selected finalist lacks a finite common-grid worst passband IL."
        pd_span = dp_span = median_delta = None
    else:
        signs = [1 if value > 1e-12 else -1 if value < -1e-12 else 0 for value in deltas]
        pd_span = float(max(pd_values) - min(pd_values))
        dp_span = float(max(dp_values) - min(dp_values))
        median_delta = float(np.median(deltas))
        same_nonzero_sign = all(sign == signs[0] and sign != 0 for sign in signs)
        threshold = max(pd_span, dp_span)
        warning = bool(same_nonzero_sign and abs(median_delta) > threshold)
        status = "SYMMETRY_SANITY_WARNING" if warning else "PASS"
        rationale = (
            "All five paired IL deltas have one nonzero sign and the absolute median delta exceeds "
            "the larger within-topology five-seed IL span."
            if warning else
            "The predeclared direction-and-seed-span warning rule did not trigger."
        )
    return {
        "status": status,
        "warning": warning,
        "metric": "common-grid selected finalist worst passband insertion loss (dB)",
        "pairing": "matched seed labels; delta = P_D - D_P",
        "criterion": "all five deltas share one nonzero sign and abs(median(delta)) exceeds max(P_D IL span, D_P IL span)",
        "p_d_seed_span_db": pd_span,
        "d_p_seed_span_db": dp_span,
        "median_delta_db": median_delta,
        "seed_pairs": pairs,
        "corroborating_diagnostics": "Per-seed common-grid maximum violation and feasibility are reported separately; they do not suppress this flag.",
        "interpretation_limit": "A warning describes separation in these optimizer results; it does not prove a physical symmetry failure or topology superiority. Five seeds do not establish an absolute engineering threshold.",
        "rationale": rationale,
    }


def _classify(summary: Sequence[Mapping[str, Any]], paired: Sequence[Mapping[str, Any]],
              integrity_complete: bool) -> dict[str, Any]:
    if not integrity_complete:
        return {"classification": "STAGE4B_INCONCLUSIVE", "primary": None, "fallback": None,
                "rationale": "The 20-cell integrity gate failed; topology ranking is prohibited."}
    usable = [row for row in summary
              if row.get("median_max_violation") is not None
              and row.get("median_sum_violation") is not None
              and row.get("median_worst_il_db") is not None
              and int(row.get("valid_finalist_seeds", 0)) == len(SEEDS)]
    if len(usable) != len(TOPOLOGIES):
        return {"classification": "STAGE4B_INCONCLUSIVE", "primary": None, "fallback": None,
                "rationale": "At least one topology lacks five finite common-grid selected finalists."}
    ordered = sorted(usable, key=lambda row: (
        row["median_max_violation"],
        float("inf") if row.get("median_sum_violation") is None else row["median_sum_violation"],
        float("inf") if row.get("median_worst_il_db") is None else row["median_worst_il_db"],
    ))
    candidate = ordered[0]["topology"]
    def wins(topology: str, opponents: Sequence[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for opponent in opponents:
            wins_count = 0
            for seed in SEEDS:
                pair = next((row for row in paired if row.get("seed") == seed and {
                    row.get("topology_left"), row.get("topology_right")
                } == {topology, opponent}), None)
                if pair is not None and pair.get("lexicographic_winner") == topology:
                    wins_count += 1
            counts[opponent] = wins_count
        return counts

    primary_wins = wins(candidate, [name for name in TOPOLOGIES if name != candidate])
    fallback = ordered[1]["topology"]
    fallback_wins = wins(fallback, [name for name in TOPOLOGIES if name not in {candidate, fallback}])
    if all(value >= 4 for value in primary_wins.values()) and all(value >= 4 for value in fallback_wins.values()):
        return {
            "classification": "STAGE4B_PRIMARY_AND_FALLBACK_IDENTIFIED",
            "primary": candidate,
            "fallback": fallback,
            "rationale": "Primary and fallback each have at least four of five strict matched-seed lexicographic wins against every remaining competitor; exact ties do not count as wins.",
            "paired_wins_vs_each_alternative": primary_wins,
            "fallback_paired_wins_vs_remaining": fallback_wins,
            "paired_metric_order": ["max normalized violation", "sum normalized violation", "worst passband IL"],
        }

    fields = ("median_max_violation", "median_sum_violation", "median_worst_il_db")
    selected_metric_index = next((index for index, field in enumerate(fields)
                                  if len({float(row[field]) for row in ordered}) > 1), None)
    if selected_metric_index is None:
        shortlist = [row["topology"] for row in ordered]
        margin = 0.0
        selected_metric = "all paired median metrics tie"
    else:
        selected_metric = fields[selected_metric_index]
        if selected_metric_index == 0:
            observed_iqrs = [float(row.get("iqr_max_violation") or 0.0) for row in ordered]
        elif selected_metric_index == 1:
            observed_iqrs = [float(row.get("iqr_sum_violation") or 0.0) for row in ordered]
        else:
            observed_iqrs = [float(row.get("iqr_worst_il_db") or 0.0) for row in ordered]
        margin = max(observed_iqrs)
        leader_value = float(ordered[0][selected_metric])
        shortlist = [row["topology"] for row in ordered
                     if float(row[selected_metric]) <= leader_value + margin]
    if len(shortlist) >= 2:
        return {
            "classification": "STAGE4B_SHORTLIST_IDENTIFIED",
            "primary": None,
            "fallback": None,
            "shortlist": shortlist,
            "shortlist_metric": selected_metric,
            "shortlist_margin": margin,
            "quartile_convention": "NumPy percentile method=linear (Hyndman-Fan type 7); descriptive seed spread, not a confidence interval.",
            "rationale": "No primary/fallback pair met the strict paired gate; every topology within the maximum observed five-seed IQR of the leader on the first discriminating median metric is included.",
            "paired_wins_vs_each_alternative": primary_wins,
            "fallback_paired_wins_vs_remaining": fallback_wins,
            "paired_metric_order": ["max normalized violation", "sum normalized violation", "worst passband IL"],
        }
    return {
        "classification": "STAGE4B_INCONCLUSIVE", "primary": None, "fallback": None,
        "rationale": "Matched-seed evidence does not meet the strict paired primary/fallback gates, and the IQR-based rule does not retain multiple topologies; review metric conflicts and failures before proposing a shortlist.",
        "paired_wins_vs_each_alternative": primary_wins,
        "fallback_paired_wins_vs_remaining": fallback_wins,
        "paired_metric_order": ["max normalized violation", "sum normalized violation", "worst passband IL"],
    }


__all__ = [
    "bound_pressure_rows", "convergence_rows", "paired_comparisons",
    "runtime_rows", "summarize_topologies", "symmetry_sanity",
    "validate_production_matrix",
]
