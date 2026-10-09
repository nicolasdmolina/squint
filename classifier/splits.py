"""Split logic for the classifier dataset (standard library only, unit-tested).

Every base document (with all its excerpts) gets exactly one split:
  ood       human texts from the out-of-distribution sets: evaluation only
  holdout   documents from held-out human sources AND AI documents written for those
            sources' prompts: evaluation only (the source-held-out test)
  train / tune / heldout
            the rest, stratified by label x family x generator x subset, deterministic seed
A paraphrased AI piece always follows its origin piece's split, so a rewrite of a training
text never shows up in an evaluation split.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict

EVAL_ONLY = ("ood", "holdout")
SPLIT_PRIORITY = {"ood": 0, "holdout": 1, "heldout": 2, "tune": 3, "train": 4}  # dedup keeps the lowest


def _h(seed: str, *parts: object) -> int:
    return int.from_bytes(hashlib.sha256("|".join([seed, *map(str, parts)]).encode()).digest()[:8], "big")


def assign_splits(bases: list[dict], holdout_sources: set[str] | list[str], ood_sources: set[str] | list[str],
                  train_frac: float, tune_frac: float, seed: str) -> dict[str, str]:
    """bases: dicts with id, label ("human"/"ai"), source, family (the human source whose
    prompts the text mirrors; a human text's own source), generator (None for human), subset,
    and optional origin_id. Returns {id: split}."""
    holdout, ood = set(holdout_sources), set(ood_sources)
    out: dict[str, str] = {}
    strata: dict[tuple, list[str]] = defaultdict(list)
    followers = []
    by_id = {b["id"]: b for b in bases}
    for b in bases:
        if b["label"] == "human" and b["source"] in ood:
            out[b["id"]] = "ood"
        elif b["family"] in holdout or (b["label"] == "human" and b["source"] in holdout):
            out[b["id"]] = "holdout"
        elif b.get("origin_id") and b["origin_id"] in by_id:
            followers.append(b)
        else:
            strata[(b["label"], b["family"], b.get("generator") or "-", b.get("subset") or "-")].append(b["id"])
    cut1, cut2 = train_frac, train_frac + tune_frac
    for key, ids in strata.items():
        ids.sort(key=lambda i: _h(seed, "split", i))
        n = len(ids)
        # rotate the start by a per-stratum offset so small strata do not all favour `train`
        off = _h(seed, "stratum", *key) % max(n, 1)
        for rank, i in enumerate(ids):
            pos = ((rank + off) % n + 0.5) / n
            out[i] = "train" if pos < cut1 else "tune" if pos < cut2 else "heldout"
    def resolve(i: str, depth: int = 0) -> str:
        if i in out:
            return out[i]
        origin = by_id[i].get("origin_id")
        # a rewrite of a rewrite follows the chain; a cycle or a missing origin falls back to train
        out[i] = resolve(origin, depth + 1) if origin in by_id and origin != i and depth < 20 else "train"
        return out[i]

    for b in followers:
        resolve(b["id"])
    return out


def norm_text(text: str) -> str:
    return re.sub(r"\W+", " ", text).strip().lower()


def dedup_across_splits(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Drop rows whose normalised text also appears in a higher-priority split (ood > holdout >
    heldout > tune > train), and exact repeats within a split. Returns (kept, dropped)."""
    best: dict[str, int] = {}
    for r in rows:
        k = norm_text(r["text"])
        best[k] = min(best.get(k, 99), SPLIT_PRIORITY[r["split"]])
    kept, dropped, seen = [], [], set()
    for r in rows:
        k = norm_text(r["text"])
        if SPLIT_PRIORITY[r["split"]] != best[k] or (k, r["split"]) in seen:
            dropped.append({"id": r["id"], "reason": f"duplicate text (kept the copy in a {('higher-priority' if SPLIT_PRIORITY[r['split']] != best[k] else 'same')} split)"})
            continue
        seen.add((k, r["split"]))
        kept.append(r)
    return kept, dropped


def leakage_problems(rows: list[dict], holdout_sources, ood_sources) -> list[str]:
    """Empty when the split is clean. Checks: one split per group; held-out / OOD sources and
    families only in evaluation splits; no text shared between training and evaluation."""
    holdout, ood = set(holdout_sources), set(ood_sources)
    problems = []
    split_of_group: dict[str, set] = defaultdict(set)
    for r in rows:
        split_of_group[r["group_id"]].add(r["split"])
    for gid, s in split_of_group.items():
        if len(s) > 1:
            problems.append(f"group {gid} spans splits {sorted(s)}")
    for r in rows:
        if r["split"] in ("train", "tune", "heldout"):
            if r["source"] in holdout | ood or r.get("family") in holdout | ood:
                problems.append(f"{r['id']} from held-out source/family {r['source']}/{r.get('family')} is in {r['split']}")
    train_texts = {norm_text(r["text"]) for r in rows if r["split"] == "train"}
    for r in rows:
        if r["split"] != "train" and norm_text(r["text"]) in train_texts:
            problems.append(f"{r['id']} ({r['split']}) shares its text with a training row")
    return problems
