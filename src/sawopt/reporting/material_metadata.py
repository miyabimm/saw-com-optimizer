"""Explicit separation of legacy geometry fields and material metadata.

The numerical solver intentionally continues to receive the same design and
provider objects.  This module only builds display/serialization metadata so
that a literature profile's effective material values cannot be confused with
the historical ``FilterDesign`` fields.
"""
from __future__ import annotations

from typing import Any, Mapping


def _source_text(source: Mapping[str, Any] | None) -> str:
    if not source:
        return "unspecified"
    title = str(source.get("title", "")).strip()
    doi = str(source.get("doi", "")).strip()
    if title and doi:
        return f"{title} (doi:{doi})"
    return title or doi or "unspecified"


def material_profile_metadata(
    profile_data: Mapping[str, Any] | None = None,
    *,
    profile_id: str = "M0",
    design: Any | None = None,
    com_parameter_source: str | None = None,
    normalization_definition_source: str | None = None,
) -> dict[str, Any]:
    """Return material-profile provenance without changing provider behavior.

    ``profile_data`` is the normalized literature YAML mapping. When it is
    absent, an M0 provenance record is emitted from the fixed-provider identity.
    No provider or solver object is modified.
    """
    if profile_data is None:
        effective_h = getattr(design, "thickness_over_lambda", None)
        effective_duty = getattr(design, "metallization_ratio", None)
        return {
            "id": str(profile_id),
            "source": "configs/models/com_params_hypothetical.yaml",
            "substrate": "hypothetical",
            "electrode_material": "hypothetical",
            "temperature_c": 25.0,
            "effective_h_over_lambda": effective_h,
            "effective_duty": effective_duty,
            "phase_policy": "M0_FIXED_PROVIDER",
            "com_parameter_source": com_parameter_source or "FixedProvider legacy configuration",
            "normalization_definition_source": (
                normalization_definition_source or "FixedProvider legacy normalization"
            ),
            "display_note": "M0 legacy profile; design fields retain historical display semantics",
        }

    source = profile_data.get("source")
    definition_source = profile_data.get("definition_source")
    return {
        "id": str(profile_data["profile_id"]),
        "source": _source_text(source if isinstance(source, Mapping) else None),
        "substrate": str(profile_data["substrate"]),
        "electrode_material": str(profile_data.get("electrode_material") or "unspecified"),
        "temperature_c": float(profile_data["temperature_c"]),
        "effective_h_over_lambda": float(profile_data["h_over_lambda"]),
        "effective_duty": float(profile_data["metallization_ratio"]),
        "phase_policy": str(profile_data.get("phase_policy", "unspecified")),
        "com_parameter_source": com_parameter_source or _source_text(source if isinstance(source, Mapping) else None),
        "normalization_definition_source": normalization_definition_source or _source_text(
            definition_source if isinstance(definition_source, Mapping) else None
        ),
        "display_note": (
            "effective MLIT profile values above override display semantics; "
            "legacy design fields are not used to generate MLIT COM parameters"
        ),
    }


__all__ = ["material_profile_metadata"]
