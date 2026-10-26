"""Strict configuration for the R6 synthetic-only CLI slice."""
from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml


class CliConfigError(ValueError):
    """CLI input is malformed or requests behavior outside the synthetic slice."""


_ROOT_KEYS = {
    "schema_version", "experiment_id", "seed", "search_fe_limit",
    "required_free_bytes", "design", "model", "search_grid",
    "validation_grid", "optimizer", "review_context",
}
_REVIEW_KEYS = {
    "purpose", "conditions", "findings", "limitations", "review_instructions",
    "scientific_disposition", "requires_comparison", "requires_validation",
}
_GRID_KEYS = {"kind", "unit", "points"}
_EXPERIMENT_ID_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


def _keys(value: Mapping[str, Any], expected: set[str], location: str) -> None:
    if any(not isinstance(key, str) for key in value):
        raise CliConfigError(f"{location} keys must be strings")
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        raise CliConfigError(f"{location} fields mismatch; missing={missing}, unknown={unknown}")


def _integer(value: Any, location: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CliConfigError(f"{location} must be an integer >= {minimum}")
    return value


def _real(value: Any, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CliConfigError(f"{location} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise CliConfigError(f"{location} must be a finite number")
    return result


def _text(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CliConfigError(f"{location} must be non-empty text")
    return value


def _validate_grid(value: Any, location: str) -> None:
    if not isinstance(value, Mapping):
        raise CliConfigError(f"{location} must be a mapping")
    _keys(value, _GRID_KEYS, location)
    if value["kind"] != "synthetic-response-points-v1":
        raise CliConfigError(f"{location}.kind must be synthetic-response-points-v1")
    if value["unit"] != "dimensionless":
        raise CliConfigError(f"{location}.unit must be dimensionless")
    points = value["points"]
    if not isinstance(points, list) or not points:
        raise CliConfigError(f"{location}.points must be a non-empty list")
    for index, point in enumerate(points):
        _real(point, f"{location}.points[{index}]")


def validate_synthetic_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and copy the intentionally small synthetic CLI config schema."""
    if not isinstance(config, Mapping):
        raise CliConfigError("configuration root must be a mapping")
    _keys(config, _ROOT_KEYS, "configuration")
    result = copy.deepcopy(dict(config))

    if _integer(result["schema_version"], "schema_version", minimum=1) != 1:
        raise CliConfigError("schema_version must be 1")
    experiment_id = _text(result["experiment_id"], "experiment_id")
    if _EXPERIMENT_ID_RE.fullmatch(experiment_id) is None:
        raise CliConfigError("experiment_id must be a lowercase hyphenated slug of at most 63 characters")
    _integer(result["seed"], "seed", minimum=0)
    budget = _integer(result["search_fe_limit"], "search_fe_limit", minimum=4)
    if budget > 64:
        raise CliConfigError("synthetic search_fe_limit must not exceed 64")
    _integer(result["required_free_bytes"], "required_free_bytes", minimum=1)

    design = result["design"]
    if not isinstance(design, Mapping):
        raise CliConfigError("design must be a mapping")
    _keys(design, {"name", "bounds"}, "design")
    _text(design["name"], "design.name")
    bounds = design["bounds"]
    if not isinstance(bounds, list) or len(bounds) != 2:
        raise CliConfigError("design.bounds must contain exactly [lower, upper]")
    lower, upper = (_real(item, f"design.bounds[{index}]") for index, item in enumerate(bounds))
    if upper <= lower:
        raise CliConfigError("design.bounds must be strictly increasing")

    model = result["model"]
    if not isinstance(model, Mapping):
        raise CliConfigError("model must be a mapping")
    _keys(model, {"kind", "offset"}, "model")
    if model["kind"] != "synthetic-offset-response-v1":
        raise CliConfigError("model.kind must be synthetic-offset-response-v1")
    _real(model["offset"], "model.offset")
    _validate_grid(result["search_grid"], "search_grid")
    _validate_grid(result["validation_grid"], "validation_grid")
    if len(result["validation_grid"]["points"]) > 100:
        raise CliConfigError("synthetic validation grid must not exceed 100 points")

    optimizer = result["optimizer"]
    if not isinstance(optimizer, Mapping):
        raise CliConfigError("optimizer must be a mapping")
    _keys(optimizer, {"name", "initial_population", "min_population", "history_size"}, "optimizer")
    if optimizer["name"] != "lshade":
        raise CliConfigError("optimizer.name must be lshade in the R6 synthetic slice")
    initial = _integer(optimizer["initial_population"], "optimizer.initial_population", minimum=4)
    minimum = _integer(optimizer["min_population"], "optimizer.min_population", minimum=4)
    _integer(optimizer["history_size"], "optimizer.history_size", minimum=1)
    if initial < minimum or initial > budget:
        raise CliConfigError("optimizer population must satisfy 4 <= min <= initial <= search_fe_limit")

    context = result["review_context"]
    if not isinstance(context, Mapping):
        raise CliConfigError("review_context must be a mapping")
    _keys(context, _REVIEW_KEYS, "review_context")
    for key in _REVIEW_KEYS - {"requires_comparison", "requires_validation"}:
        _text(context[key], f"review_context.{key}")
    if context["scientific_disposition"] != "CLAIM_PENDING_REVIEW":
        raise CliConfigError("review_context.scientific_disposition must be CLAIM_PENDING_REVIEW")
    if context["requires_comparison"] is not False or context["requires_validation"] is not False:
        raise CliConfigError("synthetic-only runs cannot claim paired or physical-response review evidence")
    return result


class _StrictLoader(yaml.SafeLoader):
    """Safe YAML with no duplicate keys, aliases, anchors or merges."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent) or getattr(self.peek_event(), "anchor", None) is not None:
            raise CliConfigError("YAML anchors and aliases are unsupported")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise CliConfigError("YAML merge keys are unsupported")
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise CliConfigError("YAML mapping keys must be strings")
            if key in result:
                raise CliConfigError(f"duplicate YAML key: {key}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def parse_strict_yaml(content: bytes) -> Any:
    """Parse one UTF-8 document without invoking YAML object constructors."""
    try:
        return yaml.load(content.decode("utf-8"), Loader=_StrictLoader)
    except (UnicodeError, yaml.YAMLError, ValueError, RecursionError) as exc:
        raise CliConfigError(f"invalid strict YAML: {exc}") from exc


def _read_config(path: str | Path) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise CliConfigError("configuration could not be read") from exc


def load_synthetic_config(path: str | Path) -> dict[str, Any]:
    """Read the synthetic format only; scientific configs cannot fall back here."""
    return validate_synthetic_config(parse_strict_yaml(_read_config(path)))


def load_cli_config(path: str | Path) -> dict[str, Any]:
    """Dispatch solely on the explicit scientific discriminator, never shape."""
    content = _read_config(path)
    raw = parse_strict_yaml(content)
    if isinstance(raw, dict) and "schema_id" in raw:
        from .scientific_config import resolve_scientific_config
        return resolve_scientific_config(raw, config_path=Path(path), config_bytes=content)
    return validate_synthetic_config(raw)


__all__ = ["CliConfigError", "load_cli_config", "load_synthetic_config", "validate_synthetic_config"]
