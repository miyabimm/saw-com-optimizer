"""Library-only, explicitly injected R5 fixture lifecycle; not scientific execution."""
from __future__ import annotations

import copy
import csv
import io
import os
from collections.abc import Mapping

import numpy as np

from ..design.space import canonical_design
from ..evaluation import measure
from ..optimization.configured_search import _input_snapshot, run_configured_lshade
from ..physics.network import evaluate as evaluate_network
from ..problem.evaluator import _thaw
from .configured_persistence import (
    PersistencePlanError, ReviewEvidenceUnavailable, _equal, _incident_classification,
    _raw_payload, build_persistence_plan,
)
from .experiment_store import (
    _validate_run_id, _validate_source_sha, create_experiment_run, read_experiment_manifest,
)


def _response_csv(response, record, context):
    """Check the captured samples against the selected validation record, then serialize."""
    if not isinstance(response, Mapping):
        raise ValueError("validation response must be a mapping")
    for key, expected in (
        ("canonical_vector", record["canonical_vector"]),
        ("effective_config_sha256", context.effective_config_sha256),
        ("model_sha256", context.input_sha256["model"]),
        ("grid_sha256", context.validation_grid_sha256),
        ("source_impedance_ohm", context.source_impedance_ohm),
        ("load_impedance_ohm", context.load_impedance_ohm),
    ):
        _equal(response[key], expected, f"validation response {key}")
    n = len(context.validation_frequencies_hz)
    shapes = {"frequencies_hz": (n,), "y_parameters": (n, 2, 2), "s": (n, 2, 2),
              "gt": (n,), "il_db": (n,), "vswr": (n, 2)}
    if "return_loss_db" in response:
        shapes["return_loss_db"] = (n, 2)
    if set(response) != set(shapes) | {"canonical_vector", "effective_config_sha256", "model_sha256", "grid_sha256", "source_impedance_ohm", "load_impedance_ohm"}:
        raise ValueError("unexpected validation response fields")
    arrays = {}
    for name, shape in shapes.items():
        array = np.asarray(response[name])
        if array.shape != shape or not np.isfinite(array).all():
            raise ValueError(f"invalid validation response {name}")
        if name not in ("s", "y_parameters") and np.iscomplexobj(array):
            raise ValueError(f"complex validation response {name}")
        arrays[name] = array
    if not np.array_equal(arrays["frequencies_hz"], np.asarray(context.validation_frequencies_hz)):
        raise ValueError("validation response grid differs from declared grid")
    # Recompute the network from the captured admittances, without another COM solve.
    recomputed = evaluate_network(arrays["y_parameters"], context.source_impedance_ohm, context.load_impedance_ohm)
    for observed, name in (("s", "s"), ("gt", "gt"), ("il_db", "il"), ("vswr", "vswr")):
        if not np.array_equal(arrays[observed], recomputed[name]):
            raise ValueError(f"validation response {observed} disagrees with captured admittance")
    design, _, _ = canonical_design(record["canonical_vector"])
    network = {"il": arrays["il_db"], "vswr": arrays["vswr"], "s": arrays["s"]}
    if "return_loss_db" in arrays:
        network["return_loss_db"] = arrays["return_loss_db"]
    measured = measure(arrays["frequencies_hz"], network, design, _thaw(context.evaluation_config))
    for name in ("metrics", "violations", "feasible", "max_violation", "objective", "search_scalar_objective", "objective_parts"):
        # Existing measure permits infinite return loss; the persistence plan
        # must report its R5_REPRESENTATION_GAP rather than altering the value.
        if measured[name] != record[name]:
            raise ValueError(f"validation response {name} disagrees with measured samples")
    columns = ["classification", "frequency_hz", "gt", "il_db", "input_vswr", "output_vswr"]
    columns += [f"{kind}{i+1}{j+1}_{part}" for kind in ("y_siemens_", "s_") for i in range(2) for j in range(2) for part in ("real", "imag")]
    if "return_loss_db" in arrays:
        columns += ["source_return_loss_db", "load_return_loss_db"]
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(columns)
    for k in range(n):
        row = [arrays["frequencies_hz"][k], arrays["gt"][k], arrays["il_db"][k], *arrays["vswr"][k]]
        for name in ("y_parameters", "s"):
            for value in arrays[name][k].flat:
                row.extend((value.real, value.imag))
        if "return_loss_db" in arrays:
            row.extend(arrays["return_loss_db"][k])
        writer.writerow(["TEST_ONLY / NOT_SCIENTIFIC_EVIDENCE", *[repr(float(value)) for value in row]])
    return output.getvalue().encode("utf-8")


def run_configured_fixture(snapshot, *, search_evaluator, validation_evaluator, data_root, run_id, execution_source_sha):
    """Run one bounded test fixture, creating R5 before either explicit callback.

    Only a fresh test-owned external data-root leaf is supported. No scientific
    CLI dispatch, production attestation, or COM optimizer study is provided.
    """
    detached, context = _input_snapshot(snapshot)
    _validate_run_id(run_id)
    _validate_source_sha(execution_source_sha)
    if not callable(search_evaluator) or not callable(validation_evaluator):
        raise PersistencePlanError("explicit SEARCH and VALIDATION evaluators are required")
    if data_root is None or not os.path.isabs(os.fspath(data_root)):
        raise PersistencePlanError("an explicit absolute test-owned data root is required")
    if os.path.lexists(data_root):
        raise FileExistsError("test-only data root already exists")
    effective = detached["effective_config"]
    storage = effective["storage"]
    cell_id = storage["expected_cells"][0]["cell_id"]
    inputs = {"model": effective["model"]["parameters"], "search_grid": effective["grids"]["search"], "validation_grid": effective["grids"]["validation"]}
    run = create_experiment_run(effective["experiment_id"], effective_config=effective,
        scientific_inputs=inputs, expected_cells=storage["expected_cells"], source_sha=execution_source_sha,
        search_fe_limit=effective["optimizer"]["search_fe_limit"], validation_point_limit=len(context.validation_frequencies_hz),
        review_context=effective["review_context"], run_id=run_id, data_root=data_root,
        required_free_bytes=storage["required_free_bytes"])
    try:
        manifest = read_experiment_manifest(run.path)
        _equal(manifest["scientific_config_sha256"], detached["effective_config_sha256"], "R5 config hash")
        _equal(manifest["scientific_input_sha256"], detached["input_sha256"], "R5 input hashes")
        _equal(manifest["expected_cells"], storage["expected_cells"], "R5 roster")
        captured = []
        def validation(vector, *, phase):
            record = validation_evaluator(vector, phase=phase)
            if isinstance(record, Mapping) and "validation_response" in record:
                captured.append(_response_csv(copy.deepcopy(record["validation_response"]), record, context))
            return record
        result = run_configured_lshade(detached, search_evaluator=search_evaluator, validation_evaluator=validation)
        plan = build_persistence_plan(detached, result, run_id=run_id, execution_source_sha=execution_source_sha)
        run.write_raw_artifact(f"cells/{cell_id}/configured_result.json", _raw_payload(result))
        csv_bytes = None
        if captured and result["validation"]["status"] == "VALIDATED":
            if len(captured) != 1:
                raise ValueError("expected exactly one final validation response")
            csv_bytes = captured[0]
            run.write_artifact("artifacts/validation.csv", csv_bytes)
        if plan["cell_status"] == "FAILED":
            run.record_error(classification=plan["failure_class"], message=plan["reason"], cell_id=cell_id)
        search_record = result["search"]["incumbent"]
        validation_record = result["validation"]["record"]
        details = {}
        if search_record:
            metrics = search_record["metrics"]
            details.update(design=search_record["design"], geometry={k: metrics[k] for k in ("length_um", "width_um", "electrodes")},
                feasible=search_record["feasible"], search_metrics=metrics, search_violations=search_record["violations"])
        if validation_record:
            details.update(validation_metrics=validation_record["metrics"], validation_violations=validation_record["violations"])
        counters = result["search"]["counters"]
        run.record_cell(cell_id, status=plan["cell_status"], executed=bool(counters["search_evaluator_attempts"] or plan["search_fes"]),
            search_fes=plan["search_fes"], validation_points=plan["validation_points"], reason=plan["reason"], failure_class=plan["failure_class"],
            result={"classification": "TEST_ONLY / NOT_SCIENTIFIC_EVIDENCE", "review_export": "RESPONSE_CAPTURED" if csv_bytes else "VALIDATION_EVIDENCE_UNAVAILABLE"}, **details)
        run.close(status=plan["cell_status"])
        return run.path
    except Exception as exc:
        try:
            run.record_error(classification=_incident_classification(exc), message=f"Test-only fixture incident: {type(exc).__name__}", cell_id=cell_id)
        except Exception as incident_exc:
            raise ExceptionGroup("fixture incident and failure recording incident", [exc, incident_exc]) from exc
        raise


def export_fixture_review(*, run_path, repository_root):
    """Export only a fixture with registered validation evidence via the R5 exporter."""
    manifest = read_experiment_manifest(run_path)
    if (len(manifest["cells"]) != 1
            or (manifest["cells"][0].get("result") or {}).get("classification") != "TEST_ONLY / NOT_SCIENTIFIC_EVIDENCE"
            or "artifacts/validation.csv" not in manifest["raw_artifact_sha256"]):
        raise ReviewEvidenceUnavailable("VALIDATION_EVIDENCE_UNAVAILABLE: no captured test-only validation response")
    from ..reporting.experiment_review import export_review_package
    return export_review_package(run_path, repository_root=repository_root)
