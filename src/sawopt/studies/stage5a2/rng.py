"""Versioned PCG64 call tape, lossless state codec, and frozen seed derivation."""
from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from .codec import canonical_json_bytes, decode_typed, encode_typed
from .identity import CELL_SCHEMA, GenesisCoordinator, GenesisError, PairIdentity
from .journal import JournalError, SQLiteJournal

RNG_CALL_SCHEMA = "stage5a2_rng_call_v1"
PCG64_STATE_SCHEMA = "stage5a2_pcg64_state_v1"
RNG_METHODS = frozenset({
    "integers", "choice", "random", "normal", "standard_cauchy", "uniform", "permutation",
})
RNG_ROLES = frozenset({"common_sampler", "lshade", "controlled_de"})
SEED_PROTOCOL = "stage5a2-q0-r1-v1"


class RNGProtocolError(RuntimeError):
    """An RNG call request or replay diverges from its durable call tape."""


def pcg64_state(generator: np.random.Generator) -> dict[str, Any]:
    """Return the exact JSON-compatible PCG64 state with strict schema checks."""
    if not isinstance(generator, np.random.Generator) or type(generator.bit_generator) is not np.random.PCG64:
        raise RNGProtocolError("Stage 5A-2 requires numpy.random.Generator(PCG64)")
    state = generator.bit_generator.state
    if state.get("bit_generator") != "PCG64":
        raise RNGProtocolError("unexpected PCG64 state name")
    inner = state.get("state")
    if not isinstance(inner, dict) or set(inner) != {"state", "inc"}:
        raise RNGProtocolError("malformed PCG64 inner state")
    if set(state) != {"bit_generator", "state", "has_uint32", "uinteger"}:
        raise RNGProtocolError("PCG64 state fields differ from the frozen schema")
    for name, value in inner.items():
        if type(value) is not int or not 0 <= value < (1 << 128):
            raise RNGProtocolError(f"invalid PCG64 128-bit {name}")
    if inner["inc"] % 2 != 1:
        raise RNGProtocolError("PCG64 increment must be odd")
    if type(state["has_uint32"]) is not int or state["has_uint32"] not in (0, 1):
        raise RNGProtocolError("invalid PCG64 cached uint32 flag")
    if type(state["uinteger"]) is not int or not 0 <= state["uinteger"] < (1 << 32):
        raise RNGProtocolError("invalid PCG64 cached uint32 value")
    return {
        "schema": PCG64_STATE_SCHEMA,
        "bit_generator": "PCG64",
        "state_128_be_hex": f"{inner['state']:032x}",
        "increment_128_be_hex": f"{inner['inc']:032x}",
        "has_uint32": state["has_uint32"],
        "cached_uint32_be_hex": f"{state['uinteger']:08x}",
    }


def restore_pcg64_state(generator: np.random.Generator, encoded: dict[str, Any]) -> None:
    pcg64_state(generator)
    if not isinstance(encoded, dict) or set(encoded) != {
        "schema", "bit_generator", "state_128_be_hex", "increment_128_be_hex",
        "has_uint32", "cached_uint32_be_hex",
    }:
        raise RNGProtocolError("malformed versioned PCG64 state")
    if encoded["schema"] != PCG64_STATE_SCHEMA or encoded["bit_generator"] != "PCG64":
        raise RNGProtocolError("unsupported PCG64 state schema or generator")
    for name, width in (("state_128_be_hex", 32), ("increment_128_be_hex", 32), ("cached_uint32_be_hex", 8)):
        token = encoded[name]
        if type(token) is not str or len(token) != width or any(c not in "0123456789abcdef" for c in token):
            raise RNGProtocolError(f"invalid PCG64 {name} hexadecimal field")
    if type(encoded["has_uint32"]) is not int or encoded["has_uint32"] not in (0, 1):
        raise RNGProtocolError("invalid PCG64 cached uint32 flag")
    state = {
        "bit_generator": "PCG64",
        "state": {
            "state": int(encoded["state_128_be_hex"], 16),
            "inc": int(encoded["increment_128_be_hex"], 16),
        },
        "has_uint32": encoded["has_uint32"],
        "uinteger": int(encoded["cached_uint32_be_hex"], 16),
    }
    # Validate through the same strict rules before assigning into NumPy.
    temporary = np.random.Generator(np.random.PCG64())
    try:
        temporary.bit_generator.state = state
    except (TypeError, ValueError) as exc:
        raise RNGProtocolError("invalid PCG64 state payload") from exc
    pcg64_state(temporary)
    generator.bit_generator.state = state


def design_space_sha256(
    topology: str,
    variable_names: tuple[str, ...],
    bounds: np.ndarray,
    integer_indices: tuple[int, ...],
    units: tuple[str, ...],
) -> str:
    """Hash the frozen Q0 design-space identity with signed zero normalized."""
    array = np.asarray(bounds, dtype=np.float64)
    if array.shape != (len(variable_names), 2) or len(units) != len(variable_names):
        raise ValueError("design-space metadata dimensions do not agree")
    if not np.isfinite(array).all() or np.any(array[:, 1] <= array[:, 0]):
        raise ValueError("design-space bounds must be finite and increasing")
    if len(set(integer_indices)) != len(integer_indices) or any(
        type(index) is not int or not 0 <= index < len(variable_names) for index in integer_indices
    ):
        raise ValueError("integer indices are invalid")
    normalized = array.copy()
    normalized[normalized == 0.0] = 0.0
    tokens = [[struct.pack(">d", float(value)).hex() for value in row] for row in normalized]
    payload = {
        "topology": topology,
        "variable_names": list(variable_names),
        "active_bounds_f64be": tokens,
        "integer_indices": list(integer_indices),
        "units": list(units),
        "rounding": "floor(x+0.5)",
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def derive_seed32(
    *, role: Literal["common_init", "optimizer_lshade", "optimizer_controlled_de"],
    root_seed: int,
    topology: str,
    design_space_hash: str,
    material: str = "MLIT",
) -> int:
    """Implement the exact Q0-R1 canonical-JSON SHA-256 seed namespace."""
    allowed = {"common_init", "optimizer_lshade", "optimizer_controlled_de"}
    if role not in allowed:
        raise ValueError(f"unsupported seed role: {role!r}")
    if type(root_seed) is not int or root_seed < 0:
        raise ValueError("root_seed must be a non-negative integer")
    if type(topology) is not str or topology not in {"D", "P_D", "D_P", "P_D_P"}:
        raise ValueError("unsupported Stage 4A topology")
    if material != "MLIT":
        raise ValueError("Stage 5A-2 seed namespace is frozen to material MLIT")
    if type(design_space_hash) is not str or len(design_space_hash) != 64 or any(
        char not in "0123456789abcdef" for char in design_space_hash
    ):
        raise ValueError("design_space_hash must be a lowercase SHA-256 hex string")
    payload = {
        "protocol": SEED_PROTOCOL,
        "role": role,
        "root_seed": root_seed,
        "material": material,
        "topology": topology,
        "design_space_sha256": design_space_hash,
    }
    return int.from_bytes(hashlib.sha256(canonical_json_bytes(payload)).digest()[:8], "big") % (2**32)


@dataclass(frozen=True, slots=True)
class RNGCallIdentity:
    owner_identity_id: str
    role: Literal["common_sampler", "lshade", "controlled_de"]
    step_id: str
    cursor: tuple[int | str, ...]
    ordinal: int

    def __post_init__(self) -> None:
        if type(self.owner_identity_id) is not str or not self.owner_identity_id:
            raise ValueError("owner_identity_id must be a non-empty string")
        if type(self.role) is not str or self.role not in RNG_ROLES:
            raise ValueError(f"unsupported RNG role {self.role!r}")
        if type(self.step_id) is not str or not self.step_id:
            raise ValueError("step_id must be a non-empty string")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("RNG ordinal must be non-negative")
        if type(self.cursor) is not tuple or any(type(item) not in (int, str) for item in self.cursor):
            raise ValueError("RNG cursor must be an immutable tuple of exact int or str values")

    def record(self) -> dict[str, Any]:
        return {
            "schema": RNG_CALL_SCHEMA,
            "owner_identity_id": self.owner_identity_id,
            "role": self.role,
            "step_id": self.step_id,
            "cursor": self.cursor,
            "ordinal": self.ordinal,
        }

    @property
    def call_id(self) -> str:
        return hashlib.sha256(
            b"sawopt-stage5a2-rng-call-v1\0" + encode_typed(self.record())
        ).hexdigest()


_POSITIONAL_NAMES = {
    "integers": ("low", "high", "size", "dtype", "endpoint"),
    "choice": ("a", "size", "replace", "p"),
    "random": ("size", "dtype", "out"),
    "normal": ("loc", "scale", "size"),
    "standard_cauchy": ("size",),
    "uniform": ("low", "high", "size"),
    "permutation": ("x", "axis"),
}


def _size_valid(value: Any) -> bool:
    if value is None:
        return True
    if type(value) is int:
        return value >= 0
    return type(value) is tuple and all(type(item) is int and item >= 0 for item in value)


def _validate_request(method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    if method not in RNG_METHODS:
        raise RNGProtocolError(f"RNG method is not permitted: {method!r}")
    if type(kwargs) is not dict or any(type(key) is not str for key in kwargs):
        raise RNGProtocolError("RNG keyword arguments must have string keys")
    names = _POSITIONAL_NAMES[method]
    if len(args) > len(names):
        raise RNGProtocolError(f"too many positional arguments for {method}")
    duplicates = set(names[:len(args)]) & set(kwargs)
    if duplicates:
        raise RNGProtocolError(f"RNG argument supplied twice: {sorted(duplicates)[0]}")
    unknown = set(kwargs) - set(names)
    if unknown:
        raise RNGProtocolError(f"unknown {method} keyword: {sorted(unknown)[0]}")
    try:
        encode_typed((args, kwargs))
    except (TypeError, ValueError) as exc:
        raise RNGProtocolError(f"RNG request contains unsupported typed arguments: {exc}") from exc

    bound = dict(zip(names, args)) | kwargs
    required = {"integers": "low", "choice": "a", "permutation": "x"}
    if method in required and required[method] not in bound:
        raise RNGProtocolError(f"{method} requires {required[method]}")
    size = bound.get("size")
    if "size" in bound and not _size_valid(size):
        raise RNGProtocolError("RNG size must be None or a non-negative int/tuple of ints")
    size_shape = () if size is None else ((size,) if type(size) is int else size)

    def finite_numeric(name: str, default: Any) -> np.ndarray:
        try:
            value = np.asarray(bound.get(name, default))
            valid = np.issubdtype(value.dtype, np.number) and np.isfinite(value).all()
        except (TypeError, ValueError, OverflowError):
            valid = False
            value = np.asarray(0.0)
        if not valid:
            raise RNGProtocolError(f"{method} {name} must be finite numeric data")
        return value

    def shape_fits(parameters: tuple[np.ndarray, ...]) -> None:
        try:
            parameter_shape = np.broadcast_shapes(*(item.shape for item in parameters))
            if size is not None and np.broadcast_shapes(parameter_shape, size_shape) != size_shape:
                raise RNGProtocolError(f"{method} parameters do not broadcast to requested size")
        except ValueError as exc:
            raise RNGProtocolError(f"{method} parameter/size shapes are incompatible") from exc

    if method == "uniform":
        low, high = finite_numeric("low", 0.0), finite_numeric("high", 1.0)
        shape_fits((low, high))
        if np.any(high < low):
            raise RNGProtocolError("uniform high must be greater than or equal to low")
    elif method == "normal":
        loc, scale = finite_numeric("loc", 0.0), finite_numeric("scale", 1.0)
        shape_fits((loc, scale))
        if np.any(scale < 0):
            raise RNGProtocolError("normal scale must be non-negative")
    elif method == "integers":
        low = np.asarray(bound["low"])
        if not np.issubdtype(low.dtype, np.integer):
            raise RNGProtocolError("integers low must be integer data")
        high_value = bound.get("high")
        high = None if high_value is None else np.asarray(high_value)
        if high is not None and not np.issubdtype(high.dtype, np.integer):
            raise RNGProtocolError("integers high must be integer data")
        endpoint = bound.get("endpoint", False)
        if type(endpoint) is not bool:
            raise RNGProtocolError("integers endpoint must be bool")
        try:
            dtype = np.dtype(bound.get("dtype", np.int64))
        except (TypeError, ValueError) as exc:
            raise RNGProtocolError("integers dtype is invalid") from exc
        if dtype.kind not in "iu":
            raise RNGProtocolError("integers dtype must be signed or unsigned integer")
        limits = np.iinfo(dtype)
        if high is None:
            if np.any(low <= 0):
                raise RNGProtocolError("integers one-argument high must be positive")
            if np.any(low > int(limits.max) + 1):
                raise RNGProtocolError("integers one-argument high exceeds dtype range")
            shape_parameters = (low,)
        else:
            try:
                if np.any(high < low if endpoint else high <= low):
                    relation = "not below" if endpoint else "greater than"
                    raise RNGProtocolError(f"integers high must be {relation} low")
                if np.any(low < int(limits.min)) or np.any(low > int(limits.max)):
                    raise RNGProtocolError("integers low exceeds dtype range")
                high_limit = int(limits.max) if endpoint else int(limits.max) + 1
                if np.any(high < int(limits.min)) or np.any(high > high_limit):
                    raise RNGProtocolError("integers high exceeds dtype range")
            except ValueError as exc:
                raise RNGProtocolError("integers low/high shapes are incompatible") from exc
            shape_parameters = (low, high)
        shape_fits(shape_parameters)
    elif method == "random":
        if bound.get("out") is not None:
            raise RNGProtocolError("random(out=...) is not allowed by the lossless result contract")
        try:
            dtype = np.dtype(bound.get("dtype", np.float64))
        except (TypeError, ValueError) as exc:
            raise RNGProtocolError("random dtype is invalid") from exc
        if dtype not in (np.dtype(np.float32), np.dtype(np.float64)):
            raise RNGProtocolError("random dtype must be float32 or float64")
    elif method == "choice":
        choices = bound["a"]
        values = np.asarray(choices)
        if values.ndim == 0 and np.issubdtype(values.dtype, np.integer):
            population_size = int(values)
            if population_size <= 0:
                raise RNGProtocolError("choice population size must be positive")
        elif values.ndim == 1 and values.size > 0 and values.dtype.kind != "O":
            population_size = int(values.size)
        else:
            raise RNGProtocolError("choice population must be a positive integer or non-empty 1-D array")
        replace_value = bound.get("replace", True)
        if type(replace_value) is not bool:
            raise RNGProtocolError("choice replace must be bool")
        probabilities = bound.get("p")
        if probabilities is not None:
            try:
                probabilities = np.asarray(probabilities, dtype=float)
            except (TypeError, ValueError, OverflowError) as exc:
                raise RNGProtocolError("choice probabilities must be numeric") from exc
            if (probabilities.ndim != 1 or probabilities.size != population_size
                    or not np.isfinite(probabilities).all() or np.any(probabilities < 0)):
                raise RNGProtocolError("choice probabilities must be a finite non-negative population vector")
            if not np.isclose(float(probabilities.sum()), 1.0, rtol=1e-12, atol=1e-15):
                raise RNGProtocolError("choice probabilities must sum to one")
        if not replace_value and size is not None and math.prod(size_shape) > population_size:
            raise RNGProtocolError("choice without replacement size exceeds its population")
    elif method == "permutation":
        values = np.asarray(bound["x"])
        axis = bound.get("axis", 0)
        if type(axis) is not int:
            raise RNGProtocolError("permutation axis must be an integer")
        if values.ndim == 0 and np.issubdtype(values.dtype, np.integer):
            if int(values) < 0 or axis != 0:
                raise RNGProtocolError("permutation integer length and axis are invalid")
        elif values.ndim == 0 or not -values.ndim <= axis < values.ndim:
            raise RNGProtocolError("permutation array/axis is invalid")
    return hashlib.sha256(encode_typed({"args": args, "kwargs": kwargs})).hexdigest()


class RNGCallService:
    """Durable call facade implementing START-before-draw and replay-no-redraw."""

    _START_FIELDS = frozenset({
        "schema", "call_id", "request_hash", "identity", "method", "args", "kwargs",
        "argument_hash", "pre_state", "pre_state_sha256",
    })
    _COMMIT_FIELDS = frozenset({
        "schema", "call_id", "request_hash", "result_typed", "result_sha256",
        "post_state", "post_state_sha256",
    })

    def __init__(
        self,
        generator: np.random.Generator,
        journal: SQLiteJournal,
        *,
        genesis: GenesisCoordinator | None = None,
        pair_identity: PairIdentity | None = None,
        synthetic_test: bool = False,
        synthetic_test_seed: int | None = None,
    ) -> None:
        initial_state = pcg64_state(generator)
        self.initial_state = decode_typed(encode_typed(initial_state))
        self.generator = generator
        self.journal = journal
        self.genesis = genesis
        self.pair_identity = pair_identity
        self.synthetic_test = synthetic_test
        self.synthetic_test_seed = synthetic_test_seed
        if type(synthetic_test) is not bool:
            raise RNGProtocolError("synthetic_test must be an explicit boolean")
        if synthetic_test:
            if type(synthetic_test_seed) is not int or synthetic_test_seed < 0:
                raise RNGProtocolError("synthetic-only RNG service requires its explicit test seed")
        elif pair_identity is None:
            raise RNGProtocolError("production RNG service requires an immutable pair identity")
        if genesis is not None and pair_identity is None:
            raise RNGProtocolError("a genesis coordinator requires its immutable pair identity")
        if pair_identity is not None and pair_identity.identity_scope != ("synthetic_test" if synthetic_test else "q0_production"):
            raise RNGProtocolError("RNG service scope differs from its pair identity scope")
        self._journal_sequence = 0
        self._journal_head_hash = ""
        self._rng_starts: dict[str, dict[str, Any]] = {}
        self._rng_commits: dict[str, dict[str, Any]] = {}
        self._stream_call_ids: dict[tuple[str, str], list[str]] = {}
        self._pending_streams: dict[tuple[str, str], str] = {}
        # Recovery validates the full existing chain exactly once. Live calls
        # validate only newly appended journal events.
        for event in journal.iter_events():
            self._accept_journal_event(event)

    @staticmethod
    def _state_hash(state: dict[str, Any]) -> str:
        return hashlib.sha256(encode_typed(state)).hexdigest()

    @staticmethod
    def _request_hash(start: dict[str, Any]) -> str:
        request = {
            key: start[key]
            for key in ("identity", "method", "args", "kwargs", "argument_hash", "pre_state")
        }
        return hashlib.sha256(encode_typed(request)).hexdigest()

    @staticmethod
    def _identity_from_record(record: Any) -> RNGCallIdentity:
        if type(record) is not dict or set(record) != {
            "schema", "owner_identity_id", "role", "step_id", "cursor", "ordinal",
        } or record.get("schema") != RNG_CALL_SCHEMA:
            raise RNGProtocolError("malformed versioned RNG call identity")
        try:
            return RNGCallIdentity(
                owner_identity_id=record["owner_identity_id"], role=record["role"],
                step_id=record["step_id"], cursor=record["cursor"], ordinal=record["ordinal"],
            )
        except (TypeError, ValueError) as exc:
            raise RNGProtocolError("malformed RNG call identity fields") from exc

    def _expected_initial_state(self, identity: RNGCallIdentity) -> dict[str, Any]:
        if self.synthetic_test:
            seed = self.synthetic_test_seed
        else:
            pair = self.pair_identity
            if pair is None or pair.identity_scope != "q0_production":
                raise RNGProtocolError("production RNG stream lacks a validated Q0 pair identity")
            seed_role = {
                "common_sampler": "common_init",
                "lshade": "optimizer_lshade",
                "controlled_de": "optimizer_controlled_de",
            }[identity.role]
            seed = derive_seed32(
                role=seed_role,
                root_seed=pair.root_seed,
                topology=pair.topology,
                design_space_hash=pair.design_space_sha256,
            )
        return pcg64_state(np.random.Generator(np.random.PCG64(seed)))

    def _accept_rng_start(self, event) -> None:
        payload = event.payload
        if type(payload) is not dict or set(payload) != self._START_FIELDS:
            raise RNGProtocolError("RNG STARTED payload fields differ from its frozen schema")
        call_id = payload["call_id"]
        if event.event_id != f"RNG_DRAW_STARTED:{call_id}" or type(call_id) is not str or len(call_id) != 64:
            raise RNGProtocolError("RNG STARTED event id does not match its call identity")
        identity = self._identity_from_record(payload["identity"])
        if identity.call_id != call_id:
            raise RNGProtocolError("RNG STARTED call ID does not match its typed identity")
        if call_id in self._rng_starts:
            raise RNGProtocolError("duplicate durable RNG STARTED event")
        try:
            argument_hash = _validate_request(payload["method"], payload["args"], payload["kwargs"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RNGProtocolError("RNG STARTED request is invalid") from exc
        if argument_hash != payload["argument_hash"]:
            raise RNGProtocolError("RNG STARTED typed argument hash mismatch")
        if self._state_hash(payload["pre_state"]) != payload["pre_state_sha256"]:
            raise RNGProtocolError("RNG STARTED pre-state hash mismatch")
        validator = np.random.Generator(np.random.PCG64())
        restore_pcg64_state(validator, payload["pre_state"])
        if self._request_hash(payload) != payload["request_hash"]:
            raise RNGProtocolError("RNG STARTED request hash mismatch")
        stream_key = (identity.owner_identity_id, identity.role)
        stream_calls = self._stream_call_ids.setdefault(stream_key, [])
        if identity.ordinal != len(stream_calls):
            raise RNGProtocolError("RNG journal ordinals are skipped, repeated, or out of order")
        if stream_key in self._pending_streams:
            raise RNGProtocolError("RNG journal starts a later call before resolving its predecessor")
        if not stream_calls:
            expected_pre_state = self._expected_initial_state(identity)
        else:
            previous_commit = self._rng_commits.get(stream_calls[-1])
            if previous_commit is None:
                raise RNGProtocolError("RNG stream predecessor has no committed post-state")
            expected_pre_state = previous_commit["post_state"]
        if payload["pre_state"] != expected_pre_state:
            raise RNGProtocolError("RNG STARTED pre-state breaks identity-seeded stream continuity")
        self._rng_starts[call_id] = payload
        stream_calls.append(call_id)
        self._pending_streams[stream_key] = call_id

    def _accept_rng_commit(self, event) -> None:
        payload = event.payload
        if type(payload) is not dict or set(payload) != self._COMMIT_FIELDS:
            raise RNGProtocolError("RNG COMMITTED payload fields differ from its frozen schema")
        call_id = payload["call_id"]
        if event.event_id != f"RNG_DRAW_COMMITTED:{call_id}" or call_id in self._rng_commits:
            raise RNGProtocolError("RNG COMMITTED event ID is invalid or duplicated")
        start = self._rng_starts.get(call_id)
        if start is None or start["request_hash"] != payload["request_hash"]:
            raise RNGProtocolError("RNG commit has no matching durable start/request")
        identity = self._identity_from_record(start["identity"])
        stream_key = (identity.owner_identity_id, identity.role)
        if self._pending_streams.get(stream_key) != call_id:
            raise RNGProtocolError("RNG commit is not resolving the current pending stream call")
        try:
            result = decode_typed(payload["result_typed"])
            if hashlib.sha256(encode_typed(result)).hexdigest() != payload["result_sha256"]:
                raise RNGProtocolError("RNG committed result hash mismatch")
            if self._state_hash(payload["post_state"]) != payload["post_state_sha256"]:
                raise RNGProtocolError("RNG committed post-state hash mismatch")
            validator = np.random.Generator(np.random.PCG64())
            restore_pcg64_state(validator, payload["post_state"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RNGProtocolError("RNG committed result or post-state is malformed") from exc
        self._rng_commits[call_id] = payload
        del self._pending_streams[stream_key]

    def _accept_journal_event(self, event) -> None:
        if event.sequence != self._journal_sequence + 1 or event.previous_hash != self._journal_head_hash:
            raise RNGProtocolError("journal changed unexpectedly during RNG stream operation")
        self._journal_sequence = event.sequence
        self._journal_head_hash = event.event_hash
        if event.event_type == "RNG_DRAW_STARTED":
            self._accept_rng_start(event)
        elif event.event_type == "RNG_DRAW_COMMITTED":
            self._accept_rng_commit(event)

    def _refresh_journal_tail(self) -> None:
        try:
            for event in self.journal.events_after(self._journal_sequence, self._journal_head_hash):
                self._accept_journal_event(event)
        except JournalError as exc:
            raise RNGProtocolError(f"journal tail integrity failure: {exc}") from exc

    def _validate_owner(self, identity: RNGCallIdentity) -> None:
        if identity.role == "common_sampler":
            pair = self.pair_identity
            if (
                pair is None or self.genesis is None or self.journal.owner_kind != "pair"
                or self.journal.journal_uuid != pair.pair_journal_uuid
                or identity.owner_identity_id != pair.identity_id
            ):
                raise RNGProtocolError("common-sampler RNG owner is not the immutable pair identity")
            try:
                # Q0-R3 requires a fresh full three-journal G4 verification on
                # every logical sampler operation, including replay/recovery.
                self.genesis.require_ready(pair)
            except (GenesisError, JournalError) as exc:
                raise RNGProtocolError("common-sampler RNG is forbidden before verified durable G4") from exc
            if self.journal.get_immutable_record("pair_identity", pair.identity_id) != pair.canonical_bytes:
                raise RNGProtocolError("common-sampler pair identity record differs from the expected bytes")
            return
        role = identity.role
        if self.journal.owner_kind != role:
            raise RNGProtocolError("optimizer RNG role does not match its private arm journal")
        if identity.owner_identity_id == "" or not self.journal.journal_uuid:
            raise RNGProtocolError("optimizer RNG owner identity is empty")
        if not self.synthetic_test:
            pair = self.pair_identity
            if pair is None or pair.identity_scope != "q0_production":
                raise RNGProtocolError("optimizer RNG requires its validated production pair identity")
        rows = [record for record in self.journal.immutable_records() if record[0] == "cell_identity"]
        matching = [record for record in rows if record[1] == identity.owner_identity_id]
        if len(rows) != 1 or len(matching) != 1:
            raise RNGProtocolError("optimizer RNG owner is not the journal's unique immutable cell identity")
        canonical = matching[0][2]
        try:
            record = json.loads(canonical.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RNGProtocolError("optimizer RNG cell identity bytes are malformed") from exc
        identity_id = hashlib.sha256(b"sawopt-stage5a2-cell-identity-v2\0" + canonical).hexdigest()
        if (
            canonical_json_bytes(record) != canonical or identity_id != identity.owner_identity_id
            or record.get("schema") != CELL_SCHEMA or record.get("role") != role
            or record.get("cell_journal_uuid") != self.journal.journal_uuid
        ):
            raise RNGProtocolError("optimizer RNG owner identity does not match its arm journal")
        if not self.synthetic_test and (
            record.get("pair_identity_id") != self.pair_identity.identity_id
            or record.get("pair_identity_sha256") != self.pair_identity.identity_sha256
            or record.get("arm_config_sha256") != dict(self.pair_identity.arm_config_hashes)[role]
            or record.get("environment_sha256") != self.pair_identity.environment_sha256
        ):
            raise RNGProtocolError("optimizer RNG cell does not bind the validated pair identity")

    def _invoke(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        return getattr(self.generator, method)(*args, **kwargs)

    def call(self, identity: RNGCallIdentity, method: str, *args: Any, **kwargs: Any) -> Any:
        self._validate_owner(identity)
        arg_hash = _validate_request(method, args, kwargs)
        self._refresh_journal_tail()
        identity_record = identity.record()
        call_id = identity.call_id
        stream_key = (identity.owner_identity_id, identity.role)
        call_ids = self._stream_call_ids.get(stream_key, [])
        existing_start = self._rng_starts.get(call_id)
        pending_call_id = self._pending_streams.get(stream_key)
        if pending_call_id is not None and pending_call_id != call_id:
            raise RNGProtocolError("an earlier RNG call is unresolved; no later draw is allowed")

        if existing_start is None:
            if identity.ordinal != len(call_ids):
                raise RNGProtocolError("RNG ordinal is skipped, repeated, or out of order")
            pre_state = pcg64_state(self.generator)
            expected_pre_state = (
                self._expected_initial_state(identity)
                if identity.ordinal == 0
                else self._rng_commits[call_ids[-1]]["post_state"]
            )
            if pre_state != expected_pre_state:
                raise RNGProtocolError("live PCG64 state drifted from the identity-bound stream predecessor")
            start_payload = {
                "schema": RNG_CALL_SCHEMA,
                "call_id": call_id,
                "request_hash": "",
                "identity": identity_record,
                "method": method,
                "args": args,
                "kwargs": kwargs,
                "argument_hash": arg_hash,
                "pre_state": pre_state,
                "pre_state_sha256": self._state_hash(pre_state),
            }
            start_payload["request_hash"] = self._request_hash(start_payload)
            event = self.journal.append_event(
                f"RNG_DRAW_STARTED:{call_id}", "RNG_DRAW_STARTED", start_payload,
            )
            self._accept_journal_event(event)
            existing_start = start_payload
        else:
            expected = {
                "identity": identity_record, "method": method, "args": args,
                "kwargs": kwargs, "argument_hash": arg_hash,
            }
            for key, value in expected.items():
                if encode_typed(existing_start.get(key)) != encode_typed(value):
                    raise RNGProtocolError(f"RNG replay mismatch at {key}; no underlying draw performed")
            if self._request_hash(existing_start) != existing_start["request_hash"]:
                raise RNGProtocolError("RNG replay request hash mismatch")
            if self._state_hash(existing_start["pre_state"]) != existing_start["pre_state_sha256"]:
                raise RNGProtocolError("RNG replay pre-state hash mismatch")

        committed = self._rng_commits.get(call_id)
        if committed is not None:
            if pcg64_state(self.generator) != existing_start["pre_state"]:
                raise RNGProtocolError("committed RNG replay is not at its recorded pre-state")
            try:
                output = decode_typed(committed["result_typed"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RNGProtocolError("committed RNG result is malformed") from exc
            restore_pcg64_state(self.generator, committed["post_state"])
            return output

        # A pending STARTED call has one authoritative recovery point. Restore
        # it before invoking NumPy, even after a lost return or arbitrary state.
        restore_pcg64_state(self.generator, existing_start["pre_state"])
        result = self._invoke(method, args, kwargs)
        post_state = pcg64_state(self.generator)
        encoded_result = encode_typed(result)
        committed_payload = {
            "schema": RNG_CALL_SCHEMA,
            "call_id": call_id,
            "request_hash": existing_start["request_hash"],
            "result_typed": encoded_result,
            "result_sha256": hashlib.sha256(encoded_result).hexdigest(),
            "post_state": post_state,
            "post_state_sha256": self._state_hash(post_state),
        }
        event = self.journal.append_event(
            f"RNG_DRAW_COMMITTED:{call_id}", "RNG_DRAW_COMMITTED", committed_payload,
        )
        self._accept_journal_event(event)
        return result


__all__ = [
    "PCG64_STATE_SCHEMA", "RNG_CALL_SCHEMA", "RNG_METHODS", "RNGCallIdentity",
    "RNGCallService", "RNGProtocolError", "derive_seed32", "design_space_sha256",
    "pcg64_state", "restore_pcg64_state",
]
