import os
import unittest

from sawopt.runtime.parallel import single_blas_thread_environment


class ParallelRuntimeTests(unittest.TestCase):
    def test_blas_context_restores_environment(self):
        names = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")
        original = {name: os.environ.get(name) for name in names}
        try:
            for name in names:
                os.environ[name] = "17"
            before_context = {name: os.environ.get(name) for name in names}
            with single_blas_thread_environment(3):
                self.assertEqual(
                    {name: os.environ[name] for name in names},
                    {name: "3" for name in names},
                )
            self.assertEqual(
                {name: os.environ.get(name) for name in names}, before_context
            )
        finally:
            for name, value in original.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
