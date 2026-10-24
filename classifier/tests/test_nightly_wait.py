import subprocess
import sys
import time
import unittest

import _path  # noqa: F401
import nightly


def night(children, limit_end):
    n = nightly.Night.__new__(nightly.Night)
    n.children = children
    n.window_end = limit_end
    n.eval_reserve = 0
    n.should_stop = lambda: False
    return n


class WaitForGenerators(unittest.TestCase):
    def test_returns_when_generators_finish(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
        t = time.time()
        night({"generate-x": p}, time.time() + 7200).wait_for_generators(60)
        self.assertIsNotNone(p.poll())
        self.assertLess(time.time() - t, 5)

    def test_gives_up_at_the_limit(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            t = time.time()
            night({"generate-x": p}, time.time() + 7200).wait_for_generators(1)
            self.assertLess(time.time() - t, 5)
            self.assertIsNone(p.poll())
        finally:
            p.kill()

    def test_never_eats_the_training_hour(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            t = time.time()
            night({"generate-x": p}, time.time() + 3600).wait_for_generators(600)
            self.assertLess(time.time() - t, 5)
        finally:
            p.kill()

    def test_no_generators(self):
        night({"train": None}, time.time() + 7200).wait_for_generators(600)


if __name__ == "__main__":
    unittest.main()
