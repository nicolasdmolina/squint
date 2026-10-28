# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Assemble classifier/data/dataset.jsonl with the source-held-out split.

Inputs (all gitignored):
  calibration/data/human_base.jsonl        5 human sources (calibration sample)
  classifier/data/human_extra.jsonl        new human sources + extra PERSUADE essays
  classifier/data/ood/*.jsonl              out-of-distribution human sets (evaluation only)
  calibration/generated/ai_*.jsonl         calibration AI pieces
  classifier/generated/ai_*.jsonl          classifier AI pieces (joined to plan.jsonl)

Each base document gives its full text plus sentence-aligned excerpts, cut exactly as the
calibration set cuts them (same function, same seeds), so a row id here that also exists in
calibration/data/all.jsonl has the same text and its Binoculars score can be joined.

Usage: uv run classifier/build_dataset.py
"""

from __future__ import annotations

import hashlib
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clf_common import CAL_DATA, CAL_GEN, DATA_DIR, GEN_DIR, cal_module, load_config  # noqa: E402
from common import read_jsonl, word_count, write_json, write_jsonl  # noqa: E402
from splits import assign_splits, dedup_across_splits, leakage_problems  # noqa: E402

from generate import family_of  # noqa: E402

cal_build = cal_module("build_dataset")  # calibration/build_dataset.py: variants(), copies_prompt()


MIN_AI_PER_HUMAN = 0.5


ONE_PARAGRAPH = {"blogs"}


def load_bases() -> tuple[list[dict], list[dict]]:
    """Base documents (one per original text) and rows dropped on the way."""
    bases, dropped = [], []
    human = [h for h in read_jsonl(CAL_DATA / "human_base.jsonl")]
    extra_path = DATA_DIR / "human_extra.jsonl"
    if extra_path.exists():
        human += read_jsonl(extra_path)
    for p in sorted((DATA_DIR / "ood").glob("*.jsonl")):
        human += read_jsonl(p)
    prompt_text = {}
    for h in human:
        if h.get("prompt_text"):
            prompt_text.setdefault(h["prompt_id"], h["prompt_text"])
        bases.append({"id": h["id"], "text": h["text"], "label": "human", "source": h["source"],
                      "family": h["source"], "generator": None, "subset": h["subset"],
                      "prompt_id": h["prompt_id"], "gen_variant": None, "origin_id": None, "model_id": None})
    plan_path = GEN_DIR / "plan.jsonl"
    plan = {p["id"]: p for p in read_jsonl(plan_path)} if plan_path.exists() else {}
    for d, from_plan in ((CAL_GEN, False), (GEN_DIR, True)):
        for p in sorted(d.glob("ai_*.jsonl")):
            for a in read_jsonl(p):
                it = plan.get(a["id"], {}) if from_plan else {}
                if from_plan and not it:
                    dropped.append({"id": a["id"], "reason": "not in plan.jsonl"})
                    continue
                if (a["kind"] in ("news", "short") or a["prompt_id"].startswith("blog:")) and \
                        it.get("variant") != "paraphrase" and \
                        cal_build.copies_prompt(a["text"], prompt_text.get(a["prompt_id"])):
                    dropped.append({"id": a["id"], "reason": "copies a 10-word run of its human prompt"})
                    continue
                bases.append({"id": a["id"], "text": a["text"], "label": "ai", "source": a["source"],
                              "family": it.get("family") or family_of(a["prompt_id"]), "generator": a["source"],
                              "subset": a["subset"], "prompt_id": a["prompt_id"],
                              "gen_variant": it.get("variant") or ("calibration-mixed-part" if a["role"] == "mixed_part"
                                                                   else "calibration"),
                              "origin_id": it.get("origin_id"), "model_id": a.get("model_id")})
    # sources whose human texts lost their line breaks: both sides become one paragraph, so
    # layout is never the label (fetch_human.blog_text)
    for b in bases:
        if b["family"] in ONE_PARAGRAPH:
            b["text"] = " ".join(b["text"].split())
    # A new human source joins only once its matched AI rows exist; trained alone, its style
    # (e.g. Reddit's) would read as a "human" cue. Generation runs after the night's build, so
    # without this a source fetched today would train one-sided tonight.
    extra_sources = {h["source"] for h in read_jsonl(extra_path)} if extra_path.exists() else set()
    n_human = Counter(b["source"] for b in bases if b["label"] == "human")
    n_ai = Counter(b["family"] for b in bases if b["label"] == "ai")
    waiting = {s for s in extra_sources if n_ai[s] < MIN_AI_PER_HUMAN * n_human[s]}
    if waiting:
        dropped += [{"id": b["id"], "reason": f"source {b['source']} waits for matched AI rows"}
                    for b in bases if b["label"] == "human" and b["source"] in waiting]
        bases = [b for b in bases if not (b["label"] == "human" and b["source"] in waiting)]
    ids = [b["id"] for b in bases]
    dup = [i for i, n in Counter(ids).items() if n > 1]
    if dup:
        raise SystemExit(f"duplicate base ids: {dup[:5]}")
    return bases, dropped


def build(cfg: dict) -> dict:
    d = cfg["data"]
    bases, dropped = load_bases()
    split_of = assign_splits(bases, d["holdout_sources"], d["ood_sources"], d["train_frac"], d["tune_frac"], d["seed"])
    rows = []
    for b in bases:
        for v in cal_build.variants(b):
            rid = b["id"] if v["variant"] == "full" else f"{b['id']}~{v['bucket']}"
            rows.append({"id": rid, "text": v["text"], "label": b["label"], "y": int(b["label"] == "ai"),
                         "source": b["source"], "family": b["family"], "generator": b["generator"],
                         "subset": b["subset"], "group_id": b["id"], "variant": v["variant"],
                         "gen_variant": b["gen_variant"], "bucket": v["bucket"], "n_words": word_count(v["text"]),
                         "split": split_of[b["id"]], "model_id": b["model_id"]})
    rows, dup_dropped = dedup_across_splits(rows)
    dropped += dup_dropped
    problems = leakage_problems(rows, d["holdout_sources"], d["ood_sources"])
    if problems:
        raise SystemExit("split leakage:\n  " + "\n  ".join(problems[:20]))
    rows.sort(key=lambda r: (r["split"], r["label"], r["source"], r["id"]))
    h = hashlib.sha256()
    for r in rows:
        h.update(f"{r['id']}\t{r['split']}\t{r['y']}\t{r['text']}\n".encode())
    digest = h.hexdigest()[:16]
    write_jsonl(DATA_DIR / "dataset.jsonl", rows)
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset_hash": digest,
        "rows": len(rows),
        "holdout_sources": d["holdout_sources"], "ood_sources": d["ood_sources"],
        "by_split_label": {f"{s}|{l}": n for (s, l), n in sorted(Counter((r["split"], r["label"]) for r in rows).items())},
        "by_split_source": {f"{s}|{l}|{so}": n for (s, l, so), n in
                            sorted(Counter((r["split"], r["label"], r["source"]) for r in rows).items())},
        "human_sources": sorted({r["source"] for r in rows if r["label"] == "human"}),
        "ai_by_generator_variant": {f"{g}|{v}": n for (g, v), n in
                                    sorted(Counter((r["generator"], r["gen_variant"]) for r in rows if r["label"] == "ai"
                                                   and r["variant"] == "full").items())},
        "documents": len(bases),
        "dropped": dropped,
    }
    write_json(DATA_DIR / "dataset-manifest.json", manifest)
    return manifest


def main() -> None:
    m = build(load_config())
    print(f"wrote {m['rows']} rows ({m['documents']} documents, hash {m['dataset_hash']}) -> {DATA_DIR / 'dataset.jsonl'}")
    for k, v in m["by_split_label"].items():
        print(f"  {k}: {v}")
    print(f"  human sources ({len(m['human_sources'])}): {', '.join(m['human_sources'])}")
    print(f"  dropped: {len(m['dropped'])}")


if __name__ == "__main__":
    main()
