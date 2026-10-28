"""Unit tests for the AI-text generator helpers (no CLI is called)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import generate_ai as g  # noqa: E402

SOURCE_ESSAY = {"id": "x-1", "kind": "essay", "target_words": None,
                "instruction": "Write an essay. Assignment: Use evidence from the passage set."}
PLAIN_ESSAY = {"id": "x-2", "kind": "essay", "target_words": None,
               "instruction": "Write an essay about summer jobs for teenagers."}


class RetryHint(unittest.TestCase):
    def test_first_attempt_has_no_hint(self):
        self.assertEqual(g.instruction_for(SOURCE_ESSAY), SOURCE_ESSAY["instruction"])
        self.assertNotIn(g.RETRY_NOTE, g.batch_prompt([SOURCE_ESSAY, PLAIN_ESSAY]))

    def test_hint_only_for_rejected_source_based_essays(self):
        hint = {"x-1", "x-2"}
        self.assertTrue(g.instruction_for(SOURCE_ESSAY, hint).endswith(g.RETRY_NOTE))
        self.assertEqual(g.instruction_for(PLAIN_ESSAY, hint), PLAIN_ESSAY["instruction"])
        self.assertEqual(g.batch_prompt([SOURCE_ESSAY, PLAIN_ESSAY], hint).count(g.RETRY_NOTE), 1)

    def test_prior_rejects_from_call_records(self):
        plan = {"x-1": SOURCE_ESSAY, "x-2": PLAIN_ESSAY}
        good = " ".join(["word"] * 300)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            items = [{"id": "x-1", "text": "Please provide the passage set so I can write the essay."},
                     {"id": "x-2", "text": good}]
            (d / "call-1.json").write_text(json.dumps({"ok": True, "text": json.dumps({"items": items})}))
            (d / "call-2.json").write_text(json.dumps({"ok": False, "text": ""}))
            self.assertEqual(g.prior_rejects(d, plan), {"x-1"})


class LengthRule(unittest.TestCase):
    def test_long_floor_follows_a_small_target(self):
        abstract = {"id": "a", "kind": "abstract", "target_words": 100}
        self.assertIsNone(g.acceptable(abstract, " ".join(["word"] * 90)))
        self.assertIsNotNone(g.acceptable(abstract, " ".join(["word"] * 60)))
        essay = {"id": "e", "kind": "essay", "target_words": None}
        self.assertIsNotNone(g.acceptable(essay, " ".join(["word"] * 110)))
        self.assertIsNone(g.acceptable(essay, " ".join(["word"] * 130)))



class LimitReset(unittest.TestCase):
    def test_reset_time_with_zone(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        ny = ZoneInfo("America/New_York")
        at = g.limit_reset("You've hit your weekly limit · resets 4am (America/New_York)",
                           datetime(2026, 10, 27, 23, 4, tzinfo=ny))
        self.assertEqual(at, datetime(2026, 10, 28, 4, 0, tzinfo=ny))

    def test_reset_later_today_with_minutes(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        ny = ZoneInfo("America/New_York")
        at = g.limit_reset("resets 1:10am (America/New_York)", datetime(2026, 10, 28, 0, 30, tzinfo=ny))
        self.assertEqual(at, datetime(2026, 10, 28, 1, 10, tzinfo=ny))
        self.assertEqual(g.limit_reset("resets 10:10pm", datetime(2026, 10, 28, 9, 0).astimezone()).hour, 22)

    def test_no_reset_time(self):
        self.assertIsNone(g.limit_reset("usage limit reached"))


class LimitWait(unittest.TestCase):
    """A nightly run (should_stop given) waits out a usage limit and carries on."""

    def run_with(self, should_stop):
        item = {"id": "claude-x-1", "source": "claude", "kind": "short", "subset": "review", "prompt_id": "p",
                "instruction": "Write a review.", "register": "review", "role": "pure", "target_words": 60,
                "mix_with": None}
        replies = [
            {"ok": False, "text": "You've hit your weekly limit · resets 4am (America/New_York)",
             "model_id": None, "stderr": "", "auth_error": False},
            {"ok": True, "text": json.dumps({"items": [{"id": "claude-x-1", "text": "word " * 60}]}),
             "model_id": "m", "stderr": "", "auth_error": False},
        ]
        orig_cli, orig_reset = g.run_cli, g.limit_reset
        g.run_cli = lambda *a: replies.pop(0)
        g.limit_reset = lambda *a: datetime.now().astimezone() - timedelta(minutes=3)  # already lifted
        try:
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / "plan.jsonl").write_text(json.dumps(item) + "\n")
                g.run_source("claude", None, 2, gen_dir=Path(d), should_stop=should_stop)
                out = Path(d) / "ai_claude.jsonl"
                return [json.loads(x)["id"] for x in out.read_text().splitlines()] if out.exists() else []
        finally:
            g.run_cli, g.limit_reset = orig_cli, orig_reset

    def test_waits_then_resumes(self):
        self.assertEqual(self.run_with(lambda: False), ["claude-x-1"])

    def test_without_a_deadline_it_stops(self):
        self.assertEqual(self.run_with(None), [])

if __name__ == "__main__":
    unittest.main()
