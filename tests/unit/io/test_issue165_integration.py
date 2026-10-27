"""Test-owned fixture lifecycle; never search using COM."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from sawopt.io.experiment_store import read_experiment_manifest
from sawopt.problem.evaluator import ConfiguredCandidateEvaluator

_spec = importlib.util.spec_from_file_location("s2b_fixture", Path(__file__).parents[1] / "optimization/test_configured_search.py")
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
RUN_ID = "20261027T000000Z-00000002"
SOURCE = "a" * 40


def test_real_final_response_lifecycle_and_export(tmp_path):
    from sawopt.io.configured_fixture import run_configured_fixture, export_fixture_review
    snapshot = _fixture.make_snapshot(budget=4)
    root = tmp_path / "raw"
    search = _fixture.synthetic_evaluator(snapshot)
    physical = ConfiguredCandidateEvaluator(snapshot, capture_validation_response=True)
    calls = []

    def checked_search(vector, *, phase):
        manifest = read_experiment_manifest(root / "runs" / snapshot["experiment_id"] / RUN_ID)
        assert manifest["status"] == "INITIALIZED"
        calls.append(phase)
        return search(vector, phase=phase)

    def checked_validation(vector, *, phase):
        calls.append(phase)
        return physical(vector, phase=phase)

    path = run_configured_fixture(snapshot, search_evaluator=checked_search,
        validation_evaluator=checked_validation, data_root=root, run_id=RUN_ID, execution_source_sha=SOURCE)
    manifest = read_experiment_manifest(path)
    assert calls == ["SEARCH"] * 4 + ["VALIDATION"]
    assert manifest["status"] == "COMPLETED"
    assert manifest["search_fe_count"] == 4
    assert manifest["validation_point_count"] == len(snapshot["effective_config"]["grids"]["validation"]["points"])
    raw = (path / "artifacts/validation.csv").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["raw_artifact_sha256"]["artifacts/validation.csv"]["sha256"]
    rows = list(csv.DictReader(raw.decode().splitlines()))
    assert [float(row["frequency_hz"]) for row in rows] == snapshot["effective_config"]["grids"]["validation"]["points"]
    saved = json.loads((path / "cells" / manifest["expected_cells"][0]["cell_id"] / "configured_result.json").read_text())
    # Independently recompute network and metrics from the serialized admittance.
    from sawopt.physics.network import evaluate as network_evaluate
    from sawopt.evaluation import measure
    from sawopt.design.space import canonical_design
    from sawopt.problem.evaluator import configured_evaluation_context, _thaw
    y = np.array([[[complex(float(row[f"y_siemens_{i}{j}_real"]), float(row[f"y_siemens_{i}{j}_imag"]))
                    for j in (1, 2)] for i in (1, 2)] for row in rows])
    context = configured_evaluation_context(snapshot)
    net = network_evaluate(y, context.source_impedance_ohm, context.load_impedance_ohm)
    assert np.array_equal(net["il"], np.array([float(row["il_db"]) for row in rows]))
    record = saved["configured_result"]["validation"]["record"]
    design = canonical_design(record["canonical_vector"])[0]
    observed = measure(np.array([float(row["frequency_hz"]) for row in rows]), net, design, _thaw(context.evaluation_config))
    assert observed["metrics"] == record["metrics"]
    assert observed["violations"] == record["violations"]
    assert saved["classification"] == "TEST_ONLY / NOT_SCIENTIFIC_EVIDENCE"
    assert saved["configured_result"]["validation"]["record"]["canonical_vector"] == saved["configured_result"]["search"]["incumbent"]["canonical_vector"]
    repo = tmp_path / "repo"
    repo.mkdir()
    review = export_fixture_review(run_path=path, repository_root=repo)
    assert (Path(review.path) / "validation.csv").read_bytes() == raw


@pytest.mark.parametrize("search_failure,validation_failure,expected_fe", [(1, None, 0), (None, 1, 4)])
def test_failures_record_separate_counts(tmp_path, search_failure, validation_failure, expected_fe):
    from sawopt.io.configured_fixture import run_configured_fixture
    snapshot = _fixture.make_snapshot(budget=4)
    path = run_configured_fixture(snapshot, search_evaluator=_fixture.synthetic_evaluator(snapshot, fail_at=search_failure),
        validation_evaluator=_fixture.synthetic_evaluator(snapshot, fail_at=validation_failure),
        data_root=tmp_path / "raw", run_id=RUN_ID, execution_source_sha=SOURCE)
    manifest = read_experiment_manifest(path)
    assert manifest["status"] == "FAILED"
    assert manifest["search_fe_count"] == expected_fe
    assert manifest["validation_point_count"] == 0
    assert len(manifest["errors"]) == 1
    artifact = path / "cells" / manifest["expected_cells"][0]["cell_id"] / "configured_result.json"
    result = json.loads(artifact.read_text())["configured_result"]
    assert result["search"]["counters"]["unique_evaluations"] == expected_fe
    assert result["search"]["counters"]["failed_search_evaluator_attempts"] == (1 if search_failure else 0)
    assert result["validation"]["evaluator_calls"] == (1 if validation_failure else 0)


def test_exhaustion_closes_incomplete_without_changing_counts(tmp_path):
    from sawopt.io.configured_fixture import run_configured_fixture
    snapshot = _fixture.make_snapshot(budget=40, compact=True, exhaustion_duplicate_streak=1, narrow=True)
    callback = _fixture.synthetic_evaluator(snapshot)
    path = run_configured_fixture(snapshot, search_evaluator=callback, validation_evaluator=callback,
        data_root=tmp_path / "raw", run_id=RUN_ID, execution_source_sha=SOURCE)
    manifest = read_experiment_manifest(path)
    assert manifest["status"] == "INCOMPLETE"
    assert manifest["cells"][0]["status"] == "INCOMPLETE"
    assert 0 < manifest["search_fe_count"] < 40
    assert manifest["validation_point_count"] == len(snapshot["effective_config"]["grids"]["validation"]["points"])


def test_preflight_rejects_mutated_snapshot_before_creating_run(tmp_path):
    from sawopt.io.configured_fixture import run_configured_fixture
    snapshot = _fixture.make_snapshot(budget=4)
    callback = _fixture.synthetic_evaluator(snapshot)
    snapshot["effective_config"]["ports"]["source"] += 1
    root = tmp_path / "raw"
    with pytest.raises(ValueError):
        run_configured_fixture(snapshot, search_evaluator=callback, validation_evaluator=callback,
            data_root=root, run_id=RUN_ID, execution_source_sha=SOURCE)
    assert not root.exists()


@pytest.mark.parametrize("damage", ["finalist", "grid", "physical"])
def test_mismatched_response_fails_validation(tmp_path, damage):
    from sawopt.io.configured_fixture import run_configured_fixture
    snapshot = _fixture.make_snapshot(budget=4)
    physical = ConfiguredCandidateEvaluator(snapshot, capture_validation_response=True)
    def bad(vector, *, phase):
        record = physical(vector, phase=phase)
        response = record["validation_response"]
        if damage == "finalist":
            response["canonical_vector"][0] += 0.01
        elif damage == "grid":
            response["frequencies_hz"][0] += 1
        else:
            response["il_db"][0] += 1
        return record
    path = run_configured_fixture(snapshot, search_evaluator=_fixture.synthetic_evaluator(snapshot),
        validation_evaluator=bad, data_root=tmp_path / "raw", run_id=RUN_ID, execution_source_sha=SOURCE)
    manifest = read_experiment_manifest(path)
    assert manifest["status"] == "FAILED"
    assert manifest["search_fe_count"] == 4
    assert manifest["validation_point_count"] == 0
    assert not (path / "artifacts/validation.csv").exists()


def test_metric_only_refuses_export(tmp_path):
    from sawopt.io.configured_fixture import run_configured_fixture, export_fixture_review
    from sawopt.io.configured_persistence import ReviewEvidenceUnavailable
    snapshot = _fixture.make_snapshot(budget=4)
    callback = _fixture.synthetic_evaluator(snapshot)
    path = run_configured_fixture(snapshot, search_evaluator=callback, validation_evaluator=callback,
        data_root=tmp_path / "raw", run_id=RUN_ID, execution_source_sha=SOURCE)
    with pytest.raises(ReviewEvidenceUnavailable, match="VALIDATION_EVIDENCE_UNAVAILABLE"):
        export_fixture_review(run_path=path, repository_root=tmp_path / "repo")


def test_interrupted_close_preserves_registered_raw(tmp_path, monkeypatch):
    from sawopt.io.configured_fixture import run_configured_fixture
    from sawopt.io.experiment_store import ExperimentRun
    snapshot = _fixture.make_snapshot(budget=4)
    callback = _fixture.synthetic_evaluator(snapshot)
    def fail(*args, **kwargs):
        raise OSError("close interrupted")
    monkeypatch.setattr(ExperimentRun, "close", fail)
    with pytest.raises(OSError, match="close interrupted"):
        run_configured_fixture(snapshot, search_evaluator=callback, validation_evaluator=callback,
            data_root=tmp_path / "raw", run_id=RUN_ID, execution_source_sha=SOURCE)
    path = tmp_path / "raw/runs" / snapshot["experiment_id"] / RUN_ID
    manifest = read_experiment_manifest(path)
    assert manifest["status"] != "COMPLETED"
    artifact = f"cells/{manifest['expected_cells'][0]['cell_id']}/configured_result.json"
    assert hashlib.sha256((path / artifact).read_bytes()).hexdigest() == manifest["raw_artifact_sha256"][artifact]["sha256"]
