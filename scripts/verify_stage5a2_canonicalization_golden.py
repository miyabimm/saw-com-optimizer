#!/usr/bin/env python3
"""Compare the frozen 92-case corpus through canonical and leaf design APIs."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/stage5a2/canonicalization_legacy_golden.json"


def _input(spec):
    if spec["kind"] == "ndarray":
        array = np.frombuffer(bytes.fromhex(spec["bytes_hex"]), dtype=np.dtype(spec["dtype"]))
        return array.copy().reshape(spec["shape"])
    if spec["kind"] == "python_value":
        return spec["value"]
    raise AssertionError(f"unknown input fixture encoding {spec['kind']!r}")


def _bits(value: float) -> str:
    return struct.pack("<d", float(value)).hex()


def _call(mode, topology, vector, bounds, integer_indices):
    if mode == "design":
        from sawopt.design.space import HybridDesignSpace

        return HybridDesignSpace(topology, bounds, tuple(integer_indices)).canonicalize(vector)
    if mode == "leaf":
        from sawopt.design.canonicalization import canonicalize_hybrid_vector

        return canonicalize_hybrid_vector(
            vector, bounds=bounds, integer_indices=tuple(integer_indices),
            dimension=len(bounds), topology=topology,
        )
    raise AssertionError(mode)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("design", "leaf"), required=True)
    args = parser.parse_args()
    corpus_bytes = FIXTURE.read_bytes()
    corpus = json.loads(corpus_bytes)
    passed = 0
    for case in corpus["cases"]:
        bounds = np.frombuffer(bytes.fromhex(case["bounds_le_f64_hex"]), dtype="<f8").copy()
        bounds = bounds.reshape(-1, 2)
        if hashlib.sha256(bounds.astype("<f8", copy=False).tobytes()).hexdigest() != case["bounds_sha256"]:
            raise AssertionError(f"{case['name']}: bounds identity mismatch")
        vector = _input(case["input"])
        before = vector.tobytes(order="C").hex() if isinstance(vector, np.ndarray) else None
        try:
            output, key = _call(args.mode, case["space"], vector, bounds, case["integer_indices"])
        except Exception as exc:
            actual = {
                "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
                "message": str(exc),
            }
            if actual != case.get("error"):
                raise AssertionError(f"{case['name']}: error differs: {actual!r} != {case.get('error')!r}")
        else:
            expected = case.get("output")
            actual = {
                "dtype": output.dtype.str,
                "shape": list(output.shape),
                "owns_data": bool(output.flags.owndata),
                "writeable": bool(output.flags.writeable),
                "bytes_le_f64_hex": np.asarray(output, dtype="<f8").tobytes().hex(),
                "key_float64_le_hex": [_bits(value) for value in key],
                "key_order": list(range(len(key))),
                "key_type": type(key).__name__,
                "key_item_types": [type(value).__name__ for value in key],
                "shares_memory_with_input": (
                    bool(np.shares_memory(output, vector)) if isinstance(vector, np.ndarray) else False
                ),
            }
            if actual != expected:
                raise AssertionError(f"{case['name']}: output differs from legacy golden")
        after = vector.tobytes(order="C").hex() if isinstance(vector, np.ndarray) else None
        unchanged = before == after if before is not None else None
        if before != case["input_before_bytes_hex"] or after != case["input_after_bytes_hex"]:
            raise AssertionError(f"{case['name']}: input bytes differ from golden")
        if unchanged != case["input_unchanged"]:
            raise AssertionError(f"{case['name']}: input mutation status differs")
        passed += 1
    print(json.dumps({
        "mode": args.mode,
        "fixture_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
        "source_commit_sha": corpus["environment"]["source_commit_sha"],
        "cases_passed": passed,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
