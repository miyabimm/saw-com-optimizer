"""Lossless live-field snapshots; never call the historical v4 JSON serializer."""
from __future__ import annotations

from dataclasses import fields, is_dataclass
import math

import numpy as np

from sawopt.optimization.controlled_de import DEMember
from sawopt.optimization.lshade import _PopulationMember

from .candidates import validate_candidate
from .codec import decode_typed, encode_typed
from .rng import pcg64_state, restore_pcg64_state

_EXCLUDED = {"evaluator", "canonicalizer", "comparator", "rng", "observe", "_q1_observer"}
_MEMBERS = {"lshade_member": _PopulationMember, "de_member": DEMember}


def _pack(value, canonical_record=False):
    if is_dataclass(value):
        tag = "lshade_member" if type(value) is _PopulationMember else "de_member"
        if type(value) not in _MEMBERS.values():
            raise ValueError("unsupported live-state dataclass")
        return (tag, {f.name: _pack(getattr(value, f.name)) for f in fields(value)})
    if isinstance(value, dict):
        canonical_record = canonical_record or value.get("schema_id") == "stage5a2_candidate_record_v1"
        items = value.items()
        if canonical_record and all(isinstance(key, str) for key in value):
            items = sorted(items)
        return ("mapping", [(_pack(k, canonical_record), _pack(v, canonical_record)) for k, v in items])
    if isinstance(value, list):
        return ("list", [_pack(v, canonical_record) for v in value])
    if isinstance(value, tuple):
        return ("tuple", [_pack(v, canonical_record) for v in value])
    if isinstance(value, (float, np.floating)) and (math.isnan(value) or value == -math.inf):
        raise ValueError("NaN/-Inf is not scientific live state")
    if isinstance(value, np.ndarray) and np.issubdtype(value.dtype, np.floating):
        if np.isnan(value).any() or np.isneginf(value).any():
            raise ValueError("NaN/-Inf array is not scientific live state")
    return ("value", value)


def _unpack(node):
    tag, value = node
    if tag == "mapping":
        return {_unpack(k): _unpack(v) for k, v in value}
    if tag == "list":
        return [_unpack(v) for v in value]
    if tag == "tuple":
        return tuple(_unpack(v) for v in value)
    if tag in _MEMBERS:
        return _MEMBERS[tag](**{k: _unpack(v) for k, v in value.items()})
    if tag != "value":
        raise ValueError("unknown live-state node")
    return value


def _validate_state(state):
    for field in ("bounds", "hard_bounds", "m_f", "m_cr"):
        if field in state:
            array = np.asarray(state[field])
            if not np.issubdtype(array.dtype, np.floating) or not np.isfinite(array).all():
                raise ValueError(f"invalid numeric live field: {field}")
    for field in ("unique_evaluations", "proposals_total", "history_index", "generations", "generation", "target", "retry"):
        if field in state and (type(state[field]) is not int or state[field] < 0):
            raise ValueError(f"invalid live counter: {field}")
    members = [member for name in ("_population", "population", "parents", "pending") for member in state.get(name, [])]
    records = []
    for member in members:
        if (member.x.shape != (13,) or member.physical.shape != (13,) or not np.isfinite(member.x).all()
                or not np.isfinite(member.physical).all() or tuple(member.physical) != member.key):
            raise ValueError("invalid live population representation")
        records.append((member.result, member.physical))
    for cache in (state.get("_cache", {}), state.get("cache", {})):
        records.extend((record, record.get("candidate_vector")) for record in cache.values())
    if state.get("_incumbent") is not None:
        records.append((state["_incumbent"], state["_incumbent"].get("candidate_vector")))
    for record, physical in records:
        # Backend-only DE fixtures may use its generic comparator seam. Q1
        # candidate-bearing snapshots, however, never accept nullified records.
        if "schema_id" in record:
            validate_candidate(record, vector=physical, ordinal=record["first_evaluation_ordinal"],
                               topology=record["topology"], grid_sha256=record["grid_sha256"])
    for rank, _physical, _order in state.get("_history_rank_index", {}).values():
        if len(rank) != 7 or any(v is None or math.isnan(v) or v == -math.inf for v in rank):
            raise ValueError("invalid/nullified live rank")
        if any(v == math.inf for v in rank) and tuple(rank) != (0., 1., math.inf, math.inf, math.inf, math.inf, math.inf):
            raise ValueError("+Inf rank outside modeled-failure ordering")


def snapshot(backend):
    state = {k: v for k, v in vars(backend).items() if k not in _EXCLUDED}
    _validate_state(state)
    return encode_typed({
        "schema": f"stage5a2_{backend.name}_state_v1", "fields": _pack(state),
        "rng": pcg64_state(backend.rng.generator if hasattr(backend.rng, "generator") else backend.rng),
    })


def inspect_snapshot(backend, payload):
    """Validate an identity-bound snapshot without mutating the backend."""
    envelope = decode_typed(payload)
    if set(envelope) != {"schema", "fields", "rng"} or envelope["schema"] != f"stage5a2_{backend.name}_state_v1":
        raise ValueError("not a Q1 live snapshot (historical v4/null payloads forbidden)")
    state = _unpack(envelope["fields"])
    expected = set(vars(backend)) - _EXCLUDED
    if set(state) != expected:
        raise ValueError("live-state fields differ from pinned backend")
    # Config/bounds are identity, not a license to hydrate a foreign trajectory.
    immutable = ("bounds", "config", "hard_bounds", "population_schedule_terminal_budget",
                 "hard_max_budget", "source_config_fingerprint")
    for name in immutable:
        if name in state and encode_typed(state[name]) != encode_typed(vars(backend)[name]):
            raise ValueError(f"live-state identity mismatch: {name}")
    _validate_state(state)
    _pack(state)  # reject NaN/-Inf even for a hand-crafted typed envelope
    validator = np.random.Generator(np.random.PCG64())
    restore_pcg64_state(validator, envelope["rng"])
    return state, envelope["rng"]


def restore(backend, payload):
    state, rng_state = inspect_snapshot(backend, payload)
    generator = backend.rng.generator if hasattr(backend.rng, "generator") else backend.rng
    restore_pcg64_state(generator, rng_state)
    vars(backend).update(state)
