"""Representative fresh-session synthetic recovery checks (not gate closure)."""
import pytest

from sawopt.studies.stage5a2.live_state import snapshot
from sawopt.studies.stage5a2.pair import prepare_pair
from .q1bc_fixture import fixture, candidate


@pytest.mark.parametrize("role", [0, 1])
def test_new_session_hydrates_committed_steps_and_replays_pending(tmp_path, role):
    metadata, pair, genesis, _ = fixture(tmp_path)
    evaluate = lambda v, o: candidate(v, o, pair=pair)
    def open_pair():
        return prepare_pair(pair=pair, genesis=genesis, metadata=metadata,
                            geometry_valid=lambda v: True, evaluators=(evaluate, evaluate))
    _, arms = open_pair()
    arm = arms[role]
    arm.step()
    original = arm._event
    def interrupt(suffix, kind, payload):
        if kind == "OPTIMIZER_STEP_COMMITTED":
            raise RuntimeError("crash before step commit")
        return original(suffix, kind, payload)
    arm._event = interrupt
    with pytest.raises(RuntimeError, match="crash before"):
        arm.step()
    expected = snapshot(arm.backend)
    _, fresh = open_pair()
    resumed = fresh[role]
    assert resumed.step_index == 1
    resumed.evaluator = lambda *args: pytest.fail("committed result redriven")
    assert resumed.step()
    actual = snapshot(resumed.backend)
    if actual != expected:
        index = next(i for i, (a, b) in enumerate(zip(actual, expected)) if a != b)
        pytest.fail(f"state mismatch at {index}: {actual[index-120:index+120]!r} != {expected[index-120:index+120]!r}")
    assert len(resumed.trace) == len(resumed.results) == resumed.backend.unique_evaluations == 236
