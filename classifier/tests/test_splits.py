import unittest
from collections import Counter

import _path  # noqa: F401
from splits import assign_splits, dedup_across_splits, leakage_problems

HOLD, OOD = {"ellipse", "toefl91"}, {"ood-hewlett"}


def bases():
    out = []
    for src, fam, subset in [("persuade", "persuade", "student"), ("arxiv", "arxiv", "academic"),
                             ("ellipse", "ellipse", "non_native"), ("toefl91", "toefl91", "non_native"),
                             ("ood-hewlett", "ood-hewlett", "student")]:
        for i in range(60):
            out.append({"id": f"{src}-{i}", "label": "human", "source": src, "family": fam, "generator": None,
                        "subset": subset})
    for gen in ("chatgpt", "claude"):
        for fam in ("persuade", "arxiv", "ellipse", "toefl91"):
            for i in range(40):
                out.append({"id": f"{gen}-{fam}-{i}", "label": "ai", "source": gen, "family": fam,
                            "generator": gen, "subset": "x"})
        # paraphrases of AI pieces, including one of a held-out family and a rewrite of a rewrite
        for i in range(40):
            out.append({"id": f"{gen}-xpar-{i}", "label": "ai", "source": gen, "family": "persuade",
                        "generator": gen, "subset": "x", "origin_id": f"{gen}-persuade-{i}"})
        out.append({"id": f"{gen}-xpar-ell", "label": "ai", "source": gen, "family": "ellipse",
                    "generator": gen, "subset": "x", "origin_id": f"{gen}-ellipse-0"})
        out.append({"id": f"{gen}-xpar-chain", "label": "ai", "source": gen, "family": "persuade",
                    "generator": gen, "subset": "x", "origin_id": f"{gen}-xpar-3"})
    return out


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.b = bases()
        self.s = assign_splits(self.b, HOLD, OOD, 0.7, 0.15, "seed-1")

    def test_every_base_gets_one_split(self):
        self.assertEqual(set(self.s), {b["id"] for b in self.b})

    def test_held_out_sources_never_in_training(self):
        for b in self.b:
            if b["source"] in HOLD or b["family"] in HOLD:
                self.assertEqual(self.s[b["id"]], "holdout", b["id"])
            if b["source"] in OOD:
                self.assertEqual(self.s[b["id"]], "ood", b["id"])
            if self.s[b["id"]] in ("holdout", "ood"):
                self.assertTrue(b["source"] in HOLD | OOD or b["family"] in HOLD | OOD, b["id"])

    def test_paraphrase_follows_origin(self):
        for b in self.b:
            if b.get("origin_id"):
                self.assertEqual(self.s[b["id"]], self.s[b["origin_id"]], b["id"])

    def test_deterministic_and_seeded(self):
        self.assertEqual(self.s, assign_splits(self.b, HOLD, OOD, 0.7, 0.15, "seed-1"))
        self.assertNotEqual(self.s, assign_splits(self.b, HOLD, OOD, 0.7, 0.15, "seed-2"))

    def test_fractions_roughly_respected(self):
        c = Counter(v for k, v in self.s.items() if k.startswith(("persuade-", "arxiv-")))
        self.assertAlmostEqual(c["train"] / 120, 0.7, delta=0.05)
        self.assertAlmostEqual(c["tune"] / 120, 0.15, delta=0.05)

    def test_leakage_checker(self):
        rows = [{"id": b["id"], "group_id": b["id"], "split": self.s[b["id"]], "source": b["source"],
                 "family": b["family"], "text": f"text of {b['id']}"} for b in self.b]
        self.assertEqual(leakage_problems(rows, HOLD, OOD), [])
        bad = [dict(r) for r in rows]
        bad[0]["text"] = next(r["text"] for r in rows if r["split"] == "holdout")
        bad[0]["split"] = "train"
        bad.append({**bad[1], "id": "dup-group", "split": "tune" if bad[1]["split"] != "tune" else "train"})
        bad.append({**next(r for r in rows if r["source"] == "ellipse"), "id": "leak", "group_id": "leak",
                    "split": "train"})
        probs = leakage_problems(bad, HOLD, OOD)
        self.assertTrue(any("shares its text" in p for p in probs))
        self.assertTrue(any("spans splits" in p for p in probs))
        self.assertTrue(any("held-out source" in p for p in probs))

    def test_dedup_keeps_evaluation_copy(self):
        rows = [{"id": "a", "split": "train", "text": "Same text!"}, {"id": "b", "split": "holdout", "text": "same text"},
                {"id": "c", "split": "tune", "text": "other"}, {"id": "d", "split": "tune", "text": "Other."}]
        kept, dropped = dedup_across_splits(rows)
        self.assertEqual([r["id"] for r in kept], ["b", "c"])
        self.assertEqual({d["id"] for d in dropped}, {"a", "d"})


if __name__ == "__main__":
    unittest.main()
