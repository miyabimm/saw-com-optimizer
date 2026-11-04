"""Bounded COM-free Q1-D storage probe; temporary SQLite data, not qualification.

Run from the repository root with
    uv run --locked python -m tools.diagnostics.q1d_storage_probe
This executes at most 20 post-initialization steps per arm. It never resumes
historical data and deletes only its own TemporaryDirectory on exit.
"""
from __future__ import annotations

import base64
import hashlib
import json
import platform
import shutil
import sqlite3
import tempfile
import time
import zlib
from pathlib import Path

import numpy as np

from sawopt.studies.stage5a2.codec import decode_typed, encode_typed
from sawopt.studies.stage5a2.journal import SQLiteJournal
from sawopt.studies.stage5a2.live_state import _pack
from sawopt.studies.stage5a2.pair import prepare_pair
from tests.unit.studies.q1bc_fixture import candidate, fixture


MAX_BYTES = 2_000_000_000
MIN_FREE_BYTES = 5_000_000_000


def size(path: Path) -> int:
    return sum(p.stat().st_size for p in (path, Path(str(path) + '-wal'),
                                           Path(str(path) + '-shm')) if p.exists())


def journal_breakdown(path: Path) -> dict:
    """Inspect the test-owned database without changing journal or event bytes."""
    files = {suffix or 'main': Path(str(path) + suffix).stat().st_size
             if Path(str(path) + suffix).exists() else 0
             for suffix in ('', '-wal', '-shm')}
    state_kinds = {'OPTIMIZER_STEP_STARTED', 'OPTIMIZER_STEP_COMMITTED',
                   'GENERATION_SNAPSHOT_COMMITTED', 'CHECKPOINT_SNAPSHOT'}
    stats = {}
    snapshot_stats = {'count': 0, 'raw_bytes': 0, 'outer_base64_bytes': 0,
                      'matching_previous_commit_count': 0, 'matching_previous_commit_bytes': 0}
    unique = set()
    previous_commit = None
    last_committed_state = None
    compression_seconds = decompression_seconds = 0.0
    connection = sqlite3.connect(f'file:{path.resolve().as_posix()}?mode=ro', uri=True)
    try:
        for kind, payload in connection.execute('SELECT event_type, payload FROM events ORDER BY sequence'):
            entry = stats.setdefault(kind, {'count': 0, 'payload_bytes': 0,
                                             'max_bytes': 0, 'zlib1_bytes': 0})
            entry['count'] += 1
            entry['payload_bytes'] += len(payload)
            entry['max_bytes'] = max(entry['max_bytes'], len(payload))
            start = time.perf_counter()
            compressed = zlib.compress(payload, 1)
            compression_seconds += time.perf_counter() - start
            start = time.perf_counter()
            if zlib.decompress(compressed) != payload:
                raise RuntimeError('in-memory compression round trip failed')
            decompression_seconds += time.perf_counter() - start
            entry['zlib1_bytes'] += len(compressed)
            if kind in state_kinds:
                outer = json.loads(payload)
                state_node = dict(outer['v'])['state']
                if state_node['t'] != 'bytes':
                    raise RuntimeError('unexpected typed snapshot payload')
                state = base64.b64decode(state_node['b64'], validate=True)
                snapshot_stats['count'] += 1
                snapshot_stats['raw_bytes'] += len(state)
                snapshot_stats['outer_base64_bytes'] += len(state_node['b64'])
                unique.add(hashlib.sha256(state).digest())
                if kind == 'OPTIMIZER_STEP_STARTED' and previous_commit is not None and state == previous_commit:
                    snapshot_stats['matching_previous_commit_count'] += 1
                    snapshot_stats['matching_previous_commit_bytes'] += len(state)
                if kind == 'OPTIMIZER_STEP_COMMITTED':
                    previous_commit = state
                    last_committed_state = state
        first_result = connection.execute(
            "SELECT payload FROM events WHERE event_type='EVALUATION_RESULT_COMMITTED' ORDER BY sequence LIMIT 1"
        ).fetchone()
        record = decode_typed(first_result[0])['result']
        vector = record['candidate_vector']
        representation = {'candidate_record_typed_bytes': len(encode_typed(record)),
                          'candidate_record_packed_typed_bytes': len(encode_typed(_pack(record))),
                          'candidate_vector_raw_bytes': vector.nbytes,
                          'candidate_vector_typed_bytes': len(encode_typed(vector))}
    finally:
        connection.close()
    total = sum(entry['payload_bytes'] for entry in stats.values())
    for kind in state_kinds:
        stats.setdefault(kind, {'count': 0, 'payload_bytes': 0, 'max_bytes': 0, 'zlib1_bytes': 0})
    for entry in stats.values():
        entry['average_bytes'] = entry['payload_bytes'] / entry['count'] if entry['count'] else 0
        entry['payload_percent'] = 100 * entry['payload_bytes'] / total if total else 0
    snapshot_stats['distinct_sha256'] = len(unique)
    # The snapshot is itself canonical typed JSON. Attribute each serialized
    # packed top-level field pair, including its key and pair wrappers; shared
    # mapping/envelope wrappers and inter-field separators are not attributed.
    envelope = dict(json.loads(last_committed_state)['v'])
    packed_fields = envelope['fields']['v'][1]['v']
    fields = {}
    for node in packed_fields:
        key = node['v'][0]['v'][1]['v']
        fields[key] = len(json.dumps(node, ensure_ascii=True, allow_nan=False,
                                     sort_keys=True, separators=(',', ':')).encode('utf-8'))
    return {'files': files, 'payload_bytes': total, 'events': stats,
            'representative_first_candidate_encoding': representation,
            'snapshots': snapshot_stats, 'last_snapshot_bytes': len(last_committed_state),
            'last_snapshot_packed_field_bytes': fields,
            'zlib1_payload_bytes': sum(e['zlib1_bytes'] for e in stats.values()),
            'zlib1_compression_seconds': compression_seconds,
            'zlib1_decompression_seconds': decompression_seconds}


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
        check_space()
        result['breakdown'] = {arm.cell.role: journal_breakdown(arm.journal.path) for arm in arms}
        check_space()
        result['free_bytes_after'] = shutil.disk_usage(root).free
        print('SUMMARY ' + json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
