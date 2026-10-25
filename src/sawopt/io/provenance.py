"""Versioned fingerprints for computation and reporting provenance.

The historical :mod:`sawopt.io.run_store` fingerprint remains unchanged. New
experiments can opt into schema v2 and declare the source dependencies that
affect their numerical computation separately from their reporting code.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


FINGERPRINT_SCHEMA_VERSION = 2
_TEXT_DEPENDENCY_SUFFIXES = {
    ".cfg", ".csv", ".ini", ".json", ".md", ".py", ".toml", ".txt",
    ".yaml", ".yml",
}


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Fingerprint input is not canonical JSON data: {exc}") from exc


def _repository_relative_path(value: str, repository_root: Path) -> str | None:
    """Return a canonical repository-relative path for an in-repository absolute path."""
    # Treat either separator as a path separator, then let the host Path parse
    # absolute paths native to this checkout. Foreign-root and relative strings
    # remain untouched.
    candidate = Path(value.replace("\\", "/"))
    if not candidate.is_absolute():
        return None
    try:
        relative = candidate.resolve().relative_to(repository_root)
    except ValueError:
        return None
    return PurePosixPath(*relative.parts).as_posix() or "."


def _canonicalize_configuration(value: Any, repository_root: Path) -> Any:
    """Copy JSON-like configuration while normalizing only repo-local absolute paths."""
    if isinstance(value, Mapping):
        return {
            key: _canonicalize_configuration(item, repository_root)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_canonicalize_configuration(item, repository_root) for item in value]
    if isinstance(value, tuple):
        return tuple(_canonicalize_configuration(item, repository_root) for item in value)
    if isinstance(value, str):
        return _repository_relative_path(value, repository_root) or value
    return value


def _canonical_dependency_bytes(path: Path, data: bytes) -> bytes:
    if path.suffix.lower() not in _TEXT_DEPENDENCY_SUFFIXES:
        return data
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _dependency_manifest(repository_root: Path, paths: Sequence[str]) -> list[dict[str, Any]]:
    root = Path(repository_root).resolve()
    normalized: list[str] = []
    for value in paths:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Fingerprint dependency paths must be non-empty strings")
        relative = value.replace("\\", "/")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
            raise ValueError(f"Fingerprint dependency must be repository-relative: {value!r}")
        normalized.append(pure.as_posix())
    if len(normalized) != len(set(normalized)):
        raise ValueError("Fingerprint dependency paths must not contain duplicates")

    manifest = []
    for relative in sorted(normalized):
        path = (root / Path(*PurePosixPath(relative).parts)).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Fingerprint dependency escapes repository root: {relative}")
        if not path.is_file():
            raise FileNotFoundError(f"Fingerprint dependency does not exist: {relative}")
        data = _canonical_dependency_bytes(path, path.read_bytes())
        manifest.append({
            "path": relative,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        })
    return manifest


def build_fingerprint_metadata(
    repository_root: str | Path,
    configuration: Mapping[str, Any],
    *,
    computation_paths: Sequence[str],
    reporting_paths: Sequence[str],
) -> dict[str, Any]:
    """Create schema-v2 fingerprints from explicit source dependency sets.

    Configuration is included only in the computation fingerprint. Callers
    must list every source file that can affect the experiment result in
    ``computation_paths`` and reporting-only source files in
    ``reporting_paths``. The dependency manifest itself is part of each hash,
    so adding or removing a listed file changes that fingerprint.
    """
    root = Path(repository_root).resolve()
    computation_manifest = _dependency_manifest(root, computation_paths)
    reporting_manifest = _dependency_manifest(root, reporting_paths)
    if set(item["path"] for item in computation_manifest) & set(
        item["path"] for item in reporting_manifest
    ):
        raise ValueError("A source path cannot be both a computation and reporting dependency")

    computation_payload = {
        "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
        "configuration": _canonicalize_configuration(configuration, root),
        "dependencies": computation_manifest,
    }
    reporting_payload = {
        "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
        "dependencies": reporting_manifest,
    }
    return {
        "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
        "computation_fingerprint": hashlib.sha256(
            _canonical_json(computation_payload)
        ).hexdigest(),
        "reporting_fingerprint": hashlib.sha256(
            _canonical_json(reporting_payload)
        ).hexdigest(),
        "dependency_manifest": {
            "computation": computation_manifest,
            "reporting": reporting_manifest,
        },
    }


def read_fingerprint_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize current schema-v2 fingerprint metadata."""
    version = metadata.get("fingerprint_schema_version", metadata.get("schema_version"))
    if version != FINGERPRINT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported fingerprint schema version: {version}")

    computation = metadata.get("computation_fingerprint")
    reporting = metadata.get("reporting_fingerprint")
    manifest = metadata.get("dependency_manifest")
    if not isinstance(computation, str) or not isinstance(reporting, str):
        raise ValueError("Schema-v2 metadata requires both fingerprints")
    if not isinstance(manifest, Mapping):
        raise ValueError("Schema-v2 metadata requires a dependency manifest")
    return {
        "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
        "computation_fingerprint": computation,
        "reporting_fingerprint": reporting,
        "dependency_manifest": manifest,
    }


def computation_gate_matches(
    expected_metadata: Mapping[str, Any], actual_metadata: Mapping[str, Any],
) -> bool:
    """Compare schema-v2 computation provenance, ignoring reporting-only edits."""
    expected = read_fingerprint_metadata(expected_metadata)
    actual = read_fingerprint_metadata(actual_metadata)
    return expected["computation_fingerprint"] == actual["computation_fingerprint"]


__all__ = [
    "FINGERPRINT_SCHEMA_VERSION",
    "build_fingerprint_metadata",
    "computation_gate_matches",
    "read_fingerprint_metadata",
]
