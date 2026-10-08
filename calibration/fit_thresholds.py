# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Fit calibration/thresholds.json from squint-score output (docs/calibration-format.md §3).

Uses the `tune` split only, human and AI rows only (mixed rows are not used for fitting).
Rows are bucketed by the scorer's `word_count` (the number the server buckets by at runtime).
Failed score rows and rows the scorer counts as under 20 words are skipped (format v1.1).

Rules, per length bucket:
  ai_below     highest cutoff with at most 1% of human texts strictly below it, computed on
               all human subsets together and on `non_native` alone; the lower one wins.
  human_above  lowest cutoff with at most 5% of AI texts strictly above it; raised to
               ai_below if it ends up below it (no uncertain zone).
segment.flag_below: the same 1% rule (overall and non-native, lower wins) over the windows of
  human texts. medians: per-label medians of each stat over tune rows.

Usage:
  uv run calibration/fit_thresholds.py [--data data/all.jsonl] [--scores data/scores.jsonl]
                                       [--out thresholds.json] [--version YYYY-MM-DD]
Diagnostics (counts, which constraint bound) go to generated/fit-details.json.
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BUCKETS, CAL_DIR, DATA_DIR, GEN_DIR, bucket_for, read_jsonl, write_json  # noqa: E402

HUMAN_FALSE_FLAG_CAP = 0.01
AI_ABOVE_CAP = 0.05
MEDIAN_KEYS = ("top1_rate", "top5_rate", "mean_surprise", "sentence_score_spread")
DEFAULT_WINDOW, DEFAULT_STRIDE = 150, 75
MIN_HUMAN_WARN = 100  # below this the 1% rule can only pick the minimum score


class FitError(RuntimeError):
    pass


def max_cut_below(scores: list[float], cap: float) -> float:
    """Highest c with #{s < c} <= floor(cap * n). That is the (k+1)-th smallest score."""
    if not scores:
        raise FitError("no scores")
    s = sorted(scores)
    k = math.floor(cap * len(s) + 1e-9)
    return s[min(k, len(s) - 1)]


def min_cut_above(scores: list[float], cap: float) -> float:
    """Lowest c with #{s > c} <= floor(cap * n). That is the (k+1)-th largest score."""
    if not scores:
        raise FitError("no scores")
    s = sorted(scores, reverse=True)
    k = math.floor(cap * len(s) + 1e-9)
    return s[min(k, len(s) - 1)]


def join(data_rows: list[dict], score_rows: list[dict], counts: dict | None = None) -> list[dict]:
    """Dataset rows joined to their score rows, keeping only usable ones (format v1.1):
    skips rows not scored yet, failed rows ({"id", "error", "score": null, ...}) and rows the
    scorer counts as under 20 words (squint-score still scores those). Tallies go into `counts`."""
    by_id = {s["id"]: s for s in score_rows}
    out = []
    tally = {"not_scored": 0, "score_error": 0, "under_20_words": 0}
    for r in data_rows:
        s = by_id.get(r["id"])
        if s is None:
            tally["not_scored"] += 1
        elif s.get("error") is not None or s.get("score") is None:
            tally["score_error"] += 1
        elif row_bucket({**r, "_s": s}) is None:
            tally["under_20_words"] += 1
        else:
            out.append({**r, "_s": s})
    for k, n in tally.items():
        if n:
            print(f"warning: skipped {n} dataset rows ({k.replace('_', ' ')})", file=sys.stderr)
    if counts is not None:
        counts.update(tally)
    return out


def row_bucket(r: dict) -> str | None:
    """Length bucket from the scorer's word_count (None when under 20 words)."""
    wc = r["_s"].get("word_count")
    return bucket_for(wc) if wc is not None else r.get("bucket")


def fit_one_percent(human: list[dict], values) -> tuple[float, dict]:
    """1% rule on all humans and on non-native humans; lower wins. `values(row)` -> list."""
    all_v = [v for r in human for v in values(r)]
    nn_v = [v for r in human if r["subset"] == "non_native" for v in values(r)]
    c_all = max_cut_below(all_v, HUMAN_FALSE_FLAG_CAP)
    info = {"n_human": len(all_v), "n_non_native": len(nn_v), "cut_all": c_all}
    if nn_v:
        c_nn = max_cut_below(nn_v, HUMAN_FALSE_FLAG_CAP)
        info["cut_non_native"] = c_nn
        cut = min(c_all, c_nn)
        info["binding"] = "non_native" if c_nn < c_all else "all_human"
    else:
        cut = c_all
        info["binding"] = "all_human (no non-native rows)"
    return cut, info


def fit(data_rows: list[dict], score_rows: list[dict], version: str | None = None,
        window_words: int | None = None, stride_words: int | None = None) -> tuple[dict, dict]:
    skipped: dict = {}
    rows = [r for r in join(data_rows, score_rows, skipped) if r["split"] == "tune" and r["label"] in ("human", "ai")]
    if not rows:
        raise FitError("no scored tune rows")
    pairs = {tuple(sorted((r["_s"].get("model_pair") or {}).items())) for r in rows}
    if len(pairs) != 1:
        raise FitError(f"scores come from {len(pairs)} different model pairs; rescore everything with one pair")
    model_pair = dict(next(iter(pairs)))

    buckets, details = {}, {"buckets": {}, "warnings": []}
    for b in BUCKETS:
        hb = [r for r in rows if r["label"] == "human" and row_bucket(r) == b]
        ab = [r for r in rows if r["label"] == "ai" and row_bucket(r) == b]
        if not hb or not ab:
            raise FitError(f"bucket {b}: need human and AI tune rows (have {len(hb)} human, {len(ab)} AI)")
        ai_below, info = fit_one_percent(hb, lambda r: [r["_s"]["score"]])
        human_above = min_cut_above([r["_s"]["score"] for r in ab], AI_ABOVE_CAP)
        clamped = human_above < ai_below
        if clamped:
            human_above = ai_below
        # no rounding: rounding a cutoff up/down could let one more text across it
        buckets[b] = {"ai_below": ai_below, "human_above": human_above}
        info.update({"n_ai": len(ab), "human_above_clamped_to_ai_below": clamped})
        details["buckets"][b] = info
        for name, n in (("human", info["n_human"]), ("non_native", info["n_non_native"])):
            if n < MIN_HUMAN_WARN:
                details["warnings"].append(
                    f"{b}: only {n} {name} tune rows; the 1% rule falls back to (near) the minimum score")

    # segment windows from human texts (only texts long enough to have windows)
    def seg_scores(r):
        return [s["score"] for s in (r["_s"].get("segments") or []) if s.get("score") is not None]

    humans = [r for r in rows if r["label"] == "human"]
    if not any(seg_scores(r) for r in humans):
        raise FitError("no human segment windows in scores")
    flag_below, seg_info = fit_one_percent([r for r in humans if seg_scores(r)], seg_scores)
    details["segment"] = seg_info

    if window_words is None or stride_words is None:
        w, st = infer_window(rows)
        window_words = window_words or w
        stride_words = stride_words or st

    medians = {}
    for label in ("human", "ai"):
        lr = [r for r in rows if r["label"] == label]
        stats_keys = list(MEDIAN_KEYS) + sorted(
            {k for r in lr for k, v in (r["_s"].get("stats") or {}).items()
             if isinstance(v, (int, float)) and k not in MEDIAN_KEYS})
        med = {}
        for k in stats_keys:
            vals = [r["_s"]["stats"][k] for r in lr if isinstance((r["_s"].get("stats") or {}).get(k), (int, float))]
            if vals:
                med[k] = round(statistics.median(vals), 6)
        medians[label] = med

    thresholds = {
        "version": version or date.today().isoformat(),
        "model_pair": model_pair,
        "buckets": buckets,
        "segment": {"window_words": window_words, "stride_words": stride_words, "flag_below": flag_below},
        "medians": medians,
    }
    details["tune_rows"] = {"human": len(humans), "ai": len(rows) - len(humans)}
    details["skipped_rows_all_splits"] = skipped
    return thresholds, details


def infer_window(rows: list[dict]) -> tuple[int, int]:
    for r in rows:
        segs = r["_s"].get("segments") or []
        if len(segs) >= 2:
            w = segs[0]["word_end"] - segs[0]["word_start"]
            st = segs[1]["word_start"] - segs[0]["word_start"]
            if w > 0 and st > 0:
                return w, st
    return DEFAULT_WINDOW, DEFAULT_STRIDE


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(DATA_DIR / "all.jsonl"))
    ap.add_argument("--scores", default=str(DATA_DIR / "scores.jsonl"))
    ap.add_argument("--out", default=str(CAL_DIR / "thresholds.json"))
    ap.add_argument("--details", default=str(GEN_DIR / "fit-details.json"))
    ap.add_argument("--version", default=None)
    ap.add_argument("--window-words", type=int, default=None)
    ap.add_argument("--stride-words", type=int, default=None)
    args = ap.parse_args()
    try:
        th, details = fit(read_jsonl(args.data), read_jsonl(args.scores), args.version,
                          args.window_words, args.stride_words)
    except FitError as e:
        sys.exit(f"fit failed: {e}")
    write_json(args.out, th)
    write_json(args.details, details)
    for b, v in th["buckets"].items():
        d = details["buckets"][b]
        print(f"{b:>7}: ai_below={v['ai_below']:.4f} human_above={v['human_above']:.4f} "
              f"(human {d['n_human']}, non-native {d['n_non_native']}, ai {d['n_ai']}, binding {d['binding']})")
    print(f"segment flag_below={th['segment']['flag_below']:.4f} ({details['segment']['n_human']} human windows)")
    for w in details["warnings"]:
        print("warning:", w)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
