import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import _path  # noqa: F401
from clf_common import CLF_DIR


def stub_night(**env) -> dict:
    """One stub night in a window that started a minute ago; returns its stage records."""
    now = datetime.now()
    with tempfile.TemporaryDirectory() as d:
        e = {**os.environ, "SQUINT_NIGHTLY_SKIP": "fetch",
             "SQUINT_NIGHTLY_START": (now - timedelta(minutes=1)).strftime("%H:%M"),
             "SQUINT_NIGHTLY_END": (now + timedelta(hours=5)).strftime("%H:%M"), **env}
        subprocess.run([sys.executable, str(CLF_DIR / "nightly.py"), "--stub", "--state-dir", d,
                        "--stub-gen-secs", "1", "--stub-train-secs", "1", "--stub-guard", ""],
                       env=e, capture_output=True, timeout=120, check=True)
        return json.loads((Path(d) / "nightly.json").read_text())["stages"]


class Rounds(unittest.TestCase):
    def test_second_round_when_time_is_left(self):
        stages = stub_night()
        for s in ("train", "evaluate", "build-2", "train-2", "evaluate-2"):
            self.assertEqual(stages[s]["status"], "done", s)
        self.assertNotIn("train-3", stages)

    def test_one_round_when_too_little_time_is_left(self):
        stages = stub_night(SQUINT_NIGHTLY_MIN_ROUND_MIN="1000")
        self.assertEqual(stages["train"]["status"], "done")
        self.assertNotIn("build-2", stages)


if __name__ == "__main__":
    unittest.main()
