"""Unit tests for the AI-text generator helpers (no CLI is called)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
