"""Builds web/src/examples.json: real preview results the app shows when every checking server is
offline. Runs the preview pipeline (the promoted classifier, preview limits) on examples.toml.

    cd server && uv run python ../web/examples/make.py
"""

import json
import os
import time
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ["SQUINT_MODE"] = "preview"

from fastapi.testclient import TestClient  # noqa: E402

from squint.app import create_app  # noqa: E402
from squint.config import load_settings  # noqa: E402
from squint.ratelimit import SlidingWindowLimiter  # noqa: E402

examples = tomllib.loads((HERE / "examples.toml").read_text())["example"]
app = create_app(load_settings(), password=None)
app.state.svc.analyze_limiter = SlidingWindowLimiter(1000, 3600)
out = []
with TestClient(app) as c:
    for ex in examples:
        text = ex["text"].strip()
        r = c.post("/api/analyze", json={"text": text})
        snap = r.json()
        while "status" not in snap or snap["status"] not in ("done", "error"):  # the first check loads torch
            time.sleep(0.5)
            snap = c.get(f"/api/jobs/{snap['job_id']}").json()
        assert snap.get("status") == "done", snap
        out.append({"label": ex["label"], "source": ex["source"], "text": text, "result": snap["result"]})
        v = snap["result"]["verdict"]
        print(f"{ex['label']}: {v['label']} ({v['ai_percent']}% AI), {snap['result']['word_count']} words")
(HERE.parent / "src" / "examples.json").write_text(json.dumps(out, indent=1) + "\n")
