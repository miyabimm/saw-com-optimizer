from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from pathlib import Path

import pytest

from sawopt.cli import _SyntheticComparator, _synthetic_response
from sawopt.io.checkpoints import CheckpointLoadError
from sawopt.optimization.checkpoint_session import LShadeCheckpointSession
from sawopt.optimization.lshade import LShadeBackend, validate_lshade_checkpoint_header
from sawopt.reporting.experiment_review import (
    ReviewPackageError,
    export_review_package,
)
from tests.fixtures.n1_transaction import (
    N1RecoveryError,
    N1RecoveryJournal,
    digest,
    evaluation_result_key,
    new_fixture,
)


ROOT = Path(__file__).resolve().parents[2]
CELL_ID = "n1-synthetic"


def _backend(config):
    lower, upper = (float(value) for value in config["design"]["bounds"])
    budget = int(config["search_fe_limit"])
    return LShadeBackend(
        [(lower, upper)], seed=int(config["seed"]), integer_indices=(),
        comparator=_SyntheticComparator(),
        config={
            "initial_population": int(config["optimizer"]["initial_population"]),
            "min_population": int(config["optimizer"]["min_population"]),
            "history_size": int(config["optimizer"]["history_size"]),
            "total_budget": budget,
            "hard_max_budget": budget,
            "population_schedule_terminal_budget": budget,
            "requested_unique_budget": budget,
        },
    )


def _metrics(config, candidate, grid):
    response = _synthetic_response(
        {"name": config["design"]["name"], "value": candidate[0]},
        config["model"], grid["points"],
    )
    return response, {
        "synthetic_peak_error": max(response),
        "synthetic_mean_error": sum(response) / len(response),
    }


def _evaluator(config, request, journal, attempt_id, calls, *, failure=None):
    def evaluate(vector):
        candidate = [float(value) for value in vector]
        result_key = evaluation_result_key(request, CELL_ID, candidate)
        journal.claim_evaluation(request["run_id"], attempt_id, CELL_ID, result_key, candidate)
        calls.append(result_key)
        if failure == "during_evaluator":
            raise RuntimeError("injected evaluator interruption")
        _response, metrics = _metrics(config, candidate, config["search_grid"])
        result = {
            "candidate_vector": candidate,
            "metrics": metrics,
            "violations": {},
            "feasible": True,
            "max_violation": 0.0,
            "sum_violation": 0.0,
        }
        if failure == "after_return_before_journal":
            raise RuntimeError("injected crash after evaluator return")
        journal.commit_evaluation(request["run_id"], attempt_id, CELL_ID, result_key, result)
        if failure == "after_journal_before_optimizer":
            raise RuntimeError("injected crash after result commit")
        return result

    return evaluate


def _session(raw_run):
    return LShadeCheckpointSession(
        raw_run.path / "checkpoints" / "n1",
        run_directory=raw_run.path,
    )


def _checkpoint(raw_run, journal, request, attempt_id, backend, *, fail_write=False):
    raw_run.checkpoint_store("n1")  # Register this existing checkpoint stream with R5.
    receipt = journal.checkpoint_intent(request["run_id"], attempt_id, backend.state_dict())
    session = _session(raw_run)
    if fail_write:
        original_write = session.store.write

        def interrupted_write(_writer, *, validator=None):
            def partial(path):
                path.write_text('{"partial":', encoding="utf-8")
                raise OSError("injected atomic checkpoint temporary-write failure")
            return original_write(partial, validator=validator)

        session.store.write = interrupted_write
        with pytest.raises(OSError, match="injected atomic checkpoint"):
            session.save(backend, extra_state={"n1_receipt": receipt})
        session.store.write = original_write
        return receipt, session

    session.save(backend, extra_state={"n1_receipt": receipt})
    payload = json.loads(session.store.latest_path.read_text(encoding="utf-8"))
    checkpoint_sha = digest(payload)
    journal.reconcile_checkpoint(request["run_id"], payload, checkpoint_sha)
    raw_run.refresh_checkpoint_state()
    return receipt, session


def _load_checkpoint(config, raw_run, journal, request):
    backend = _backend(config)
    session = _session(raw_run)
    loaded = session.store.load_state(
        validator=lambda state: session._validate(backend, state),
        preflight_validator=validate_lshade_checkpoint_header,
        include_final=False,
    )
    receipt = journal.verify_checkpoint(request["run_id"], loaded.state)
    backend.load_state_dict(loaded.state)
    return backend, session, receipt, loaded.state


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _finish_raw_run(config, raw_run, journal, request, backend):
    search_fes = int(backend.unique_evaluations)
    incumbent = backend.incumbent()
    assert incumbent is not None
    best_value = float(incumbent["candidate_vector"][0])
    design = {"name": config["design"]["name"], "value": best_value, "unit": "dimensionless"}
    validation_response, validation_metrics = _metrics(config, [best_value], config["validation_grid"])

    raw_run.record_cell(
        CELL_ID, status="RUNNING", executed=True,
        search_fes=search_fes, validation_points=0,
    )
    output = []
    for coordinate, value in zip(config["validation_grid"]["points"], validation_response, strict=True):
        output.append(f"{best_value},{float(coordinate)},{value},dimensionless\n")
    raw_run.write_artifact(
        "artifacts/validation.csv",
        ("design_value,grid_coordinate,synthetic_error,unit\n" + "".join(output)).encode("utf-8"),
    )
    geometry = {"status": "NOT_APPLICABLE", "unit": "dimensionless"}
    violations = {}
    raw_run.record_cell(
        CELL_ID, status="COMPLETED", executed=True,
        search_fes=search_fes, validation_points=len(validation_response),
        result={
            "design": design, "geometry": geometry,
            "metrics": dict(incumbent["metrics"]), "violations": violations,
            "feasible": True, "synthetic_only": True,
        },
        design=design, geometry=geometry,
        search_metrics=dict(incumbent["metrics"]), search_violations=violations,
        validation_metrics=validation_metrics, validation_violations=violations,
        feasible=True,
        search_proposals=int(backend.proposals_total),
        duplicate_proposals=int(backend.duplicate_count), cache_hits=int(backend.cache_hits),
    )
    raw_run.record_checkpoint(
        CELL_ID, phase="SEARCH", search_fes=search_fes, validation_points=0,
        metric_name="synthetic_peak_error",
        metric_value=float(incumbent["metrics"]["synthetic_peak_error"]),
        unit="dimensionless", observed_at_utc=_utc_now(),
    )
    raw_run.record_checkpoint(
        CELL_ID, phase="VALIDATION", search_fes=search_fes,
        validation_points=len(validation_response), metric_name="synthetic_peak_error",
        metric_value=validation_metrics["synthetic_peak_error"],
        unit="dimensionless", observed_at_utc=_utc_now(),
    )
    manifest = raw_run.close(status="COMPLETED")
    journal.close_raw_run(request["run_id"])
    return manifest


def _package_digest(directory: Path) -> str:
    if directory.is_symlink() or not directory.is_dir():
        raise N1RecoveryError("RECOVERY_AMBIGUOUS", "review package is absent or not a regular directory")
    records = []
    for path in sorted(directory.rglob("*"), key=lambda item: item.relative_to(directory).as_posix()):
        if path.is_symlink():
            raise N1RecoveryError("RECOVERY_AMBIGUOUS", "review package unexpectedly contains a symlink")
        if path.is_file():
            records.append({
                "path": path.relative_to(directory).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
    return digest(records)


def _review_destination(raw_run, repository):
    return repository / "reports/experiments" / raw_run.experiment_id / raw_run.run_id


def _reconcile_existing_export(raw_run, repository, journal, run_id):
    intent = journal.export_intent(run_id)
    state = journal.run_state(run_id)
    prior = journal.export_receipt(run_id)
    if (intent is None or state not in {"EXPORT_INTENT", "EXPORT_READY"}
            or (state == "EXPORT_INTENT") != (prior is None)):
        raise N1RecoveryError("RECOVERY_AMBIGUOUS", "local export has no reconcilable durable intent/receipt pair")
    raw_bytes = (raw_run.path / "manifest.json").read_bytes()
    raw_manifest = json.loads(raw_bytes)
    raw_sha = hashlib.sha256(raw_bytes).hexdigest()
    if (raw_sha != intent["raw_manifest_sha256"] or intent["run_id"] != run_id
            or intent["experiment_id"] != raw_run.experiment_id):
        raise N1RecoveryError("RECOVERY_AMBIGUOUS", "raw R5 manifest differs from local export intent")
    destination = _review_destination(raw_run, repository)
    if destination.is_symlink() or not destination.is_dir():
        raise N1RecoveryError("RECOVERY_AMBIGUOUS", "local export intent has no exact existing review package")
    try:
        verified = export_review_package(raw_run.path, repository_root=repository)
        review_path = Path(verified.path)
        review_manifest = json.loads((review_path / "manifest.json").read_text(encoding="utf-8"))
        package_sha = _package_digest(review_path)
    except (OSError, ValueError, ReviewPackageError) as exc:
        raise N1RecoveryError("RECOVERY_AMBIGUOUS", "existing review package cannot be verified exactly") from exc
    if (verified.status != "ALREADY_VALID" or review_path != destination
            or review_manifest.get("run_id") != run_id
            or review_manifest.get("experiment_id") != raw_run.experiment_id
            or review_manifest.get("execution_source_sha") != raw_manifest.get("execution_source_sha")
            or review_manifest.get("frozen_provenance_sha256") != raw_manifest.get("frozen_provenance_sha256")
            or review_manifest.get("package_status") != "READY_FOR_REVIEW"):
        raise N1RecoveryError("RECOVERY_AMBIGUOUS", "existing review package identity differs from raw R5 run")
    expected_receipt = {
        **intent, "package_sha256": package_sha,
        "status": "READY_FOR_REVIEW", "accepted": False,
    }
    if prior is None:
        journal.acknowledge_export(
            run_id, package_sha,
            observed_run_id=review_manifest["run_id"],
            observed_experiment_id=review_manifest["experiment_id"],
            raw_manifest_sha256=raw_sha,
            package_status=review_manifest["package_status"],
        )
    elif state != "EXPORT_READY" or prior != expected_receipt:
        raise N1RecoveryError("RECOVERY_AMBIGUOUS", "committed local export receipt differs from package bytes")
    return journal.export_receipt(run_id)


def _export_once(raw_run, repository, journal, run_id, *, exporter):
    state = journal.run_state(run_id)
    if state == "CLOSED":
        raw_manifest_bytes = (raw_run.path / "manifest.json").read_bytes()
        raw_manifest_sha = hashlib.sha256(raw_manifest_bytes).hexdigest()
        journal.begin_export(run_id, raw_manifest_sha)
        result = exporter(raw_run.path, repository_root=repository)
        if Path(result.path) != _review_destination(raw_run, repository):
            raise N1RecoveryError("RECOVERY_AMBIGUOUS", "R5 review exporter returned the wrong run identity path")
    elif state not in {"EXPORT_INTENT", "EXPORT_READY"}:
        raise N1RecoveryError("EXPORT_NOT_READY", "run has no closed R5 export intent")
    return _reconcile_existing_export(raw_run, repository, journal, run_id)


def _completed_fixture(tmp_path):
    config, raw_run, repository, journal, request, attempt_id = new_fixture(tmp_path)
    journal.claim_attempt(request["run_id"], attempt_id)
    calls = []
    backend = _backend(config)
    backend.initialize(_evaluator(config, request, journal, attempt_id, calls))
    backend.advance_to_unique_budget(request["budget"])
    _checkpoint(raw_run, journal, request, attempt_id, backend)
    _finish_raw_run(config, raw_run, journal, request, backend)
    return config, raw_run, repository, journal, request, attempt_id, backend


def test_same_run_resume_preserves_lshade_state_results_and_one_r5_export(tmp_path):
    config, raw_run, repository, journal, request, attempt_id = new_fixture(tmp_path)
    child = subprocess.run(
        [
            sys.executable, "-c", '''
import sys
from pathlib import Path
from sawopt.io.cli_config import load_synthetic_config
from sawopt.io.experiment_store import ExperimentRun
from tests.fixtures.n1_transaction import N1RecoveryJournal
from tests.unit.test_n1_synthetic_recovery import _backend, _checkpoint, _evaluator
source_root, raw_path, journal_root, run_id, attempt_id = sys.argv[1:]
config = load_synthetic_config(Path(source_root) / "configs/examples/r6_synthetic_smoke.yaml")
raw_run = ExperimentRun(raw_path)
journal = N1RecoveryJournal.open_existing(journal_root, raw_run=raw_path)
request = journal.identity(run_id)
journal.claim_attempt(run_id, attempt_id)
backend = _backend(config)
backend.initialize(_evaluator(config, request, journal, attempt_id, []))
_checkpoint(raw_run, journal, request, attempt_id, backend)
''',
            str(ROOT), str(raw_run.path), str(journal.root), request["run_id"], attempt_id,
        ],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert child.returncode == 0, child.stderr
    journal = N1RecoveryJournal.open_existing(journal.root, raw_run=raw_run.path)
    with sqlite3.connect(journal.path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM evaluations WHERE run_id=? AND state='COMMITTED'",
            (request["run_id"],),
        ).fetchone()[0] == 4
    recovered, _session_value, prior_receipt, checkpoint_payload = _load_checkpoint(
        config, raw_run, journal, request,
    )
    assert prior_receipt["result_count"] == 4
    successor = journal.resume(
        request["run_id"], attempt_id, journal.identity(request["run_id"]), checkpoint_payload,
    )
    assert successor != attempt_id
    journal.claim_attempt(request["run_id"], successor)
    assert prior_receipt["attempt_id"] == attempt_id
    calls = []
    recovered.set_evaluator(_evaluator(config, request, journal, successor, calls))
    recovered.advance_to_unique_budget(request["budget"])
    assert recovered.unique_evaluations == request["budget"]
    final_receipt, _session_value = _checkpoint(raw_run, journal, request, successor, recovered)

    uninterrupted_calls = []
    uninterrupted = _backend(config)
    uninterrupted.initialize(lambda vector: _direct_evaluation(config, vector, uninterrupted_calls))
    uninterrupted.advance_to_unique_budget(request["budget"])
    assert recovered.state_dict() == uninterrupted.state_dict()
    assert len(calls) == recovered.unique_evaluations - prior_receipt["result_count"]
    assert final_receipt["result_count"] == recovered.unique_evaluations
    assert final_receipt["attempt_generation"] == 2

    raw_manifest = _finish_raw_run(config, raw_run, journal, request, recovered)
    assert raw_manifest["run_id"] == request["run_id"]
    assert raw_manifest["search_fe_count"] == request["budget"]
    assert request["requested_unique_budget"] == request["hard_max_budget"] == request["budget"]
    assert raw_manifest["search_fe_limit_per_cell"] == request["requested_unique_budget"]
    assert raw_manifest["scientific_config_sha256"] == request["effective_config_sha256"]
    assert raw_manifest["scientific_input_sha256"]["model"] == request["model_sha256"]
    assert raw_manifest["scientific_input_sha256"]["search_grid"] == request["search_grid_sha256"]
    assert raw_manifest["scientific_input_sha256"]["validation_grid"] == request["validation_grid_sha256"]
    assert raw_manifest["expected_cells"] == request["expected_cells"]
    export_calls = []

    def exporter(*args, **kwargs):
        export_calls.append(1)
        return export_review_package(*args, **kwargs)

    first = _export_once(raw_run, repository, journal, request["run_id"], exporter=exporter)
    second = _export_once(raw_run, repository, journal, request["run_id"], exporter=exporter)
    assert first == second
    assert first["status"] == "READY_FOR_REVIEW"
    assert first["accepted"] is False
    assert len(export_calls) == 1
    review_path = _review_destination(raw_run, repository)
    review_manifest = json.loads((review_path / "manifest.json").read_text(encoding="utf-8"))
    checks = json.loads((review_path / "checks.json").read_text(encoding="utf-8"))
    assert review_manifest["run_id"] == request["run_id"]
    assert checks["config_sha256"] == request["effective_config_sha256"]
    assert checks["scientific_input_sha256"]["model"] == request["model_sha256"]
    assert checks["scientific_input_sha256"]["search_grid"] == request["search_grid_sha256"]
    assert checks["scientific_input_sha256"]["validation_grid"] == request["validation_grid_sha256"]


def _direct_evaluation(config, vector, calls):
    candidate = [float(value) for value in vector]
    calls.append(candidate)
    _response, metrics = _metrics(config, candidate, config["search_grid"])
    return {
        "candidate_vector": candidate, "metrics": metrics, "violations": {},
        "feasible": True, "max_violation": 0.0, "sum_violation": 0.0,
    }


def test_checkpoint_replace_with_lost_journal_ack_reconciles_exact_payload(tmp_path):
    config, raw_run, _repository, journal, request, attempt_id = new_fixture(tmp_path)
    journal.claim_attempt(request["run_id"], attempt_id)
    calls = []
    backend = _backend(config)
    backend.initialize(_evaluator(config, request, journal, attempt_id, calls))
    raw_run.checkpoint_store("n1")
    receipt = journal.checkpoint_intent(request["run_id"], attempt_id, backend.state_dict())
    session = _session(raw_run)
    session.save(backend, extra_state={"n1_receipt": receipt})
    payload = json.loads(session.store.latest_path.read_text(encoding="utf-8"))
    reconciled = journal.reconcile_checkpoint(request["run_id"], payload, digest(payload))
    assert reconciled["attempt_id"] == attempt_id
    assert reconciled["result_count"] == 4
    raw_run.refresh_checkpoint_state()
    resumed = journal.resume(
        request["run_id"], attempt_id, journal.identity(request["run_id"]), payload,
    )
    assert resumed != attempt_id


@pytest.mark.parametrize("failure", [
    "before_evaluator", "during_evaluator", "after_return_before_journal",
    "after_journal_before_optimizer",
])
def test_uncertain_evaluator_or_result_checkpoint_gap_never_retries(tmp_path, failure):
    config, _raw_run, _repository, journal, request, attempt_id = new_fixture(tmp_path)
    journal.claim_attempt(request["run_id"], attempt_id)
    calls = []
    if failure == "before_evaluator":
        result_key = evaluation_result_key(request, CELL_ID, [0.25])
        journal.claim_evaluation(request["run_id"], attempt_id, CELL_ID, result_key, [0.25])
    else:
        backend = _backend(config)
        with pytest.raises(RuntimeError, match="injected"):
            backend.initialize(_evaluator(
                config, request, journal, attempt_id, calls, failure=failure,
            ))
        assert calls  # The local deterministic evaluator was entered exactly once.
    if failure == "after_journal_before_optimizer":
        with sqlite3.connect(journal.path) as connection:
            assert connection.execute(
                "SELECT count(*) FROM evaluations WHERE run_id=? AND state='COMMITTED'",
                (request["run_id"],),
            ).fetchone()[0] == 1
    with pytest.raises(N1RecoveryError) as blocked:
        journal.resume(request["run_id"], attempt_id, journal.identity(request["run_id"]))
    assert blocked.value.code == "RECOVERY_AMBIGUOUS"
    if failure != "before_evaluator":
        assert len(calls) == 1
    if failure == "before_evaluator":
        with pytest.raises(N1RecoveryError, match="no retry"):
            journal.claim_evaluation(request["run_id"], attempt_id, CELL_ID, result_key, [0.25])


def test_result_transaction_rollback_and_duplicate_attempt_fe_result_claims(tmp_path):
    _config, _raw_run, _repository, journal, request, attempt_id = new_fixture(tmp_path)
    journal.claim_attempt(request["run_id"], attempt_id)
    with pytest.raises(N1RecoveryError, match="already committed"):
        journal.claim_attempt(request["run_id"], attempt_id)

    result_key = evaluation_result_key(request, CELL_ID, [0.5])
    def claim():
        try:
            journal.claim_evaluation(request["run_id"], attempt_id, CELL_ID, result_key, [0.5])
            return "claimed"
        except N1RecoveryError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _index: claim(), range(2)))
    assert outcomes.count("claimed") == 1
    assert outcomes.count("RECOVERY_AMBIGUOUS") == 1
    value = {"candidate_vector": [0.5], "metrics": {"synthetic_peak_error": 0.25}}
    with pytest.raises(OSError, match="transaction interruption"):
        journal.commit_evaluation(
            request["run_id"], attempt_id, CELL_ID, result_key, value, fail_before_commit=True,
        )
    with sqlite3.connect(journal.path) as connection:
        row = connection.execute(
            "SELECT state,result_json FROM evaluations WHERE run_id=? AND result_key=?",
            (request["run_id"], result_key),
        ).fetchone()
    assert row == ("CLAIMED", None)

    def commit():
        try:
            journal.commit_evaluation(request["run_id"], attempt_id, CELL_ID, result_key, value)
            return "committed"
        except N1RecoveryError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        commits = list(pool.map(lambda _index: commit(), range(2)))
    assert commits.count("committed") == 1
    assert commits.count("DUPLICATE_RESULT") == 1


def test_evaluator_result_candidate_must_match_fenced_fe_key(tmp_path):
    _config, _raw_run, _repository, journal, request, attempt_id = new_fixture(tmp_path)
    journal.claim_attempt(request["run_id"], attempt_id)
    candidate = [0.25]
    result_key = evaluation_result_key(request, CELL_ID, candidate)
    journal.claim_evaluation(request["run_id"], attempt_id, CELL_ID, result_key, candidate)
    result = {"candidate_vector": [0.75], "metrics": {"synthetic_peak_error": 0.5}}
    with pytest.raises(N1RecoveryError) as mismatch:
        journal.commit_evaluation(request["run_id"], attempt_id, CELL_ID, result_key, result)
    assert mismatch.value.code == "IDENTITY_MISMATCH"
    with sqlite3.connect(journal.path) as connection:
        row = connection.execute(
            "SELECT state,result_json FROM evaluations WHERE run_id=? AND result_key=?",
            (request["run_id"], result_key),
        ).fetchone()
    assert row == ("CLAIMED", None)
    with pytest.raises(N1RecoveryError) as blocked:
        journal.resume(request["run_id"], attempt_id, journal.identity(request["run_id"]))
    assert blocked.value.code == "RECOVERY_AMBIGUOUS"


@pytest.mark.parametrize("field", [
    "experiment_id", "authorization_test_only", "expected_cells",
    "execution_source_sha", "effective_config_sha256", "model_sha256",
    "search_grid_sha256", "validation_grid_sha256", "expected_cells_sha256",
    "topology", "design_bounds", "optimizer", "optimizer_state_version",
    "rng", "budget", "requested_unique_budget", "hard_max_budget",
    "validation_point_limit", "runtime", "authorization_reference",
])
def test_changed_frozen_identity_blocks_same_run_resume(tmp_path, field):
    _config, _raw_run, _repository, journal, request, attempt_id = new_fixture(tmp_path)
    changed = dict(request)
    changed[field] = {"changed": True}
    with pytest.raises(N1RecoveryError) as mismatch:
        journal.resume(request["run_id"], attempt_id, changed)
    assert mismatch.value.code == "IDENTITY_MISMATCH"
    assert journal.identity(request["run_id"]) == request


@pytest.mark.parametrize("crash_point", ["after_evaluator_return", "after_result_commit"])
def test_subprocess_crash_leaves_unreplayable_fe_state_and_closes_cleanly(tmp_path, crash_point):
    _config, raw_run, _repository, journal, request, attempt_id = new_fixture(tmp_path)
    journal.claim_attempt(request["run_id"], attempt_id)
    candidate = [0.375]
    result_key = evaluation_result_key(request, CELL_ID, candidate)
    marker = tmp_path / "evaluator-invoked.txt"
    script = '''
import json, os, sys
from pathlib import Path
from tests.fixtures.n1_transaction import N1RecoveryJournal
root, raw_run, run_id, attempt, cell, result_key, candidate_json, mode, marker = sys.argv[1:]
candidate = json.loads(candidate_json)
journal = N1RecoveryJournal.open_existing(root, raw_run=raw_run)
journal.claim_evaluation(run_id, attempt, cell, result_key, candidate)
value = float(candidate[0])
result = {"candidate_vector": candidate, "metrics": {"synthetic_peak_error": value * value}}
Path(marker).write_text("one synthetic evaluator invocation\\n", encoding="utf-8")
if mode == "after_evaluator_return":
    os._exit(73)
journal.commit_evaluation(run_id, attempt, cell, result_key, result)
os._exit(74)
'''
    child = subprocess.run(
        [
            sys.executable, "-c", script, str(journal.root), str(raw_run.path),
            request["run_id"], attempt_id, CELL_ID, result_key,
            json.dumps(candidate), crash_point, str(marker),
        ],
        cwd=Path(__file__).resolve().parents[2],
        text=True, capture_output=True, check=False,
    )
    assert child.returncode == (73 if crash_point == "after_evaluator_return" else 74), child.stderr
    assert marker.read_text(encoding="utf-8") == "one synthetic evaluator invocation\n"

    reopened = N1RecoveryJournal.open_existing(journal.root, raw_run=raw_run.path)
    with sqlite3.connect(reopened.path) as connection:
        row = connection.execute(
            "SELECT state,result_json FROM evaluations WHERE run_id=? AND result_key=?",
            (request["run_id"], result_key),
        ).fetchone()
    if crash_point == "after_evaluator_return":
        assert row == ("CLAIMED", None)
    else:
        assert row[0] == "COMMITTED"
        assert json.loads(row[1])["candidate_vector"] == candidate
    with pytest.raises(N1RecoveryError) as blocked:
        reopened.resume(request["run_id"], attempt_id, reopened.identity(request["run_id"]))
    assert blocked.value.code == "RECOVERY_AMBIGUOUS"
    with pytest.raises(N1RecoveryError, match="no retry"):
        reopened.claim_evaluation(request["run_id"], attempt_id, CELL_ID, result_key, candidate)


def test_journal_rejects_symlink_and_any_part_of_the_r5_raw_root(tmp_path):
    _config, raw_run, _repository, journal, _request, _attempt = new_fixture(tmp_path)
    alias = tmp_path / "journal-alias"
    alias.symlink_to(journal.root, target_is_directory=True)
    with pytest.raises(N1RecoveryError, match="symlinks"):
        N1RecoveryJournal(alias, raw_run=raw_run.path)

    nested_raw_root = raw_run.path.parents[2] / "journal-alias"
    nested_raw_root.mkdir(mode=0o700)
    with pytest.raises(N1RecoveryError, match="data-root tree"):
        N1RecoveryJournal(nested_raw_root, raw_run=raw_run.path)
    assert sorted(path.name for path in nested_raw_root.iterdir()) == []


def test_concurrent_resume_claims_create_one_fenced_successor(tmp_path):
    config, raw_run, _repository, journal, request, attempt_id = new_fixture(tmp_path)
    journal.claim_attempt(request["run_id"], attempt_id)
    calls = []
    backend = _backend(config)
    backend.initialize(_evaluator(config, request, journal, attempt_id, calls))
    _checkpoint(raw_run, journal, request, attempt_id, backend)
    _recovered, _session_value, _receipt, payload = _load_checkpoint(
        config, raw_run, journal, request,
    )

    def resume():
        try:
            return journal.resume(request["run_id"], attempt_id, journal.identity(request["run_id"]), payload)
        except N1RecoveryError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _index: resume(), range(2)))
    successors = [value for value in outcomes if isinstance(value, str) and len(value) == 32]
    assert len(successors) == 1
    assert len(outcomes) == 2
    with sqlite3.connect(journal.path) as connection:
        attempts = connection.execute(
            "SELECT attempt_id,generation,state FROM attempts WHERE run_id=? ORDER BY generation",
            (request["run_id"],),
        ).fetchall()
    assert len(attempts) == 2
    assert attempts[0] == (attempt_id, 1, "SUPERSEDED")
    assert attempts[1][0] == successors[0]
    assert attempts[1][1:] == (2, "CREATED")


def test_uncertain_r5_export_ack_reconciles_exact_local_package_without_acceptance(tmp_path):
    _config, raw_run, repository, journal, request, _attempt_id, _backend_value = _completed_fixture(tmp_path)
    raw_manifest_sha = hashlib.sha256((raw_run.path / "manifest.json").read_bytes()).hexdigest()
    journal.begin_export(request["run_id"], raw_manifest_sha)
    exported = export_review_package(raw_run.path, repository_root=repository)
    review_path = Path(exported.path)
    review_manifest = json.loads((review_path / "manifest.json").read_text(encoding="utf-8"))
    raw_manifest = json.loads((raw_run.path / "manifest.json").read_text(encoding="utf-8"))
    package_sha = _package_digest(review_path)
    assert review_manifest["run_id"] == request["run_id"]
    assert review_manifest["experiment_id"] == request["experiment_id"]
    assert review_manifest["execution_source_sha"] == request["execution_source_sha"]
    assert review_manifest["frozen_provenance_sha256"] == raw_manifest["frozen_provenance_sha256"]
    assert review_manifest["package_status"] == "READY_FOR_REVIEW"

    # Reopen after package creation but before the local ACK. Verification
    # requires the exact deterministic R5 package; it does not republish it.
    reopened = N1RecoveryJournal.open_existing(journal.root, raw_run=raw_run.path)
    assert reopened.export_receipt(request["run_id"]) is None
    assert _package_digest(review_path) == package_sha
    receipt = _reconcile_existing_export(raw_run, repository, reopened, request["run_id"])
    assert receipt["package_sha256"] == package_sha
    assert receipt["status"] == "READY_FOR_REVIEW"
    assert receipt["accepted"] is False


@pytest.mark.parametrize("crash_point", ["before_export", "after_package", "after_ack"])
def test_subprocess_export_crash_fails_closed_or_reconciles_exact_package(tmp_path, crash_point):
    _config, raw_run, repository, journal, request, _attempt_id, _backend_value = _completed_fixture(tmp_path)
    raw_manifest_sha = hashlib.sha256((raw_run.path / "manifest.json").read_bytes()).hexdigest()
    journal.begin_export(request["run_id"], raw_manifest_sha)
    script = '''
import os, sys
from pathlib import Path
from sawopt.io.experiment_store import ExperimentRun
from sawopt.reporting.experiment_review import export_review_package
from tests.fixtures.n1_transaction import N1RecoveryJournal
from tests.unit.test_n1_synthetic_recovery import _reconcile_existing_export
raw_path, repository, journal_root, run_id, mode = sys.argv[1:]
raw_run = ExperimentRun(raw_path)
if mode == "before_export":
    os._exit(81)
export_review_package(raw_path, repository_root=Path(repository))
if mode == "after_package":
    os._exit(82)
journal = N1RecoveryJournal.open_existing(journal_root, raw_run=raw_path)
_reconcile_existing_export(raw_run, Path(repository), journal, run_id)
os._exit(83)
'''
    child = subprocess.run(
        [sys.executable, "-c", script, str(raw_run.path), str(repository),
         str(journal.root), request["run_id"], crash_point],
        cwd=ROOT, text=True, capture_output=True, check=False, timeout=30,
    )
    assert child.returncode == {"before_export": 81, "after_package": 82, "after_ack": 83}[crash_point], child.stderr
    reopened = N1RecoveryJournal.open_existing(journal.root, raw_run=raw_run.path)
    if crash_point == "before_export":
        with pytest.raises(N1RecoveryError, match="no exact existing review package"):
            _reconcile_existing_export(raw_run, repository, reopened, request["run_id"])
        assert reopened.run_state(request["run_id"]) == "EXPORT_INTENT"
        assert not _review_destination(raw_run, repository).exists()
    else:
        receipt = _reconcile_existing_export(raw_run, repository, reopened, request["run_id"])
        assert receipt["run_id"] == request["run_id"]
        assert receipt["experiment_id"] == request["experiment_id"]
        assert receipt["accepted"] is False
        assert receipt["package_sha256"] == _package_digest(_review_destination(raw_run, repository))
        assert reopened.run_state(request["run_id"]) == "EXPORT_READY"


def test_concurrent_and_repeated_r5_export_requests_do_not_publish_twice(tmp_path):
    _config, raw_run, repository, journal, request, _attempt_id, _backend_value = _completed_fixture(tmp_path)
    entered, release = Event(), Event()
    export_calls = []

    def blocked_exporter(*args, **kwargs):
        export_calls.append(1)
        entered.set()
        if not release.wait(timeout=10):
            raise TimeoutError("test export release was not signalled")
        return export_review_package(*args, **kwargs)

    with ThreadPoolExecutor(max_workers=1) as pool:
        first_future = pool.submit(
            _export_once, raw_run, repository, journal, request["run_id"],
            exporter=blocked_exporter,
        )
        assert entered.wait(timeout=10)
        with pytest.raises(N1RecoveryError, match="no exact existing review package"):
            _export_once(
                raw_run, repository, journal, request["run_id"],
                exporter=lambda *_args, **_kwargs: pytest.fail("duplicate exporter invocation"),
            )
        release.set()
        first = first_future.result(timeout=30)
    second = _export_once(
        raw_run, repository, journal, request["run_id"],
        exporter=lambda *_args, **_kwargs: pytest.fail("repeated exporter invocation"),
    )
    assert first == second
    assert export_calls == [1]


@pytest.mark.parametrize("checkpoint_damage", ["missing", "corrupt"])
def test_missing_or_corrupt_checkpoint_cannot_be_resumed(tmp_path, checkpoint_damage):
    config, raw_run, _repository, journal, request, attempt_id = new_fixture(tmp_path)
    journal.claim_attempt(request["run_id"], attempt_id)
    calls = []
    backend = _backend(config)
    backend.initialize(_evaluator(config, request, journal, attempt_id, calls))
    _receipt, session = _checkpoint(raw_run, journal, request, attempt_id, backend)
    if checkpoint_damage == "missing":
        session.store.latest_path.unlink()
        with pytest.raises(FileNotFoundError):
            session.store.load_state(
                validator=lambda state: session._validate(backend, state),
                preflight_validator=validate_lshade_checkpoint_header,
                include_final=False,
            )
    else:
        payload = json.loads(session.store.latest_path.read_text(encoding="utf-8"))
        payload["unique_evaluations"] -= 1
        with pytest.raises(N1RecoveryError, match="hash differs"):
            journal.verify_checkpoint(request["run_id"], payload)
        session.store.latest_path.write_text("{corrupt", encoding="utf-8")
        with pytest.raises(CheckpointLoadError):
            session.store.load_state(
                validator=lambda state: session._validate(backend, state),
                preflight_validator=validate_lshade_checkpoint_header,
                include_final=False,
            )
    with pytest.raises(N1RecoveryError) as blocked:
        journal.resume(request["run_id"], attempt_id, journal.identity(request["run_id"]))
    assert blocked.value.code == "RECOVERY_AMBIGUOUS"


@pytest.mark.parametrize("corruption", ["missing", "orphan", "uncommitted", "mismatched_candidate"])
def test_result_journal_roster_must_match_exact_checkpoint(tmp_path, corruption):
    config, raw_run, _repository, journal, request, attempt_id, _backend_value = _completed_fixture(tmp_path)
    with sqlite3.connect(journal.path) as connection:
        if corruption == "missing":
            connection.execute(
                "DELETE FROM evaluations WHERE rowid=(SELECT rowid FROM evaluations WHERE run_id=? LIMIT 1)",
                (request["run_id"],),
            )
        elif corruption == "uncommitted":
            connection.execute(
                "UPDATE evaluations SET state='CLAIMED',result_json=NULL,result_sha256=NULL "
                "WHERE rowid=(SELECT rowid FROM evaluations WHERE run_id=? LIMIT 1)",
                (request["run_id"],),
            )
        elif corruption == "mismatched_candidate":
            row = connection.execute(
                "SELECT rowid,result_json FROM evaluations WHERE run_id=? LIMIT 1",
                (request["run_id"],),
            ).fetchone()
            result_value = json.loads(row[1])
            result_value["candidate_vector"] = [0.875]
            result_json = json.dumps(result_value, sort_keys=True, separators=(",", ":"), allow_nan=False)
            result_sha = hashlib.sha256(result_json.encode("utf-8")).hexdigest()
            connection.execute(
                "UPDATE evaluations SET result_json=?,result_sha256=? WHERE rowid=?",
                (result_json, result_sha, row[0]),
            )
        else:
            candidate = [0.875]
            key = evaluation_result_key(request, CELL_ID, candidate)
            _response, metrics = _metrics(config, candidate, config["search_grid"])
            value = {
                "candidate_vector": candidate, "metrics": metrics, "violations": {},
                "feasible": True, "max_violation": 0.0, "sum_violation": 0.0,
            }
            result_json = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
            result_sha = hashlib.sha256(result_json.encode("utf-8")).hexdigest()
            connection.execute(
                "INSERT INTO evaluations VALUES (?,?,?,?,'COMMITTED',?,?,?)",
                (request["run_id"], CELL_ID, key, json.dumps(candidate, separators=(",", ":")),
                 attempt_id, result_json, result_sha),
            )
    checkpoint = json.loads((raw_run.path / "checkpoints/n1/latest.json").read_text(encoding="utf-8"))
    with pytest.raises(N1RecoveryError) as blocked:
        journal.verify_checkpoint(request["run_id"], checkpoint)
    assert blocked.value.code == "RECOVERY_AMBIGUOUS"


def test_r5_export_is_not_available_before_close_and_never_overwrites_existing_package(tmp_path):
    config, raw_run, repository, journal, request, attempt_id = new_fixture(tmp_path)
    with pytest.raises(ReviewPackageError):
        export_review_package(raw_run.path, repository_root=repository)
    raw_manifest_sha = hashlib.sha256((raw_run.path / "manifest.json").read_bytes()).hexdigest()
    with pytest.raises(N1RecoveryError) as premature:
        journal.begin_export(request["run_id"], raw_manifest_sha)
    assert premature.value.code == "EXPORT_NOT_READY"

    journal.claim_attempt(request["run_id"], attempt_id)
    calls = []
    backend = _backend(config)
    backend.initialize(_evaluator(config, request, journal, attempt_id, calls))
    backend.advance_to_unique_budget(request["budget"])
    _checkpoint(raw_run, journal, request, attempt_id, backend)
    _finish_raw_run(config, raw_run, journal, request, backend)
    destination = _review_destination(raw_run, repository)
    first = _export_once(
        raw_run, repository, journal, request["run_id"], exporter=export_review_package,
    )
    assert first["status"] == "READY_FOR_REVIEW"
    manifest_before = (destination / "manifest.json").read_bytes()
    (destination / "README.md").write_text("test-owned changed file\n", encoding="utf-8")
    with pytest.raises(ReviewPackageError, match="differs from deterministic export"):
        export_review_package(raw_run.path, repository_root=repository)
    with pytest.raises(N1RecoveryError, match="cannot be verified exactly"):
        _export_once(
            raw_run, repository, journal, request["run_id"],
            exporter=lambda *_args, **_kwargs: pytest.fail("acknowledged export must not run again"),
        )
    assert (destination / "manifest.json").read_bytes() == manifest_before
    assert (destination / "README.md").read_text(encoding="utf-8") == "test-owned changed file\n"


def test_checkpoint_write_failure_retains_previous_checkpoint_and_blocks_recovery(tmp_path):
    config, raw_run, _repository, journal, request, first_attempt = new_fixture(tmp_path)
    journal.claim_attempt(request["run_id"], first_attempt)
    calls = []
    backend = _backend(config)
    backend.initialize(_evaluator(config, request, journal, first_attempt, calls))
    _checkpoint(raw_run, journal, request, first_attempt, backend)
    resumed, _session_value, _receipt, initial_payload = _load_checkpoint(
        config, raw_run, journal, request,
    )
    initial_sha = digest(initial_payload)

    successor = journal.resume(
        request["run_id"], first_attempt, journal.identity(request["run_id"]), initial_payload,
    )
    journal.claim_attempt(request["run_id"], successor)
    resumed.set_evaluator(_evaluator(config, request, journal, successor, calls))
    resumed.advance_to_unique_budget(request["budget"])
    _receipt, session = _checkpoint(raw_run, journal, request, successor, resumed, fail_write=True)
    latest = json.loads(session.store.latest_path.read_text(encoding="utf-8"))
    assert digest(latest) == initial_sha
    with pytest.raises(N1RecoveryError) as blocked:
        journal.reconcile_checkpoint(request["run_id"], latest, digest(latest))
    assert blocked.value.code == "RECOVERY_AMBIGUOUS"
    with pytest.raises(N1RecoveryError):
        journal.resume(request["run_id"], successor, journal.identity(request["run_id"]))
