"""Reusable DMS reference-design and immutable validation-grid helpers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import yaml

from ..design.space import decode_t0
from ..design.topology import (
    FiveIdtDesign,
    ParallelThreeIdtDesign,
    T0,
    T1,
    T2,
    ThreeIdtDesign,
    decode_t1,
    decode_t2,
)
from ..physics.com import FixedProvider
from ..physics.literature_com import profile_from_mapping
from ..reporting.material_metadata import material_profile_metadata


ROOT = Path(__file__).resolve().parents[3]


def load_common_validation_grid(
    cfg: Mapping[str, Any],
) -> tuple[np.ndarray, str, str, dict[str, Any]]:
    """Load and verify the retained DMS/hybrid validation-grid reference."""
    metadata_path = ROOT / cfg["dms_topology"]["common_validation_grid_metadata"]
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    grid_path = Path(metadata["source"])
    if not grid_path.is_absolute():
        grid_path = ROOT / grid_path
    # Git stores this reference CSV with LF endings; normalize CRLF worktrees
    # before checking the content hash so Windows and Linux validate the same
    # immutable bytes.
    grid_bytes = grid_path.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(grid_bytes).hexdigest() != metadata["sha256"]:
        raise ValueError("common validation grid file hash does not match its metadata")
    grid = np.loadtxt(grid_path, delimiter=",", skiprows=1).astype(float)
    grid_id = hashlib.sha256(np.asarray(grid, dtype="<f8").tobytes()).hexdigest()
    if grid_id != metadata["grid_id"]:
        raise ValueError(f"validation-grid identity mismatch: {grid_id} != {metadata['grid_id']}")
    return grid, grid_id, str(metadata_path), metadata


def decode_design(vector: Sequence[float], topology: str, cfg: Mapping[str, Any]):
    """Decode a retained DMS reference vector through canonical design owners."""
    if topology == T0:
        return decode_t0(vector)
    if topology == T1:
        return decode_t1(vector, int(cfg["dms_topology"]["t1_reflector_electrodes"]))
    if topology == T2:
        return decode_t2(vector)
    raise ValueError(topology)


def _provider(material: str, cfg: Mapping[str, Any]):
    section = cfg["dms_topology"]["materials"][material]
    if material == "M0":
        values = yaml.safe_load((ROOT / section["com_file"]).read_text(encoding="utf-8"))
        return FixedProvider(values), material_profile_metadata(profile_id="M0")
    profile_path = ROOT / section["profile_file"]
    profile_data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    provider = profile_from_mapping(profile_data)
    return provider, material_profile_metadata(
        profile_data, profile_id=provider.profile_id,
        com_parameter_source=str(profile_path),
    )


def _initial_t0(material: str, cfg: Mapping[str, Any]) -> ThreeIdtDesign:
    path = ROOT / cfg["dms_topology"]["initial_designs"][material]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "design" in payload:
        payload = payload["design"]
    allowed = {field.name for field in ThreeIdtDesign.__dataclass_fields__.values()}
    return ThreeIdtDesign(**{key: payload[key] for key in allowed if key in payload})


def initial_design(material: str, topology: str, cfg: Mapping[str, Any]):
    """Construct a deterministic current-owner design from retained DMS inputs."""
    t0 = _initial_t0(material, cfg)
    if topology == T0:
        return t0
    if topology == T1:
        center = t0.center_wavelength_um or t0.wavelength_um
        outer_pairs = max(4, int(round(t0.io_idt_pairs / 2)))
        return FiveIdtDesign(
            wavelength_A_um=t0.wavelength_um,
            wavelength_B_um=(t0.wavelength_um + center) / 2,
            wavelength_C_um=center,
            reflector_wavelength_um=t0.reflector_wavelength_um or t0.wavelength_um,
            pairs_A=outer_pairs, pairs_B=outer_pairs, pairs_C=t0.center_idt_pairs,
            common_idt_gap_lambda=t0.idt_gap_lambda,
            reflector_gap_lambda=t0.reflector_gap_lambda,
            aperture_um=t0.aperture_um,
            reflector_electrodes=int(cfg["dms_topology"]["t1_reflector_electrodes"]),
        )
    offset = float(cfg["dms_topology"].get("t2_initial_main_offset_fraction", 0.01))
    center = t0.center_wavelength_um or t0.wavelength_um
    reflector = t0.reflector_wavelength_um or t0.wavelength_um
    return ParallelThreeIdtDesign(
        track_A_main_wavelength_um=t0.wavelength_um * (1 - offset),
        track_B_main_wavelength_um=t0.wavelength_um * (1 + offset),
        io_idt_pairs=t0.io_idt_pairs, center_idt_pairs=t0.center_idt_pairs,
        reflector_electrodes=t0.reflector_electrodes,
        idt_gap_lambda=t0.idt_gap_lambda, reflector_gap_lambda=t0.reflector_gap_lambda,
        center_wavelength_ratio=center / t0.wavelength_um,
        reflector_wavelength_ratio=reflector / t0.wavelength_um,
        total_aperture_um=t0.aperture_um,
    )


def provider_for_material(material: str, cfg: Mapping[str, Any]):
    """Select a retained M0/MLIT provider without launching a study."""
    return _provider(material, cfg)


__all__ = [
    "decode_design",
    "initial_design",
    "load_common_validation_grid",
    "provider_for_material",
]
