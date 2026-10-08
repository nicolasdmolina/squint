"""Unit tests for fit_thresholds.py and report.py on synthetic squint-score output.

Run: uv run --no-project --python 3.12 python -m unittest discover -s calibration/tests -v
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CAL))

import fit_thresholds as ft  # noqa: E402
import report as rp  # noqa: E402
from common import write_jsonl  # noqa: E402

PAIR = {"observer": "obs-test", "performer": "perf-test"}
WC = {"20-49": 30, "50-149": 100, "150+": 400}


def score_row(rid, score, wc, segs=(), stats=None):
    segments = []
    for i, s in enumerate(segs):
        segments.append({"word_start": i * 75, "word_end": i * 75 + 150, "start": i * 400,
                         "end": i * 400 + 900, "score": s})
    return {"id": rid, "word_count": wc, "token_count": int(wc * 1.3), "score": score,
            "stats": stats or {"top1_rate": 0.5, "top5_rate": 0.8, "mean_surprise": 2.0,
                               "mean_expected_surprise": 2.5, "sentence_score_spread": 0.1},
            "segments": segments, "model_pair": PAIR}


def data_row(rid, label, subset, split, source="persuade", bucket="150+"):
    return {"id": rid, "text": "x " * WC[bucket], "label": label, "source": source, "subset": subset,
            "split": split, "model_id": None if label == "human" else "m", "prompt_id": "p",
            "group_id": rid, "bucket": bucket}


class CutoffRules(unittest.TestCase):
    def test_max_cut_below_exact_rank(self):
        scores = [i / 1000 for i in range(1, 201)]  # 0.001 .. 0.200, n=200 -> k=2
        c = ft.max_cut_below(scores, 0.01)
        self.assertAlmostEqual(c, 0.003)
        self.assertLessEqual(sum(s < c for s in scores), 2)
        self.assertGreater(sum(s < c + 1e-6 for s in scores), 2)  # any higher cutoff breaks the cap

    def test_max_cut_below_small_n_is_minimum(self):
        self.assertEqual(ft.max_cut_below([0.9, 0.8, 0.95], 0.01), 0.8)

    def test_max_cut_below_ties(self):
        scores = [0.5] * 10 + [0.9] * 90  # n=100 -> k=1; cutoff 0.5 leaves nobody strictly below
        c = ft.max_cut_below(scores, 0.01)
        self.assertEqual(c, 0.5)
        self.assertEqual(sum(s < c for s in scores), 0)

    def test_min_cut_above(self):
        scores = [i / 100 for i in range(1, 101)]  # n=100 -> k=5 above allowed
        c = ft.min_cut_above(scores, 0.05)
        self.assertAlmostEqual(c, 0.95)
        self.assertLessEqual(sum(s > c for s in scores), 5)
        self.assertGreater(sum(s > c - 1e-6 for s in scores), 5)

    def test_brute_force_matches(self):
        rng = random.Random(7)
        for n in (5, 37, 100, 101, 250, 999):
            xs = [round(rng.random(), 3) for _ in range(n)]
            c = ft.max_cut_below(xs, 0.01)
            cands = sorted(set(xs + [x + 1e-4 for x in xs]))
            best = max(cc for cc in cands if sum(x < cc for x in xs) <= int(0.01 * n))
            # best is either c itself or within the open gap just above it
            self.assertLessEqual(sum(x < c for x in xs), int(0.01 * n))
            self.assertTrue(c <= best < min([x for x in xs if x > c], default=2.0) + 1e-9)
            d = ft.min_cut_above(xs, 0.05)
            self.assertLessEqual(sum(x > d for x in xs), int(0.05 * n))


class FitEndToEnd(unittest.TestCase):
    def make(self, seed=1, nn_shift=0.0, ai_low=False):
        rng = random.Random(seed)
        data, scores = [], []
        i = 0
        for b in WC:
            for split in ("tune", "heldout"):
                for _ in range(300):  # native humans ~ N(1.0, 0.05)
                    rid = f"h{i}"; i += 1
                    data.append(data_row(rid, "human", "student", split, bucket=b))
                    segs = [rng.gauss(1.0, 0.05) for _ in range(3)] if b == "150+" else []
                    scores.append(score_row(rid, rng.gauss(1.0, 0.05), WC[b], segs,
                                            {"top1_rate": 0.4, "top5_rate": 0.65, "mean_surprise": 3.0,
                                             "sentence_score_spread": 0.12}))
                for _ in range(150):  # non-native humans, optionally shifted towards AI
                    rid = f"n{i}"; i += 1
                    data.append(data_row(rid, "human", "non_native", split, source="ellipse", bucket=b))
                    segs = [rng.gauss(0.97 - nn_shift, 0.05) for _ in range(3)] if b == "150+" else []
                    scores.append(score_row(rid, rng.gauss(0.97 - nn_shift, 0.05), WC[b], segs))
                for src in ("chatgpt", "claude"):
                    for _ in range(150):
                        rid = f"a{i}"; i += 1
                        data.append(data_row(rid, "ai", "student", split, source=src, bucket=b))
                        mu = 0.5 if ai_low else 0.75
                        segs = [rng.gauss(mu, 0.05) for _ in range(3)] if b == "150+" else []
                        scores.append(score_row(rid, rng.gauss(mu, 0.05), WC[b], segs,
                                                {"top1_rate": 0.66, "top5_rate": 0.88, "mean_surprise": 1.8,
                                                 "sentence_score_spread": 0.05}))
        # a mixed row must never influence the fit
        data.append({**data_row("m1", "mixed", "student", "tune"), "spans": []})
        scores.append(score_row("m1", 0.0, 400))
        return data, scores

    def test_rules_hold_on_tune(self):
        data, scores = self.make(nn_shift=0.1)
        th, det = ft.fit(data, scores, version="2026-10-07")
        self.assertEqual(th["model_pair"], PAIR)
        self.assertEqual(set(th["buckets"]), {"20-49", "50-149", "150+"})
        sc = {s["id"]: s for s in scores}
        for b, t in th["buckets"].items():
            tune_h = [r for r in data if r["split"] == "tune" and r["label"] == "human" and r["bucket"] == b]
            tune_nn = [r for r in tune_h if r["subset"] == "non_native"]
            tune_ai = [r for r in data if r["split"] == "tune" and r["label"] == "ai" and r["bucket"] == b]
            below = lambda rs: sum(sc[r["id"]]["score"] < t["ai_below"] for r in rs) / len(rs)  # noqa: E731
            self.assertLessEqual(below(tune_h), 0.01)
            self.assertLessEqual(below(tune_nn), 0.01)
            # non-native is shifted towards AI, so it must be the binding constraint
            self.assertEqual(det["buckets"][b]["binding"], "non_native")
            self.assertLess(t["ai_below"], det["buckets"][b]["cut_all"])
            above = sum(sc[r["id"]]["score"] > t["human_above"] for r in tune_ai) / len(tune_ai)
            self.assertLessEqual(above, 0.05)
            self.assertGreaterEqual(t["human_above"], t["ai_below"])
        self.assertEqual(th["segment"]["window_words"], 150)
        self.assertEqual(th["segment"]["stride_words"], 75)
        hw = [s for r in data if r["split"] == "tune" and r["label"] == "human"
              for s in [x["score"] for x in sc[r["id"]]["segments"]]]
        self.assertLessEqual(sum(s < th["segment"]["flag_below"] for s in hw) / len(hw), 0.01)
        self.assertAlmostEqual(th["medians"]["ai"]["top1_rate"], 0.66)
        self.assertIn("sentence_score_spread", th["medians"]["human"])

    def test_clamp_when_ai_scores_far_below_humans(self):
        # every AI text sits well under ai_below -> the 5% AI rule lands below ai_below -> clamp
        data, scores = self.make(ai_low=True)
        th, det = ft.fit(data, scores)
        for b, t in th["buckets"].items():
            self.assertEqual(t["human_above"], t["ai_below"])
            self.assertTrue(det["buckets"][b]["human_above_clamped_to_ai_below"])

    def test_heldout_is_ignored(self):
        data, scores = self.make()
        th1, _ = ft.fit(data, scores)
        sc = {s["id"]: s for s in scores}
        for r in data:
            if r["split"] == "heldout":
                sc[r["id"]]["score"] = -5.0
        th2, _ = ft.fit(data, list(sc.values()))
        self.assertEqual(th1["buckets"], th2["buckets"])

    def test_buckets_follow_scorer_word_count(self):
        data, scores = self.make()
        # dataset says 150+, scorer says 30 words -> must count in 20-49
        data.append(data_row("odd", "human", "student", "tune", bucket="150+"))
        scores.append(score_row("odd", 0.01, 30))
        _, det1 = ft.fit(data, scores)
        self.assertEqual(det1["buckets"]["20-49"]["n_human"], 451)

    def test_missing_bucket_fails(self):
        data, scores = self.make()
        keep = {r["id"] for r in data if not (r["bucket"] == "20-49" and r["label"] == "ai")}
        with self.assertRaises(ft.FitError):
            ft.fit([r for r in data if r["id"] in keep], scores)

    def test_mixed_model_pairs_fail(self):
        data, scores = self.make()
        scores[0] = {**scores[0], "model_pair": {"observer": "other", "performer": "x"}}
        with self.assertRaises(ft.FitError):
            ft.fit(data, scores)

    def test_error_and_short_rows_are_skipped(self):
        # format v1.1: failed rows look like {"id","error","score":null,"model_pair"}, and rows
        # under 20 words are still scored; neither may reach the fit
        data, scores = self.make()
        th1, _ = ft.fit(data, scores)
        extra_d, extra_s = [], []
        for i in range(40):
            extra_d.append(data_row(f"err{i}", "human", "non_native", "tune", source="ellipse", bucket="20-49"))
            extra_s.append({"id": f"err{i}", "error": "scoring_failed", "score": None, "model_pair": PAIR})
            extra_d.append(data_row(f"tiny{i}", "human", "non_native", "tune", source="ellipse", bucket="20-49"))
            # a very low score that would drag ai_below down if it were used; 12 words < 20
            extra_s.append(score_row(f"tiny{i}", -3.0, 12, segs=[-3.0]))
        th2, det = ft.fit(data + extra_d, scores + extra_s)
        self.assertEqual(th1["buckets"], th2["buckets"])
        self.assertEqual(th1["segment"], th2["segment"])
        self.assertEqual(th1["medians"], th2["medians"])
        self.assertEqual(det["skipped_rows_all_splits"],
                         {"not_scored": 0, "score_error": 40, "under_20_words": 40})
        # an error row from another model pair still must not trip the one-pair check
        bad = [{"id": "err0", "error": "too_short", "score": None, "model_pair": {"observer": "x", "performer": "y"}}]
        ft.fit(data + extra_d[:1], scores + bad)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.th = {"version": "2026-10-07", "model_pair": PAIR,
                   "buckets": {b: {"ai_below": 0.8, "human_above": 0.9} for b in WC},
                   "segment": {"window_words": 150, "stride_words": 75, "flag_below": 0.8}}

    def test_band_edges(self):
        t = {"ai_below": 0.8, "human_above": 0.9}
        self.assertEqual(rp.band(0.7999, t), "likely_ai")
        self.assertEqual(rp.band(0.8, t), "uncertain")
        self.assertEqual(rp.band(0.9, t), "uncertain")
        self.assertEqual(rp.band(0.9001, t), "likely_human")

    def test_counts_and_rates(self):
        data, scores = [], []
        spec = [  # (id, label, subset, source, split, score, wc)
            ("h1", "human", "student", "persuade", "heldout", 0.75, 400),     # false flag, 150+
            ("h2", "human", "student", "persuade", "heldout", 0.95, 400),
            ("h3", "human", "non_native", "ellipse", "heldout", 0.85, 100),  # uncertain
            ("h4", "human", "non_native", "ellipse", "heldout", 0.79, 30),   # false flag, non-native
            ("h5", "human", "student", "persuade", "tune", 0.10, 400),       # tune: ignored
            ("a1", "ai", "student", "chatgpt", "heldout", 0.70, 400),        # caught
            ("a2", "ai", "student", "chatgpt", "heldout", 0.85, 100),        # uncertain
            ("a3", "ai", "general", "claude", "heldout", 0.95, 30),          # missed
            ("a4", "ai", "general", "claude", "heldout", 0.60, 30),          # caught
            ("a5", "ai", "general", "claude", "tune", 0.99, 30),             # tune: ignored
        ]
        for rid, label, subset, source, split, s, wc in spec:
            b = "150+" if wc >= 150 else "50-149" if wc >= 50 else "20-49"
            data.append(data_row(rid, label, subset, split, source=source, bucket=b))
            scores.append(score_row(rid, s, wc))
        rep, det = rp.build_report(data, scores, self.th)
        self.assertEqual(rep["held_out"], {"human": 4, "ai": 4})
        self.assertEqual(rep["false_flag_rate"]["overall"], 0.5)
        self.assertEqual(rep["false_flag_rate"]["non_native"], 0.5)
        self.assertEqual(rep["false_flag_rate"]["by_length"], {"20-49": 1.0, "50-149": 0.0, "150+": 0.5})
        self.assertEqual(rep["catch_rate"]["overall"], 0.5)
        self.assertEqual(rep["catch_rate"]["by_source"], {"chatgpt": 0.5, "claude": 0.5})
        self.assertEqual(rep["catch_rate"]["by_length"], {"20-49": 0.5, "50-149": 0.0, "150+": 1.0})
        self.assertEqual(rep["uncertain_rate"], {"human": 0.25, "ai": 0.25})
        self.assertEqual(rep["sample_counts"]["human"]["by_length"], {"20-49": 1, "50-149": 1, "150+": 2})
        self.assertEqual(rep["sample_counts"]["ai"]["by_source"], {"chatgpt": 2, "claude": 2})
        for key in ("version", "model_pair", "held_out", "false_flag_rate", "catch_rate", "uncertain_rate", "notes"):
            self.assertIn(key, rep)
        self.assertTrue(any("gemini" in n for n in rep["notes"]))
        self.assertTrue(any("does NOT meet" in n for n in rep["notes"]))
        lo, hi = det["false_flag"]["overall"]["ci95"]
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)

    def test_report_skips_error_and_short_rows(self):
        data = [data_row("h1", "human", "student", "heldout"), data_row("a1", "ai", "student", "heldout", "claude"),
                data_row("e1", "human", "non_native", "heldout", "ellipse", bucket="20-49"),
                data_row("s1", "human", "non_native", "heldout", "ellipse", bucket="20-49")]
        scores = [score_row("h1", 0.95, 400), score_row("a1", 0.5, 400),
                  {"id": "e1", "error": "scoring_failed", "score": None, "model_pair": PAIR},
                  score_row("s1", 0.1, 15)]  # would be a false flag if it were counted
        rep, det = rp.build_report(data, scores, self.th)
        self.assertEqual(rep["held_out"], {"human": 1, "ai": 1})
        self.assertEqual(rep["false_flag_rate"]["overall"], 0.0)
        self.assertIsNone(rep["false_flag_rate"]["non_native"])
        self.assertEqual(det["skipped_heldout_rows"], {"not_scored": 0, "score_error": 1, "under_20_words": 1})

    def test_ai_percent_uses_word_indices_not_offsets(self):
        # 300 words with emoji: UTF-16 offsets differ from Python string offsets, word indices do not
        text = " ".join(["w\U0001F600"] * 300)
        u16 = lambda i: len(text[:i].encode("utf-16-le")) // 2  # noqa: E731
        segs = [{"start": 0, "end": u16(449), "word_start": 0, "word_end": 150, "score": 0.5},
                {"start": u16(450), "end": u16(len(text)), "word_start": 150, "word_end": 300, "score": 0.95}]
        self.assertAlmostEqual(rp.ai_percent(300, segs, 0.8), 0.5)
        overlap = [{"word_start": 0, "word_end": 150, "score": 0.5}, {"word_start": 75, "word_end": 225, "score": 0.5},
                   {"word_start": 150, "word_end": 300, "score": 0.9}]
        self.assertAlmostEqual(rp.ai_percent(300, overlap, 0.8), 0.75)
        self.assertEqual(rp.ai_percent(0, overlap, 0.8), 0.0)

    def test_mixed_ai_percent(self):
        text = " ".join(["w"] * 300)
        segs = [{"start": 0, "end": 300, "word_start": 0, "word_end": 150, "score": 0.5},
                {"start": 300, "end": 600, "word_start": 150, "word_end": 300, "score": 0.95}]
        self.assertAlmostEqual(rp.ai_percent(300, segs, 0.8), 0.5)
        data = [{**data_row("m1", "mixed", "student", "heldout"), "text": text, "ai_word_share": 0.5,
                 "spans": [{"start": 0, "end": 300, "label": "ai"}, {"start": 300, "end": 599, "label": "human"}]},
                data_row("h1", "human", "student", "heldout"), data_row("a1", "ai", "student", "heldout", "claude")]
        scores = [{**score_row("m1", 0.7, 300), "segments": segs}, score_row("h1", 0.95, 400), score_row("a1", 0.5, 400)]
        _, det = rp.build_report(data, scores, self.th)
        self.assertEqual(det["mixed"]["n"], 1)
        self.assertAlmostEqual(det["mixed"]["mean_abs_error"], 0.0)

    def test_wilson(self):
        lo, hi = rp.wilson(1, 100)
        self.assertTrue(0.0 < lo < 0.01 < hi < 0.06)
        self.assertIsNone(rp.wilson(0, 0))


class CliSmoke(unittest.TestCase):
    """fit_thresholds.py and report.py run as scripts on synthetic files."""

    def test_scripts(self):
        data, scores = FitEndToEnd().make(seed=3)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            write_jsonl(d / "all.jsonl", data)
            write_jsonl(d / "scores.jsonl", scores)
            py = sys.executable
            subprocess.run([py, str(CAL / "fit_thresholds.py"), "--data", str(d / "all.jsonl"),
                            "--scores", str(d / "scores.jsonl"), "--out", str(d / "thresholds.json"),
                            "--details", str(d / "fit.json"), "--version", "2026-10-07"],
                           check=True, capture_output=True)
            th = json.loads((d / "thresholds.json").read_text())
            self.assertEqual(set(th), {"version", "model_pair", "buckets", "segment", "medians"})
            subprocess.run([py, str(CAL / "report.py"), "--data", str(d / "all.jsonl"),
                            "--scores", str(d / "scores.jsonl"), "--thresholds", str(d / "thresholds.json"),
                            "--out", str(d / "report.json"), "--details", str(d / "rd.json")],
                           check=True, capture_output=True)
            rep = json.loads((d / "report.json").read_text())
            self.assertEqual(rep["version"], "2026-10-07")
            # heldout drawn from the same distributions -> false flags stay small
            self.assertLess(rep["false_flag_rate"]["overall"], 0.05)
            self.assertGreater(rep["catch_rate"]["overall"], 0.5)


if __name__ == "__main__":
    unittest.main()
