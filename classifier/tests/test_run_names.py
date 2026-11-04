import unittest

import _path  # noqa: F401
import progress
import train


class RunNames(unittest.TestCase):
    def test_baseline_settings_keep_the_old_name(self):
        d = train.default_run_dir("answerdotai/ModernBERT-base", "90eac052e0629eff", dict(train.BASELINE))
        self.assertEqual(d.name, "modernbert-base-90eac052e0629eff")

    def test_other_settings_get_their_own_run(self):
        d = train.default_run_dir("answerdotai/ModernBERT-base", "90eac052e0629eff",
                                  {**train.BASELINE, "epochs": 3.0})
        self.assertEqual(d.name, "modernbert-base-90eac052e0629eff-epochs3")
        self.assertEqual(progress.short(d.name), "90eac052-epochs3")
        self.assertEqual(progress.short("modernbert-base-2ba047ff8496e270"), "2ba047ff")


if __name__ == "__main__":
    unittest.main()
