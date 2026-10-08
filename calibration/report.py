# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Write calibration/report.json (docs/api-contract.md, "Accuracy report") from the
`heldout` split only, using the fitted thresholds and the server's band rules:

  score < ai_below -> likely_ai;  score > human_above -> likely_human;  else uncertain.

Rows are bucketed by the scorer's word_count; failed score rows and rows under 20 words are
skipped (format v1.1). "False flag" = a human text called likely_ai. "Catch" = an AI text
called likely_ai. Uncertain rates are per label.

The report keeps the contract's keys and adds `sample_counts` (held-out rows behind every
rate). Wilson 95% intervals, the mixed-document check and per-subset numbers go to
generated/report-details.json; the honest caveats go into `notes`.

Usage: uv run calibration/report.py [--data ...] [--scores ...] [--thresholds ...] [--out ...]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BUCKETS, CAL_DIR, DATA_DIR, GEN_DIR, read_jsonl, write_json  # noqa: E402
from fit_thresholds import join, row_bucket  # noqa: E402

GATE_NON_NATIVE = 0.01


def band(score: float, th: dict) -> str:
    if score < th["ai_below"]:
        return "likely_ai"
    if score > th["human_above"]:
        return "likely_human"
    return "uncertain"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def rate(rows: list[dict], pred) -> float | None:
    return round(sum(1 for r in rows if pred(r)) / len(rows), 4) if rows else None


def ai_percent(n_words: int, segments: list[dict], flag_below: float) -> float:
    """Share of the text's words covered by flagged windows, computed like the server does:
    by word index (word_start/word_end), so the UTF-16 character offsets never matter."""
    if n_words <= 0:
        return 0.0
    covered = [False] * n_words
    for s in segments:
        if s.get("score") is not None and s["score"] < flag_below:
            for i in range(max(0, s["word_start"]), min(n_words, s["word_end"])):
                covered[i] = True
    return sum(covered) / n_words


def build_report(data_rows: list[dict], score_rows: list[dict], th: dict) -> tuple[dict, dict]:
    pair = th["model_pair"]
    heldout = [r for r in data_rows if r["split"] == "heldout"]
    skipped: dict = {}
    rows = []
    for r in join(heldout, score_rows, skipped):
        s = r["_s"]
        if (s.get("model_pair") or pair) != pair:
            raise SystemExit(f"row {r['id']} was scored with {s.get('model_pair')}, thresholds are for {pair}")
        b = row_bucket(r)
        rows.append({**r, "_b": b, "_band": band(s["score"], th["buckets"][b])})

    human = [r for r in rows if r["label"] == "human"]
    ai = [r for r in rows if r["label"] == "ai"]
    nn = [r for r in human if r["subset"] == "non_native"]
    flagged = lambda r: r["_band"] == "likely_ai"  # noqa: E731
    unsure = lambda r: r["_band"] == "uncertain"  # noqa: E731
    sources = sorted({r["source"] for r in ai})

    report = {
        "version": th["version"],
        "model_pair": pair,
        "held_out": {"human": len(human), "ai": len(ai)},
        "false_flag_rate": {
            "overall": rate(human, flagged),
            "non_native": rate(nn, flagged),
            "by_length": {b: rate([r for r in human if r["_b"] == b], flagged) for b in BUCKETS},
        },
        "catch_rate": {
            "overall": rate(ai, flagged),
            "by_source": {s: rate([r for r in ai if r["source"] == s], flagged) for s in sources},
            "by_length": {b: rate([r for r in ai if r["_b"] == b], flagged) for b in BUCKETS},
        },
        "uncertain_rate": {"human": rate(human, unsure), "ai": rate(ai, unsure)},
        "sample_counts": {
            "human": {"by_length": {b: sum(r["_b"] == b for r in human) for b in BUCKETS},
                      "non_native": len(nn),
                      "by_subset": dict(sorted(Counter(r["subset"] for r in human).items())),
                      "documents": len({r.get("group_id", r["id"]) for r in human})},
            "ai": {"by_length": {b: sum(r["_b"] == b for r in ai) for b in BUCKETS},
                   "by_source": {s: sum(r["source"] == s for r in ai) for s in sources},
                   "documents": len({r.get("group_id", r["id"]) for r in ai})},
        },
        "notes": [],
    }

    # details: intervals and breakdowns
    def cell(rs, pred):
        k, n = sum(1 for r in rs if pred(r)), len(rs)
        ci = wilson(k, n)
        return {"k": k, "n": n, "rate": round(k / n, 4) if n else None,
                "ci95": [round(ci[0], 4), round(ci[1], 4)] if ci else None}

    details = {
        "false_flag": {
            "overall": cell(human, flagged), "non_native": cell(nn, flagged),
            "by_length": {b: cell([r for r in human if r["_b"] == b], flagged) for b in BUCKETS},
            "non_native_by_length": {b: cell([r for r in nn if r["_b"] == b], flagged) for b in BUCKETS},
            "by_source": {s: cell([r for r in human if r["source"] == s], flagged)
                          for s in sorted({r["source"] for r in human})},
        },
        "catch": {
            "overall": cell(ai, flagged),
            "by_source_and_length": {f"{s}|{b}": cell([r for r in ai if r["source"] == s and r["_b"] == b], flagged)
                                     for s in sources for b in BUCKETS},
            "by_register": {g: cell([r for r in ai if r.get("register") == g], flagged)
                            for g in sorted({r.get("register") for r in ai if r.get("register")})},
        },
        "uncertain": {"human": cell(human, unsure), "ai": cell(ai, unsure)},
        "skipped_heldout_rows": skipped,
    }

    # mixed documents: does the % estimate track the true AI share?
    mixed = [r for r in rows if r["label"] == "mixed" and r["_s"].get("segments")]
    flag_below = th.get("segment", {}).get("flag_below")
    if mixed and flag_below is not None:
        errs = []
        for r in mixed:
            n_words = r["_s"].get("word_count") or len(r["text"].split())
            est = ai_percent(n_words, r["_s"]["segments"], flag_below)
            errs.append({"id": r["id"], "true": r.get("ai_word_share"), "estimated": round(est, 4)})
        mae = sum(abs(e["estimated"] - (e["true"] or 0)) for e in errs) / len(errs)
        details["mixed"] = {"n": len(errs), "mean_abs_error": round(mae, 4), "rows": errs}

    # human windows on held-out texts flagged by the segment rule (drives "% AI" on human text)
    if flag_below is not None:
        hw = [s["score"] for r in human for s in (r["_s"].get("segments") or []) if s.get("score") is not None]
        nnw = [s["score"] for r in nn for s in (r["_s"].get("segments") or []) if s.get("score") is not None]
        details["segment_false_flag"] = {
            "human_windows": cell([{"v": v} for v in hw], lambda x: x["v"] < flag_below),
            "non_native_windows": cell([{"v": v} for v in nnw], lambda x: x["v"] < flag_below),
        }

    report["notes"] = notes(report, details, data_rows)
    return report, details


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def notes(report: dict, details: dict, data_rows: list[dict]) -> list[str]:
    out = []
    ff = details["false_flag"]
    out.append(
        f"Measured on {report['held_out']['human']} human and {report['held_out']['ai']} AI held-out samples "
        f"that were not used to set the thresholds. Shorter samples are excerpts of longer documents, so "
        f"there are {report['sample_counts']['human']['documents']} distinct human and "
        f"{report['sample_counts']['ai']['documents']} distinct AI documents behind them.")
    nn = ff["non_native"]
    if nn["n"]:
        verdict = "meets" if nn["rate"] <= GATE_NON_NATIVE else "does NOT meet"
        out.append(
            f"Non-native English writers: {nn['k']} of {nn['n']} wrongly flagged ({pct(nn['rate'])}, 95% range "
            f"{pct(nn['ci95'][0])}-{pct(nn['ci95'][1])}); this {verdict} the 1% go-public gate on the point estimate.")
    ov = ff["overall"]
    if ov["n"]:
        out.append(
            f"With about {ov['n']} human samples, a 1% false-flag rate can only be measured roughly "
            f"(95% range for the overall figure: {pct(ov['ci95'][0])}-{pct(ov['ci95'][1])}).")
    srcs = report["catch_rate"]["by_source"]
    missing = [s for s in ("chatgpt", "claude", "gemini") if s not in srcs]
    if missing:
        out.append(f"Not tested against {', '.join(missing)} text: none was available for this run.")
    by_len = report["catch_rate"]["by_length"]
    if all(by_len.get(b) is not None for b in BUCKETS):
        out.append(f"Length matters: AI text was caught {pct(by_len['20-49'])} of the time at 20-49 words, "
                   f"{pct(by_len['50-149'])} at 50-149 words and {pct(by_len['150+'])} at 150+ words.")
    out.append("AI samples were written by each model on its own (default model, via the vendor's command-line "
               "app, several pieces per request). Edited, paraphrased or 'humanized' AI text was not tested; "
               "expect misses there.")
    out.append("Human samples were written before ChatGPT existed: US school essays, English-learner essays, "
               "TOEFL practice essays, 1990s Reuters news and Reddit short stories. Other kinds of writing "
               "(technical, legal, poetry, very formal or formulaic text) were not tested.")
    if "mixed" in details:
        out.append(f"On {details['mixed']['n']} documents that mix human and AI paragraphs, the '% AI' estimate "
                   f"was off by {details['mixed']['mean_abs_error'] * 100:.0f} percentage points on average.")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA_DIR / "all.jsonl"))
    ap.add_argument("--scores", default=str(DATA_DIR / "scores.jsonl"))
    ap.add_argument("--thresholds", default=str(CAL_DIR / "thresholds.json"))
    ap.add_argument("--out", default=str(CAL_DIR / "report.json"))
    ap.add_argument("--details", default=str(GEN_DIR / "report-details.json"))
    args = ap.parse_args()
    th = json.loads(Path(args.thresholds).read_text())
    report, details = build_report(read_jsonl(args.data), read_jsonl(args.scores), th)
    write_json(args.out, report)
    write_json(args.details, details)
    print(json.dumps({k: report[k] for k in ("held_out", "false_flag_rate", "catch_rate", "uncertain_rate")}, indent=1))
    for n in report["notes"]:
        print("-", n)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
