"""The sealed final test (docs/roadmap.md R5): human writing from sources no run has used.

  classifier/.venv/bin/python classifier/sealed.py collect     # -> classifier/data/sealed/human.jsonl

Collected once, then sealed: classifier/sealed/MANIFEST.json records the file's sha256 and the
counts. Nothing in training, tuning, evaluation or the nightly reads data/sealed/, and nobody
looks at its scores until a model is chosen; then it is scored once and the number reported
unchanged. The AI half (fresh ChatGPT and Claude pieces from each row's `cue`) is generated
later. All sources predate ChatGPT (2022-11-30):

  bbc-news      BBC articles 2010-2017 (XSum)                     cue: the one-line summary
  imdb          IMDB reviews to 2011 (Maas et al.)                cue: positive / negative
  yelp          Yelp reviews to 2015 (Yelp Open Dataset)          cue: star rating
  plos-summary  PLOS author summaries 2003-2015 (lay summaries)   cue: the paper title
  enron-email   Enron employee email 1999-2002                    cue: the subject line
  newsgroups    Usenet posts 1993 (20 Newsgroups)                 cue: the newsgroup
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clf_common import CLF_DIR, DATA_DIR  # noqa: E402
from common import normalize_text, write_json, write_jsonl  # noqa: E402
from fetch_human import balanced, cached_json, hf_blocks  # noqa: E402

OUT = DATA_DIR / "sealed" / "human.jsonl"
MANIFEST = CLF_DIR / "sealed" / "MANIFEST.json"
PER_SOURCE = 100


def ok_len(text: str, lo: int, hi: int) -> bool:
    return lo <= len(text.split()) <= hi


def unwrap(text: str) -> str:
    """Join hard-wrapped lines (1990s mail and Usenet wrap at ~72 columns) into paragraphs, or
    the wrapping alone would mark the text human."""
    paras = re.split(r"\n\s*\n", text)
    return "\n\n".join(re.sub(r"\s*\n\s*", " ", p).strip() for p in paras if p.strip())


def prose(text: str) -> bool:
    """Mostly sentences: no tables or code."""
    return "\t" not in text and sum(c.isdigit() for c in text) / max(len(text), 1) < 0.03


def bbc(raw: list[dict]) -> list[dict]:
    out = []
    for r in raw:
        # XSum keeps one paragraph per line
        text = normalize_text("\n\n".join(p.strip() for p in r["document"].split("\n") if p.strip()))
        if ok_len(text, 150, 600) and r.get("summary"):
            out.append({"_uid": r["id"], "text": text, "cue": r["summary"].strip(), "group": "-"})
    return out


def imdb(raw: list[dict]) -> list[dict]:
    out = []
    for r in raw:
        text = normalize_text(re.sub(r"<[^>]+>", " ", r["text"].replace("<br /><br />", "\n\n")))
        if ok_len(text, 80, 450):
            mood = "positive" if r["label"] == 1 else "negative"
            out.append({"_uid": str(r["_row"]), "text": text, "cue": mood, "group": mood})
    return out


def yelp(raw: list[dict]) -> list[dict]:
    out = []
    for r in raw:
        text = r["text"].replace("\\n", "\n")
        text = normalize_text(re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text))
        if ok_len(text, 80, 450) and "http" not in text:
            stars = f"{r['label'] + 1} stars"
            out.append({"_uid": str(r["_row"]), "text": text, "cue": stars, "group": stars})
    return out


def plos(raw: list[dict]) -> list[dict]:
    out = []
    for r in raw:
        text = normalize_text(r["summary"])
        if ok_len(text, 120, 400) and r.get("title"):
            out.append({"_uid": str(r["_row"]), "text": text, "cue": r["title"].strip(), "group": "-"})
    return out


QUOTED = re.compile(r"(?im)^\s*(-{3,}|>|from:|to:|cc:|sent:|subject:)|forwarded by|original message|@|http|www\.")


def enron(raw: list[dict]) -> list[dict]:
    out, per_box = [], Counter()
    for r in raw:
        body = r["body"]
        # only messages a person typed: no forwards, replies with quoted text, or addresses
        if QUOTED.search(body) or not r.get("subject"):
            continue
        text = normalize_text(unwrap(body))
        box = r["file_name"].split("/")[0]
        if ok_len(text, 80, 400) and prose(text) and per_box[box] < 3:
            per_box[box] += 1
            out.append({"_uid": str(r["_row"]), "text": text, "cue": r["subject"].strip(), "group": box})
    return out


def newsgroups(raw: list[dict]) -> list[dict]:
    out = []
    for r in raw:
        lines = []
        for line in r["text"].split("\n"):
            if line.strip() in ("--", "-- "):
                break  # signature
            if line.lstrip().startswith((">", "|", ":")) or re.search(r"writes:$|wrote:$|^In article", line.strip()):
                continue
            lines.append(line)
        text = normalize_text(unwrap("\n".join(lines)))
        code = sum(text.count(c) for c in "{};=#$")
        if ok_len(text, 80, 400) and prose(text) and code < 5 and text.count("@") <= 1 and "http" not in text:
            out.append({"_uid": str(r["_row"]), "text": text, "cue": r["label_text"], "group": r["label_text"]})
    return out


SOURCES = {  # name: (dataset, config, split, blocks, parse, subset, licence)
    "bbc-news": ("EdinburghNLP/xsum", "default", "test", 4, bbc, "news", "XSum (Narayan et al. 2018), BBC; research use"),
    "imdb": ("stanfordnlp/imdb", "plain_text", "test", 4, imdb, "review", "IMDB (Maas et al. 2011); research use"),
    "yelp": ("Yelp/yelp_review_full", "yelp_review_full", "test", 5, yelp, "review", "Yelp Open Dataset terms"),
    "plos-summary": ("pszemraj/scientific_lay_summarisation-plos-norm", "default", "test", 4, plos, "academic",
                     "PLOS (CC BY 4.0)"),
    "enron-email": ("corbt/enron-emails", "default", "train", 60, enron, "email", "Enron corpus (FERC release); public"),
    "newsgroups": ("SetFit/20_newsgroups", "default", "test", 10, newsgroups, "forum", "20 Newsgroups (1993); research use"),
}


def collect(refresh: bool) -> int:
    if OUT.exists() and not refresh:
        print(f"{OUT} exists; it is sealed (pass --refresh only if nothing has been scored on it)")
        return 1
    rows = []
    for name, (dataset, config, split, blocks, parse, subset, licence) in SOURCES.items():
        raw = cached_json(f"sealed-{name}.json", False, lambda: hf_blocks(dataset, config, split, blocks, name))
        seen, items = set(), []
        for it in parse(raw):
            k = re.sub(r"\W+", " ", it["text"]).lower()
            if k not in seen:
                seen.add(k)
                items.append(it)
        picked = balanced(items, "group", PER_SOURCE, f"sealed-{name}")
        print(f"{name}: {len(picked)} of {len(items)} usable ({len(raw)} fetched)")
        rows += [{"id": f"sealed-{name}-{p['_uid']}", "text": p["text"], "label": "human", "source": name,
                  "subset": subset, "cue": p["cue"], "license": licence} for p in picked]
    write_jsonl(OUT, rows)
    write_json(MANIFEST, {
        "collected": date.today().isoformat(),
        "file": str(OUT.relative_to(CLF_DIR.parent)),
        "sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
        "rows": len(rows),
        "by_source": dict(sorted(Counter(r["source"] for r in rows).items())),
        "datasets": {k: f"{v[0]} ({v[1]}/{v[2]})" for k, v in SOURCES.items()},
        "scored": None,
    })
    print(f"wrote {len(rows)} rows -> {OUT}\nsealed: {MANIFEST}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    return collect(args.refresh)


if __name__ == "__main__":
    sys.exit(main())
