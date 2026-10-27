"""RED contract tests: synthetic callback records only, never a COM search."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "optimization/test_configured_search.py"
_spec = importlib.util.spec_from_file_location("configured_search_test_fixtures", _FIXTURE_PATH)
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)

RUN_ID = "20261027T000000Z-00000001"
TEST_SOURCE = "a" * 40


def result_fixture(*, search_fail=None, validation_fail=None):
    snapshot = _fixtures.make_snapshot(budget=8)
    search = _fixtures.synthetic_evaluator(snapshot, fail_at=search_fail)
    validation = _fixtures.synthetic_evaluator(snapshot, fail_at=validation_fail)
    return snapshot, _fixtures.run(snapshot, search, validation)


def build(snapshot, result, *, run_id=RUN_ID, source=TEST_SOURCE):
    from sawopt.io.configured_persistence import build_persistence_plan

    return build_persistence_plan(snapshot, result, run_id=run_id, execution_source_sha=source)


def test_pure_completed_plan_and_defensive_detachment(monkeypatch):
    import sawopt.io.experiment_store as store

    snapshot, result = result_fixture()
    monkeypatch.setattr(store, "validate_data_root", lambda *a, **kw: pytest.fail("filesystem preflight in pure plan"))
    plan = build(snapshot, result)
    snapshot["effective_config"]["experiment_id"] = "changed"
    result["search"]["counters"]["unique_evaluations"] = 0
    assert plan["cell_status"] == "COMPLETED"
    assert plan["search_fes"] == 8
    assert plan["validation_points"] > 0
    assert plan["snapshot"]["effective_config"]["experiment_id"] != "changed"


@pytest.mark.parametrize("search_fail,validation_fail,search_fes", [(1, None, 0), (5, None, 4), (None, 1, 8)])
def test_failure_mapping_keeps_committed_counts_and_does_not_charge_requested_validation(search_fail, validation_fail, search_fes):
    snapshot, result = result_fixture(search_fail=search_fail, validation_fail=validation_fail)
    plan = build(snapshot, result)
    assert plan["cell_status"] == "FAILED"
    assert plan["search_fes"] == search_fes
    assert plan["validation_points"] == 0
    assert plan["reason"]
    assert plan["failure_class"] in {"MODEL", "VALIDATION", "UNKNOWN", "INFRASTRUCTURE"}


@pytest.mark.parametrize("damage", [
    "schema", "seed", "roster", "source", "config_hash", "input_hash", "status",
    "phase", "rank", "objective", "canonical", "counter", "validation_count", "finalist",
])
def test_inconsistent_results_are_rejected(damage):
    snapshot, result = result_fixture()
    result = copy.deepcopy(result)
    if damage == "schema": result["schema_id"] = "wrong"
    elif damage == "seed": result["identity"]["seed"] += 1
    elif damage == "roster": result["identity"]["expected_cells"][0]["cell_id"] = "wrong"
    elif damage == "source": result["identity"]["declared_source_commit_sha"] = "0" * 40
    elif damage == "config_hash": result["identity"]["effective_config_sha256"] = "0" * 64
    elif damage == "input_hash": result["identity"]["input_sha256"].pop("model")
    elif damage == "status": result["search"]["status"] = "EXHAUSTED"
    elif damage == "phase": result["validation"]["record"]["evaluation_phase"] = "SEARCH"
    elif damage == "rank": result["search"]["incumbent"]["rank_key"] = [999]
    elif damage == "objective": result["search"]["incumbent"]["objective"] += 1
    elif damage == "canonical": result["search"]["incumbent"]["canonical_vector"][0] += 0.01
    elif damage == "counter": result["search"]["counters"]["unique_evaluations"] += 1
    elif damage == "validation_count": result["validation"]["requested_grid_points"] += 1
    else: result["validation"]["record"]["canonical_vector"][0] += 0.01
    with pytest.raises(ValueError):
        build(snapshot, result)


def test_persist_completed_fixture_and_reject_run_id_reuse(tmp_path):
    from sawopt.io.configured_persistence import persist_persistence_plan
    from sawopt.io.experiment_store import read_experiment_manifest

    snapshot, result = result_fixture()
    plan = build(snapshot, result)
    root = tmp_path / "external-data"
    path = persist_persistence_plan(plan, data_root=root)
    manifest = read_experiment_manifest(path)
    assert manifest["status"] == "COMPLETED"
    assert manifest["cells"][0]["search_fes"] == 8
    assert manifest["scientific_config_sha256"] == snapshot["effective_config_sha256"]
    assert manifest["scientific_input_sha256"] == snapshot["input_sha256"]
    artifact = f"cells/{manifest['expected_cells'][0]['cell_id']}/configured_result.json"
    content = (path / artifact).read_bytes()
    assert hashlib.sha256(content).hexdigest() == manifest["raw_artifact_sha256"][artifact]["sha256"]
    assert json.loads(content)["classification"] == "TEST_ONLY / NOT_SCIENTIFIC_EVIDENCE"
    before = (path / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        persist_persistence_plan(plan, data_root=root)
    assert (path / "manifest.json").read_bytes() == before


@pytest.mark.parametrize("search_fail,validation_fail,expected_fes", [(1, None, 0), (5, None, 4), (None, 1, 8)])
def test_persist_failed_fixture(tmp_path, search_fail, validation_fail, expected_fes):
    from sawopt.io.configured_persistence import persist_persistence_plan
    from sawopt.io.experiment_store import read_experiment_manifest

    snapshot, result = result_fixture(search_fail=search_fail, validation_fail=validation_fail)
    path = persist_persistence_plan(build(snapshot, result), data_root=tmp_path / "raw")
    manifest = read_experiment_manifest(path)
    assert manifest["status"] == "FAILED"
    assert manifest["cells"][0]["status"] == "FAILED"
    assert manifest["cells"][0]["executed"] is True
    assert manifest["cells"][0]["search_fes"] == expected_fes
    assert manifest["cells"][0]["validation_points"] == 0
    assert len(manifest["errors"]) == 1


@pytest.mark.parametrize("point", ["write", "close"])
def test_persistence_failure_retains_raw_and_never_closes_success(tmp_path, monkeypatch, point):
    from sawopt.io.configured_persistence import persist_persistence_plan
    from sawopt.io.experiment_store import ExperimentRun, read_experiment_manifest

    snapshot, result = result_fixture()
    plan = build(snapshot, result)
    def fail(*args, **kwargs):
        raise OSError("injected incident")
    monkeypatch.setattr(ExperimentRun, "write_raw_artifact" if point == "write" else "close", fail)
    root = tmp_path / "raw"
    with pytest.raises(OSError, match="injected incident"):
        persist_persistence_plan(plan, data_root=root)
    path = root / "runs" / snapshot["experiment_id"] / RUN_ID
    manifest = read_experiment_manifest(path)
    assert manifest["status"] != "COMPLETED"
    assert manifest["errors"][-1]["classification"] == "IO"
    for relative, digest in manifest["raw_artifact_sha256"].items():
        assert hashlib.sha256((path / relative).read_bytes()).hexdigest() == digest["sha256"]


def test_existing_data_root_is_rejected_without_writes(tmp_path):
    from sawopt.io.configured_persistence import persist_persistence_plan

    snapshot, result = result_fixture()
    root = tmp_path / "existing"
    root.mkdir()
    marker = root / "historical-evidence"
    marker.write_bytes(b"preserve")
    with pytest.raises(FileExistsError):
        persist_persistence_plan(build(snapshot, result), data_root=root)
    assert list(root.iterdir()) == [marker]
    assert marker.read_bytes() == b"preserve"


def test_explicit_review_request_is_denied_without_creating_package(tmp_path):
    from sawopt.io.configured_persistence import ReviewEvidenceUnavailable, export_persistence_review

    with pytest.raises(ReviewEvidenceUnavailable, match="VALIDATION_EVIDENCE_UNAVAILABLE"):
        export_persistence_review(run_path=tmp_path / "run", repository_root=tmp_path / "report-repo")
    assert list(tmp_path.iterdir()) == []


def test_exhausted_search_maps_to_incomplete():
    snapshot = _fixtures.make_snapshot(budget=40, compact=True, exhaustion_duplicate_streak=1, narrow=True)
    result = _fixtures.run(snapshot, _fixtures.synthetic_evaluator(snapshot))
    assert result["status"] == "EXHAUSTED"
    plan = build(snapshot, result)
    assert plan["cell_status"] == "INCOMPLETE"
    assert plan["search_fes"] < 40
    assert plan["validation_points"] == result["validation"]["grid_point_count"]


@pytest.mark.parametrize("run_id,source", [(None, TEST_SOURCE), ("../unsafe", TEST_SOURCE), (RUN_ID, None), (RUN_ID, "bad")])
def test_invalid_identifiers_are_rejected(run_id, source):
    snapshot, result = result_fixture()
    with pytest.raises(ValueError):
        build(snapshot, result, run_id=run_id, source=source)
