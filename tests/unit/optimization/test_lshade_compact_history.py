import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from sawopt.optimization.checkpoint_session import LShadeCheckpointSession
from sawopt.optimization.lshade import LShadeBackend
from sawopt.optimization.selection import GeometryFirstComparator


def _record(vector, *, tie=False, grid=0, payload=""):
    values = np.asarray(vector, dtype=float)
    score = 1.0 if tie else float(np.sum((values - 0.37) ** 2) + grid * 0.01)
    return {
        "evaluation_status": "PHYSICS_EVALUATED",
        "candidate_vector": values.tolist(),
        "topology": "P_D",
        "feasible": True,
        "max_violation": 0.0,
        "sum_violation": 0.0,
        "violations": {},
        "metrics": {"worst_il_db": score, "ripple_db": score / 2},
        "large_payload": payload,
    }


def _backend(*, compact, seed=17, budget=72, finalist_count=6,
             integer_indices=(), canonicalizer=None, hard_bounds=None):
    config = {
        "initial_population": 8,
        "min_population": 4,
        "history_size": 4,
        "max_duplicate_retries": 3,
        "total_budget": budget,
        "hard_max_budget": budget,
        "population_schedule_terminal_budget": budget,
        "canonical_space_size": 625 if tuple(integer_indices) == (0, 1, 2, 3) else None,
        "compact_history_cache": compact,
        "historical_finalist_count": finalist_count,
    }
    if hard_bounds is not None:
        config["hard_bounds"] = np.asarray(hard_bounds, dtype=float).tolist()
    return LShadeBackend(
        [(0.0, 1.0)] * 4,
        seed=seed,
        config=config,
        integer_indices=integer_indices,
        canonicalizer=canonicalizer,
        comparator=GeometryFirstComparator(),
    )


def _signature(backend):
    summary = backend.summary()
    return {
        "population": backend.population().tolist(),
        "incumbent": backend.incumbent(),
        "unique": summary["unique_evaluations"],
        "proposals": summary["proposals_total"],
        "duplicates": summary["duplicate_count"],
        "cache_hits": summary["cache_hits"],
        "generations": summary["generations"],
        "best_trace": summary["best_so_far_trace"],
        "population_trace": summary["population_trace"],
        "archive_trace": summary["archive_trace"],
    }


class CompactLShadeHistoryTests(unittest.TestCase):
    def test_compact_mode_preserves_duplicate_trajectory_and_top_finalists(self):
        def canonicalizer(vector):
            value = np.floor(np.asarray(vector) * 4 + 0.5) / 4
            value = np.clip(value, 0, 1)
            return value, tuple(value.tolist())

        full = _backend(compact=False, seed=6, budget=56, integer_indices=range(4),
                        canonicalizer=canonicalizer)
        compact = _backend(compact=True, seed=6, budget=56, finalist_count=6,
                           integer_indices=range(4), canonicalizer=canonicalizer)
        full.initialize(_record)
        compact.initialize(_record)
        full.advance_to_unique_budget(56)
        compact.advance_to_unique_budget(56)

        self.assertEqual(_signature(compact), _signature(full))
        self.assertGreater(compact.summary()["cache_hits"], 0)
        self.assertEqual(compact.state_dict()["state_version"], 4)
        self.assertTrue(compact.state_dict()["compact_history_cache"])
        expected = sorted(full._cache.values(), key=GeometryFirstComparator().rank_key)[:6]
        actual = compact.historical_finalists(6)
        self.assertEqual(
            [row["candidate_vector"] for row in actual],
            [row["candidate_vector"] for row in expected],
        )

    def test_equal_rank_finalists_keep_historical_insertion_order(self):
        full = _backend(compact=False, seed=23, budget=32, finalist_count=5)
        compact = _backend(compact=True, seed=23, budget=32, finalist_count=5)
        evaluator = lambda vector: _record(vector, tie=True)
        full.initialize(evaluator)
        compact.initialize(evaluator)
        full.advance_to_unique_budget(32)
        compact.advance_to_unique_budget(32)
        expected = sorted(full._cache.values(), key=GeometryFirstComparator().rank_key)[:5]
        actual = compact.historical_finalists(5)
        self.assertEqual(
            [row["candidate_vector"] for row in actual],
            [row["candidate_vector"] for row in expected],
        )

    def test_unretained_same_grid_hit_is_not_reevaluated_or_selected(self):
        compact = _backend(compact=True, seed=4, budget=48, finalist_count=2)
        calls = []

        def evaluator(vector):
            calls.append(np.asarray(vector).copy())
            return _record(vector)

        compact.initialize(evaluator)
        compact.advance_to_unique_budget(48)
        retained_keys = set(compact._cache)
        active_keys = {member.key for member in compact._population}
        key = next(
            value for value in compact._cache_frequency_versions
            if value not in retained_keys and value not in active_keys
        )
        before_population = compact.population().copy()
        before_unique = compact.unique_evaluations
        before_hits = compact.cache_hits
        before_calls = len(calls)
        physical = np.asarray(key, dtype=float)
        member = compact._make_member(compact._normalize(physical))
        self.assertIsNone(member)
        self.assertEqual(len(calls), before_calls)
        self.assertEqual(compact.unique_evaluations, before_unique)
        self.assertEqual(compact.cache_hits, before_hits + 1)
        np.testing.assert_array_equal(compact.population(), before_population)

    def test_checkpoint_resume_and_study_counter_state_match_uninterrupted(self):
        config = {
            "initial_population": 8, "min_population": 4, "history_size": 4,
            "max_duplicate_retries": 3, "total_budget": 64, "hard_max_budget": 64,
            "population_schedule_terminal_budget": 64, "compact_history_cache": True,
            "historical_finalist_count": 6,
        }
        full = LShadeBackend([(0, 1)] * 4, seed=12, config=config, integer_indices=())
        full.initialize(_record)
        full.advance_to_unique_budget(64)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            split = LShadeBackend([(0, 1)] * 4, seed=12, config=config, integer_indices=())
            split.initialize(_record)
            split.advance_to_unique_budget(32)
            session = LShadeCheckpointSession(
                root / "checkpoints", run_directory=root,
            )
            counters = {"physics_attempted_evaluations": 32, "search_frequency_points": 32032}
            session.save(split, extra_state={"geometry_gate_counters": counters})

            resumed = LShadeBackend([(0, 1)] * 4, seed=12, config=config, integer_indices=())
            resumed_session = LShadeCheckpointSession(
                root / "checkpoints", run_directory=root,
            )
            loaded = resumed_session.load(resumed)
            self.assertEqual(
                loaded.state["extra_state"]["geometry_gate_counters"], counters,
            )
            resumed.set_evaluator(_record)
            resumed.advance_to_unique_budget(64)

        self.assertEqual(_signature(resumed), _signature(full))
        self.assertEqual(
            [row["candidate_vector"] for row in resumed.historical_finalists(6)],
            [row["candidate_vector"] for row in full.historical_finalists(6)],
        )

    def test_frequency_grid_exchange_and_bounds_update_keep_trajectory(self):
        grid = [0]
        full_calls, compact_calls = [], []

        def make_evaluator(calls):
            def evaluator(vector):
                calls.append(tuple(np.asarray(vector, dtype=float)))
                return _record(vector, grid=grid[0])
            return evaluator

        full = _backend(compact=False, seed=19, budget=56)
        compact = _backend(compact=True, seed=19, budget=56)
        full_eval, compact_eval = make_evaluator(full_calls), make_evaluator(compact_calls)
        full.initialize(full_eval)
        compact.initialize(compact_eval)
        full.advance_to_unique_budget(40)
        compact.advance_to_unique_budget(40)
        grid[0] = 1
        full.exchange_frequency_grid([10.0, 20.0], evaluator=full_eval, version=2)
        compact.exchange_frequency_grid([10.0, 20.0], evaluator=compact_eval, version=2)

        old_key = next(
            key for key, version in compact._cache_frequency_versions.items()
            if version == 1 and key not in {item.key for item in compact._population}
        )
        before_unique = compact.unique_evaluations
        before_calls = len(compact_calls)
        x = compact._normalize(np.asarray(old_key, dtype=float))
        full._evaluate(x)
        compact._evaluate(x)
        self.assertEqual(len(compact_calls), before_calls + 1)
        self.assertEqual(compact.unique_evaluations, before_unique)

        full.advance_to_unique_budget(56)
        compact.advance_to_unique_budget(56)
        self.assertEqual(_signature(compact), _signature(full))
        self.assertEqual(
            [row["candidate_vector"] for row in compact.historical_finalists(6)],
            [row["candidate_vector"] for row in full.historical_finalists(6)],
        )

        bounds = np.asarray([[-0.1, 1.1]] * 4)
        hard = np.asarray([[-1.0, 2.0]] * 4)
        full_bounds = _backend(compact=False, seed=30, budget=48, hard_bounds=hard)
        compact_bounds = _backend(compact=True, seed=30, budget=48, hard_bounds=hard)
        full_bounds.initialize(_record)
        compact_bounds.initialize(_record)
        full_bounds.advance_to_unique_budget(32)
        compact_bounds.advance_to_unique_budget(32)
        full_bounds.update_bounds(bounds, rng=np.random.default_rng(100))
        compact_bounds.update_bounds(bounds, rng=np.random.default_rng(100))
        self.assertEqual(_signature(compact_bounds), _signature(full_bounds))

    def test_large_evaluator_payload_is_not_retained_for_every_design(self):
        payload = "x" * 8192
        full = _backend(compact=False, seed=10, budget=48, finalist_count=6)
        compact = _backend(compact=True, seed=10, budget=48, finalist_count=6)
        evaluator = lambda vector: _record(vector, payload=payload)
        full.initialize(evaluator)
        compact.initialize(evaluator)
        full.advance_to_unique_budget(48)
        compact.advance_to_unique_budget(48)
        full_size = len(json.dumps(full.state_dict(), separators=(",", ":")))
        compact_state = compact.state_dict()
        compact_size = len(json.dumps(compact_state, separators=(",", ":")))
        self.assertEqual(len(compact_state["compact_history_index"]), 48)
        self.assertLessEqual(len(compact_state["retained_results"]), 8 + 6)
        self.assertLess(compact_size, full_size * 0.55)

    def test_nonfinite_comparator_ranks_remain_json_checkpoint_safe(self):
        backend = _backend(compact=True, seed=20, budget=16, finalist_count=4)

        def failed_physics(vector):
            record = _record(vector)
            record["evaluation_status"] = "PHYSICS_FAILED"
            return record

        backend.initialize(failed_physics)
        state = backend.state_dict()
        encoded = json.dumps(state, allow_nan=False)
        restored = _backend(compact=True, seed=20, budget=16, finalist_count=4)
        restored.load_state_dict(json.loads(encoded))
        self.assertEqual(
            restored.historical_finalists(4), backend.historical_finalists(4),
        )

    def test_v3_checkpoint_is_rejected_from_header_before_json_parse(self):
        backend = _backend(compact=True)
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "old.json"
            checkpoint.write_text('{"state_version": 3, "payload": ' + ("0" * 2_000_000),
                                  encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "state version 3.*unsupported"):
                backend.load_checkpoint(checkpoint)


if __name__ == "__main__":
    unittest.main()
