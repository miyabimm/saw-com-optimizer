"""Immutable Phase-I/II identities and fail-closed G0--G4 coordination."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from .codec import canonical_json_bytes

PAIR_SCHEMA = "stage5a2_pair_identity_v2"
ROSTER_SCHEMA = "stage5a2_genesis_roster_v1"
CELL_SCHEMA = "stage5a2_cell_identity_v2"
ARM_ROLES = ("lshade", "controlled_de")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class IdentityError(ValueError):
    """An immutable identity or genesis reference is invalid."""


class GenesisError(RuntimeError):
    """Genesis cannot safely reconcile the current persistent state."""


def _sha256(value: str, name: str) -> None:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise IdentityError(f"{name} must be a lowercase SHA-256 hex digest")


def _uuid(value: str, name: str) -> None:
    if type(value) is not str:
        raise IdentityError(f"{name} must be a canonical UUID string")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError(value)
    except ValueError as exc:
        raise IdentityError(f"{name} must be a canonical lowercase UUID") from exc


def _source_commit(value: str) -> None:
    if type(value) is not str or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) is None:
        raise IdentityError("source_commit_sha must be a full lowercase Git object ID")


def _domain_id(tag: bytes, payload: bytes) -> str:
    return hashlib.sha256(tag + payload).hexdigest()


@dataclass(frozen=True, slots=True)
class PairIdentity:
    pair_journal_uuid: str
    protocol_id: str
    source_commit_sha: str
    config_sha256: str
    evaluator_sha256: str
    grid_sha256: str
    environment_sha256: str
    topology: str
    root_seed: int
    design_space_sha256: str
    sampler_version: str
    arm_config_hashes: tuple[tuple[str, str], ...]
    cell_journal_uuids: tuple[tuple[str, str], ...]
    identity_scope: Literal["synthetic_test", "q0_production"]
    production_manifest_json: bytes | None
    schema: str = PAIR_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PAIR_SCHEMA:
            raise IdentityError(f"pair identity schema must be {PAIR_SCHEMA}")
        _uuid(self.pair_journal_uuid, "pair_journal_uuid")
        for name in ("protocol_id", "topology", "sampler_version"):
            if type(getattr(self, name)) is not str or not getattr(self, name):
                raise IdentityError(f"{name} must be a non-empty string")
        _source_commit(self.source_commit_sha)
        for name in (
            "config_sha256", "evaluator_sha256", "grid_sha256", "environment_sha256",
            "design_space_sha256",
        ):
            _sha256(getattr(self, name), name)
        if self.topology not in {"D", "P_D", "D_P", "P_D_P"}:
            raise IdentityError("topology must be one of the four supported Stage 4A designs")
        if self.identity_scope not in ("synthetic_test", "q0_production"):
            raise IdentityError("pair identity scope must be explicit synthetic_test or q0_production")
        if self.identity_scope == "synthetic_test":
            if self.production_manifest_json is not None:
                raise IdentityError("synthetic pair identities cannot carry a production manifest")
        else:
            try:
                from .production_identity import Q0ProductionIdentityManifest

                manifest = Q0ProductionIdentityManifest.from_bytes(self.production_manifest_json)
                manifest.verify_pair_fields(self)
            except (TypeError, ValueError) as exc:
                raise IdentityError(f"Q0 production pair identity is not backed by a valid manifest: {exc}") from exc
        if self.sampler_version != "independent_uniform_rejection_lshade_image_v2":
            raise IdentityError("sampler version differs from the frozen Q0 contract")
        if type(self.root_seed) is not int or self.root_seed < 0:
            raise IdentityError("root_seed must be a non-negative integer")
        if type(self.arm_config_hashes) is not tuple or any(
            type(pair) is not tuple or len(pair) != 2 for pair in self.arm_config_hashes
        ):
            raise IdentityError("arm config hashes must be an immutable ordered tuple of pairs")
        if type(self.cell_journal_uuids) is not tuple or any(
            type(pair) is not tuple or len(pair) != 2 for pair in self.cell_journal_uuids
        ):
            raise IdentityError("cell journal UUIDs must be an immutable ordered tuple of pairs")
        if tuple(role for role, _ in self.arm_config_hashes) != ARM_ROLES:
            raise IdentityError("arm config hashes must list lshade then controlled_de")
        if tuple(role for role, _ in self.cell_journal_uuids) != ARM_ROLES:
            raise IdentityError("cell journal UUIDs must list lshade then controlled_de")
        for role, value in self.arm_config_hashes:
            _sha256(value, f"{role} config hash")
        for role, value in self.cell_journal_uuids:
            _uuid(value, f"{role} cell journal UUID")
        cell_uuids = {value for _, value in self.cell_journal_uuids}
        if len(cell_uuids) != len(ARM_ROLES):
            raise IdentityError("arm cell journal UUIDs must be unique")
        if self.pair_journal_uuid in cell_uuids:
            raise IdentityError("pair and cell journal UUIDs must be distinct")

    @classmethod
    def from_q0_production_manifest(
        cls,
        *,
        pair_journal_uuid: str,
        cell_journal_uuids: tuple[tuple[str, str], ...],
        production_manifest_json: bytes,
    ) -> "PairIdentity":
        """Build the pair's aggregate hashes from the complete frozen preimage."""
        from .production_identity import Q0ProductionIdentityManifest

        manifest = Q0ProductionIdentityManifest.from_bytes(production_manifest_json)
        record = manifest.record
        return cls(
            pair_journal_uuid=pair_journal_uuid,
            protocol_id=record["protocol_id"],
            source_commit_sha=record["source"]["source_commit_sha"],
            config_sha256=hashlib.sha256(canonical_json_bytes(record["configuration"])).hexdigest(),
            evaluator_sha256=hashlib.sha256(canonical_json_bytes(record["evaluator"])).hexdigest(),
            grid_sha256=hashlib.sha256(canonical_json_bytes(record["grids"])).hexdigest(),
            environment_sha256=hashlib.sha256(canonical_json_bytes(record["environment"])).hexdigest(),
            topology=record["topology"],
            root_seed=record["root_seed"],
            design_space_sha256=record["design_space"]["design_space_sha256"],
            sampler_version=record["sampler"]["version"],
            arm_config_hashes=tuple(
                (role, hashlib.sha256(canonical_json_bytes(record["arms"][role])).hexdigest())
                for role in ARM_ROLES
            ),
            cell_journal_uuids=cell_journal_uuids,
            identity_scope="q0_production",
            production_manifest_json=manifest.canonical_bytes,
        )

    def record(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "pair_journal_uuid": self.pair_journal_uuid,
            "protocol_id": self.protocol_id,
            "source_commit_sha": self.source_commit_sha,
            "config_sha256": self.config_sha256,
            "evaluator_sha256": self.evaluator_sha256,
            "grid_sha256": self.grid_sha256,
            "environment_sha256": self.environment_sha256,
            "topology": self.topology,
            "root_seed": self.root_seed,
            "design_space_sha256": self.design_space_sha256,
            "sampler_version": self.sampler_version,
            "arm_config_hashes": [[role, value] for role, value in self.arm_config_hashes],
            "cell_journal_uuids": [[role, value] for role, value in self.cell_journal_uuids],
            "identity_scope": self.identity_scope,
            "production_manifest": (
                None if self.production_manifest_json is None
                else json.loads(self.production_manifest_json.decode("utf-8"))
            ),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.record())

    @property
    def identity_id(self) -> str:
        return _domain_id(b"sawopt-stage5a2-pair-identity-v2\0", self.canonical_bytes)

    @property
    def identity_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()


@dataclass(frozen=True, slots=True)
class CellIdentity:
    cell_journal_uuid: str
    pair_journal_uuid: str
    pair_identity_id: str
    pair_identity_sha256: str
    role: Literal["lshade", "controlled_de"]
    arm_config_sha256: str
    environment_sha256: str
    schema: str = CELL_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CELL_SCHEMA:
            raise IdentityError(f"cell identity schema must be {CELL_SCHEMA}")
        for name in ("cell_journal_uuid", "pair_journal_uuid"):
            _uuid(getattr(self, name), name)
        _sha256(self.pair_identity_id, "pair_identity_id")
        _sha256(self.pair_identity_sha256, "pair_identity_sha256")
        _sha256(self.arm_config_sha256, "arm_config_sha256")
        _sha256(self.environment_sha256, "environment_sha256")
        if self.role not in ARM_ROLES:
            raise IdentityError(f"unsupported cell role: {self.role!r}")
        if self.cell_journal_uuid == self.pair_journal_uuid:
            raise IdentityError("pair and cell journal UUIDs must be distinct")

    def record(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "cell_journal_uuid": self.cell_journal_uuid,
            "pair_journal_uuid": self.pair_journal_uuid,
            "pair_identity_id": self.pair_identity_id,
            "pair_identity_sha256": self.pair_identity_sha256,
            "role": self.role,
            "arm_config_sha256": self.arm_config_sha256,
            "environment_sha256": self.environment_sha256,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.record())

    @property
    def identity_id(self) -> str:
        return _domain_id(b"sawopt-stage5a2-cell-identity-v2\0", self.canonical_bytes)

    @property
    def identity_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()


@dataclass(frozen=True, slots=True)
class GenesisRoster:
    pair_identity_id: str
    pair_journal_uuid: str
    cells: tuple[CellIdentity, CellIdentity]
    cell_journal_locators: tuple[str, str]
    schema: str = ROSTER_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != ROSTER_SCHEMA:
            raise IdentityError(f"roster schema must be {ROSTER_SCHEMA}")
        _sha256(self.pair_identity_id, "pair_identity_id")
        _uuid(self.pair_journal_uuid, "pair_journal_uuid")
        if type(self.cells) is not tuple or tuple(cell.role for cell in self.cells) != ARM_ROLES:
            raise IdentityError("roster cells must be ordered lshade, controlled_de")
        if self.cells[0].pair_identity_sha256 != self.cells[1].pair_identity_sha256:
            raise IdentityError("roster cells reference different pair identity bytes")
        if type(self.cell_journal_locators) is not tuple or len(self.cell_journal_locators) != 2:
            raise IdentityError("roster must record both ordered cell journal locators")
        if any(
            type(locator) is not str or not locator or not Path(locator).is_absolute()
            for locator in self.cell_journal_locators
        ):
            raise IdentityError("cell journal locators must be absolute non-empty paths")
        for cell in self.cells:
            if cell.pair_identity_id != self.pair_identity_id:
                raise IdentityError("roster cell references a different pair identity")
            if cell.pair_journal_uuid != self.pair_journal_uuid:
                raise IdentityError("roster cell references a different pair journal")
        if len({cell.identity_id for cell in self.cells}) != 2 or len(
            {cell.cell_journal_uuid for cell in self.cells}
        ) != 2:
            raise IdentityError("roster cell identities and journal UUIDs must be unique")

    def record(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "pair_identity_id": self.pair_identity_id,
            "pair_identity_sha256": self.cells[0].pair_identity_sha256,
            "pair_journal_uuid": self.pair_journal_uuid,
            "cells": [
                cell.record() | {
                    "identity_id": cell.identity_id,
                    "identity_sha256": cell.identity_sha256,
                    "cell_journal_locator": self.cell_journal_locators[index],
                }
                for index, cell in enumerate(self.cells)
            ],
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.record())

    @property
    def roster_hash(self) -> str:
        return _domain_id(b"sawopt-stage5a2-genesis-roster-v1\0", self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class GenesisReady:
    """Proof token returned only after G4 records are read back and verified."""

    pair_identity_id: str
    roster_hash: str
    cell_identity_ids: tuple[str, str]
    barrier_event_hash: str

    def __post_init__(self) -> None:
        _sha256(self.pair_identity_id, "pair_identity_id")
        _sha256(self.roster_hash, "roster_hash")
        _sha256(self.barrier_event_hash, "barrier_event_hash")
        if type(self.cell_identity_ids) is not tuple or len(self.cell_identity_ids) != 2:
            raise IdentityError("G4 readiness must bind exactly two ordered cell identities")
        for value in self.cell_identity_ids:
            _sha256(value, "cell_identity_id")
        if len(set(self.cell_identity_ids)) != 2:
            raise IdentityError("G4 cell identities must be distinct")


@dataclass(frozen=True, slots=True)
class GenesisResult:
    stage: Literal["G0", "G1", "G2", "G3", "G4"]
    pair_identity_id: str
    roster_hash: str
    cell_identity_ids: tuple[str, str]
    readiness: GenesisReady | None


class GenesisCoordinator:
    """Coordinate immutable identities across three separate SQLite journals.

    The pair database coordinates the ordered writes; there is deliberately
    no claim of distributed atomicity across the independent SQLite files.
    """

    def __init__(
        self,
        pair_path: str | Path,
        cell_paths: tuple[str | Path, str | Path],
        *,
        identity_scope: Literal["synthetic_test", "q0_production"] = "q0_production",
    ) -> None:
        self.pair_path = Path(pair_path)
        self.cell_paths = tuple(Path(path) for path in cell_paths)
        if identity_scope not in ("synthetic_test", "q0_production"):
            raise ValueError("genesis identity_scope must be synthetic_test or q0_production")
        self.identity_scope = identity_scope
        if len(self.cell_paths) != 2:
            raise ValueError("exactly two cell journal paths are required")
        resolved_paths = {self.pair_path.resolve(), *(path.resolve() for path in self.cell_paths)}
        if len(resolved_paths) != 3:
            raise ValueError("pair and cell journal paths must be distinct")

    @staticmethod
    def _inspect(path: Path, journal_uuid: str, owner_kind: str) -> tuple[str, object | None]:
        """Inspect without creating files; reject foreign or malformed state."""
        from .journal import SQLiteJournal

        return SQLiteJournal.inspect(path, journal_uuid=journal_uuid, owner_kind=owner_kind)

    def _validate_pair_scope(self, pair: PairIdentity) -> None:
        if pair.identity_scope != self.identity_scope:
            raise GenesisError(
                f"{self.identity_scope} genesis cannot accept {pair.identity_scope} pair identities"
            )
        if pair.identity_scope == "q0_production":
            try:
                from .production_identity import Q0ProductionIdentityManifest

                Q0ProductionIdentityManifest.from_bytes(pair.production_manifest_json).verify_pair_fields(pair)
            except (TypeError, ValueError) as exc:
                raise GenesisError(f"Q0 production identity manifest validation failed: {exc}") from exc

    def reconcile(
        self,
        pair: PairIdentity,
        *,
        fault_hook: Callable[[str], None] | None = None,
    ) -> GenesisResult:
        from .journal import SQLiteJournal

        self._validate_pair_scope(pair)
        if pair.pair_journal_uuid == dict(pair.cell_journal_uuids)["lshade"] or pair.pair_journal_uuid == dict(pair.cell_journal_uuids)["controlled_de"]:
            raise GenesisError("pair and cell journal UUIDs must be distinct")
        cell_ids = tuple(dict(pair.cell_journal_uuids)[role] for role in ARM_ROLES)
        expected_cells = tuple(
            CellIdentity(
                cell_journal_uuid=cell_ids[index],
                pair_journal_uuid=pair.pair_journal_uuid,
                pair_identity_id=pair.identity_id,
                pair_identity_sha256=pair.identity_sha256,
                role=role,
                arm_config_sha256=dict(pair.arm_config_hashes)[role],
                environment_sha256=pair.environment_sha256,
            )
            for index, role in enumerate(ARM_ROLES)
        )
        locators = tuple(str(path.resolve()) for path in self.cell_paths)
        roster = GenesisRoster(pair.identity_id, pair.pair_journal_uuid, expected_cells, locators)

        # Inspect every path before any file creation or identity mutation.
        statuses = [self._inspect(self.pair_path, pair.pair_journal_uuid, "pair")]
        statuses.extend(
            self._inspect(path, expected_cells[index].cell_journal_uuid, expected_cells[index].role)
            for index, path in enumerate(self.cell_paths)
        )
        pair_state = statuses[0][0]
        cell_states = [item[0] for item in statuses[1:]]
        if pair_state == "absent" and any(state != "absent" for state in cell_states):
            raise GenesisError("orphan cell database exists without its pair coordinator")
        if pair_state == "pristine" and any(state not in ("absent", "pristine") for state in cell_states):
            raise GenesisError("pristine pair coordinator has a non-pristine cell database")
        if pair_state == "absent" and fault_hook is not None:
            fault_hook("G0")

        pair_journal = SQLiteJournal(
            self.pair_path, pair.pair_journal_uuid, "pair",
            create=pair_state in ("absent", "pristine"),
        )
        if pair_state == "absent":
            # A fresh pair is only valid if both cell locations were absent.
            if any(state != "absent" for state in cell_states):
                raise GenesisError("G0 requires absent pair and cell journals")
            pair_journal.commit_identity_and_roster(pair, roster)
            stage = "G1"
            if fault_hook is not None:
                fault_hook(stage)
        else:
            stored_pair = pair_journal.get_immutable_record("pair_identity", pair.identity_id)
            stored_roster = pair_journal.get_immutable_record("genesis_roster", roster.roster_hash)
            if stored_pair is None and stored_roster is None and pair_state == "pristine":
                pair_journal.commit_identity_and_roster(pair, roster)
                stage = "G1"
                if fault_hook is not None:
                    fault_hook(stage)
            elif stored_pair == pair.canonical_bytes and stored_roster == roster.canonical_bytes:
                stage = "G1"
            else:
                raise GenesisError("pair identity or roster conflicts with immutable expected bytes")

        # Once G4 exists, missing/mismatched identities are terminal: never
        # recreate a cell record after the durable readiness barrier.
        barrier_id = f"ALL_IDENTITIES_READY:{pair.identity_id}:{roster.roster_hash}"
        if pair_journal.get_event(barrier_id) is not None:
            readiness = self._verify_g4(pair, roster, expected_cells, pair_journal)
            return GenesisResult("G4", pair.identity_id, roster.roster_hash,
                                 readiness.cell_identity_ids, readiness)

        expected_pair_records = {
            ("pair_identity", pair.identity_id, pair.canonical_bytes),
            ("genesis_roster", roster.roster_hash, roster.canonical_bytes),
        }
        if set(pair_journal.immutable_records()) != expected_pair_records:
            raise GenesisError("pair journal contains unexpected immutable identity records")
        if [event.event_type for event in pair_journal.events()] != [
            "PAIR_IDENTITY_COMMITTED", "GENESIS_ROSTER_COMMITTED",
        ]:
            raise GenesisError("pre-G4 pair journal contains unexpected events")

        # G1 -> G2 -> G3: create only absent/pristine expected destinations.
        for index, cell in enumerate(expected_cells):
            state = self._inspect(self.cell_paths[index], cell.cell_journal_uuid, cell.role)[0]
            if state in ("absent", "pristine", "active"):
                cell_journal = SQLiteJournal(
                    self.cell_paths[index], cell.cell_journal_uuid, cell.role,
                    create=state in ("absent", "pristine"),
                )
                stored = cell_journal.get_immutable_record("cell_identity", cell.identity_id)
                if stored is None:
                    if state == "active" or not cell_journal.is_pristine():
                        raise GenesisError(f"{cell.role} cell DB is not pristine before identity creation")
                    cell_journal.commit_identity(cell)
                    if fault_hook is not None:
                        fault_hook("G2" if index == 0 else "G3")
                elif stored != cell.canonical_bytes:
                    raise GenesisError(f"{cell.role} cell identity conflicts with expected bytes")
                if state == "active":
                    if cell_journal.immutable_records() != (("cell_identity", cell.identity_id, cell.canonical_bytes),):
                        raise GenesisError(f"{cell.role} cell DB contains unexpected immutable records")
                    if [event.event_type for event in cell_journal.events()] != ["CELL_IDENTITY_COMMITTED"]:
                        raise GenesisError(f"{cell.role} cell DB contains unexpected pre-G4 events")
            else:
                raise GenesisError(f"{cell.role} cell journal is malformed or incompatible")
            stage = "G2" if index == 0 else "G3"

        # Read back both cell identities and all reciprocal refs before G4.
        verified_cells = []
        for index, cell in enumerate(expected_cells):
            cell_journal = SQLiteJournal(self.cell_paths[index], cell.cell_journal_uuid, cell.role, create=False)
            stored = cell_journal.get_immutable_record("cell_identity", cell.identity_id)
            if stored != cell.canonical_bytes:
                raise GenesisError(f"{cell.role} cell identity read-back mismatch")
            verified_cells.append(cell.identity_id)
        pair_journal.verify_genesis_records(pair, roster)
        reciprocal_reference = {
            "pair_identity_id": pair.identity_id,
            "pair_identity_sha256": hashlib.sha256(pair.canonical_bytes).hexdigest(),
            "roster_hash": roster.roster_hash,
            "cell_identity_ids": verified_cells,
            "cell_identity_sha256": [hashlib.sha256(cell.canonical_bytes).hexdigest() for cell in expected_cells],
        }
        barrier_payload = {
            "schema": "stage5a2_all_identities_ready_v1",
            "schema_versions": {"pair": PAIR_SCHEMA, "roster": ROSTER_SCHEMA, "cell": CELL_SCHEMA},
            "pair_identity_id": pair.identity_id,
            "pair_identity_sha256": hashlib.sha256(pair.canonical_bytes).hexdigest(),
            "roster_hash": roster.roster_hash,
            "cell_identity_ids": list(verified_cells),
            "cell_identity_sha256": [hashlib.sha256(cell.canonical_bytes).hexdigest() for cell in expected_cells],
            "reciprocal_reference_sha256": hashlib.sha256(canonical_json_bytes(reciprocal_reference)).hexdigest(),
            "common_config_sha256": pair.config_sha256,
            "environment_sha256": pair.environment_sha256,
            "arm_config_hashes": [[role, value] for role, value in pair.arm_config_hashes],
            "ready": True,
        }
        barrier_id = f"ALL_IDENTITIES_READY:{pair.identity_id}:{roster.roster_hash}"
        barrier = pair_journal.append_event(barrier_id, "ALL_IDENTITIES_READY", barrier_payload)
        if fault_hook is not None:
            fault_hook("G4")
        # Revalidate all three records after the durable barrier as part of G4.
        self._verify_g4(pair, roster, expected_cells, pair_journal, barrier.event_hash)
        readiness = GenesisReady(pair.identity_id, roster.roster_hash, tuple(verified_cells), barrier.event_hash)
        return GenesisResult("G4", pair.identity_id, roster.roster_hash, tuple(verified_cells), readiness)

    def _verify_g4(self, pair, roster, cells, pair_journal, expected_barrier_hash: str | None = None) -> GenesisReady:
        from .journal import SQLiteJournal

        pair_journal.verify_genesis_records(pair, roster)
        expected_pair_records = {
            ("pair_identity", pair.identity_id, pair.canonical_bytes),
            ("genesis_roster", roster.roster_hash, roster.canonical_bytes),
        }
        if set(pair_journal.immutable_records()) != expected_pair_records:
            raise GenesisError("G4 pair journal immutable identity records mismatch")
        for index, cell in enumerate(cells):
            cell_journal = SQLiteJournal(self.cell_paths[index], cell.cell_journal_uuid, cell.role, create=False)
            if (
                cell_journal.get_immutable_record("cell_identity", cell.identity_id) != cell.canonical_bytes
                or cell_journal.immutable_records() != (("cell_identity", cell.identity_id, cell.canonical_bytes),)
            ):
                raise GenesisError("G4 cell identity is missing or changed; it may not be recreated")
            for _ in cell_journal.iter_events():  # verify the full post-genesis chain
                pass
        barrier_id = f"ALL_IDENTITIES_READY:{pair.identity_id}:{roster.roster_hash}"
        barrier = pair_journal.get_event(barrier_id)
        if barrier is None or barrier["event_type"] != "ALL_IDENTITIES_READY":
            raise GenesisError("G4 readiness barrier is missing")
        if expected_barrier_hash is not None and barrier["event_hash"] != expected_barrier_hash:
            raise GenesisError("G4 readiness barrier hash changed")
        payload = barrier["payload"]
        ids = tuple(cell.identity_id for cell in cells)
        cell_hashes = [hashlib.sha256(cell.canonical_bytes).hexdigest() for cell in cells]
        reciprocal_reference = {
            "pair_identity_id": pair.identity_id,
            "pair_identity_sha256": hashlib.sha256(pair.canonical_bytes).hexdigest(),
            "roster_hash": roster.roster_hash,
            "cell_identity_ids": list(ids),
            "cell_identity_sha256": cell_hashes,
        }
        if (
            payload.get("schema") != "stage5a2_all_identities_ready_v1"
            or payload.get("schema_versions") != {"pair": PAIR_SCHEMA, "roster": ROSTER_SCHEMA, "cell": CELL_SCHEMA}
            or payload.get("ready") is not True
            or payload.get("pair_identity_id") != pair.identity_id
            or payload.get("pair_identity_sha256") != hashlib.sha256(pair.canonical_bytes).hexdigest()
            or payload.get("roster_hash") != roster.roster_hash
            or payload.get("cell_identity_ids") != list(ids)
            or payload.get("cell_identity_sha256") != cell_hashes
            or payload.get("reciprocal_reference_sha256")
            != hashlib.sha256(canonical_json_bytes(reciprocal_reference)).hexdigest()
            or payload.get("common_config_sha256") != pair.config_sha256
            or payload.get("environment_sha256") != pair.environment_sha256
            or payload.get("arm_config_hashes") != [[role, value] for role, value in pair.arm_config_hashes]
        ):
            raise GenesisError("G4 readiness barrier does not match expected pair/roster/cell identities")
        return GenesisReady(pair.identity_id, roster.roster_hash, ids, barrier["event_hash"])

    def require_ready(self, pair: PairIdentity) -> GenesisReady:
        """Re-read and validate the committed barrier and its full identity set."""
        from .journal import SQLiteJournal

        self._validate_pair_scope(pair)
        cells = tuple(
            CellIdentity(
                cell_journal_uuid=dict(pair.cell_journal_uuids)[role],
                pair_journal_uuid=pair.pair_journal_uuid,
                pair_identity_id=pair.identity_id,
                pair_identity_sha256=pair.identity_sha256,
                role=role,
                arm_config_sha256=dict(pair.arm_config_hashes)[role],
                environment_sha256=pair.environment_sha256,
            )
            for role in ARM_ROLES
        )
        locators = tuple(str(path.resolve()) for path in self.cell_paths)
        roster = GenesisRoster(pair.identity_id, pair.pair_journal_uuid, cells, locators)
        pair_journal = SQLiteJournal(self.pair_path, pair.pair_journal_uuid, "pair", create=False)
        # The method never repairs cell identity loss after a committed barrier.
        return self._verify_g4(pair, roster, cells, pair_journal)


__all__ = [
    "ARM_ROLES", "CELL_SCHEMA", "PAIR_SCHEMA", "ROSTER_SCHEMA", "CellIdentity",
    "GenesisCoordinator", "GenesisError", "GenesisReady", "GenesisResult", "GenesisRoster",
    "IdentityError", "PairIdentity",
]
