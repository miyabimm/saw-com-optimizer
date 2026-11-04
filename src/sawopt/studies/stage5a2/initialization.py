"""Representation-aware common initialization and pure pre-FE identity checks.

All geometry, L-SHADE coordinate transforms, canonicalization and evaluator
behavior are injected as pure callables. This module imports no physics or
provider package and never selects candidates using fitness.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import Any, Callable, Literal, Sequence

import numpy as np

from sawopt.design.canonicalization import canonicalize_hybrid_vector

from .codec import canonical_json_bytes
from .identity import CellIdentity, GenesisCoordinator, GenesisError, GenesisReady, PairIdentity
from .journal import JournalError, SQLiteJournal
from .rng import RNGCallIdentity, RNGCallService, derive_seed32, design_space_sha256, pcg64_state

SAMPLER_VERSION = "independent_uniform_rejection_lshade_image_v2"
POPULATION_SIZE = 234
MAX_DRAWS = 10_000
_KEY_SCHEMA = "f64be_tuple_v1"


class InitializationError(RuntimeError):
    """Initialization cannot produce or verify the exact common population."""


class InitializationGateError(InitializationError):
    """A sampler/evaluator path attempted to pass an identity barrier early."""


def _vector_bytes(value: Sequence[float] | np.ndarray, dimension: int) -> bytes:
    array = np.asarray(value, dtype=np.float64)
    if array.shape != (dimension,) or not np.isfinite(array).all():
        raise InitializationError(f"representation must be a finite {dimension}-vector")
    return np.asarray(array, dtype="<f8").tobytes()


def _vector_from_bytes(payload: bytes, dimension: int) -> np.ndarray:
    if len(payload) != dimension * 8:
        raise InitializationError("representation vector byte length does not match dimension")
    return np.frombuffer(payload, dtype="<f8").copy()


def canonical_key_tokens(key: Sequence[float]) -> tuple[str, ...]:
    tokens: list[str] = []
    for value in key:
        number = float(value)
        if not np.isfinite(number):
            raise InitializationError("canonical key values must be finite")
        # Q0-R1 §6.3: canonical cache/database keys collapse signed zeros,
        # while physical/genotype vectors preserve their original IEEE-754 bits.
        tokens.append(struct.pack(">d", 0.0 if number == 0.0 else number).hex())
    return tuple(tokens)


def _key_bytes(tokens: tuple[str, ...]) -> bytes:
    return canonical_json_bytes({"schema": _KEY_SCHEMA, "dimension": len(tokens), "values": list(tokens)})


@dataclass(frozen=True, slots=True)
class DesignSpaceMetadata:
    topology: str
    variable_names: tuple[str, ...]
    bounds: tuple[tuple[float, float], ...]
    integer_indices: tuple[int, ...]
    units: tuple[str, ...]
    design_space_sha256: str

    def __post_init__(self) -> None:
        if self.topology not in {"D", "P_D", "D_P", "P_D_P"}:
            raise ValueError("design-space topology must be a supported Stage 4A label")
        if type(self.variable_names) is not tuple or type(self.bounds) is not tuple:
            raise ValueError("design-space names and bounds must be immutable tuples")
        if any(type(row) is not tuple or len(row) != 2 for row in self.bounds):
            raise ValueError("design-space bounds must be immutable lower/upper pairs")
        if type(self.integer_indices) is not tuple or type(self.units) is not tuple:
            raise ValueError("design-space integer indices and units must be immutable tuples")
        if any(type(value) not in (int, float) for row in self.bounds for value in row):
            raise ValueError("design-space bounds must contain exact integer/float scalars")
        array = np.asarray(self.bounds, dtype=np.float64)
        if array.ndim != 2 or array.shape[1] != 2:
            raise ValueError("design-space bounds must be an ordered (dimension, 2) array")
        if not np.isfinite(array).all() or np.any(array[:, 1] <= array[:, 0]):
            raise ValueError("design-space bounds must be finite and increasing")
        if len(set(self.integer_indices)) != len(self.integer_indices) or any(
            type(index) is not int or not 0 <= index < len(array) for index in self.integer_indices
        ) or tuple(sorted(self.integer_indices)) != self.integer_indices:
            raise ValueError("design-space integer indices must be unique and ordered")
        if len(self.variable_names) != len(array) or len(self.units) != len(array):
            raise ValueError("design-space variable names and units must match the dimension")
        if any(type(name) is not str or not name for name in self.variable_names):
            raise ValueError("design-space variable names must be non-empty strings")
        if any(type(unit) is not str or not unit for unit in self.units):
            raise ValueError("design-space units must be non-empty strings")
        object.__setattr__(self, "bounds", tuple(tuple(float(value) for value in row) for row in array))
        expected_hash = design_space_sha256(
            self.topology, self.variable_names, array, self.integer_indices, self.units,
        )
        if self.design_space_sha256 != expected_hash:
            raise ValueError("design-space SHA-256 does not match frozen metadata")

    @property
    def dimension(self) -> int:
        return len(self.bounds)

    def bounds_array(self) -> np.ndarray:
        return np.asarray(self.bounds, dtype=np.float64)


@dataclass(frozen=True, slots=True)
class PopulationMember:
    ordinal: int
    raw_physical_le_f64: bytes
    provisional_canonical_le_f64: bytes
    lshade_input_genotype_le_f64: bytes
    lshade_reconstructed_le_f64: bytes
    sealed_physical_le_f64: bytes
    canonical_key_f64be: tuple[str, ...]
    de_initial_physical_le_f64: bytes
    de_phenotype_genotype_le_f64: bytes

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("population ordinal must be non-negative")
        byte_fields = (
            self.raw_physical_le_f64, self.provisional_canonical_le_f64,
            self.lshade_input_genotype_le_f64, self.lshade_reconstructed_le_f64,
            self.sealed_physical_le_f64, self.de_initial_physical_le_f64,
            self.de_phenotype_genotype_le_f64,
        )
        if any(type(value) is not bytes for value in byte_fields):
            raise ValueError("population representations must use immutable bytes")
        if type(self.canonical_key_f64be) is not tuple:
            raise ValueError("canonical key tokens must be an immutable tuple")
        size = len(self.sealed_physical_le_f64)
        if size == 0 or size % 8:
            raise ValueError("sealed physical vector has invalid binary64 byte length")
        if len(self.canonical_key_f64be) != size // 8:
            raise ValueError("canonical key dimension differs from sealed vector")
        representations = (
            self.raw_physical_le_f64, self.provisional_canonical_le_f64,
            self.lshade_input_genotype_le_f64, self.lshade_reconstructed_le_f64,
            self.de_initial_physical_le_f64, self.de_phenotype_genotype_le_f64,
        )
        if any(len(value) != size for value in representations):
            raise ValueError("population representations have different dimensions")
        if any(not np.isfinite(np.frombuffer(value, dtype="<f8")).all() for value in (self.sealed_physical_le_f64, *representations)):
            raise ValueError("population representations must contain only finite binary64 values")
        if self.de_initial_physical_le_f64 != self.sealed_physical_le_f64:
            raise ValueError("controlled DE initial physical input must equal the sealed evaluator vector")
        if any(type(token) is not str or len(token) != 16 for token in self.canonical_key_f64be):
            raise ValueError("canonical key must contain 16-hex-digit binary64 tokens")
        for token in self.canonical_key_f64be:
            try:
                bytes.fromhex(token)
            except ValueError as exc:
                raise ValueError("canonical key contains invalid hexadecimal") from exc
        sealed = np.frombuffer(self.sealed_physical_le_f64, dtype="<f8")
        if canonical_key_tokens(sealed) != self.canonical_key_f64be:
            raise ValueError("canonical key differs from sealed physical vector")

    @property
    def dimension(self) -> int:
        return len(self.sealed_physical_le_f64) // 8

    def representation_record(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "raw_physical_le_f64": self.raw_physical_le_f64.hex(),
            "provisional_canonical_le_f64": self.provisional_canonical_le_f64.hex(),
            "lshade_input_genotype_le_f64": self.lshade_input_genotype_le_f64.hex(),
            "lshade_reconstructed_le_f64": self.lshade_reconstructed_le_f64.hex(),
            "sealed_physical_le_f64": self.sealed_physical_le_f64.hex(),
            "canonical_key_schema": _KEY_SCHEMA,
            "canonical_key_f64be": list(self.canonical_key_f64be),
            "de_initial_physical_le_f64": self.de_initial_physical_le_f64.hex(),
            "de_phenotype_genotype_le_f64": self.de_phenotype_genotype_le_f64.hex(),
        }


def _population_hashes(
    pair_identity_id: str,
    topology: str,
    design_space_sha256: str,
    members: tuple[PopulationMember, ...],
) -> tuple[str, str]:
    identity_header = canonical_json_bytes({
        "schema": "stage5a2_population_seal_v1",
        "pair_identity_id": pair_identity_id,
        "sampler_version": SAMPLER_VERSION,
        "topology": topology,
        "design_space_sha256": design_space_sha256,
        "dimension": members[0].dimension,
        "member_count": POPULATION_SIZE,
    })
    population_payload = (
        b"sawopt-stage5a2-lshade-image-population-v2\0"
        + identity_header + b"\0"
        + b"".join(member.sealed_physical_le_f64 for member in members)
        + b"".join(_key_bytes(member.canonical_key_f64be) for member in members)
    )
    representation_payload = canonical_json_bytes({
        "schema": "stage5a2_population_representation_v1",
        "members": [member.representation_record() for member in members],
    })
    return (
        hashlib.sha256(population_payload).hexdigest(),
        hashlib.sha256(b"sawopt-stage5a2-population-representation-v1\0" + representation_payload).hexdigest(),
    )


@dataclass(frozen=True, slots=True)
class PopulationSeal:
    pair_identity_id: str
    topology: str
    design_space_sha256: str
    members: tuple[PopulationMember, ...]
    sampler_version: str
    draws: int
    duplicate_rejections: int
    geometry_rejections: int
    population_sha256: str
    representation_sha256: str

    def __post_init__(self) -> None:
        if type(self.pair_identity_id) is not str or len(self.pair_identity_id) != 64:
            raise ValueError("population seal must bind a pair identity SHA-256")
        if self.topology not in {"D", "P_D", "D_P", "P_D_P"}:
            raise ValueError("population seal topology is unsupported")
        for value in (self.pair_identity_id, self.design_space_sha256, self.population_sha256, self.representation_sha256):
            if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("population seal identities must be lowercase SHA-256 hex digests")
        if len(self.design_space_sha256) != 64 or len(self.population_sha256) != 64 or len(self.representation_sha256) != 64:
            raise ValueError("population seal identities must be SHA-256 hex digests")
        try:
            for value in (self.design_space_sha256, self.population_sha256, self.representation_sha256):
                bytes.fromhex(value)
        except ValueError as exc:
            raise ValueError("population seal identities must be hexadecimal") from exc
        if type(self.members) is not tuple or any(not isinstance(member, PopulationMember) for member in self.members):
            raise ValueError("population members must be immutable typed records")
        if len(self.members) != POPULATION_SIZE:
            raise ValueError(f"population seal must contain exactly {POPULATION_SIZE} members")
        if tuple(member.ordinal for member in self.members) != tuple(range(POPULATION_SIZE)):
            raise ValueError("population member ordinals must be complete and ordered")
        if len({member.dimension for member in self.members}) != 1:
            raise ValueError("population members must have one common dimension")
        if self.sampler_version != SAMPLER_VERSION:
            raise ValueError("unexpected initializer sampler version")
        if any(type(value) is not int or value < 0 for value in (
            self.draws, self.duplicate_rejections, self.geometry_rejections,
        )):
            raise ValueError("sampler counters must be non-negative integers")
        if self.draws != POPULATION_SIZE + self.duplicate_rejections + self.geometry_rejections:
            raise ValueError("sampler draw counters do not reconcile")
        if self.draws > MAX_DRAWS:
            raise ValueError("sampler draw count exceeds the frozen 10,000-call limit")
        equality_keys = {
            tuple(float(value) for value in np.frombuffer(member.sealed_physical_le_f64, dtype="<f8"))
            for member in self.members
        }
        if len(equality_keys) != POPULATION_SIZE:
            raise ValueError("sealed population contains duplicate final evaluator keys")
        expected_population, expected_representation = _population_hashes(
            self.pair_identity_id, self.topology, self.design_space_sha256, self.members,
        )
        if self.population_sha256 != expected_population or self.representation_sha256 != expected_representation:
            raise ValueError("population or representation seal hash does not match its ordered records")

    @property
    def dimension(self) -> int:
        return self.members[0].dimension

    def record(self) -> dict[str, Any]:
        return {
            "schema": "stage5a2_population_seal_v1",
            "pair_identity_id": self.pair_identity_id,
            "sampler_version": self.sampler_version,
            "topology": self.topology,
            "design_space_sha256": self.design_space_sha256,
            "dimension": self.dimension,
            "member_count": len(self.members),
            "members_le_f64": [member.sealed_physical_le_f64.hex() for member in self.members],
            "keys_f64be": [list(member.canonical_key_f64be) for member in self.members],
            "population_sha256": self.population_sha256,
            "representation_sha256": self.representation_sha256,
            "draws": self.draws,
            "duplicate_rejections": self.duplicate_rejections,
            "geometry_rejections": self.geometry_rejections,
        }


@dataclass(frozen=True, slots=True)
class PopulationAttachment:
    cell_identity_id: str
    population_sha256: str
    representation_sha256: str
    event_hash: str


@dataclass(frozen=True, slots=True)
class PreflightCertificate:
    role: Literal["lshade", "controlled_de"]
    cell_identity_id: str
    population_sha256: str
    representation_sha256: str
    member_count: int
    ordered_vector_key_sha256: str
    certificate_sha256: str


@dataclass(frozen=True, slots=True)
class SyntheticPreflightEvidence:
    """Non-authoritative synthetic evidence; it can never authorize an FE."""

    pair_identity_id: str
    population_sha256: str
    representation_sha256: str
    lshade_certificate_sha256: str
    controlled_de_certificate_sha256: str


def _key_from_vector(vector: np.ndarray, key: Sequence[float]) -> tuple[str, ...]:
    if len(key) != len(vector):
        raise InitializationError("canonical key dimension differs from evaluator vector")
    tokens = canonical_key_tokens(key)
    if tokens != canonical_key_tokens(vector):
        raise InitializationError("canonical key does not encode its canonical evaluator vector")
    return tokens


def _make_member(
    ordinal: int,
    raw: np.ndarray,
    provisional: np.ndarray,
    genotype: np.ndarray,
    reconstructed: np.ndarray,
    sealed: np.ndarray,
    key: Sequence[float],
    metadata: DesignSpaceMetadata,
    normalize: Callable[[np.ndarray], np.ndarray],
) -> PopulationMember:
    de_genotype = np.asarray(normalize(sealed.copy()), dtype=np.float64)
    return PopulationMember(
        ordinal=ordinal,
        raw_physical_le_f64=_vector_bytes(raw, metadata.dimension),
        provisional_canonical_le_f64=_vector_bytes(provisional, metadata.dimension),
        lshade_input_genotype_le_f64=_vector_bytes(genotype, metadata.dimension),
        lshade_reconstructed_le_f64=_vector_bytes(reconstructed, metadata.dimension),
        sealed_physical_le_f64=_vector_bytes(sealed, metadata.dimension),
        canonical_key_f64be=_key_from_vector(sealed, key),
        de_initial_physical_le_f64=_vector_bytes(sealed, metadata.dimension),
        de_phenotype_genotype_le_f64=_vector_bytes(de_genotype, metadata.dimension),
    )


def _seal(
    pair_identity_id: str,
    metadata: DesignSpaceMetadata,
    members: tuple[PopulationMember, ...],
    draws: int,
    duplicate_rejections: int,
    geometry_rejections: int,
) -> PopulationSeal:
    population_hash, representation_hash = _population_hashes(
        pair_identity_id, metadata.topology, metadata.design_space_sha256, members,
    )
    return PopulationSeal(
        pair_identity_id, metadata.topology, metadata.design_space_sha256, members, SAMPLER_VERSION, draws,
        duplicate_rejections, geometry_rejections, population_hash, representation_hash,
    )


def _verify_metadata_scope(metadata: DesignSpaceMetadata, pair: PairIdentity, genesis: GenesisCoordinator) -> None:
    if pair.identity_scope != genesis.identity_scope:
        raise InitializationGateError("design-space/pair identity scope differs from the genesis path")
    if pair.identity_scope == "synthetic_test":
        return
    try:
        from .production_identity import Q0ProductionIdentityManifest

        manifest = Q0ProductionIdentityManifest.from_bytes(pair.production_manifest_json)
        expected = manifest.metadata_record()
    except (TypeError, ValueError) as exc:
        raise InitializationGateError(f"Q0 production design-space identity is invalid: {exc}") from exc
    actual_bounds = np.asarray(metadata.bounds, dtype="<f8").tobytes().hex()
    if (
        metadata.topology != expected["topology"]
        or metadata.variable_names != tuple(expected["variable_names"])
        or actual_bounds != expected["bounds_le_f64_hex"]
        or metadata.integer_indices != tuple(expected["integer_indices"])
        or metadata.units != tuple(expected["units"])
        or metadata.design_space_sha256 != expected["design_space_sha256"]
        or metadata.dimension != expected["dimension"]
    ):
        raise InitializationGateError("production metadata differs from the complete frozen Q0 design-space identity")


def _check_ready(readiness: GenesisReady | None, pair_identity_id: str) -> None:
    if not isinstance(readiness, GenesisReady):
        raise InitializationGateError("sampler RNG is forbidden before verified G4 readiness")
    if readiness.pair_identity_id != pair_identity_id or not readiness.barrier_event_hash:
        raise InitializationGateError("G4 readiness token belongs to another pair or lacks barrier proof")
    if len(readiness.cell_identity_ids) != 2 or any(len(item) != 64 for item in readiness.cell_identity_ids):
        raise InitializationGateError("G4 readiness token has invalid arm identities")


def sample_initial_population(
    *,
    metadata: DesignSpaceMetadata,
    pair_identity: PairIdentity,
    genesis: GenesisCoordinator,
    rng: RNGCallService,
    canonicalize: Callable[[Sequence[float]], tuple[np.ndarray, tuple[float, ...]]] | None = None,
    normalize: Callable[[np.ndarray], np.ndarray],
    physical: Callable[[np.ndarray], np.ndarray],
    geometry_valid: Callable[[np.ndarray], bool],
    after_draw_commit: Callable[[int], None] | None = None,
) -> PopulationSeal:
    """Construct the exact 234-member L-SHADE-image seal; never use fitness."""
    # Reject wrong production dimensions/bounds/grids before touching genesis
    # journals or making any sampler RNG call.
    _verify_metadata_scope(metadata, pair_identity, genesis)
    if (
        pair_identity.topology != metadata.topology
        or pair_identity.design_space_sha256 != metadata.design_space_sha256
        or pair_identity.sampler_version != SAMPLER_VERSION
    ):
        raise InitializationGateError("sampler metadata does not match the immutable pair identity")
    try:
        readiness = genesis.require_ready(pair_identity)
    except (GenesisError, JournalError) as exc:
        raise InitializationGateError("sampler RNG is forbidden before verified durable G4 readiness") from exc
    _check_ready(readiness, pair_identity.identity_id)  # checked before any sampler call
    if rng.journal.journal_uuid != pair_identity.pair_journal_uuid or rng.journal.owner_kind != "pair":
        raise InitializationGateError("common sampler RNG must be owned by the pair journal")
    seed = derive_seed32(
        role="common_init", root_seed=pair_identity.root_seed,
        topology=pair_identity.topology, design_space_hash=pair_identity.design_space_sha256,
    )
    expected_generator = np.random.Generator(np.random.PCG64(seed))
    stream_initial_state = getattr(rng, "initial_state", None)
    if stream_initial_state is None:
        stream_initial_state = pcg64_state(rng.generator)
    if stream_initial_state != pcg64_state(expected_generator):
        raise InitializationGateError("common sampler PCG64 stream does not match the immutable pair seed")
    pair_identity_id = pair_identity.identity_id
    canonicalizer = canonicalize or (
        lambda value: canonicalize_hybrid_vector(
            value, bounds=metadata.bounds_array(), integer_indices=metadata.integer_indices,
            dimension=metadata.dimension, topology=metadata.topology,
        )
    )
    bounds = metadata.bounds_array()
    low, high = bounds[:, 0], bounds[:, 1]
    accepted: list[PopulationMember] = []
    seen: set[tuple[float, ...]] = set()
    draws = duplicates = geometry_rejections = 0
    for draw_index in range(MAX_DRAWS):
        draws = draw_index + 1
        call = RNGCallIdentity(
            owner_identity_id=pair_identity_id,
            role="common_sampler",
            step_id=f"sampler-draw-{draw_index}",
            cursor=(draw_index,),
            ordinal=draw_index,
        )
        raw = np.asarray(rng.call(call, "uniform", low, high), dtype=np.float64)
        if raw.shape != (metadata.dimension,) or not np.isfinite(raw).all():
            raise InitializationError("PCG64 uniform sampler returned an invalid physical vector")
        provisional, _provisional_key = canonicalizer(raw)
        genotype = np.asarray(normalize(provisional.copy()), dtype=np.float64)
        reconstructed = np.asarray(physical(genotype.copy()), dtype=np.float64)
        sealed, key = canonicalizer(reconstructed)
        sealed = np.asarray(sealed, dtype=np.float64)
        key_tokens = _key_from_vector(sealed, key)
        representation = {
            "raw_physical_le_f64": _vector_bytes(raw, metadata.dimension).hex(),
            "provisional_canonical_le_f64": _vector_bytes(provisional, metadata.dimension).hex(),
            "lshade_input_genotype_le_f64": _vector_bytes(genotype, metadata.dimension).hex(),
            "lshade_reconstructed_le_f64": _vector_bytes(reconstructed, metadata.dimension).hex(),
            "sealed_physical_le_f64": _vector_bytes(sealed, metadata.dimension).hex(),
            "canonical_key_f64be": list(key_tokens),
        }
        equality_key = tuple(float(value) for value in key)
        if equality_key in seen:
            duplicates += 1
            classification = "duplicate_reject"
        elif not geometry_valid(sealed.copy()):
            geometry_rejections += 1
            classification = "geometry_reject"
        else:
            member = _make_member(
                len(accepted), raw, provisional, genotype, reconstructed, sealed, key,
                metadata, normalize,
            )
            accepted.append(member)
            seen.add(equality_key)
            classification = "accepted"
        rng.journal.append_event(
            f"SAMPLER_DRAW:{pair_identity_id}:{draw_index}",
            "SAMPLER_DRAW",
            {
                "pair_identity_id": pair_identity_id,
                "draw_index": draw_index,
                "classification": classification,
                "accepted_index": len(accepted) - 1 if classification == "accepted" else None,
                "representations": representation,
                "counters": {
                    "draws": draws,
                    "accepted": len(accepted),
                    "duplicate_rejections": duplicates,
                    "geometry_rejections": geometry_rejections,
                },
            },
        )
        if after_draw_commit is not None:
            after_draw_commit(draw_index)
        if len(accepted) == POPULATION_SIZE:
            seal = _seal(pair_identity_id, metadata, tuple(accepted), draws, duplicates, geometry_rejections)
            rng.journal.append_event(
                f"POPULATION_ATTACHMENT_SEALED:{pair_identity_id}:{seal.population_sha256}",
                "POPULATION_ATTACHMENT_SEALED",
                seal.record(),
            )
            return seal
    failure = {
        "pair_identity_id": pair_identity_id,
        "status": "INITIALIZATION_FAILED",
        "draws": draws,
        "accepted": len(accepted),
        "duplicate_rejections": duplicates,
        "geometry_rejections": geometry_rejections,
        "max_draws": MAX_DRAWS,
    }
    rng.journal.append_event(
        f"INITIALIZATION_FAILED:{pair_identity_id}:{MAX_DRAWS}",
        "INITIALIZATION_FAILED", failure,
    )
    raise InitializationError(
        f"initialization exhausted {MAX_DRAWS} draws with {len(accepted)} accepted members"
    )


def _attachment_event_id(cell: CellIdentity, seal: PopulationSeal) -> str:
    return f"POPULATION_ATTACHMENT_ATTACHED:{cell.identity_id}:{seal.population_sha256}:{seal.representation_sha256}"


def _attachment_payload(cell: CellIdentity, seal: PopulationSeal) -> dict[str, Any]:
    return {
        "schema": "stage5a2_population_attachment_v1",
        "event": "POPULATION_ATTACHMENT_ATTACHED",
        "cell_identity_id": cell.identity_id,
        "pair_identity_id": seal.pair_identity_id,
        "role": cell.role,
        "population_sha256": seal.population_sha256,
        "representation_sha256": seal.representation_sha256,
        "population_member_count": len(seal.members),
    }


def _verify_population_attachment(
    *, cell: CellIdentity, journal: SQLiteJournal, seal: PopulationSeal,
) -> None:
    if journal.journal_uuid != cell.cell_journal_uuid or journal.owner_kind != cell.role:
        raise InitializationError("arm journal does not match its immutable cell identity")
    if journal.get_immutable_record("cell_identity", cell.identity_id) != cell.canonical_bytes:
        raise InitializationError("arm journal lacks the exact Phase-I cell identity")
    for _ in journal.iter_events():  # validate the complete cell event hash chain
        pass
    event = journal.get_event(_attachment_event_id(cell, seal))
    if (
        event is None or event["event_type"] != "POPULATION_ATTACHMENT_ATTACHED"
        or event["payload"] != _attachment_payload(cell, seal)
    ):
        raise InitializationError("arm lacks an exact durable Phase-II population attachment")


def attach_population(
    *, cell: CellIdentity, journal: SQLiteJournal, pair_journal: SQLiteJournal, seal: PopulationSeal,
) -> PopulationAttachment:
    """Append the Phase-II attachment without mutating Phase-I identity bytes."""
    if cell.pair_identity_id != seal.pair_identity_id:
        raise InitializationError("Phase-II population seal belongs to a different pair identity")
    if pair_journal.journal_uuid != cell.pair_journal_uuid or pair_journal.owner_kind != "pair":
        raise InitializationError("population seal must be owned by its immutable pair journal")
    pair_bytes = pair_journal.get_immutable_record("pair_identity", cell.pair_identity_id)
    if (
        pair_bytes is None
        or hashlib.sha256(pair_bytes).hexdigest() != cell.pair_identity_sha256
        or hashlib.sha256(b"sawopt-stage5a2-pair-identity-v2\0" + pair_bytes).hexdigest() != cell.pair_identity_id
    ):
        raise InitializationError("pair journal lacks the exact reciprocal Phase-I identity")
    for _ in pair_journal.iter_events():  # verify the complete pair chain
        pass
    sealed = pair_journal.get_event(
        f"POPULATION_ATTACHMENT_SEALED:{seal.pair_identity_id}:{seal.population_sha256}"
    )
    if sealed is None or sealed["event_type"] != "POPULATION_ATTACHMENT_SEALED" or sealed["payload"] != seal.record():
        raise InitializationError("population seal is not durably owned by its pair journal")
    if journal.journal_uuid != cell.cell_journal_uuid or journal.owner_kind != cell.role:
        raise InitializationError("arm journal does not match its immutable cell identity")
    stored = journal.get_immutable_record("cell_identity", cell.identity_id)
    if stored != cell.canonical_bytes:
        raise InitializationError("cannot attach a population to an unverified Phase-I cell identity")
    payload = _attachment_payload(cell, seal)
    event = journal.append_event(_attachment_event_id(cell, seal), "POPULATION_ATTACHMENT_ATTACHED", payload)
    return PopulationAttachment(
        cell.identity_id, seal.population_sha256, seal.representation_sha256, event.event_hash,
    )


def _ordered_vector_key_digest(observed: Sequence[tuple[bytes, tuple[str, ...]]]) -> str:
    digest = hashlib.sha256()
    digest.update(b"sawopt-stage5a2-preflight-vector-key-v1\0")
    for vector, key in observed:
        digest.update(len(vector).to_bytes(8, "big"))
        digest.update(vector)
        digest.update(_key_bytes(key))
    return digest.hexdigest()


def _sealed_vector_key_digest(seal: PopulationSeal) -> str:
    return _ordered_vector_key_digest([
        (member.sealed_physical_le_f64, member.canonical_key_f64be)
        for member in seal.members
    ])


def _certificate_body(
    role: str, cell_identity_id: str, seal: PopulationSeal, ordered_digest: str,
) -> dict[str, Any]:
    return {
        "schema": "stage5a2_preflight_certificate_v1",
        "pair_identity_id": seal.pair_identity_id,
        "role": role,
        "cell_identity_id": cell_identity_id,
        "population_sha256": seal.population_sha256,
        "representation_sha256": seal.representation_sha256,
        "member_count": len(seal.members),
        "ordered_vector_key_sha256": ordered_digest,
    }


def _certificate(
    role: Literal["lshade", "controlled_de"], cell: CellIdentity, seal: PopulationSeal,
    observed: list[tuple[bytes, tuple[str, ...]]],
) -> PreflightCertificate:
    digest_value = _ordered_vector_key_digest(observed)
    body = _certificate_body(role, cell.identity_id, seal, digest_value)
    return PreflightCertificate(
        role, cell.identity_id, seal.population_sha256, seal.representation_sha256,
        len(seal.members), digest_value,
        hashlib.sha256(b"sawopt-stage5a2-preflight-certificate-v1\0" + canonical_json_bytes(body)).hexdigest(),
    )


def preflight_lshade(
    seal: PopulationSeal,
    cell: CellIdentity,
    *,
    physical: Callable[[np.ndarray], np.ndarray],
    canonicalize: Callable[[Sequence[float]], tuple[np.ndarray, tuple[float, ...]]],
) -> PreflightCertificate:
    """Recreate actual L-SHADE evaluator inputs from stored normalized genotypes."""
    if cell.role != "lshade" or cell.pair_identity_id != seal.pair_identity_id:
        raise InitializationError("L-SHADE preflight received the wrong Phase-I cell identity")
    observed = []
    for member in seal.members:
        genotype = _vector_from_bytes(member.lshade_input_genotype_le_f64, seal.dimension)
        reconstructed = np.asarray(physical(genotype.copy()), dtype=np.float64)
        actual, key = canonicalize(reconstructed.copy())
        actual = np.asarray(actual, dtype=np.float64)
        actual_bytes = _vector_bytes(actual, seal.dimension)
        tokens = _key_from_vector(actual, key)
        if actual_bytes != member.sealed_physical_le_f64 or tokens != member.canonical_key_f64be:
            raise InitializationError(f"L-SHADE preflight mismatch at member {member.ordinal}")
        observed.append((actual_bytes, tokens))
    return _certificate("lshade", cell, seal, observed)


def preflight_controlled_de(
    seal: PopulationSeal,
    cell: CellIdentity,
    *,
    canonicalize: Callable[[Sequence[float]], tuple[np.ndarray, tuple[float, ...]]],
    normalize: Callable[[np.ndarray], np.ndarray],
) -> PreflightCertificate:
    """Verify DE's direct sealed-physical initialization path and genotype."""
    if cell.role != "controlled_de" or cell.pair_identity_id != seal.pair_identity_id:
        raise InitializationError("DE preflight received the wrong Phase-I cell identity")
    observed = []
    for member in seal.members:
        physical_input = _vector_from_bytes(member.de_initial_physical_le_f64, seal.dimension)
        actual, key = canonicalize(physical_input.copy())
        actual = np.asarray(actual, dtype=np.float64)
        actual_bytes = _vector_bytes(actual, seal.dimension)
        tokens = _key_from_vector(actual, key)
        if actual_bytes != member.sealed_physical_le_f64 or tokens != member.canonical_key_f64be:
            raise InitializationError(f"Controlled DE preflight mismatch at member {member.ordinal}")
        genotype = np.asarray(normalize(actual.copy()), dtype=np.float64)
        if _vector_bytes(genotype, seal.dimension) != member.de_phenotype_genotype_le_f64:
            raise InitializationError(f"Controlled DE genotype preflight mismatch at member {member.ordinal}")
        observed.append((actual_bytes, tokens))
    return _certificate("controlled_de", cell, seal, observed)


def persist_both_preflight_certificates(
    *,
    seal: PopulationSeal,
    pair_identity_id: str,
    cells: tuple[CellIdentity, CellIdentity],
    journals: tuple[SQLiteJournal, SQLiteJournal],
    lshade_certificate: PreflightCertificate,
    controlled_de_certificate: PreflightCertificate,
) -> SyntheticPreflightEvidence:
    """Persist synthetic-only preflight evidence; it is not FE authorization."""
    if type(cells) is not tuple or len(cells) != 2 or tuple(cell.role for cell in cells) != ("lshade", "controlled_de"):
        raise InitializationError("cells must be ordered L-SHADE then controlled DE")
    if type(journals) is not tuple or len(journals) != 2:
        raise InitializationError("both separate arm journals are required")
    by_role = {cell.role: (cell, journal) for cell, journal in zip(cells, journals)}
    if pair_identity_id != seal.pair_identity_id:
        raise InitializationError("population seal belongs to a different pair identity")
    if any(cell.pair_identity_id != pair_identity_id for cell in cells):
        raise InitializationError("Phase-I cells do not reference the expected pair identity")
    certificates = {"lshade": lshade_certificate, "controlled_de": controlled_de_certificate}
    if set(by_role) != {"lshade", "controlled_de"}:
        raise InitializationError("both distinct Phase-I arm identities are required")
    for role in ("lshade", "controlled_de"):
        cell, journal = by_role[role]
        cert = certificates[role]
        expected_digest = _sealed_vector_key_digest(seal)
        expected_certificate = hashlib.sha256(
            b"sawopt-stage5a2-preflight-certificate-v1\0"
            + canonical_json_bytes(_certificate_body(role, cell.identity_id, seal, expected_digest))
        ).hexdigest()
        if (
            cert.role != role or cert.cell_identity_id != cell.identity_id
            or cert.population_sha256 != seal.population_sha256
            or cert.representation_sha256 != seal.representation_sha256
            or cert.member_count != POPULATION_SIZE
            or cert.ordered_vector_key_sha256 != expected_digest
            or cert.certificate_sha256 != expected_certificate
        ):
            raise InitializationError(f"{role} certificate does not bind the sealed population and Phase-I cell")
        try:
            _verify_population_attachment(cell=cell, journal=journal, seal=seal)
        except InitializationError as exc:
            raise InitializationError(f"{role} certificate lacks verified Phase-I/II records: {exc}") from exc
    # Compare the supplied synthetic claims before recording them. This only
    # proves consistency with the seal; it does not prove either real optimizer
    # transformation ran or authorize any evaluator call.
    if lshade_certificate.ordered_vector_key_sha256 != controlled_de_certificate.ordered_vector_key_sha256:
        raise InitializationError("the two arm preflight inputs differ; both arms remain blocked before FE")
    for role in ("lshade", "controlled_de"):
        cert = certificates[role]
        payload = {
            "schema": "stage5a2_preflight_certificate_v1",
            "pair_identity_id": pair_identity_id,
            "role": role,
            "cell_identity_id": cert.cell_identity_id,
            "population_sha256": cert.population_sha256,
            "representation_sha256": cert.representation_sha256,
            "member_count": cert.member_count,
            "ordered_vector_key_sha256": cert.ordered_vector_key_sha256,
            "certificate_sha256": cert.certificate_sha256,
        }
        by_role[role][1].append_event(
            f"INITIALIZATION_PREFLIGHT_CERTIFICATE:{cert.cell_identity_id}:{cert.certificate_sha256}",
            "INITIALIZATION_PREFLIGHT_CERTIFICATE", payload,
        )
    return require_both_preflight_certificates(
        seal=seal, pair_identity_id=pair_identity_id, cells=cells, journals=journals,
    )


def require_both_preflight_certificates(
    *,
    seal: PopulationSeal,
    pair_identity_id: str,
    cells: tuple[CellIdentity, CellIdentity],
    journals: tuple[SQLiteJournal, SQLiteJournal],
) -> SyntheticPreflightEvidence:
    """Read back matching synthetic evidence without authorizing evaluation."""
    found: dict[str, dict[str, Any]] = {}
    if pair_identity_id != seal.pair_identity_id:
        raise InitializationGateError("population seal belongs to a different pair identity")
    if any(cell.pair_identity_id != pair_identity_id for cell in cells):
        raise InitializationGateError("Phase-I cells do not reference the expected pair identity")
    if type(cells) is not tuple or len(cells) != 2 or tuple(cell.role for cell in cells) != ("lshade", "controlled_de"):
        raise InitializationGateError("both ordered Phase-I arm identities are required")
    if type(journals) is not tuple or len(journals) != 2:
        raise InitializationGateError("both separate arm journals are required")
    for cell, journal in zip(cells, journals):
        try:
            _verify_population_attachment(cell=cell, journal=journal, seal=seal)
        except InitializationError as exc:
            raise InitializationGateError(f"verified Phase-I/II attachment is required: {exc}") from exc
        events = [
            event.payload for event in journal.iter_events()
            if event.event_type == "INITIALIZATION_PREFLIGHT_CERTIFICATE"
            and event.payload.get("cell_identity_id") == cell.identity_id
        ]
        if len(events) != 1:
            raise InitializationGateError("both durable arm preflight certificates are required before FE")
        payload = events[0]
        expected_digest = _sealed_vector_key_digest(seal)
        expected_certificate = hashlib.sha256(
            b"sawopt-stage5a2-preflight-certificate-v1\0"
            + canonical_json_bytes(_certificate_body(cell.role, cell.identity_id, seal, expected_digest))
        ).hexdigest()
        if (
            payload.get("pair_identity_id") != pair_identity_id
            or payload.get("role") != cell.role
            or payload.get("population_sha256") != seal.population_sha256
            or payload.get("representation_sha256") != seal.representation_sha256
            or payload.get("member_count") != POPULATION_SIZE
            or payload.get("ordered_vector_key_sha256") != expected_digest
            or payload.get("certificate_sha256") != expected_certificate
        ):
            raise InitializationGateError("durable arm preflight certificate does not match the population seal")
        found[cell.role] = payload
    if set(found) != {"lshade", "controlled_de"}:
        raise InitializationGateError("both arm certificates are required")
    lshade, controlled = found["lshade"], found["controlled_de"]
    if lshade["ordered_vector_key_sha256"] != controlled["ordered_vector_key_sha256"]:
        raise InitializationGateError("durable arm evaluator-input certificates disagree")
    return SyntheticPreflightEvidence(
        pair_identity_id, seal.population_sha256, seal.representation_sha256,
        lshade["certificate_sha256"], controlled["certificate_sha256"],
    )


def dispatch_initial_evaluation(
    readiness: SyntheticPreflightEvidence,
    *,
    role: Literal["lshade", "controlled_de"],
    seal: PopulationSeal,
    member: PopulationMember,
    cells: tuple[CellIdentity, CellIdentity],
    journals: tuple[SQLiteJournal, SQLiteJournal],
    evaluator: Callable[[np.ndarray], Any],
) -> Any:
    """Disable Q1-A FE dispatch until the actual B/C paths are integrated.

    Seal-derived synthetic certificates cannot prove execution of either real
    optimizer transformation path, so this API intentionally has no evaluator
    authorization capability in Q1-A.
    """
    del readiness, role, seal, member, cells, journals, evaluator
    raise InitializationGateError(
        "Q1-A synthetic preflight evidence cannot authorize evaluator calls; actual B/C path qualification is pending"
    )


__all__ = [
    "DesignSpaceMetadata", "InitializationError",
    "InitializationGateError", "POPULATION_SIZE", "PopulationAttachment", "PopulationMember",
    "PopulationSeal", "PreflightCertificate", "SAMPLER_VERSION", "attach_population",
    "canonical_key_tokens", "dispatch_initial_evaluation", "persist_both_preflight_certificates",
    "preflight_controlled_de", "preflight_lshade", "require_both_preflight_certificates",
    "SyntheticPreflightEvidence",
    "sample_initial_population",
]
