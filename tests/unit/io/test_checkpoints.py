import json

import numpy as np
import pytest

from sawopt.io.checkpoints import (
    CheckpointFinalizationError,
    CheckpointStore,
    complete_study_run,
    finalize_direct_run,
    finalize_run_checkpoints,
)
from sawopt.io.lifecycle import RunDisposition
from sawopt.optimization.checkpoint_session import LShadeCheckpointSession
from sawopt.optimization.lshade import LShadeBackend
def _write_json(path, value):
    path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")


def _state_value(value):
    return lambda path: _write_json(path, {"value": value})


def test_store_retains_only_latest_and_previous_generations(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints", run_directory=tmp_path)

    store.write(_state_value(1))
    assert json.loads(store.latest_path.read_text(encoding="utf-8")) == {"value": 1}
    assert not store.previous_path.exists()

    store.write(_state_value(2))
    store.write(_state_value(3))
    assert json.loads(store.latest_path.read_text(encoding="utf-8")) == {"value": 3}
    assert json.loads(store.previous_path.read_text(encoding="utf-8")) == {"value": 2}
    assert len(list(store.directory.glob("*.json"))) == 3  # two states + retention metadata
    manifest = json.loads(store.retention_path.read_text(encoding="utf-8"))
    assert manifest["write_count"] == 3


def test_failed_temporary_write_keeps_both_retained_generations(tmp_path):
    store = CheckpointStore(tmp_path / "stream")
    store.write(_state_value(1))
    store.write(_state_value(2))

    def interrupted(path):
        path.write_text('{"partial":', encoding="utf-8")
        raise OSError("simulated interrupted write")

    with pytest.raises(OSError, match="simulated interrupted write"):
        store.write(interrupted)

    assert json.loads(store.latest_path.read_text(encoding="utf-8")) == {"value": 2}
    assert json.loads(store.previous_path.read_text(encoding="utf-8")) == {"value": 1}
    assert not list(store.directory.glob(".latest.*.tmp"))


def test_corrupt_latest_falls_back_to_previous(tmp_path):
    store = CheckpointStore(tmp_path / "stream")
    store.write(_state_value(1))
    store.write(_state_value(2))
    store.latest_path.write_text('{"value":', encoding="utf-8")

    loaded = store.load_state()
    assert loaded.state == {"value": 1}
    assert loaded.source == store.previous_path
    assert loaded.recovered_from_previous is True


def test_semantically_invalid_latest_uses_previous_validator(tmp_path):
    store = CheckpointStore(tmp_path / "stream")
    store.write(_state_value(1))
    store.write(_state_value(2))

    def require_positive(state):
        if state["value"] != 1:
            raise ValueError("fixture rejects latest")

    loaded = store.load_state(validator=require_positive)
    assert loaded.state == {"value": 1}
    assert loaded.recovered_from_previous


def _sphere(vector):
    value = float(np.sum((np.asarray(vector) - 0.35) ** 2))
    return {
        "feasible": True,
        "max_violation": 0.0,
        "violations": {},
        "metrics": {"worst_il_db": value, "ripple_db": value},
    }


def _backend(seed=17):
    config = {
        "initial_population": 8,
        "min_population": 4,
        "history_size": 4,
        "pbest_max_fraction": 0.3,
        "max_duplicate_retries": 3,
        "total_budget": 64,
    }
    return LShadeBackend([(0, 1)] * 3, seed=seed, config=config, integer_indices=())


def _session(root):
    return LShadeCheckpointSession(
        root / "checkpoints",
        run_directory=root,
    )


def test_fixed_seed_resume_matches_uninterrupted_lshade_run(tmp_path):
    uninterrupted = _backend()
    uninterrupted.initialize(_sphere)
    uninterrupted.advance_to_unique_budget(64)

    split = _backend()
    split.initialize(_sphere)
    split.advance_to_unique_budget(32)
    _session(tmp_path).save(split)

    resumed = _backend()
    resumed_session = _session(tmp_path)
    assert resumed_session.has_checkpoint
    loaded = resumed_session.load(resumed)
    assert loaded is not None
    assert loaded.source.name == "latest.json"
    resumed.set_evaluator(_sphere)
    resumed.advance_to_unique_budget(64)

    np.testing.assert_array_equal(uninterrupted.population(), resumed.population())
    assert uninterrupted.incumbent() == resumed.incumbent()
    assert uninterrupted.rng.bit_generator.state == resumed.rng.bit_generator.state
    assert uninterrupted.unique_evaluations == resumed.unique_evaluations
    assert uninterrupted.generations == resumed.generations
    assert uninterrupted.proposals_total == resumed.proposals_total
    assert uninterrupted.duplicate_count == resumed.duplicate_count
    assert uninterrupted.incumbent()["metrics"] == resumed.incumbent()["metrics"]


def test_runtime_result_reference_names_logical_stream_not_future_final(tmp_path):
    session = _session(tmp_path)
    assert session.reference_path is None
    assert session.reference_metadata == {
        "checkpoint_policy": "rolling_latest_previous",
        "checkpoint_stream": "checkpoints",
        "checkpoint_state": "runtime_recovery",
    }

    backend = _backend()
    backend.initialize(_sphere)
    backend.advance_to_unique_budget(8)
    session.save(backend)
    assert session.reference_metadata["checkpoint_stream"] == "checkpoints"
    assert session.reference_metadata["checkpoint_state"] == "runtime_recovery"
    assert session.store.latest_path.is_file()
    assert not session.store.final_path.exists()


def test_history_remains_complete_while_checkpoint_storage_is_bounded(tmp_path):
    import csv

    backend = _backend()
    backend.initialize(_sphere)
    history_path = tmp_path / "history" / "convergence.csv"
    history_path.parent.mkdir(parents=True)
    store = CheckpointStore(tmp_path / "checkpoints", run_directory=tmp_path)
    with history_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=(
            "evaluation", "generation", "best_objective", "population_mean",
            "population_std", "proposal_count", "duplicate_count",
        ))
        writer.writeheader()
        for budget in (16, 32, 48, 64):
            backend.advance_to_unique_budget(budget)
            incumbent = backend.incumbent()
            population = backend.population()
            writer.writerow({
                "evaluation": backend.unique_evaluations,
                "generation": backend.generations,
                "best_objective": incumbent["metrics"]["worst_il_db"],
                "population_mean": float(np.mean(population)),
                "population_std": float(np.std(population)),
                "proposal_count": backend.proposals_total,
                "duplicate_count": backend.duplicate_count,
            })
            store.write(backend.save_checkpoint)

    with history_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    evaluations = [int(row["evaluation"]) for row in rows]
    assert evaluations == [16, 32, 48, 64]
    assert [int(row["generation"]) for row in rows] == sorted(
        int(row["generation"]) for row in rows
    )
    assert len(rows) == 4
    assert json.loads(store.latest_path.read_text(encoding="utf-8"))["unique_evaluations"] == 64
    assert json.loads(store.previous_path.read_text(encoding="utf-8"))["unique_evaluations"] == 48
    stream_metadata = json.loads(store.retention_path.read_text(encoding="utf-8"))
    assert stream_metadata["write_count"] == 4
    assert len([store.latest_path, store.previous_path]) == 2


def test_failed_finalize_keeps_recovery_until_completion_marker(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints", run_directory=tmp_path)
    store.write(_state_value(1))
    store.write(_state_value(2))

    with pytest.raises(CheckpointFinalizationError, match="COMPLETED marker"):
        finalize_run_checkpoints(tmp_path)

    assert store.latest_path.exists()
    assert store.previous_path.exists()


def test_explicit_failed_disposition_records_and_preserves_recovery(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints", run_directory=tmp_path)
    store.write(_state_value(1))
    store.write(_state_value(2))

    result = complete_study_run(
        tmp_path, {"status": "FAIL_STOP"}, disposition=RunDisposition.FAILED,
    )
    assert result["status"] == "FAILED"
    marker = json.loads((tmp_path / "metadata" / "run_completion.json").read_text())
    assert marker["disposition"] == "FAILED"
    assert not store.final_path.exists()
    assert store.latest_path.exists()
    assert store.previous_path.exists()


def test_review_waiting_disposition_keeps_runtime_generations_and_metadata(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints", run_directory=tmp_path)
    store.write(_state_value(1))
    store.write(_state_value(2))
    result = complete_study_run(
        tmp_path, {"status": "COMPLETE"},
        disposition=RunDisposition.REVIEW_WAITING,
    )
    assert result["status"] == "REVIEW_WAITING"
    marker = json.loads((tmp_path / "metadata" / "run_completion.json").read_text())
    assert marker["disposition"] == "REVIEW_WAITING"
    assert not store.final_path.exists()
    assert store.latest_path.exists()
    assert store.previous_path.exists()


def test_missing_or_unknown_disposition_never_finalizes(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints", run_directory=tmp_path)
    store.write(_state_value(1))
    store.write(_state_value(2))

    result = complete_study_run(tmp_path, {"status": "COMPLETED"})
    assert result["status"] == "UNKNOWN"
    marker = json.loads((tmp_path / "metadata" / "run_completion.json").read_text())
    assert marker["disposition"] == "UNKNOWN"
    assert store.latest_path.exists() and store.previous_path.exists()
    assert not store.final_path.exists()

    complete_study_run(tmp_path, disposition=RunDisposition.UNKNOWN)
    assert store.latest_path.exists() and store.previous_path.exists()
    assert not store.final_path.exists()
    with pytest.raises(CheckpointFinalizationError, match="durable COMPLETED marker"):
        finalize_run_checkpoints(tmp_path)
    assert store.latest_path.exists() and store.previous_path.exists()
    assert not store.final_path.exists()


def test_generic_core_honors_explicit_disposition_without_stage_marker_translation(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints", run_directory=tmp_path)
    store.write(_state_value(5))
    (tmp_path / "PHASE_C_SUPPLEMENT_COMPLETE_WAITING_FOR_REVIEW.txt").write_text(
        "historical\n", encoding="utf-8",
    )

    result = complete_study_run(tmp_path, disposition=RunDisposition.COMPLETED)
    assert result["status"] == "FINALIZED"
    assert store.final_path.is_file()
    assert not store.latest_path.exists()


def test_unrecognized_retention_file_is_not_discovered_as_managed_store(tmp_path):
    unrecognized = tmp_path / "misc" / "checkpoints" / "retention.json"
    unrecognized.parent.mkdir(parents=True)
    _write_json(unrecognized, {"policy": "other", "format_version": 1})

    assert finalize_run_checkpoints(tmp_path) == {
        "status": "NO_MANAGED_CHECKPOINTS", "finalized_streams": 0,
    }
    assert unrecognized.is_file()


def test_direct_completion_promotes_final_and_keeps_only_explicit_pin_and_history(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints", run_directory=tmp_path)
    store.write(_state_value(1))
    store.write(_state_value(2))
    pinned = store.pin("diagnostic_32k")
    policy_while_active = json.loads(
        (tmp_path / "metadata" / "recovery_policy.json").read_text(encoding="utf-8")
    )
    assert policy_while_active["pinned_checkpoint_count"] == 1
    (tmp_path / "history").mkdir()
    (tmp_path / "history" / "convergence.csv").write_text("eval,best\n1,1\n", encoding="utf-8")

    result = finalize_direct_run(tmp_path)
    assert result["status"] == "FINALIZED"
    assert store.final_path.is_file()
    assert json.loads(store.final_path.read_text(encoding="utf-8")) == {"value": 2}
    assert not store.latest_path.exists()
    assert not store.previous_path.exists()
    assert pinned.is_file()
    assert store.retention_path.is_file()
    completion = json.loads((tmp_path / "metadata" / "run_completion.json").read_text())
    assert completion["disposition"] == "COMPLETED"
    assert completion["final_checkpoint"] == "checkpoints/final.json"
    assert (tmp_path / completion["final_checkpoint"]).is_file()

    policy = json.loads((tmp_path / "metadata" / "recovery_policy.json").read_text(encoding="utf-8"))
    assert policy["checkpoint_policy"] == "rolling_latest_previous"
    assert policy["checkpoint_retention_count"] == 2
    assert policy["checkpoint_rotation_enabled"] is True
    assert policy["final_checkpoint_present"] is True
    assert policy["pinned_checkpoint_count"] == 1
    assert policy["checkpoint_write_count"] == 2
    assert policy["retained_full_checkpoint_count"] == 2
    assert policy["history_artifacts"] == ["history/convergence.csv"]

    again = finalize_run_checkpoints(tmp_path)
    assert again["status"] == "FINALIZED"
    assert store.final_path.is_file()


def test_finalizer_ignores_legacy_checkpoint_without_store_marker(tmp_path):
    legacy = tmp_path / "seed" / "optimizer_checkpoint.json"
    legacy.parent.mkdir()
    legacy.write_text('{"old": true}', encoding="utf-8")

    assert finalize_run_checkpoints(tmp_path) == {
        "status": "NO_MANAGED_CHECKPOINTS",
        "finalized_streams": 0,
    }
    assert legacy.read_text(encoding="utf-8") == '{"old": true}'


def test_finalization_promotes_previous_when_latest_is_corrupt(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints", run_directory=tmp_path)
    store.write(_state_value(1))
    store.write(_state_value(2))
    store.latest_path.write_text('{"value":', encoding="utf-8")
    (tmp_path / "metadata" / "run_completion.json").parent.mkdir(parents=True, exist_ok=True)
    _write_json(tmp_path / "metadata" / "run_completion.json", {
        "status": "COMPLETED", "disposition": "COMPLETED",
    })

    result = finalize_run_checkpoints(tmp_path)
    assert result["status"] == "FINALIZED"
    assert json.loads(store.final_path.read_text(encoding="utf-8")) == {"value": 1}
    assert not store.latest_path.exists()
    assert not store.previous_path.exists()


def test_resume_after_finalization_preserves_previous_final_until_next_closeout(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints", run_directory=tmp_path)
    store.write(_state_value(1))
    finalize_direct_run(tmp_path)
    assert store.final_path.is_file()

    store.write(_state_value(2))

    policy = json.loads((tmp_path / "metadata" / "recovery_policy.json").read_text(encoding="utf-8"))
    assert policy["status"] == "ACTIVE"
    assert policy["final_checkpoint_present"] is True
    assert store.final_path.is_file()
    assert json.loads(store.final_path.read_text(encoding="utf-8")) == {"value": 1}
    finalize_direct_run(tmp_path)
    assert json.loads(store.final_path.read_text(encoding="utf-8")) == {"value": 2}
