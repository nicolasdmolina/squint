"""Promote a finished, evaluated run to the Squint server.

  classifier/.venv/bin/python classifier/promote.py --run modernbert-base-e1d93574b0af18b2 \
      --report classifier/reports/2026-10-14-min50.json

Copies <run>/final/ to server/models/classifier/<run>/ and writes calibration/classifier.json,
which the server reads (like thresholds.json) to decide whether the classifier is usable:

  ai_above      flag as likely AI when P(AI) > ai_above (the report's classifier-only cutoff,
                fitted on tune humans so false flags stay <= the cap)
  human_below   likely human when P(AI) < human_below: the highest cutoff with at most 5% of
                tune AI texts of min_words+ words below it (the rule Binoculars uses for
                human_above)
  min_words     shorter texts get "too short to tell"

Refuses a report whose gate did not pass, unless --force.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clf_common import RUNS_DIR, load_config  # noqa: E402
from common import read_jsonl  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SERVER_MODELS = REPO / "server" / "models" / "classifier"
OUT = REPO / "calibration" / "classifier.json"
AI_BELOW_CAP = 0.05


def human_below(ai_scores: list[float], cap: float) -> float:
    """Highest c with at most floor(cap * n) scores strictly below it: the (k+1)-th smallest."""
    s = sorted(ai_scores)
    k = math.floor(cap * len(s) + 1e-9)
    return s[min(k, len(s) - 1)]


def bucket(n_words: int) -> str:
    return "150+" if n_words >= 150 else "50-149" if n_words >= 50 else "20-49"


def by_length(rows: list[dict], ai_above: float, hb: float) -> dict:
    """Held-out numbers per length bucket for the accuracy page: humans from held-out sources and
    OOD sets, AI texts from held-out sources."""
    out = {}
    for b in ("20-49", "50-149", "150+"):
        hum = [r["p"] for r in rows if r["split"] in ("holdout", "ood") and r["label"] == "human" and bucket(r["n_words"]) == b]
        ai = [r for r in rows if r["split"] == "holdout" and r["label"] == "ai" and bucket(r["n_words"]) == b]
        cell = {"humans": len(hum),
                "false_flag": round(sum(p > ai_above for p in hum) / len(hum), 4) if hum else None,
                "humans_likely_human": round(sum(p < hb for p in hum) / len(hum), 4) if hum else None}
        for gen in sorted({r["generator"] for r in ai}):
            ps = [r["p"] for r in ai if r["generator"] == gen]
            cell[gen] = {"n": len(ps), "caught": round(sum(p > ai_above for p in ps) / len(ps), 4),
                         "called_human": round(sum(p < hb for p in ps) / len(ps), 4)}
        out[b] = cell
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="run directory name under classifier/runs/")
    ap.add_argument("--report", type=Path, required=True, help="evaluate.py report JSON for that run")
    ap.add_argument("--force", action="store_true", help="promote even if the gate failed")
    args = ap.parse_args()

    cfg = load_config()
    run_dir = RUNS_DIR / args.run
    final = run_dir / "final"
    rep = json.loads(args.report.read_text())
    if rep["run"] != args.run:
        print(f"report is for run {rep['run']}, not {args.run}", file=sys.stderr)
        return 1
    rule = rep["gate"]["rules"]["classifier_only"]
    if not rule["pass"] and not args.force:
        print("the classifier-only gate did not pass; use --force to promote anyway", file=sys.stderr)
        return 1
    min_words = rep["gate"].get("min_words", 0)
    trained = json.loads((final / "trained.json").read_text())

    preds = {r["id"]: r["p"] for r in read_jsonl(run_dir / "predictions.jsonl")}
    rows = [{**r, "p": preds[r["id"]]} for r in read_jsonl(run_dir / "dataset.jsonl") if r["id"] in preds]
    tune_ai = [r["p"] for r in rows if r["split"] == "tune" and r["label"] == "ai" and r["n_words"] >= min_words]
    ai_above = rep["cutoffs"]["classifier_only"]["t"]
    hb = min(human_below(tune_ai, AI_BELOW_CAP), ai_above)

    dest = SERVER_MODELS / args.run
    if not dest.exists():
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(final, tmp)
        tmp.rename(dest)
    tc = cfg["train"]
    out = {
        "version": rep["date"],
        "run": args.run,
        "model": trained["model"],
        "path": str(dest.relative_to(REPO)),
        "max_length": tc["max_length"],
        "max_chunks": 8,  # evaluate.py scores with predict_texts' default
        "min_words": min_words,
        "ai_above": ai_above,
        "human_below": hb,
        "n_tune_ai": len(tune_ai),
        "held_out": {
            "false_flags": rule["false_flags_overall"],
            "false_flags_non_native": rule["false_flags_non_native"],
            "chatgpt_catch": rule["chatgpt_catch_holdout"],
        },
        "by_length": by_length(rows, ai_above, hb),
        "report": str(args.report),
        "gate_pass": bool(rule["pass"]),
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
