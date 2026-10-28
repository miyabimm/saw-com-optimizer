"""Deterministic COM-free fixture; no scientific objective or run claim."""
import hashlib
import uuid

import numpy as np

from sawopt.design.canonicalization import canonicalize_hybrid_vector
from sawopt.studies.stage5a2.candidates import SCHEMA, VIOLATIONS
from sawopt.studies.stage5a2.identity import PairIdentity, GenesisCoordinator
from sawopt.studies.stage5a2.initialization import DesignSpaceMetadata, canonical_key_tokens
from sawopt.studies.stage5a2.pair import arm_config_hashes
from sawopt.studies.stage5a2.production_identity import Q0_BOUNDS_LE_F64_HEX, Q0_VARIABLE_NAMES, Q0_VARIABLE_UNITS
from sawopt.studies.stage5a2.rng import design_space_sha256


def fixture(root):
    bounds = np.frombuffer(bytes.fromhex(Q0_BOUNDS_LE_F64_HEX["P_D"]), dtype="<f8").reshape(13, 2)
    indices = (4, 5, 6, 11)
    metadata = DesignSpaceMetadata(
        "P_D", tuple(Q0_VARIABLE_NAMES), tuple(tuple(float(v) for v in row) for row in bounds), indices, tuple(Q0_VARIABLE_UNITS),
        design_space_sha256("P_D", Q0_VARIABLE_NAMES, bounds, indices, Q0_VARIABLE_UNITS),
    )
    digest = lambda s: hashlib.sha256(s.encode()).hexdigest()
    pair = PairIdentity(
        pair_journal_uuid=str(uuid.UUID(int=1, version=4)), protocol_id="stage5a2-q0-r1-v1",
        source_commit_sha=digest("synthetic-source"), config_sha256=digest("synthetic-config"),
        evaluator_sha256=digest("synthetic-evaluator"), grid_sha256=digest("synthetic-grid"),
        environment_sha256=digest("synthetic-environment"), topology="P_D", root_seed=20261012,
        design_space_sha256=metadata.design_space_sha256,
        sampler_version="independent_uniform_rejection_lshade_image_v2", arm_config_hashes=arm_config_hashes(),
        cell_journal_uuids=tuple((role, str(uuid.UUID(int=i, version=4)))
                                 for i, role in enumerate(("lshade", "controlled_de"), 2)),
        identity_scope="synthetic_test", production_manifest_json=None,
    )
    genesis = GenesisCoordinator(root / "pair.sqlite", (root / "lshade.sqlite", root / "de.sqlite"), identity_scope="synthetic_test")
    canonicalize = lambda value: canonicalize_hybrid_vector(
        value, bounds=bounds, integer_indices=indices, dimension=13, topology="P_D")
    return metadata, pair, genesis, canonicalize


def candidate(vector, ordinal, *, pair, status="PHYSICS_EVALUATED", score=None):
    score = float(np.sum(vector * vector)) if score is None else float(score)
    success = status == "PHYSICS_EVALUATED"
    geometry = status != "GEOMETRY_REJECTED"
    return {
        "schema_id": SCHEMA, "schema_version": 1, "evaluation_phase": "search",
        "evaluation_status": status, "topology": pair.topology,
        "candidate_key": canonical_key_tokens(vector), "candidate_vector": vector.copy(),
        "first_evaluation_ordinal": ordinal, "grid_sha256": pair.grid_sha256,
        "geometry_valid": geometry, "geometry_dimensions": {"synthetic": 1.},
        "geometry_violations": {"synthetic": 0. if geometry else 2.},
        "metrics": {"worst_il_db": score, "ripple_db": 0., "input_vswr": 1., "output_vswr": 1.,
                    "source_return_loss_db_min": 20., "load_return_loss_db_min": 20.,
                    "stop_attenuation_db": [30.] * 4} if success else {},
        "violations": {k: 0. for k in sorted(VIOLATIONS)} if success else {},
        "filter_metrics_available": success, "feasible": success,
        "max_violation": 0. if success else None, "sum_violation": 0. if success else None,
        "objective": score if success else None,
        "source_impedance_ohm": 50., "load_impedance_ohm": 50.,
        "failure_stage": None if success else "physics" if geometry else "geometry",
        "failure_code": None if success else "NONFINITE_METRICS" if geometry else "GEOMETRY_LIMIT",
        "failure_message": None if success else "deterministic synthetic fixture",
    }
