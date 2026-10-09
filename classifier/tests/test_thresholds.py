import math
import unittest

import _path  # noqa: F401
from thresholds import allowed, apply_or_rule, cut_above, fit_or_rule, fit_threshold, flag_rate, wilson


class ThresholdTests(unittest.TestCase):
    def test_allowed_and_cut(self):
        self.assertEqual(allowed(100, 0.01), 1)
        self.assertEqual(allowed(99, 0.01), 0)
        self.assertEqual(allowed(300, 0.01), 3)
        self.assertEqual(cut_above([0.1, 0.9, 0.5], 0), 0.9)
        self.assertEqual(cut_above([0.1, 0.9, 0.5], 1), 0.5)
        self.assertEqual(cut_above([0.1], 1), float("-inf"))

    def test_fit_respects_cap_on_every_group(self):
        all_h = [i / 1000 for i in range(200)]  # 0.000 .. 0.199, 2 may be flagged
        nn = [0.5, 0.4, 0.05] + [0.01] * 97  # 100 non-native, 1 may be flagged
        t, bind = fit_threshold({"all": all_h + nn, "non_native": nn}, 0.01)
        self.assertEqual(bind, "non_native")
        self.assertEqual(t, 0.4)
        self.assertLessEqual(flag_rate(nn, t), 0.01)
        self.assertLessEqual(flag_rate(all_h + nn, t), 0.01)

    def test_fit_ties_never_exceed_cap(self):
        hs = [0.9] * 5 + [0.1] * 95
        t, _ = fit_threshold({"all": hs}, 0.01)
        self.assertLessEqual(flag_rate(hs, t), 0.01)

    def test_fit_needs_data(self):
        with self.assertRaises(ValueError):
            fit_threshold({"all": []}, 0.01)

    def test_or_rule_uses_binoculars_when_it_helps(self):
        # humans: classifier unsure on non-native (high p), Binoculars confident (high b)
        humans = [{"p": 0.2, "b": 1.0, "subset": "native"} for _ in range(100)]
        humans += [{"p": 0.8, "b": 1.0, "subset": "non_native"} for _ in range(5)]
        humans += [{"p": 0.1, "b": 0.95, "subset": "non_native"} for _ in range(95)]
        ais = [{"p": 0.5, "b": 0.7, "subset": "x"} for _ in range(50)] + [{"p": 0.9, "b": 0.9, "subset": "x"} for _ in range(50)]
        rule = fit_or_rule(humans, ais, 0.01)
        flagged_h = [h for h in humans if apply_or_rule(h["p"], h["b"], rule, 1.0)]
        nn = [h for h in humans if h["subset"] == "non_native"]
        self.assertLessEqual(len(flagged_h), allowed(len(humans), 0.01))
        self.assertLessEqual(sum(1 for h in nn if apply_or_rule(h["p"], h["b"], rule, 1.0)), allowed(len(nn), 0.01))
        self.assertGreater(rule["b_cut"], 0.7)  # Binoculars catches the p=0.5 pieces
        self.assertEqual(rule["catch"], 1.0)

    def test_or_rule_falls_back_without_score(self):
        rule = {"t": 0.9, "b_cut": 0.8}
        self.assertTrue(apply_or_rule(0.6, None, rule, 0.5))
        self.assertFalse(apply_or_rule(0.6, 0.85, rule, 0.5))
        self.assertTrue(apply_or_rule(0.6, 0.79, rule, 0.5))

    def test_wilson(self):
        lo, hi = wilson(0, 100)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.037, places=3)
        self.assertTrue(all(math.isnan(x) for x in wilson(0, 0)))


if __name__ == "__main__":
    unittest.main()
