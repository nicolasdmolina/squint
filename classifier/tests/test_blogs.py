import unittest
from unittest import mock

import _path  # noqa: F401
import fetch_human

POST = ("I went down to the lake this morning before work. " + "I sat on the dock and watched the fog lift "
        "off the water while my coffee went cold. " * 12).strip()


def raw(i, text, author="a"):
    return {"_row": i, "id": author, "text": "        " + text + "     ", "topic": "Student", "age": 17,
            "date": "1,May,2004"}


class BlogRows(unittest.TestCase):
    def rows(self, raws):
        with mock.patch.object(fetch_human, "cached_json", lambda name, refresh, make: raws):
            return fetch_human.blog_rows(10, False)

    def test_keeps_a_plain_first_person_post_as_one_paragraph(self):
        [r] = self.rows([raw(1, POST.replace(". I sat", ".   \n I sat", 1))])
        self.assertEqual(r["source"], "blogs")
        self.assertEqual(r["prompt_id"], "blog:1")
        self.assertEqual(r["prompt_text"], "I went down to the lake this morning before work.")
        self.assertNotIn("\n", r["text"])
        self.assertNotIn("  ", r["text"])

    def test_drops_link_stubs_entities_title_case_and_short_posts(self):
        bad = [raw(1, "urlLink " + POST), raw(2, POST + " &nbsp;"), raw(3, POST.title()),
               raw(4, "I went out. I came back. I slept.")]
        self.assertEqual(self.rows(bad), [])

    def test_at_most_two_posts_per_author(self):
        self.assertEqual(len(self.rows([raw(i, POST) for i in range(5)])), 2)


if __name__ == "__main__":
    unittest.main()
