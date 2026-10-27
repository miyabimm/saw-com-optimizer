"""Fixed-input software regression, not an optimization study."""
import numpy as np

from sawopt.io.cli_config import load_cli_config
from sawopt.problem.evaluator import ConfiguredCandidateEvaluator


def test_opt_in_response_is_final_validation_only_and_detached():
    snapshot = load_cli_config("configs/examples/scientific_validation_only.yaml")
    evaluator = ConfiguredCandidateEvaluator(snapshot, capture_validation_response=True)
    vector = [5.0, 24, 16, 40, 0.5, 0.5, 80.0]
    assert "validation_response" not in evaluator(vector, phase="SEARCH")
    result = evaluator(vector, phase="VALIDATION")
    evidence = result["validation_response"]
    assert evidence["frequencies_hz"].tolist() == snapshot["effective_config"]["grids"]["validation"]["points"]
    assert evidence["canonical_vector"] == result["canonical_vector"]
    assert evidence["grid_sha256"] == result["grid_sha256"]
    assert evidence["model_sha256"] == result["model_sha256"]
    assert evidence["effective_config_sha256"] == result["effective_config_sha256"]
    assert evidence["y_parameters"].shape == (len(evidence["frequencies_hz"]), 2, 2)
    assert evidence["s"].shape == evidence["y_parameters"].shape
    assert np.isfinite(evidence["il_db"]).all()
    assert evidence["vswr"].shape == (len(evidence["frequencies_hz"]), 2)
    assert "validation_response" not in ConfiguredCandidateEvaluator(snapshot)(vector, phase="VALIDATION")
