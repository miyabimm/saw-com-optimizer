"""Q1-BC local synthetic evidence; not formal Q1 certification."""
import numpy as np

from sawopt.optimization.controlled_de import ControlledDEBackend, de_trial


def test_de_operator_golden_draw_order_and_reflection():
    class Tape:
        def __init__(self):
            self.calls = []
        def permutation(self, values):
            self.calls.append(("permutation", values))
            return np.asarray([3, 1, 2])
        def integers(self, low, high):
            self.calls.append(("integers", low, high))
            return 1
        def random(self, size):
            self.calls.append(("random", size))
            return np.asarray([.95, .99, .1])
    rng = Tape()
    parents = np.asarray([[.2, .3, .4], [.9, 0., .9], [.1, 1., .1], [.8, .1, .8]])
    trial, evidence = de_trial(parents, 0, rng)
    assert rng.calls == [("permutation", [1, 2, 3]), ("integers", 0, 3), ("random", 3)]
    assert evidence["donors"] == (3, 1, 2)
    np.testing.assert_array_equal(evidence["before_reflection"], [.2, -.4, float.fromhex("0x1.3333333333334p+0")])
    np.testing.assert_array_equal(trial, [.2, float.fromhex("0x1.9999999999998p-2"), float.fromhex("0x1.9999999999998p-1")])
