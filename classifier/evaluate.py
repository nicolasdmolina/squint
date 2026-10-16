"""Score a trained run on tune / heldout / held-out sources / OOD sets, fit the cutoffs on tune,
and write the gate report.

  classifier/.venv/bin/python classifier/evaluate.py                  # newest finished run
  classifier/.venv/bin/python classifier/evaluate.py --run-dir classifier/runs/<run>

Outputs:
  <run>/predictions.jsonl              P(AI) per row (cached; reruns only score what is missing)
  classifier/reports/<date>.json       full numbers + gate (pass/fail)
  classifier/reports/<date>.md         short morning summary of the gate
  <run>/binoculars-needed.jsonl        evaluation rows that have no Binoculars score yet, in the
                                       squint-score input format (score them to complete the
                                       combined-rule numbers; see README)

Cutoffs (fitted on the tune split only, then frozen):
  classifier-only   flag when P(AI) > t; t keeps false flags <= cap on all tune humans and on
                    tune non-native humans (the stricter wins)
  combined          flag when P(AI) > t' OR Binoculars score < b_cut, fitted on tune rows that
                    have a Binoculars score; rows without one use the classifier-only cutoff
Gate (on human texts the model never saw in training or tuning: held-out sources + OOD sets):
  false flags <= cap overall and for non-native writers, and the ChatGPT catch rate on the
  held-out sources' AI texts >= min_chatgpt_catch. Reported for both rules. Only texts of at
  least min_words words count: shorter texts get "too short to tell" in the product, and their
  numbers are reported separately for information.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clf_common import CAL_DATA, DATA_DIR, REPORTS_DIR, RUNS_DIR, load_config  # noqa: E402
from common import read_jsonl, write_json, write_jsonl  # noqa: E402
from thresholds import apply_or_rule, fit_or_rule, fit_threshold, wilson  # noqa: E402

EVAL_SPLITS = ("tune", "heldout", "holdout", "ood")
GATE_SPLITS = ("holdout", "ood")
EXIT_DONE, EXIT_STOPPED, EXIT_ERROR = 0, 3, 1


class Stop:
    requested = False


def newest_finished_run() -> Path | None:
    done = [p.parent for p in RUNS_DIR.glob("*/final/trained.json")]
    return max(done, key=lambda p: (p / "final" / "trained.json").stat().st_mtime) if done else None


def load_binoculars(paths: list[Path], cal_rows: dict[str, str], rows: dict[str, dict]) -> tuple[dict, dict]:
    """id -> Binoculars score for rows whose text matches the text that was scored."""
    out, stats = {}, {"files": [], "joined": 0, "text_mismatch": 0, "errors": 0, "pairs": set()}
    for p in paths:
        if not p.exists():
            continue
        stats["files"].append(str(p))
        for s in read_jsonl(p):
            r = rows.get(s["id"])
            if r is None:
                continue
            if s.get("error") is not None or s.get("score") is None or (s.get("word_count") or 0) < 20:
                stats["errors"] += 1
                continue
            scored_text = cal_rows.get(s["id"])
            if scored_text is not None and scored_text != r["text"]:
                stats["text_mismatch"] += 1
                continue
            out[s["id"]] = s["score"]
            stats["pairs"].add(json.dumps(s.get("model_pair"), sort_keys=True))
    stats["joined"] = len(out)
    stats["pairs"] = sorted(stats["pairs"])
    return out, stats


def summarize(rows: list[dict], flag) -> dict:
    """Per split x source: human false flags, AI catch rates by generator (with Wilson CIs)."""
    cells = defaultdict(lambda: [0, 0])
    for r in rows:
        f = flag(r)
        keys = [(r["split"], r["label"], r["source"], r["generator"] or "-")]
        keys.append((r["split"], r["label"], "*all*", r["generator"] or "-"))
        if r["label"] == "human" and r["subset"] == "non_native":
            keys.append((r["split"], "human", "*non_native*", "-"))
        keys += [(f"{k[0]}|{r['bucket']}", *k[1:]) for k in list(keys)]
        for k in keys:
            cells[k][0] += int(f)
            cells[k][1] += 1
    out = {}
    for (split, label, source, gen), (k, n) in sorted(cells.items()):
        lo, hi = wilson(k, n)
        name = "false_flag" if label == "human" else "catch"
        out.setdefault(split, {}).setdefault(label, {})[source if label == "human" else f"{source}|{gen}"] = {
            "n": n, "flagged": k, name: round(k / n, 4), "ci95": [round(lo, 4), round(hi, 4)]}
    return out


def gate(rows: list[dict], flag, cap: float, min_catch: float, min_words: int = 0) -> dict:
    rows = [r for r in rows if r["n_words"] >= min_words]
    hum = [r for r in rows if r["split"] in GATE_SPLITS and r["label"] == "human"]
    nn = [r for r in hum if r["subset"] == "non_native"]
    cg = [r for r in rows if r["split"] == "holdout" and r["label"] == "ai" and r["generator"] == "chatgpt"]

    def rate(xs):
        k = sum(1 for r in xs if flag(r))
        lo, hi = wilson(k, len(xs))
        return {"n": len(xs), "flagged": k, "rate": round(k / len(xs), 4) if xs else None,
                "ci95": [round(lo, 4), round(hi, 4)] if xs else None}

    ff, ffn, catch = rate(hum), rate(nn), rate(cg)
    checks = {
        "false_flags_overall": ff["rate"] is not None and ff["rate"] <= cap,
        "false_flags_non_native": ffn["rate"] is not None and ffn["rate"] <= cap,
        "chatgpt_catch": catch["rate"] is not None and catch["rate"] >= min_catch,
    }
    return {"pass": all(checks.values()), "checks": checks, "false_flags_overall": ff,
            "false_flags_non_native": ffn, "chatgpt_catch_holdout": catch}


def render_markdown(rep: dict) -> str:
    g = rep["gate"]
    lines = [f"# Squint classifier report {rep['date']}", "",
             f"**Gate: {'PASS' if g['pass'] else 'FAIL'}** (recommended rule: {g['recommended_rule']})", "",
             f"- Run `{rep['run']}`, model `{rep['model']}`, dataset `{rep['dataset_hash']}`, "
             f"trained {rep['trained']['steps']} steps on {rep['trained']['train_rows']} rows.",
             f"- Cutoffs fitted on tune: classifier-only P(AI) > {rep['cutoffs']['classifier_only']['t']:.4f} "
             f"(bound by {rep['cutoffs']['classifier_only']['binding']}); combined "
             + (f"P(AI) > {rep['cutoffs']['combined']['t']:.4f} or Binoculars < {rep['cutoffs']['combined']['b_cut']:.4f}"
                if rep["cutoffs"].get("combined") else "not fitted (no Binoculars scores on tune)") + ".",
             f"- Gate counts texts of {g.get('min_words', 0)}+ words; shorter ones are shown below it for information.",
             "", "| Rule | Pass | False flags, held-out humans | Non-native | ChatGPT caught (held-out sources) |",
             "|---|---|---|---|---|"]

    def cell(d):
        return "n/a" if d["rate"] is None else f"{d['rate']:.1%} ({d['flagged']}/{d['n']}, CI to {d['ci95'][1]:.1%})"
    for name in ("classifier_only", "combined"):
        x = g["rules"].get(name)
        if x:
            lines.append(f"| {name} | {'yes' if x['pass'] else 'no'} | {cell(x['false_flags_overall'])} | "
                         f"{cell(x['false_flags_non_native'])} | {cell(x['chatgpt_catch_holdout'])} |")
    for name in ("classifier_only", "combined"):
        x = g.get("short_texts_info", {}).get(name)
        if x:
            lines.append(f"| {name}, under {g['min_words']} words (info) | {'yes' if x['pass'] else 'no'} | "
                         f"{cell(x['false_flags_overall'])} | {cell(x['false_flags_non_native'])} | "
                         f"{cell(x['chatgpt_catch_holdout'])} |")
    lines += ["", "Per held-out human source (classifier-only false flags):", ""]
    for split in GATE_SPLITS:
        for src, v in rep["by_rule"]["classifier_only"].get(split, {}).get("human", {}).items():
            lines.append(f"- {split} / {src}: {v['false_flag']:.1%} of {v['n']}")
    lines += ["", "AI catch on held-out sources (classifier-only):", ""]
    for key, v in rep["by_rule"]["classifier_only"].get("holdout", {}).get("ai", {}).items():
        if key.startswith("*all*"):
            lines.append(f"- {key.split('|')[1]}: {v['catch']:.1%} of {v['n']}")
    b = rep["binoculars"]
    lines += ["", f"Binoculars scores joined: {b['joined']} rows; evaluation rows still missing one: "
              f"{rep['binoculars_needed']} (listed in {rep['run']}/binoculars-needed.jsonl).", ""]
    return "\n".join(lines)


def main() -> int:
    cfg = load_config()
    ec, tc = cfg["evaluate"], cfg["train"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, default=None)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--batch-size", type=int, default=ec["batch_size"])
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    ap.add_argument("--binoculars", type=Path, nargs="*",
                    default=[CAL_DATA / "scores-falcon-7b.jsonl", DATA_DIR / "scores-extra-falcon-7b.jsonl"])
    ap.add_argument("--limit-per-split", type=int, default=None, help="smoke tests: score only N rows per split")
    ap.add_argument("--deadline", type=float, default=None)
    args = ap.parse_args()

    import modeling

    modeling.set_mps_memory_cap(tc["mps_memory_fraction"])
    signal.signal(signal.SIGTERM, lambda *_: setattr(Stop, "requested", True))
    run_dir = args.run_dir or newest_finished_run()
    if run_dir is None or not (run_dir / "final" / "trained.json").exists():
        print("no finished run to evaluate", file=sys.stderr)
        return EXIT_ERROR
    trained = json.loads((run_dir / "final" / "trained.json").read_text())
    rows = [r for r in read_jsonl(run_dir / "dataset.jsonl") if r["split"] in EVAL_SPLITS]
    if args.limit_per_split:
        by = defaultdict(list)
        for r in sorted(rows, key=lambda r: r["id"]):
            by[(r["split"], r["label"])].append(r)
        rows = [r for v in by.values() for r in v[: args.limit_per_split]]
    by_id = {r["id"]: r for r in rows}

    # ---- predictions (cached, resumable) -------------------------------------------------
    pred_path = run_dir / "predictions.jsonl"
    preds = {p["id"]: p["p"] for p in read_jsonl(pred_path)} if pred_path.exists() else {}
    todo = [r for r in rows if r["id"] not in preds]
    if todo:
        import torch  # noqa: F401  (after the MPS cap is set)

        device = modeling.pick_device(args.device)
        tok, model = modeling.load_model(trained["model"], path=str(run_dir / "final"))
        amp = trained.get("amp", "none")
        step = 64
        with open(pred_path, "a") as f:
            for s in range(0, len(todo), step):
                if Stop.requested or (args.deadline and time.time() > args.deadline):
                    print(f"stopped with {len(todo) - s} rows unscored; rerun to continue", flush=True)
                    return EXIT_STOPPED
                part = todo[s:s + step]
                ps = modeling.predict_texts(model, tok, [r["text"] for r in part], device, tc["max_length"],
                                            args.batch_size, amp)
                for r, p in zip(part, ps):
                    preds[r["id"]] = p
                    f.write(json.dumps({"id": r["id"], "p": round(p, 6)}) + "\n")
                f.flush()
                print(f"scored {min(s + step, len(todo))}/{len(todo)}", flush=True)
    for r in rows:
        r["p"] = preds[r["id"]]

    # ---- Binoculars join -------------------------------------------------------------------
    cal_path = CAL_DATA / "all.jsonl"
    cal_text = {r["id"]: r["text"] for r in read_jsonl(cal_path)} if cal_path.exists() else {}
    bino, bstats = load_binoculars(args.binoculars, cal_text, by_id)
    for r in rows:
        r["b"] = bino.get(r["id"])
    needed = [{"id": r["id"], "text": r["text"], "label": r["label"], "source": r["source"], "subset": r["subset"],
               "split": r["split"]} for r in rows if r["b"] is None and r["n_words"] >= 20]
    write_jsonl(run_dir / "binoculars-needed.jsonl", needed)

    # ---- cutoffs on tune -----------------------------------------------------------------
    cap = ec["false_flag_cap"]
    tune_h = [r for r in rows if r["split"] == "tune" and r["label"] == "human"]
    t, bind = fit_threshold({"all": [r["p"] for r in tune_h],
                             "non_native": [r["p"] for r in tune_h if r["subset"] == "non_native"]}, cap)
    cutoffs = {"classifier_only": {"t": t, "binding": bind, "n_tune_human": len(tune_h)}}
    tune_hb = [r for r in tune_h if r["b"] is not None]
    tune_ab = [r for r in rows if r["split"] == "tune" and r["label"] == "ai" and r["b"] is not None]
    rules = {"classifier_only": lambda r: r["p"] > t}
    if tune_hb and tune_ab:
        comb = fit_or_rule(tune_hb, tune_ab, cap)
        cutoffs["combined"] = {**comb, "n_tune_human": len(tune_hb), "n_tune_ai": len(tune_ab)}
        rules["combined"] = lambda r: apply_or_rule(r["p"], r["b"], comb, t)

    # ---- metrics and gate -----------------------------------------------------------------
    by_rule = {name: summarize(rows, f) for name, f in rules.items()}
    min_words = ec.get("min_words", 0)
    gates = {name: gate(rows, f, cap, ec["min_chatgpt_catch"], min_words) for name, f in rules.items()}
    short_rows = [r for r in rows if r["n_words"] < min_words]
    short = {name: gate(short_rows, f, cap, ec["min_chatgpt_catch"]) for name, f in rules.items()} if short_rows else {}
    passing = [n for n in ("combined", "classifier_only") if n in gates and gates[n]["pass"]]
    rep = {
        "date": args.date, "run": run_dir.name, "model": trained["model"], "dataset_hash": trained["dataset_hash"],
        "trained": trained, "cap": cap, "min_chatgpt_catch": ec["min_chatgpt_catch"],
        "gate": {"pass": bool(passing), "recommended_rule": passing[0] if passing else "none", "rules": gates,
                 "min_words": min_words, "short_texts_info": short},
        "cutoffs": {k: {kk: (None if isinstance(vv, float) and vv == float("-inf") else vv) for kk, vv in v.items()}
                    for k, v in cutoffs.items()},
        "by_rule": by_rule,
        "binoculars": bstats, "binoculars_needed": len(needed),
        "rows_scored": len(rows), "limited": bool(args.limit_per_split),
    }
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.reports_dir / f"{args.date}.json", rep)
    if rep["cutoffs"].get("combined") and rep["cutoffs"]["combined"]["b_cut"] is None:
        rep["cutoffs"]["combined"]["b_cut"] = float("-inf")  # for the markdown formatter only
    (args.reports_dir / f"{args.date}.md").write_text(render_markdown(rep) + "\n")
    print(render_markdown(rep))
    return EXIT_DONE


if __name__ == "__main__":
    sys.exit(main())
