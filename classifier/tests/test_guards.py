import unittest
from datetime import datetime, timedelta

import _path  # noqa: F401
from guards import heavy_stage_blocker, memory_free_pct, seconds_left, service_busy, window_bounds


def at(h, m, day=8):
    return datetime(2026, 10, day, h, m)


class WindowTests(unittest.TestCase):
    def test_inside_same_day_window(self):
        b = window_bounds(at(1, 0), "00:30", "07:30")
        self.assertEqual(b, (at(0, 30), at(7, 30)))
        self.assertEqual(seconds_left(at(7, 0), "00:30", "07:30"), 1800)

    def test_outside_window(self):
        self.assertIsNone(window_bounds(at(9, 0), "00:30", "07:30"))
        self.assertIsNone(window_bounds(at(0, 29), "00:30", "07:30"))
        self.assertIsNone(window_bounds(at(7, 30), "00:30", "07:30"))  # end is exclusive
        self.assertEqual(seconds_left(at(12, 0), "00:30", "07:30"), 0.0)

    def test_window_across_midnight(self):
        b = window_bounds(at(23, 30, day=7), "23:00", "06:00")
        self.assertEqual(b, (at(23, 0, day=7), at(6, 0, day=8)))
        b = window_bounds(at(2, 0), "23:00", "06:00")
        self.assertEqual(b, (at(23, 0, day=7), at(6, 0, day=8)))
        self.assertEqual(seconds_left(at(5, 0), "23:00", "06:00"), timedelta(hours=1).total_seconds())
        self.assertIsNone(window_bounds(at(12, 0), "23:00", "06:00"))

    def test_empty_window(self):
        self.assertIsNone(window_bounds(at(1, 0), "01:00", "01:00"))


class GuardTests(unittest.TestCase):
    def test_service_busy(self):
        self.assertIsNone(service_busy(None))  # not running
        self.assertIsNone(service_busy({"model_state": "unloaded", "queue_length": 0}))
        self.assertIn("queued", service_busy({"model_state": "unloaded", "queue_length": 2}))
        self.assertIn("ready", service_busy({"model_state": "ready", "queue_length": 0}))
        self.assertIn("loading", service_busy({"model_state": "loading"}))
        self.assertIn("in time", service_busy({"_timeout": True}))

    def test_memory_parse(self):
        txt = "The system has 17179869184 (1048576 pages with a page size of 16384).\n...\nSystem-wide memory free percentage: 13%\n"
        self.assertEqual(memory_free_pct(txt), 13)
        self.assertIsNone(memory_free_pct("garbage"))

    def test_heavy_blocker_order_and_thresholds(self):
        idle = {"model_state": "unloaded", "queue_length": 0}
        self.assertIsNone(heavy_stage_blocker(idle, 40, 20, 50.0, 6.0))
        self.assertIn("memory", heavy_stage_blocker(idle, 13, 20))
        self.assertIn("disk", heavy_stage_blocker(idle, 40, 20, 3.0, 6.0))
        self.assertIn("queued", heavy_stage_blocker({"queue_length": 1}, 90, 20))
        self.assertIn("heavy job", heavy_stage_blocker(idle, 90, 20, busy_procs=["squint-score --pair falcon"]))
        self.assertIsNone(heavy_stage_blocker(idle, None, 20))  # unknown memory does not block


if __name__ == "__main__":
    unittest.main()
