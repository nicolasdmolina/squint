"""Unit tests for the dataset builder helpers (common.py, build_dataset.py)."""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_dataset as bd  # noqa: E402
from common import bucket_for, normalize_text, sentence_spans, word_count  # noqa: E402

ESSAY = "\n\n".join(
    " ".join(f"Sentence number {p}-{s} talks about Dr. Smith and the U.S. economy in some detail." for s in range(6))
    for p in range(5))  # 5 paragraphs x 6 sentences x 15 words = 450 words


class Common(unittest.TestCase):
    def test_buckets(self):
        self.assertIsNone(bucket_for(19))
        self.assertEqual(bucket_for(20), "20-49")
        self.assertEqual(bucket_for(49), "20-49")
        self.assertEqual(bucket_for(50), "50-149")
        self.assertEqual(bucket_for(149), "50-149")
        self.assertEqual(bucket_for(150), "150+")

    def test_sentence_spans(self):
        text = 'He said "hi." Then Mr. Brown left at 5 p.m. today! Did it work? yes it did.\n\nNew para here'
        spans = sentence_spans(text)
        sents = [text[s:e] for s, e in spans]
        self.assertEqual(sents[0], 'He said "hi."')
        self.assertTrue(sents[1].startswith("Then Mr. Brown"))
        self.assertEqual(sents[-1], "New para here")
        self.assertIn("Did it work? yes it did.", sents)  # lowercase continuation is not a boundary
        for s, e in spans:
            self.assertEqual(text[s:e], text[s:e].strip())

    def test_spans_cover_all_words(self):
        spans = sentence_spans(ESSAY)
        self.assertEqual(len(spans), 30)
        self.assertEqual(sum(word_count(ESSAY[s:e]) for s, e in spans), word_count(ESSAY))

    def test_normalize(self):
        self.assertEqual(normalize_text("itâ€™s fine\r\n\r\n\r\n\r\nok  \n"), "it’s fine\n\nok")


class Excerpts(unittest.TestCase):
    def test_excerpt_in_range_and_sentence_aligned(self):
        for seed in range(30):
            for lo, hi in bd.EXCERPT_RANGES.values():
                ex = bd.excerpt(ESSAY, lo, hi, random.Random(seed))
                self.assertIsNotNone(ex)
                self.assertTrue(lo <= word_count(ex) <= hi, (lo, hi, word_count(ex)))
                self.assertIn(ex, ESSAY)
                self.assertTrue(ex.startswith("Sentence") and ex.endswith("."))

    def test_variants_identical_for_both_labels(self):
        h = {"id": "x1", "text": ESSAY, "label": "human"}
        a = {"id": "x1", "text": ESSAY, "label": "ai"}
        self.assertEqual(bd.variants(h), bd.variants(a))
        buckets = [v["bucket"] for v in bd.variants(h)]
        self.assertEqual(sorted(buckets), ["150+", "20-49", "50-149"])

    def test_variants_short_doc(self):
        text = " ".join(f"Short sentence {i} has exactly six words." for i in range(15))  # ~105 words
        vs = bd.variants({"id": "s", "text": text})
        self.assertEqual(sorted(v["bucket"] for v in vs), ["20-49", "50-149"])
        tiny = bd.variants({"id": "t", "text": "word " * 30})
        self.assertEqual([v["bucket"] for v in tiny], ["20-49"])
        self.assertEqual(bd.variants({"id": "u", "text": "word " * 10}), [])

    def test_unsplittable_text_gets_no_excerpt(self):
        one_sentence = " ".join(["word"] * 300)  # a single 300-word sentence
        vs = bd.variants({"id": "o", "text": one_sentence})
        self.assertEqual([v["bucket"] for v in vs], ["150+"])


class Mixed(unittest.TestCase):
    def test_splice_patterns(self):
        human = "\n\n".join(f"Human paragraph {i}. It has words." for i in range(5))
        ai = "\n\n".join(f"AI paragraph {i}. It also has words." for i in range(5))
        for pattern in ("HA", "AH", "HAH", "AHA"):
            text, spans = bd.splice(human, ai, pattern)
            self.assertEqual(spans[0]["start"], 0)
            self.assertEqual(spans[-1]["end"], len(text))
            for a, b in zip(spans, spans[1:]):
                self.assertEqual(a["end"], b["start"])
                self.assertNotEqual(a["label"], b["label"])
            self.assertEqual("".join(s["label"][0].upper() for s in spans), pattern)
            for s in spans:
                chunk = text[s["start"]:s["end"]]
                marker = "Human" if s["label"] == "human" else "AI"
                other = "AI" if marker == "Human" else "Human"
                self.assertIn(marker, chunk)
                self.assertNotIn(other + " paragraph", chunk)
            share = bd.ai_word_share(text, spans)
            self.assertTrue(0 < share < 1)

    def test_single_paragraph_texts_use_sentence_chunks(self):
        human = " ".join(f"Human sentence {i} is here." for i in range(12))
        ai = " ".join(f"AI sentence {i} is here." for i in range(12))
        text, spans = bd.splice(human, ai, "HAH")
        self.assertEqual(len(spans), 3)
        self.assertIn("\n\n", text)


class Splits(unittest.TestCase):
    def test_balanced_and_deterministic(self):
        groups = {f"g{i}": ("human", "persuade", "student", "150+") for i in range(101)}
        groups.update({f"a{i}": ("ai", "claude", "general", "20-49") for i in range(10)})
        s1 = bd.assign_splits(groups)
        s2 = bd.assign_splits(dict(reversed(list(groups.items()))))
        self.assertEqual(s1, s2)
        tune = sum(1 for g, s in s1.items() if g.startswith("g") and s == "tune")
        self.assertIn(tune, (50, 51))
        self.assertEqual(sum(1 for g, s in s1.items() if g.startswith("a") and s == "tune"), 5)

    def test_copy_check(self):
        lead = "The Federal Communications Commission has tentatively decided not to impose fees on providers."
        self.assertTrue(bd.copies_prompt("Today the Federal Communications Commission has tentatively decided "
                                         "not to impose fees on Internet providers.", lead))
        self.assertFalse(bd.copies_prompt("Regulators at the FCC will not charge internet providers new fees "
                                          "for using local phone lines, an official said.", lead))


if __name__ == "__main__":
    unittest.main()
