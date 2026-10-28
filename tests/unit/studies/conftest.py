"""Test-owned SQLite baseline for repeated post-initialization Q1 checks.

The Q0 genesis roster binds absolute cell paths. Each pytest worker therefore
owns one fixed private directory and resets it from a consistent SQLite backup
before every consuming test; databases cannot be copied to a new locator.
No connection or arm is reused across resets, and backup files are never opened
for writing after creation. Full genesis/preflight tests use separate fixtures.
"""
import sqlite3

import pytest

from sawopt.studies.stage5a2.pair import prepare_pair
from .q1bc_fixture import fixture, candidate


@pytest.fixture(scope="session")
def _q1_initialized_baseline(tmp_path_factory):
    root = tmp_path_factory.mktemp("q1-initialized")
    baseline = tmp_path_factory.mktemp("q1-backup")
    metadata, pair, genesis, canonicalize = fixture(root)
    evaluate = lambda v, o: candidate(v, o, pair=pair)
    prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                 geometry_valid=lambda v: True, evaluators=(evaluate, evaluate))
    paths = (genesis.pair_path, *genesis.cell_paths)
    for path in paths:
        with sqlite3.connect(path) as source, sqlite3.connect(baseline / path.name) as target:
            source.backup(target)
    def reset():
        # Every journal operation opens and closes its own SQLite connection.
        # Remove WAL/SHM with the old databases before restoring the isolated
        # test-owned prefix; no live session may be used after reset.
        for path in paths:
            for suffix in ("", "-wal", "-shm"):
                path.with_name(path.name + suffix).unlink(missing_ok=True)
            with sqlite3.connect(f"file:{baseline / path.name}?mode=ro", uri=True) as source, sqlite3.connect(path) as target:
                source.backup(target)
        seal, arms = prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                                  geometry_valid=lambda v: pytest.fail("sealed sampler reentered"),
                                  evaluators=(evaluate, evaluate))
        return metadata, pair, genesis, canonicalize, seal, arms
    return reset


@pytest.fixture
def initialized_pair(_q1_initialized_baseline):
    return _q1_initialized_baseline()
