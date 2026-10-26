import unittest

import _path  # noqa: F401
from clf_common import CLF_DIR

OPS = CLF_DIR.parent / "ops"


class Window(unittest.TestCase):
    def test_plist_does_not_override_the_window(self):
        # ops/nightly.sh owns the window; a copy in the plist silently wins (lost night 2026-10-25)
        plist = (OPS / "com.nickymolina.squint-nightly.plist").read_text()
        self.assertNotIn("SQUINT_NIGHTLY_START", plist)
        self.assertNotIn("SQUINT_NIGHTLY_END", plist)

    def test_launch_time_is_the_window_start(self):
        plist = (OPS / "com.nickymolina.squint-nightly.plist").read_text()
        sh = (OPS / "nightly.sh").read_text()
        self.assertIn(': "${SQUINT_NIGHTLY_START:=23:00}"', sh)
        self.assertIn("<key>Hour</key>\n\t\t<integer>23</integer>\n\t\t<key>Minute</key>\n\t\t<integer>0</integer>", plist)


if __name__ == "__main__":
    unittest.main()
