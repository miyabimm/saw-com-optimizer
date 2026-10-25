import os
import subprocess
import sys
import time
import unittest

from sawopt.orchestration import pid_utils, worktree_safety


class PidLivenessTests(unittest.TestCase):
    def test_current_and_invalid_pids(self):
        self.assertTrue(pid_utils.pid_exists(os.getpid()))
        self.assertFalse(pid_utils.pid_exists(None))
        self.assertFalse(pid_utils.pid_exists(0))
        self.assertFalse(pid_utils.pid_exists(99999999))

    def test_live_child_remains_live_during_non_destructive_probe(self):
        child = subprocess.Popen([
            sys.executable,
            "-c",
            "import time; time.sleep(3)",
        ])
        try:
            for _ in range(3):
                self.assertIsNone(child.poll())
                self.assertTrue(pid_utils.pid_exists(child.pid))
                time.sleep(0.1)
            self.assertIsNone(child.poll())
        finally:
            child.terminate()
            child.wait(timeout=5)
        self.assertFalse(pid_utils.pid_exists(child.pid))

    def test_worktree_lock_uses_platform_safe_pid_probe(self):
        self.assertIs(worktree_safety.pid_exists, pid_utils.pid_exists)


if __name__ == "__main__":
    unittest.main()
