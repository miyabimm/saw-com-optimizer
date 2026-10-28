"""Q1-BC common, synthetic-only two-arm boundary (not a study dispatcher)."""
from __future__ import annotations

import hashlib

import numpy as np

from sawopt.design.canonicalization import canonicalize_hybrid_vector
from sawopt.optimization.controlled_de import ControlledDEBackend
from sawopt.optimization.lshade import LShadeBackend
from sawopt.optimization.selection import GeometryFirstComparator

from .arm import ArmSession
from .codec import encode_typed
from .identity import CellIdentity
from .initialization import (
    InitializationError, PopulationSeal, attach_population, canonical_key_tokens,
    _make_member,
    persist_both_preflight_certificates, preflight_controlled_de,
    preflight_lshade, require_both_preflight_certificates, sample_initial_population,
)
from .journal import SQLiteJournal
from .production_identity import Q0_BOUNDS_LE_F64_HEX, Q0_VARIABLE_NAMES, Q0_VARIABLE_UNITS
from .rng import RNGCallService, derive_seed32

LSHADE_CONFIG = {
    "initial_population": 234, "min_population": 4, "history_size": 6,
    "pbest_max_fraction": .20, "archive_rate": 1., "max_duplicate_retries": 5,
    "total_budget": 4096, "hard_max_budget": 4096,
    "population_schedule_terminal_budget": 4096, "memory_update_batch_size": 234,
    "compact_history_cache": True, "historical_finalist_count": 16,
}
DE_CONFIG = {"algorithm": "DE/rand/1/bin", "population": 234, "F": .5, "CR": .9,
             "budget": 4096, "target_proposal_limit": 4096, "no_progress_limit": 65536}


def arm_config_hashes():
    return tuple((role, hashlib.sha256(encode_typed(config)).hexdigest())
                 for role, config in (("lshade", LSHADE_CONFIG), ("controlled_de", DE_CONFIG)))


def _existing_seal(journal, pair, metadata, normalize):
    """Load a completed immutable seal without re-entering the sampler."""
    events = journal.events()
    seals = [event.payload for event in events if event.event_type == "POPULATION_ATTACHMENT_SEALED"]
    if not seals:
        return None
    if len(seals) != 1:
        raise InitializationError("conflicting population seals")
    sealed = seals[0]
    members = []
    for event in events:
        if event.event_type != "SAMPLER_DRAW" or event.payload["classification"] != "accepted":
            continue
        row = event.payload["representations"]
        arrays = [np.frombuffer(bytes.fromhex(row[name]), dtype="<f8").copy() for name in (
            "raw_physical_le_f64", "provisional_canonical_le_f64", "lshade_input_genotype_le_f64",
            "lshade_reconstructed_le_f64", "sealed_physical_le_f64")]
        member = _make_member(len(members), *arrays, tuple(arrays[-1]), metadata, normalize)
        members.append(member)
    result = PopulationSeal(pair.identity_id, pair.topology, metadata.design_space_sha256, tuple(members),
                            pair.sampler_version, sealed["draws"], sealed["duplicate_rejections"],
                            sealed["geometry_rejections"], sealed["population_sha256"], sealed["representation_sha256"])
    if result.record() != sealed:
        raise InitializationError("durable seal differs from its representation rows")
    return result


def prepare_pair(*, pair, genesis, metadata, geometry_valid, evaluators):
    """Seal and qualify BOTH actual input paths before returning either arm.

    The two explicitly injected evaluators are private synthetic fixtures. This
    function does not execute search, validation, a 12-cell matrix or production.
    """
    if pair.identity_scope != "synthetic_test" or pair.topology not in {"P_D", "D_P"} or metadata.dimension != 13:
        raise ValueError("Q1-BC requires a synthetic 13-variable P_D/D_P pair")
    if (pair.root_seed not in (20261012, 20261013, 20261014)
            or metadata.topology != pair.topology
            or metadata.bounds_array().astype("<f8").tobytes().hex() != Q0_BOUNDS_LE_F64_HEX[pair.topology]
            or metadata.variable_names != Q0_VARIABLE_NAMES or metadata.units != Q0_VARIABLE_UNITS
            or metadata.integer_indices != (4, 5, 6, 11)):
        raise ValueError("Q1-BC metadata differs from the Q0-frozen hybrid contract")
    if pair.arm_config_hashes != arm_config_hashes():
        raise ValueError("pair does not bind the frozen Q1-BC arm settings")
    if type(evaluators) is not tuple or len(evaluators) != 2 or not all(callable(e) for e in evaluators):
        raise ValueError("two explicitly injected synthetic evaluators are required")
    bounds = metadata.bounds_array()
    canonicalize = lambda value: canonicalize_hybrid_vector(
        value, bounds=bounds, integer_indices=metadata.integer_indices,
        dimension=13, topology=metadata.topology,
    )
    seeds = tuple(derive_seed32(role=role, root_seed=pair.root_seed, topology=pair.topology,
                               design_space_hash=metadata.design_space_sha256)
                  for role in ("common_init", "optimizer_lshade", "optimizer_controlled_de"))
    lshade = LShadeBackend(bounds, seed=seeds[1], config=LSHADE_CONFIG,
                          canonicalizer=canonicalize, integer_indices=metadata.integer_indices,
                          comparator=GeometryFirstComparator(), source_config_fingerprint=pair.config_sha256)
    de = ControlledDEBackend(bounds, seed=seeds[2], canonicalizer=canonicalize)
    genesis.reconcile(pair)
    genesis.require_ready(pair)  # durable G4 before sampler construction/draw
    cells = tuple(CellIdentity(
        cell_journal_uuid=dict(pair.cell_journal_uuids)[role], pair_journal_uuid=pair.pair_journal_uuid,
        pair_identity_id=pair.identity_id, pair_identity_sha256=pair.identity_sha256,
        role=role, arm_config_sha256=dict(pair.arm_config_hashes)[role], environment_sha256=pair.environment_sha256,
    ) for role in ("lshade", "controlled_de"))
    pair_journal = SQLiteJournal(genesis.pair_path, pair.pair_journal_uuid, "pair", create=False)
    journals = tuple(SQLiteJournal(path, cell.cell_journal_uuid, cell.role, create=False)
                     for path, cell in zip(genesis.cell_paths, cells))
    seal = _existing_seal(pair_journal, pair, metadata, lshade._normalize)
    if seal is None:
        sampler = RNGCallService(np.random.Generator(np.random.PCG64(seeds[0])), pair_journal,
                                 genesis=genesis, pair_identity=pair, synthetic_test=True, synthetic_test_seed=seeds[0])
        seal = sample_initial_population(metadata=metadata, pair_identity=pair, genesis=genesis,
                                         rng=sampler, canonicalize=canonicalize, normalize=lshade._normalize,
                                         physical=lshade._physical, geometry_valid=geometry_valid)
    for cell, journal in zip(cells, journals):
        attach_population(cell=cell, journal=journal, pair_journal=pair_journal, seal=seal)
    # Exercise the very methods used by backend evaluation, including copies,
    # hard-bound validation and canonical keys, not just a seal-derived claim.
    inputs = [[], []]
    for member in seal.members:
        gl = np.frombuffer(member.lshade_input_genotype_le_f64, dtype="<f8").copy()
        gd = np.frombuffer(member.de_initial_physical_le_f64, dtype="<f8").copy()
        for backend, value in ((lshade, gl), (de, gd)):
            actual, key = backend._canonical(value) if backend is lshade else backend.initial_input(value)
            argument = actual.copy()
            if (argument.tobytes() != member.sealed_physical_le_f64
                    or canonical_key_tokens(key) != member.canonical_key_f64be
                    or np.shares_memory(argument, actual)):
                raise InitializationError("INITIALIZATION_REPRESENTATION_MISMATCH before either FE")
        inputs[0].append(gl)
        inputs[1].append(gd)
    certificates = (
        preflight_lshade(seal, cells[0], physical=lshade._physical, canonicalize=canonicalize),
        preflight_controlled_de(seal, cells[1], canonicalize=de.initial_input, normalize=de._normalize),
    )
    persist_both_preflight_certificates(
        seal=seal, pair_identity_id=pair.identity_id, cells=cells, journals=journals,
        lshade_certificate=certificates[0], controlled_de_certificate=certificates[1],
    )
    require_both_preflight_certificates(seal=seal, pair_identity_id=pair.identity_id, cells=cells, journals=journals)
    arms = tuple(ArmSession(backend, cell=cell, pair=pair, journal=journal, evaluator=evaluator, seed=seed)
                 for backend, cell, journal, evaluator, seed in zip((lshade, de), cells, journals, evaluators, seeds[1:]))
    # FE dispatch is enabled only here, after both complete actual-path checks
    # and durable certificate readback. Q1-A's standalone dispatch stays disabled.
    for arm, population in zip(arms, inputs):
        arm.expected_initial_inputs = tuple(member.sealed_physical_le_f64 for member in seal.members)
        raw = np.asarray(population)
        arm.transition(lambda arm=arm, raw=raw: arm.backend.initialize(arm.evaluate, population=raw))
    return seal, arms
