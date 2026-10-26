"""Pure scientific declaration validation; intentionally no execution imports.

See docs/scientific_config_v1.md for exact fields and canonical byte identity.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re
import stat
from typing import Any

from .cli_config import CliConfigError, _EXPERIMENT_ID_RE, _keys

SCHEMA_ID = "sawopt.scientific_config/1"
COMPARATOR = "sawopt.optimization.selection.FeasibilityFirstComparator"
VARIABLES = (
    ("wavelength_um", "um"), ("io_idt_pairs", "count"),
    ("center_idt_pairs", "count"), ("reflector_electrodes", "count"),
    ("idt_gap_lambda", "lambda"), ("reflector_gap_lambda", "lambda"),
    ("aperture_um", "um"),
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _object(value: Any, keys: str, location: str) -> dict:
    if not isinstance(value, dict):
        raise CliConfigError(f"{location} must be a mapping")
    _keys(value, set(keys.split()), location)
    return value


def _expect(value: Any, expected: Any, location: str) -> None:
    if type(value) is not type(expected) or value != expected:
        raise CliConfigError(f"{location} must be {expected!r}")


def _text(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CliConfigError(f"{location} must be nonempty text without surrounding whitespace")
    return value


def _slug(value: Any, location: str) -> None:
    if _EXPERIMENT_ID_RE.fullmatch(_text(value, location)) is None:
        raise CliConfigError(f"{location} must be an R5-safe lowercase slug")


def _hex(value: Any, location: str, *, source: bool = False) -> None:
    pattern = r"(?:[0-9a-f]{40}|[0-9a-f]{64})" if source else r"[0-9a-f]{64}"
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise CliConfigError(f"{location} must be a full lowercase {'Git ID' if source else 'SHA-256'}")


def _integer(value: Any, location: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise CliConfigError(f"{location} must be an integer >= {minimum}")
    return value


def _real(value: Any, location: str, *, minimum: float | None = None,
          positive: bool = False) -> float:
    if type(value) not in (int, float):
        raise CliConfigError(f"{location} must be a finite real number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise CliConfigError(f"{location} overflows binary64") from exc
    if not math.isfinite(result) or (minimum is not None and result < minimum) or (positive and result <= 0):
        raise CliConfigError(f"{location} is nonfinite or outside its supported range")
    return result


def _real_fields(value: dict, names: str, location: str, **options) -> None:
    for name in names.split():
        value[name] = _real(value[name], f"{location}.{name}", **options)


def _pair(value: Any, location: str, *, minimum: float = 0, positive: bool = False) -> list[float]:
    if not isinstance(value, list) or len(value) != 2:
        raise CliConfigError(f"{location} must be [lower, upper]")
    result = [_real(item, location, minimum=minimum, positive=positive) for item in value]
    if result[0] >= result[1]:
        raise CliConfigError(f"{location} must be strictly increasing")
    return result


def _model(payload: Any) -> dict:
    p = _object(payload, "reference_aperture_um idt reflector gap", "model.parameters")
    _real_fields(p, "reference_aperture_um", "model.parameters", positive=True)
    for region in ("idt", "reflector", "gap"):
        keys = "velocity_m_s loss_db_per_lambda"
        if region != "gap":
            keys += " kappa_lambda kappa_phase_rad alpha_sqrtS_per_m alpha_phase_rad capacitance_F_per_m"
        r = _object(p[region], keys, f"model.parameters.{region}")
        _real_fields(r, "velocity_m_s", region, positive=True)
        _real_fields(r, "loss_db_per_lambda", region, minimum=0)
        if region != "gap":
            _real_fields(r, "kappa_lambda alpha_sqrtS_per_m capacitance_F_per_m", region, minimum=0)
            _real_fields(r, "kappa_phase_rad alpha_phase_rad", region)
    return p


def _design(d: Any) -> None:
    _object(d, "topology decoder center wiring variables integer_indices fixed geometry", "design")
    _expect(d["topology"], "filter_design", "design.topology")
    _expect(d["decoder"], "sawopt.design.space.decode", "design.decoder")
    _expect(d["wiring"], "outer_ports", "design.wiring")
    if d["center"] not in ("grounded", "floating"):
        raise CliConfigError("design.center must be grounded or floating")
    indices = d["integer_indices"]
    if not isinstance(indices, list) or any(type(i) is not int for i in indices) or indices != [1, 2, 3]:
        raise CliConfigError("design.integer_indices must be [1, 2, 3]")
    variables = d["variables"]
    if not isinstance(variables, list) or len(variables) != len(VARIABLES):
        raise CliConfigError("design.variables must contain seven ordered variables")
    for i, (v, (name, unit)) in enumerate(zip(variables, VARIABLES, strict=True)):
        _object(v, "name unit bounds hard_bounds", f"design.variables[{i}]")
        _expect(v["name"], name, f"variable {i} name")
        _expect(v["unit"], unit, f"variable {i} unit")
        for field in ("bounds", "hard_bounds"):
            v[field] = _pair(v[field], f"{name}.{field}", positive=i in (0, 1, 2, 3, 6))
            if i in indices and any(not item.is_integer() or item < 1 for item in v[field]):
                raise CliConfigError(f"{name}.{field} must have positive integer endpoints")
        if v["bounds"][0] < v["hard_bounds"][0] or v["bounds"][1] > v["hard_bounds"][1]:
            raise CliConfigError(f"{name}.bounds must be inside hard_bounds")
    f = _object(d["fixed"], "metallization_ratio thickness_over_lambda", "design.fixed")
    _real_fields(f, "metallization_ratio thickness_over_lambda", "design.fixed", positive=True)
    # The named seven-variable decoder supplies these exact dataclass defaults.
    # Until a completed-design adapter is qualified, reject ignored declarations.
    _expect(f["metallization_ratio"], 0.5, "design.fixed.metallization_ratio")
    _expect(f["thickness_over_lambda"], 0.04, "design.fixed.thickness_over_lambda")
    g = _object(d["geometry"], "max_length_um max_width_um min_electrode_width_um min_electrode_gap_um max_electrodes", "design.geometry")
    _real_fields(g, "max_length_um max_width_um min_electrode_width_um min_electrode_gap_um", "design.geometry", positive=True)
    _integer(g["max_electrodes"], "geometry.max_electrodes", 1)


def _spec(s: Any) -> None:
    _object(s, "metric_contract frequency_unit passband stopbands il_db ripple_db vswr feasibility_tolerance comparator", "specification")
    _expect(s["metric_contract"], "sawopt.evaluation.measure", "specification.metric_contract")
    _expect(s["frequency_unit"], "MHz", "specification.frequency_unit")
    _expect(s["comparator"], COMPARATOR, "specification.comparator")
    _real_fields(s, "il_db ripple_db vswr feasibility_tolerance", "specification", positive=True)
    if s["vswr"] <= 1 or s["feasibility_tolerance"] != 1e-10:
        raise CliConfigError("specification requires vswr >1 and the existing 1e-10 feasibility tolerance")
    s["passband"] = _pair(s["passband"], "specification.passband", positive=True)
    if not isinstance(s["stopbands"], list) or not s["stopbands"]:
        raise CliConfigError("specification.stopbands must be a nonempty ordered list")
    bands = [s["passband"]]
    for index, band in enumerate(s["stopbands"]):
        if not isinstance(band, list) or len(band) != 3:
            raise CliConfigError("stopband must be [lower_MHz, upper_MHz, attenuation_dB]")
        pair = _pair(band[:2], "stopband frequencies", positive=True)
        s["stopbands"][index] = pair + [_real(band[2], "stopband attenuation", positive=True)]
        if any(pair[0] <= other[1] and other[0] <= pair[1] for other in bands):
            raise CliConfigError("passband and stopbands must be disjoint")
        bands.append(pair)


def _grid(g: Any, spec: dict) -> dict:
    _object(g, "kind unit points", "grid")
    _expect(g["kind"], "explicit_points", "grid.kind")
    _expect(g["unit"], "Hz", "grid.unit")
    points = g["points"]
    if not isinstance(points, list) or len(points) < 2:
        raise CliConfigError("grid.points needs at least two points")
    g["points"] = points = [_real(p, "grid point", positive=True) for p in points]
    if any(a >= b for a, b in zip(points, points[1:])):
        raise CliConfigError("grid points must be strictly increasing")
    # Match measure's Hz -> MHz inclusive masks; no grid construction/physics.
    for band, count in [(spec["passband"], 2), *[(b, 1) for b in spec["stopbands"]]]:
        if sum(band[0] <= p / 1e6 <= band[1] for p in points) < count:
            raise CliConfigError("grid lacks required passband/stopband samples")
    return g


def _optimizer(o: Any, resources: dict) -> None:
    _object(o, "name version seed rng comparator search_fe_limit proposal_policy checkpoint_policy settings", "optimizer")
    for key, expected in (("name", "lshade"), ("rng", "numpy.random.default_rng/PCG64"),
                          ("comparator", COMPARATOR), ("proposal_policy", "backend"),
                          ("checkpoint_policy", "disabled")):
        _expect(o[key], expected, f"optimizer.{key}")
    _hex(o["version"], "optimizer.version", source=True)
    _expect(o["version"], resources["source_commit_sha"], "optimizer.version")
    _integer(o["seed"], "optimizer.seed")
    budget = _integer(o["search_fe_limit"], "optimizer.search_fe_limit", 4)
    s = _object(o["settings"], "initial_population min_population history_size pbest_max_fraction archive_rate max_duplicate_retries total_budget hard_max_budget population_schedule_terminal_budget requested_unique_budget canonical_space_size compact_history_cache historical_finalist_count exhaustion_duplicate_streak memory_update_batch_size", "optimizer.settings")
    for key in ("initial_population", "min_population"):
        _integer(s[key], key, 4)
    if not s["min_population"] <= s["initial_population"] <= budget:
        raise CliConfigError("population must satisfy min <= initial <= search FE limit")
    for key in ("history_size", "historical_finalist_count"):
        _integer(s[key], key, 1)
    for key in ("max_duplicate_retries", "memory_update_batch_size"):
        _integer(s[key], key)
    for key in ("total_budget", "hard_max_budget", "population_schedule_terminal_budget", "requested_unique_budget"):
        _integer(s[key], key, 4)
        _expect(s[key], budget, key)
    _real_fields(s, "pbest_max_fraction", "optimizer.settings", positive=True)
    _real_fields(s, "archive_rate", "optimizer.settings", minimum=0)
    if s["pbest_max_fraction"] > 1:
        raise CliConfigError("pbest_max_fraction must be <=1")
    _expect(s["canonical_space_size"], None, "canonical_space_size")
    if type(s["compact_history_cache"]) is not bool:
        raise CliConfigError("compact_history_cache must be boolean")
    if s["exhaustion_duplicate_streak"] is not None:
        _integer(s["exhaustion_duplicate_streak"], "exhaustion_duplicate_streak", 1)


def _resources(r: Any) -> None:
    _object(r, "workers processes threads memory_bytes wall_time_seconds stop_policy source_commit_sha environment_sha256", "resources")
    for key in ("workers", "processes", "threads"):
        _integer(r[key], key, 1)
        _expect(r[key], 1, key)
    _integer(r["memory_bytes"], "resources.memory_bytes", 1)
    _real_fields(r, "wall_time_seconds", "resources", positive=True)
    _expect(r["stop_policy"], "fail_closed", "resources.stop_policy")
    _hex(r["source_commit_sha"], "resources.source_commit_sha", source=True)
    _hex(r["environment_sha256"], "resources.environment_sha256")


def _storage(s: Any, optimizer: dict) -> None:
    _object(s, "kind data_root_env required_free_bytes expected_cells", "storage")
    _expect(s["kind"], "r5_external", "storage.kind")
    _expect(s["data_root_env"], "SAWOPT_DATA_ROOT", "storage.data_root_env")
    _integer(s["required_free_bytes"], "storage.required_free_bytes", 1)
    cells = s["expected_cells"]
    if not isinstance(cells, list) or len(cells) != 1:
        raise CliConfigError("storage.expected_cells requires exactly one cell")
    c = _object(cells[0], "cell_id topology method seed", "expected cell")
    _slug(c["cell_id"], "cell_id")
    _expect(c["topology"], "filter_design", "cell.topology")
    _expect(c["method"], "lshade", "cell.method")
    _integer(c["seed"], "cell.seed")
    _expect(c["seed"], optimizer["seed"], "cell.seed")


def _review(r: Any) -> None:
    _object(r, "purpose conditions findings limitations review_instructions scientific_disposition requires_comparison requires_validation", "review_context")
    for key in ("purpose", "conditions", "limitations", "review_instructions"):
        _text(r[key], f"review_context.{key}")
    _expect(r["findings"], "NOT_EVALUATED: no experimental findings; declaration only.", "review_context.findings")
    _expect(r["scientific_disposition"], "CLAIM_PENDING_REVIEW", "scientific_disposition")
    _expect(r["requires_comparison"], False, "requires_comparison")
    _expect(r["requires_validation"], True, "requires_validation")


def _input(wrapper: Any, config_path: Path, name: str, references: dict) -> Any:
    if isinstance(wrapper, dict) and set(wrapper) == {"inline"}:
        return wrapper["inline"]
    _object(wrapper, "path sha256", name)
    path = _text(wrapper["path"], f"{name}.path")
    _hex(wrapper["sha256"], f"{name}.sha256")
    if "\\" in path or ":" in path or any(p in ("", ".", "..") for p in path.split("/")):
        raise CliConfigError(f"{name}.path must be a relative POSIX path without traversal")
    current = config_path.parent.resolve()
    try:
        for component in path.split("/"):
            current = current / component
            mode = current.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise CliConfigError(f"{name}.path has a symlink component")
        if not stat.S_ISREG(mode):
            raise CliConfigError(f"{name}.path must refer to a regular file")
        content = current.read_bytes()
    except OSError as exc:
        raise CliConfigError(f"{name} reference could not be read") from exc
    if hashlib.sha256(content).hexdigest() != wrapper["sha256"]:
        raise CliConfigError(f"{name} reference SHA-256 mismatch")
    references[name] = dict(wrapper)
    from .cli_config import parse_strict_yaml
    return parse_strict_yaml(content)


def resolve_scientific_config(config: Any, *, config_path: Path, config_bytes: bytes) -> dict[str, Any]:
    """Validate copied declarations and pinned files, without importing consumers."""
    c = copy.deepcopy(config)
    _object(c, "schema_id experiment_id model design specification ports grids optimizer resources storage review_context", "configuration")
    _expect(c["schema_id"], SCHEMA_ID, "schema_id")
    _slug(c["experiment_id"], "experiment_id")
    model = _object(c["model"], "kind material assumptions parameters", "model")
    _expect(model["kind"], "fixed", "model.kind")
    _text(model["material"], "model.material")
    _text(model["assumptions"], "model.assumptions")
    references: dict[str, dict] = {}
    model["parameters"] = _model(_input(model["parameters"], config_path, "model", references))
    _design(c["design"])
    _spec(c["specification"])
    ports = _object(c["ports"], "domain unit source load", "ports")
    _expect(ports["domain"], "positive_real", "ports.domain")
    _expect(ports["unit"], "ohm", "ports.unit")
    _real_fields(ports, "source load", "ports", positive=True)
    grids = _object(c["grids"], "search validation", "grids")
    for role in ("search", "validation"):
        grids[role] = _grid(_input(grids[role], config_path, f"{role}_grid", references), c["specification"])
    _resources(c["resources"])
    _optimizer(c["optimizer"], c["resources"])
    _storage(c["storage"], c["optimizer"])
    _review(c["review_context"])
    return {
        "status": "VALID", "schema_valid": True, "schema_id": SCHEMA_ID,
        "experiment_id": c["experiment_id"], "qualification": "NOT_EVALUATED",
        "run_authorized": False, "scientific_run_implemented": False,
        "effective_config": c, "effective_config_sha256": _digest(c),
        "config_file_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "input_sha256": {"model": _digest(model["parameters"]),
                         "search_grid": _digest(grids["search"]),
                         "validation_grid": _digest(grids["validation"])},
        "references": references,
    }


__all__ = ["SCHEMA_ID", "canonical_bytes", "resolve_scientific_config"]
