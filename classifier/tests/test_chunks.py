import unittest

import _path  # noqa: F401
from textchunks import chunk_token_ids, weighted_mean


class ChunkTests(unittest.TestCase):
    def test_short_text_is_one_chunk(self):
        self.assertEqual(chunk_token_ids(list(range(10)), 20), [list(range(10))])

    def test_windows_cover_text_and_fix_short_tail(self):
        ids = list(range(1010))
        ch = chunk_token_ids(ids, 500)
        self.assertEqual([len(c) for c in ch], [500, 500, 500])
        self.assertEqual(ch[-1], ids[-500:])  # 10-token tail replaced by the last full window
        ch = chunk_token_ids(list(range(1300)), 500)
        self.assertEqual([len(c) for c in ch], [500, 500, 300])

    def test_max_chunks_evenly_spaced(self):
        ids = list(range(5000))
        ch = chunk_token_ids(ids, 500, max_chunks=4)
        self.assertEqual(len(ch), 4)
        self.assertEqual(ch[0][0], 0)
        self.assertEqual(ch[-1][-1], 4999)
        self.assertEqual(len(chunk_token_ids(ids, 500, max_chunks=1)), 1)

    def test_weighted_mean(self):
        self.assertAlmostEqual(weighted_mean([1.0, 0.0], [3, 1]), 0.75)
        self.assertAlmostEqual(weighted_mean([0.2, 0.4], [0, 0]), 0.3)


if __name__ == "__main__":
    unittest.main()
