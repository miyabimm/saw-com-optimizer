"""Bounded COM-free Q1-D storage probe; temporary SQLite data, not qualification.

Run from the repository root with
    uv run --locked python -m tools.diagnostics.q1d_storage_probe
This executes at most 20 post-initialization steps per arm. It never resumes
historical data and deletes only its own TemporaryDirectory on exit.
"""
from __future__ import annotations

import json
import platform
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np

from sawopt.studies.stage5a2.journal import SQLiteJournal
from sawopt.studies.stage5a2.pair import prepare_pair
from tests.unit.studies.q1bc_fixture import candidate, fixture


MAX_BYTES = 2_000_000_000
MIN_FREE_BYTES = 5_000_000_000


def size(path: Path) -> int:
    return sum(p.stat().st_size for p in (path, Path(str(path) + '-wal'),
                                           Path(str(path) + '-shm')) if p.exists())


def main() -> None:
    with tempfile.TemporaryDirectory(prefix='q1d-storage-probe-') as directory:
        root = Path(directory)
        free = shutil.disk_usage(root).free
        if free < MIN_FREE_BYTES:
            raise RuntimeError('insufficient free space for bounded probe')
        metadata, pair, genesis, _ = fixture(root)
        evaluate = lambda v, o: candidate(v, o, pair=pair)
        def open_pair():
            return prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                                geometry_valid=lambda v: True, evaluators=(evaluate, evaluate))
        def check_space():
            if sum(size(p) for p in (genesis.pair_path, *genesis.cell_paths)) > MAX_BYTES:
                raise RuntimeError('bounded probe storage limit exceeded')
            if shutil.disk_usage(root).free < MIN_FREE_BYTES:
                raise RuntimeError('bounded probe free-space floor reached')
        start = time.perf_counter()
        _, arms = open_pair()
        init = time.perf_counter() - start
        result = {'python': platform.python_version(), 'platform': platform.platform(),
                  'numpy': np.__version__, 'free_bytes_before': free,
                  'initialization_seconds': init, 'samples': []}
        for checkpoint in (0, 5, 10, 20):
            if checkpoint:
                for role, arm in enumerate(arms):
                    timings = []
                    for _ in range(checkpoint - previous):
                        check_space()
                        start = time.perf_counter()
                        if not arm.step():
                            raise RuntimeError('probe terminated before its bounded checkpoint')
                        timings.append(time.perf_counter() - start)
                    step_times[role] = timings
            else:
                step_times = [[], []]
            check_space()
            samples = []
            for arm in arms:
                start = time.perf_counter()
                SQLiteJournal(arm.journal.path, arm.journal.journal_uuid,
                              arm.journal.owner_kind, create=False)
                verify_seconds = time.perf_counter() - start
                samples.append({'role': arm.cell.role, 'fe': arm.backend.unique_evaluations,
                                'bytes_including_sidecars': size(arm.journal.path),
                                'step_seconds': step_times[len(samples)],
                                'chain_verify_seconds': verify_seconds})
            start = time.perf_counter()
            _, arms = open_pair()
            restart = time.perf_counter() - start
            result['samples'].append({'step': checkpoint, 'arms': samples,
                                      'pair_restart_seconds': restart,
                                      'pair_bytes_including_sidecars': size(genesis.pair_path)})
            previous = checkpoint
            print(json.dumps(result['samples'][-1]), flush=True)
        result['free_bytes_after'] = shutil.disk_usage(root).free
        print('SUMMARY ' + json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
