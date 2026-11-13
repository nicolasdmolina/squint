import unittest
from unittest import mock

import _path  # noqa: F401
import fetch_human

ESSAY = ("My grandmother taught me to bake bread in her small kitchen in Ohio. " + "I learned that my hands could "
         "make something my whole family would share at dinner, and I carry that lesson with me to college. " * 14)


def raw(i, text):
    return {"_row": i, "Cleaned Essay": text, "Correct Grammar": text}


class EssayForumRows(unittest.TestCase):
    def rows(self, raws):
        with mock.patch.object(fetch_human, "cached_json", lambda name, refresh, make: raws):
            return fetch_human.essayforum_rows(10, False)

    def test_strips_the_request_and_the_prompt_around_the_essay(self):
        [r] = self.rows([raw(1, "Hi guys, please review my Common App essay! Describe a lesson you learned. "
                               + ESSAY + " Thanks for any feedback!")])
        self.assertEqual(r["source"], "essayforum")
        self.assertEqual(r["prompt_id"], "eforum:1")
        self.assertEqual(r["prompt_text"], "My grandmother taught me to bake bread in her small kitchen in Ohio.")
        self.assertFalse(r["text"].endswith("feedback!"))

    def test_drops_test_prep_and_requests_inside_the_text(self):
        bad = [raw(1, "The chart shows university enrolment. " + ESSAY),
               raw(2, ESSAY[:600] + " Here is my essay, what do you guys think? " + ESSAY[600:]),
               raw(3, ESSAY.replace("college", "the market"))]
        self.assertEqual(self.rows(bad), [])

    def test_a_reposted_draft_counts_once(self):
        self.assertEqual(len(self.rows([raw(1, ESSAY), raw(2, ESSAY + " I am ready.")])), 1)


if __name__ == "__main__":
    unittest.main()
