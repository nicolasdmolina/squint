import unittest

import _path  # noqa: F401
import sealed


class Cleaning(unittest.TestCase):
    def test_unwrap_joins_hard_wrapped_lines_and_keeps_paragraphs(self):
        self.assertEqual(sealed.unwrap("one line\nwrapped here\n\nnext\n  para"), "one line wrapped here\n\nnext para")

    def test_prose_rejects_tables(self):
        self.assertFalse(sealed.prose("27642\tCalpine\t40,000/d"))
        self.assertFalse(sealed.prose("Totals 1/1/02 20,000 40,000 25,000 12/31/04 365 1999"))
        self.assertTrue(sealed.prose("I went to the game on Friday and it was great."))

    def test_yelp_escapes_are_decoded(self):
        [r] = sealed.yelp([{"_row": 1, "label": 4, "text": "An upscale-ish d\\u00e9cor. " * 30}])
        self.assertIn("décor", r["text"])
        self.assertEqual(r["cue"], "5 stars")


if __name__ == "__main__":
    unittest.main()
