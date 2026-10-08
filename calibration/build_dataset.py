# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Assemble calibration/data/all.jsonl (docs/calibration-format.md §1) and manifest.json.

Inputs:  data/human_base.jsonl (fetch_human.py), generated/ai_<source>.jsonl (generate_ai.py)

1. Length coverage. Every base document gives its full text plus sentence-aligned excerpts
   in the shorter buckets (20-49 and/or 50-149 words). The excerpt procedure is identical for
   human and AI text: same target ranges, same random-start rule, same seeds.
2. Mixed documents. Each reserved human essay is spliced with an AI essay written for the same
   prompt (patterns H|A, A|H, H|A|H, A|H|A), with character `spans` labelling each part.
3. Splits. Whole base documents (with all their excerpts) go to `tune` or `heldout`, 50/50,
   stratified by label x source x subset x bucket-of-the-full-text, deterministic seed.

Rows carry the schema fields plus a few extras (group_id, variant, bucket, n_words, register)
that the scorer ignores.

Usage: uv run calibration/build_dataset.py
"""

from __future__ import annotations

import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (BUCKETS, DATA_DIR, GEN_DIR, bucket_for, paragraphs, read_jsonl, sentence_spans,  # noqa: E402
                    stable_hash, word_count, write_json, write_jsonl)

# excerpt targets sit inside the bucket so small word-count differences in the scorer
# cannot push them across an edge
EXCERPT_RANGES = {"20-49": (23, 46), "50-149": (55, 140)}
MIN_FULL_FOR_150 = 160
COPY_NGRAM = 10  # AI rows sharing a 10-word run with their human lead/prompt are dropped


# --- excerpts -----------------------------------------------------------------------------

def excerpt(text: str, lo: int, hi: int, rng: random.Random) -> str | None:
    """A run of whole consecutive sentences with lo..hi words, starting at a random sentence."""
    spans = sentence_spans(text)
    if not spans:
        return None
    wcs = [word_count(text[s:e]) for s, e in spans]
    target = rng.randint(lo, hi)
    starts = list(range(len(spans)))
    rng.shuffle(starts)
    for i in starts:
        total = 0
        for j in range(i, len(spans)):
            total += wcs[j]
            if total >= target:
                break
        if lo <= total <= hi:
            out = text[spans[i][0]:spans[j][1]]
            if lo <= word_count(out) <= hi:
                return out
    # fall back to any start whose run lands in range (target may have been unlucky)
    for i in starts:
        total = 0
        for j in range(i, len(spans)):
            total += wcs[j]
            if lo <= total <= hi:
                return text[spans[i][0]:spans[j][1]]
            if total > hi:
                break
    return None


def variants(base: dict) -> list[dict]:
    """Full text plus excerpts for the shorter buckets."""
    text = base["text"]
    w = word_count(text)
    out = []
    full_bucket = bucket_for(w)
    if full_bucket is None:
        return out
    if full_bucket == "150+" and w < MIN_FULL_FOR_150:
        full_bucket_ok = False
    else:
        full_bucket_ok = True
    if full_bucket_ok:
        out.append({"variant": "full", "text": text, "bucket": full_bucket})
    for b in ("50-149", "20-49"):
        lo, hi = EXCERPT_RANGES[b]
        if BUCKETS.index(b) >= BUCKETS.index(full_bucket) and full_bucket_ok:
            continue  # the full text already covers this bucket or a shorter one
        if w < hi + 15:
            continue  # too little text to cut a meaningful excerpt of this size
        rng = random.Random(stable_hash("excerpt", base["id"], b))
        ex = excerpt(text, lo, hi, rng)
        if ex:
            out.append({"variant": f"excerpt-{b}", "text": ex, "bucket": b})
    return out


# --- copy check ---------------------------------------------------------------------------

def _ngrams(text: str, n: int) -> set[tuple[str, ...]]:
    toks = re.findall(r"[a-z0-9']+", text.lower())
    return {tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def copies_prompt(ai_text: str, prompt_text: str | None, n: int = COPY_NGRAM) -> bool:
    if not prompt_text:
        return False
    return bool(_ngrams(ai_text, n) & _ngrams(prompt_text, n))


# --- mixed documents ----------------------------------------------------------------------

def units(text: str) -> list[str]:
    """Paragraphs when the text has at least 3, else chunks of ~3 sentences."""
    paras = paragraphs(text)
    if len(paras) >= 3:
        return paras
    spans = sentence_spans(text)
    sents = [text[s:e] for s, e in spans]
    return [" ".join(sents[i:i + 3]) for i in range(0, len(sents), 3)] if sents else paras


def splice(human_text: str, ai_text: str, pattern: str) -> tuple[str, list[dict]]:
    """Join human (H) and AI (A) units by pattern; returns text and tiling spans."""
    hu, au = units(human_text), units(ai_text)

    def head(u):
        return u[: max(1, len(u) // 2)]

    def tail(u):
        return u[max(1, len(u) // 2):] or u[-1:]

    if pattern == "HA":
        parts = [("human", head(hu)), ("ai", tail(au))]
    elif pattern == "AH":
        parts = [("ai", head(au)), ("human", tail(hu))]
    elif pattern == "HAH":
        mid = au[1:-1] or au[:1]
        parts = [("human", hu[:1]), ("ai", mid), ("human", hu[-1:] if len(hu) > 1 else hu)]
    elif pattern == "AHA":
        mid = hu[1:-1] or hu[:1]
        parts = [("ai", au[:1]), ("human", mid), ("ai", au[-1:] if len(au) > 1 else au)]
    else:
        raise ValueError(pattern)
    text = ""
    spans = []
    for k, (label, us) in enumerate(parts):
        chunk = "\n\n".join(us)
        if k < len(parts) - 1:
            chunk += "\n\n"
        start = len(text)
        text += chunk
        spans.append({"start": start, "end": len(text), "label": label})
    # merge neighbours with the same label (cannot happen with these patterns, kept for safety)
    merged = []
    for s in spans:
        if merged and merged[-1]["label"] == s["label"]:
            merged[-1]["end"] = s["end"]
        else:
            merged.append(dict(s))
    return text, merged


def ai_word_share(text: str, spans: list[dict]) -> float:
    words = [m.start() for m in re.finditer(r"\S+", text)]
    ai = sum(1 for p in words if any(s["label"] == "ai" and s["start"] <= p < s["end"] for s in spans))
    return ai / len(words) if words else 0.0


# --- splits -------------------------------------------------------------------------------

def assign_splits(groups: dict[str, tuple]) -> dict[str, str]:
    """groups: group_id -> stratum key. 50/50 per stratum, deterministic; odd leftovers
    alternate by a per-stratum coin so neither split is systematically larger."""
    by_stratum: dict[tuple, list[str]] = defaultdict(list)
    for gid, key in groups.items():
        by_stratum[key].append(gid)
    out = {}
    for key, gids in by_stratum.items():
        gids.sort(key=lambda g: stable_hash("split", g))
        first = "tune" if stable_hash("stratum", *key) % 2 == 0 else "heldout"
        second = "heldout" if first == "tune" else "tune"
        for i, g in enumerate(gids):
            out[g] = first if i % 2 == 0 else second
    return out


# --- main ---------------------------------------------------------------------------------

def main() -> None:
    human = read_jsonl(DATA_DIR / "human_base.jsonl")
    ai: list[dict] = []
    model_ids: dict[str, Counter] = defaultdict(Counter)
    for p in sorted(GEN_DIR.glob("ai_*.jsonl")):
        for r in read_jsonl(p):
            ai.append(r)
            model_ids[r["source"]][r["model_id"]] += 1
    human_by_id = {h["id"]: h for h in human}
    prompt_text_by_pid = {}
    for h in human:
        if h.get("prompt_text"):
            prompt_text_by_pid.setdefault(h["prompt_id"], h["prompt_text"])

    dropped = []
    seen_text = set()
    bases = []  # pure base documents (human + AI)
    for h in human:
        if h["role"] == "pure":
            bases.append({**h, "model_id": None, "register": None})
    for a in ai:
        if a["role"] != "pure":
            continue
        if a["kind"] in ("news", "short") and copies_prompt(a["text"], prompt_text_by_pid.get(a["prompt_id"])):
            dropped.append({"id": a["id"], "reason": f"shares a {COPY_NGRAM}-word run with its human prompt/lead"})
            continue
        bases.append({**a})
    for b in bases:
        key = re.sub(r"\s+", " ", b["text"]).strip().lower()
        if key in seen_text:
            dropped.append({"id": b["id"], "reason": "duplicate text"})
            b["_drop"] = True
        seen_text.add(key)
    bases = [b for b in bases if not b.get("_drop")]

    # split by base document
    strata = {}
    for b in bases:
        fb = bucket_for(word_count(b["text"])) or "short"
        strata[b["id"]] = (b["label"], b["source"], b["subset"], fb)
    split_of = assign_splits(strata)

    rows = []
    for b in bases:
        for v in variants(b):
            rid = b["id"] if v["variant"] == "full" else f"{b['id']}~{v['bucket']}"
            rows.append({
                "id": rid, "text": v["text"], "label": b["label"], "source": b["source"],
                "subset": b["subset"], "split": split_of[b["id"]], "model_id": b.get("model_id"),
                "prompt_id": b["prompt_id"], "group_id": b["id"], "variant": v["variant"],
                "bucket": v["bucket"], "n_words": word_count(v["text"]), "register": b.get("register"),
            })

    # mixed documents
    mixed = []
    for a in ai:
        if a["role"] != "mixed_part" or a.get("mix_with") not in human_by_id:
            continue
        h = human_by_id[a["mix_with"]]
        pattern = ("HA", "AH", "HAH", "AHA")[stable_hash("pattern", a["id"]) % 4]
        text, spans = splice(h["text"], a["text"], pattern)
        mixed.append({
            "id": f"mixed-{a['id']}", "text": text, "label": "mixed", "source": a["source"],
            "subset": h["subset"], "model_id": a["model_id"], "prompt_id": h["prompt_id"], "spans": spans,
            "group_id": f"mixed-{a['id']}", "variant": f"mixed-{pattern}", "n_words": word_count(text),
            "register": "student_essay", "mix_human_id": h["id"], "mix_ai_id": a["id"],
            "ai_word_share": round(ai_word_share(text, spans), 4),
        })
    mstrata = {m["id"]: ("mixed", m["source"], m["subset"]) for m in mixed}
    msplit = assign_splits(mstrata)
    for m in mixed:
        m["split"] = msplit[m["id"]]
        m["bucket"] = bucket_for(m["n_words"])
        rows.append(m)

    rows.sort(key=lambda r: (r["label"], r["source"], r["id"]))
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "duplicate row ids"
    write_jsonl(DATA_DIR / "all.jsonl", rows)

    # manifest
    cells = Counter((r["label"], r["source"], r["subset"], r["split"], r["bucket"]) for r in rows)
    groups = Counter((r["label"], r["split"]) for r in {r["group_id"]: r for r in rows}.values())
    status_path = GEN_DIR / "status.json"
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": len(rows),
        "by_label": dict(Counter(r["label"] for r in rows)),
        "by_label_split": {f"{l}|{s}": n for (l, s), n in sorted(Counter((r["label"], r["split"]) for r in rows).items())},
        "by_label_bucket_split": {f"{l}|{b}|{s}": n for (l, b, s), n in sorted(
            Counter((r["label"], r["bucket"], r["split"]) for r in rows).items())},
        "unique_documents": {f"{l}|{s}": n for (l, s), n in sorted(groups.items())},
        "cells": [{"label": l, "source": so, "subset": su, "split": sp, "bucket": b, "n": n}
                  for (l, so, su, sp, b), n in sorted(cells.items())],
        "ai_model_ids": {s: dict(c) for s, c in model_ids.items()},
        "generation_status": __import__("json").loads(status_path.read_text()) if status_path.exists() else None,
        "dropped": dropped,
        "mixed_ai_word_share_mean": round(sum(m["ai_word_share"] for m in mixed) / len(mixed), 3) if mixed else None,
        # `spans` are Python string offsets; they equal the scorer's UTF-16 offsets (format
        # v1.1) only while no text holds a character outside the BMP (e.g. an emoji)
        "rows_with_non_bmp_chars": sum(1 for r in rows if any(ord(c) > 0xFFFF for c in r["text"])),
    }
    if manifest["rows_with_non_bmp_chars"]:
        print(f"warning: {manifest['rows_with_non_bmp_chars']} rows contain non-BMP characters; "
              "their character offsets differ between Python and UTF-16", file=sys.stderr)
    write_json(DATA_DIR / "manifest.json", manifest)
    print(f"wrote {len(rows)} rows -> {DATA_DIR / 'all.jsonl'}")
    for k, v in manifest["by_label_bucket_split"].items():
        print(f"  {k}: {v}")
    print(f"  unique documents: {manifest['unique_documents']}")
    print(f"  dropped: {len(dropped)}")


if __name__ == "__main__":
    main()
