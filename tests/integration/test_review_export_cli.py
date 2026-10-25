from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sawopt.cli import build_parser, main
from sawopt.io.experiment_store import create_experiment_run


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_SHA = "c" * 40
RUN_ID = "20261025T000000Z-00000125"
CELL_ID = "synthetic-fixture"


def _closed_raw_run(
    tmp_path: Path,
    *,
    status: str = "COMPLETED",
    requires_comparison: bool = False,
    requires_validation: bool = False,
    with_checkpoint: bool = False,
):
    data_root = tmp_path / "test-owned-external-r5-root"
    data_root.mkdir(parents=True)
    run = create_experiment_run(
        "review-cli-test",
        data_root=data_root,
        required_free_bytes=1,
        run_id=RUN_ID,
        source_sha=SOURCE_SHA,
        effective_config={"synthetic_fixture": True, "unit": "dimensionless"},
        scientific_inputs={
            "model": {"offset": 0.25},
            "search_grid": {"points": [0.0, 1.0]},
            "validation_grid": {"points": [0.0, 0.5, 1.0]},
        },
        expected_cells=[{
            "cell_id": CELL_ID, "topology": "synthetic-fixture", "method": "fixture", "seed": 1,
        }],
        search_fe_limit=10,
        validation_point_limit=3,
        review_context={
            "purpose": "Synthetic R5 CLI export test",
            "conditions": "Test-owned fixture only; no COM/FE or optimizer execution",
            "findings": "Fixture evidence only",
            "limitations": "Does not qualify scientific behavior",
            "review_instructions": "Verify fixture identities and statuses",
            "scientific_disposition": "CLAIM_PENDING_REVIEW",
            "requires_comparison": requires_comparison,
            "requires_validation": requires_validation,
        },
    )
    if with_checkpoint:
        run.record_cell(CELL_ID, status="RUNNING", executed=True, search_fes=2)
        checkpoint = run.checkpoint_store("fixture")
        checkpoint.write(lambda path: path.write_text('{"fixture": true}\n', encoding="utf-8"))
        run.record_checkpoint(
            CELL_ID, phase="SEARCH", search_fes=1, validation_points=0,
            metric_name="synthetic_error", metric_value=0.5, unit="dimensionless",
            observed_at_utc="2026-10-25T00:01:00Z",
        )
        run.record_cell(
            CELL_ID, status="FAILED", executed=True, search_fes=2, validation_points=0,
            reason="synthetic fixture closed as failed", failure_class="MODEL",
        )
        run.close(status="FAILED")
    elif status == "COMPLETED":
        run.record_cell(
            CELL_ID, status="COMPLETED", executed=True, search_fes=1, validation_points=0,
            result={"synthetic_peak_error": 0.5, "feasible": True},
            design={"value": 0.25}, geometry={"status": "NOT_APPLICABLE"},
            search_metrics={"synthetic_peak_error": 0.5}, search_violations={}, feasible=True,
        )
        run.close(status="COMPLETED")
    elif status == "FAILED":
        run.record_cell(
            CELL_ID, status="FAILED", executed=True, search_fes=0, validation_points=0,
            reason="synthetic fixture closed as failed", failure_class="MODEL",
        )
        run.close(status="FAILED")
    elif status == "INCOMPLETE":
        run.record_cell(
            CELL_ID, status="INCOMPLETE", executed=True, search_fes=1, validation_points=0,
            reason="synthetic fixture intentionally incomplete",
        )
        run.close(status="INCOMPLETE")
    elif status == "RUNNING":
        run.record_cell(CELL_ID, status="RUNNING", executed=True, search_fes=1)
    else:
        raise AssertionError(f"unknown fixture status: {status}")
    return run


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "test-owned-review-repository"
    repository.mkdir()
    return repository


def _argv(raw_path: Path, repository: Path) -> list[str]:
    return ["review", "export", "--run", str(raw_path), "--repository-root", str(repository)]


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*") if path.is_file()
    }


def test_review_export_parser_help_and_required_arguments(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as missing:
        parser.parse_args(["review", "export"])
    assert missing.value.code == 2

    with pytest.raises(SystemExit) as help_exit:
        parser.parse_args(["review", "export", "--help"])
    assert help_exit.value.code == 0
    help_text = capsys.readouterr().out
    assert "--run" in help_text
    assert "--repository-root" in help_text


def test_closed_runs_export_to_canonical_package_and_repeat_byte_identically(tmp_path, capsys):
    for status in ("COMPLETED", "FAILED", "INCOMPLETE"):
        case = tmp_path / status.lower()
        case.mkdir()
        run = _closed_raw_run(case, status=status)
        repository = _repository(case)
        raw_before = _snapshot(run.path)

        assert main(_argv(run.path, repository)) == 0
        first = json.loads(capsys.readouterr().out)
        expected = repository / "reports" / "experiments" / run.experiment_id / run.run_id
        assert first == {
            "experiment_id": run.experiment_id,
            "package_status": "READY_FOR_REVIEW",
            "review_directory": str(expected),
            "run_id": run.run_id,
            "status": "EXPORTED",
        }
        review_manifest = json.loads((expected / "manifest.json").read_text(encoding="utf-8"))
        assert review_manifest["review_schema_id"] == "sawopt.review/1"
        assert review_manifest["review_schema_version"] == 1
        assert review_manifest["package_status"] == "READY_FOR_REVIEW"
        assert review_manifest["raw_run_status"] == status
        package_before = _snapshot(expected)

        assert main(_argv(run.path, repository)) == 0
        repeated = json.loads(capsys.readouterr().out)
        assert repeated == {**first, "status": "ALREADY_VALID"}
        assert _snapshot(expected) == package_before
        assert _snapshot(run.path) == raw_before


def test_review_export_dispatch_does_not_request_source_sha_run_or_synthetic_task(tmp_path):
    run = _closed_raw_run(tmp_path)
    repository = _repository(tmp_path)
    script = r"""
import sys
from sawopt import cli

def forbidden(*args, **kwargs):
    raise AssertionError("review export touched a run/evaluation dispatch")

cli._source_sha = forbidden
cli.run_experiment = forbidden
cli._synthetic_task_main = forbidden
assert not any(name.startswith("sawopt.physics") for name in sys.modules)
assert cli.main(["review", "export", "--run", sys.argv[1], "--repository-root", sys.argv[2]]) == 0
assert not any(name.startswith("sawopt.physics") for name in sys.modules)
assert "sawopt.optimization.lshade" not in sys.modules
assert "sawopt.synthetic_worker" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(run.path), str(repository)],
        cwd=PROJECT_ROOT, text=True, capture_output=True, check=False,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["package_status"] == "READY_FOR_REVIEW"
    assert result.stderr == ""


@pytest.mark.parametrize("status", ["FAILED", "INCOMPLETE"])
def test_closed_noncompleted_run_status_is_not_recast_as_scientific_success(tmp_path, status, capsys):
    run = _closed_raw_run(tmp_path, status=status)
    repository = _repository(tmp_path)

    assert main(_argv(run.path, repository)) == 0
    result = json.loads(capsys.readouterr().out)
    manifest = json.loads((Path(result["review_directory"]) / "manifest.json").read_text(encoding="utf-8"))
    cells = json.loads((Path(result["review_directory"]) / "cells.json").read_text(encoding="utf-8"))
    assert result["package_status"] == "READY_FOR_REVIEW"
    assert manifest["raw_run_status"] == status
    assert cells[0]["status"] == status
    assert manifest["completeness"]["scientifically_completed_cells"] == 0


def test_review_export_failures_are_json_private_and_leave_no_success_output(tmp_path, capsys):
    run = _closed_raw_run(tmp_path, status="RUNNING")
    repository = _repository(tmp_path)

    assert main(_argv(run.path, repository)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["error"]["code"] == "REVIEW_EXPORT_FAILED"
    assert str(run.path) not in captured.err
    assert not (repository / "reports" / "experiments" / run.experiment_id / run.run_id).exists()


def test_review_export_rejects_relative_run_path_as_json(tmp_path, capsys):
    repository = _repository(tmp_path)
    assert main(["review", "export", "--run", "relative/raw/run", "--repository-root", str(repository)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "REVIEW_EXPORT_FAILED"
    assert "relative/raw/run" not in captured.err


@pytest.mark.parametrize("invalidity", ["old_schema", "identity_mismatch", "raw_tamper", "symlink"])
def test_invalid_raw_evidence_and_unsafe_path_fail_closed(tmp_path, capsys, invalidity):
    run = _closed_raw_run(tmp_path)
    repository = _repository(tmp_path)
    raw_path = run.path
    if invalidity == "old_schema":
        manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
        manifest["schema_version"] = 4
        (run.path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    elif invalidity == "identity_mismatch":
        manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
        manifest["run_id"] = "20261025T000000Z-00000124"
        (run.path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    elif invalidity == "raw_tamper":
        (run.path / "config.yaml").write_text("synthetic_fixture: false\n", encoding="utf-8")
    else:
        raw_path = tmp_path / "symlink-to-raw-run"
        raw_path.symlink_to(run.path, target_is_directory=True)

    assert main(_argv(raw_path, repository)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "REVIEW_EXPORT_FAILED"
    assert str(raw_path) not in captured.err
    assert not (repository / "reports" / "experiments" / run.experiment_id / run.run_id).exists()


@pytest.mark.parametrize("required_artifact", ["comparison", "validation"])
def test_missing_required_comparison_or_validation_evidence_fails_closed(tmp_path, capsys, required_artifact):
    run = _closed_raw_run(
        tmp_path,
        status="FAILED",
        requires_comparison=required_artifact == "comparison",
        requires_validation=required_artifact == "validation",
    )
    repository = _repository(tmp_path)

    assert main(_argv(run.path, repository)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "REVIEW_EXPORT_FAILED"
    assert not (repository / "reports" / "experiments" / run.experiment_id / run.run_id).exists()


def test_checkpoint_tampering_fails_closed_through_review_cli(tmp_path, capsys):
    run = _closed_raw_run(tmp_path, with_checkpoint=True)
    repository = _repository(tmp_path)
    latest = run.path / "checkpoints" / "fixture" / "latest.json"
    latest.write_text('{"fixture": false}\n', encoding="utf-8")

    assert main(_argv(run.path, repository)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "REVIEW_EXPORT_FAILED"
    assert not (repository / "reports" / "experiments" / run.experiment_id / run.run_id).exists()


def test_conflicting_review_package_is_never_overwritten(tmp_path, capsys):
    run = _closed_raw_run(tmp_path)
    repository = _repository(tmp_path)

    assert main(_argv(run.path, repository)) == 0
    initial = capsys.readouterr()
    result = json.loads(initial.out)
    package = Path(result["review_directory"])
    marker = b"test-owned conflicting contents\n"
    (package / "README.md").write_bytes(marker)

    assert main(_argv(run.path, repository)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "REVIEW_EXPORT_FAILED"
    assert (package / "README.md").read_bytes() == marker
    assert not list(package.parent.glob(".r5-*.tmp"))


def test_repository_local_fake_raw_root_is_rejected(tmp_path, capsys):
    run = _closed_raw_run(tmp_path / "source")
    repository = _repository(tmp_path)
    (repository / ".git").mkdir()
    copied_root = repository / "data"
    copied_run = copied_root / "runs" / run.experiment_id / run.run_id
    copied_run.parent.mkdir(parents=True)
    shutil.copytree(run.path, copied_run)

    assert main(_argv(copied_run, repository)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "REVIEW_EXPORT_FAILED"
    assert not (repository / "reports" / "experiments" / run.experiment_id / run.run_id).exists()
