from sawopt.reporting.material_metadata import material_profile_metadata


MLIT = {
    "profile_id": "LI2024_42YX_LT_METAL_UNSPECIFIED_T25",
    "substrate": "42YX-LiTaO3",
    "electrode_material": "unspecified_metal",
    "temperature_c": 25.0,
    "h_over_lambda": 0.08,
    "metallization_ratio": 0.65,
    "phase_policy": "SIGNED_REAL_TABLE_ASSUMPTION",
    "source": {"title": "source", "doi": "10.0000/source"},
    "definition_source": {"title": "definition", "doi": "10.0000/definition"},
}


def test_mlit_profile_metadata_preserves_effective_values_and_provenance():
    profile = material_profile_metadata(MLIT)
    assert profile["id"] == "LI2024_42YX_LT_METAL_UNSPECIFIED_T25"
    assert profile["source"] == "source (doi:10.0000/source)"
    assert profile["effective_h_over_lambda"] == 0.08
    assert profile["effective_duty"] == 0.65
    assert profile["normalization_definition_source"] == "definition (doi:10.0000/definition)"


def test_m0_metadata_preserves_hypothetical_provider_identity():
    profile = material_profile_metadata(profile_id="M0")
    assert profile["id"] == "M0"
    assert profile["source"] == "configs/models/com_params_hypothetical.yaml"
    assert profile["substrate"] == "hypothetical"
    assert profile["phase_policy"] == "M0_FIXED_PROVIDER"
