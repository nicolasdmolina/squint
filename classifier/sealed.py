"""The sealed final test (docs/roadmap.md R5): human writing from sources no run has used.

  classifier/.venv/bin/python classifier/sealed.py collect     # -> classifier/data/sealed/human.jsonl
  classifier/.venv/bin/python classifier/sealed.py plan        # -> classifier/data/sealed/gen/plan.jsonl

Collected once, then sealed: classifier/sealed/MANIFEST.json records the file's sha256 and the
counts. Nothing in training, tuning, evaluation or the nightly reads data/sealed/, and nobody
looks at its scores until a model is chosen; then it is scored once and the number reported
unchanged. The AI half is one ChatGPT and one Claude piece per row, written from its `cue`
into data/sealed/gen/ (generate.py run --then-sealed, which the nightly passes once the
training plan is done); build_dataset never reads that folder. All sources predate ChatGPT (2022-11-30):

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
from common import normalize_text, read_jsonl, word_count, write_json, write_jsonl  # noqa: E402
from fetch_human import balanced, cached_json, hf_blocks  # noqa: E402
from generate import about, item  # noqa: E402

OUT = DATA_DIR / "sealed" / "human.jsonl"
MANIFEST = CLF_DIR / "sealed" / "MANIFEST.json"
GEN = DATA_DIR / "sealed" / "gen"
GENERATORS = ("chatgpt", "claude")
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


def instruction(h: dict, n: int) -> tuple[str, str]:
    """(kind, instruction) for the AI piece matching sealed human row h. Only the cue is shown,
    never the human text."""
    src, cue = h["source"], h["cue"]
    if src == "bbc-news":
        return "news", (f"Write a news article (about {n} words) for a British news website reporting this: "
                        f"\"{cue}\". Use short paragraphs and no headline.")
    if src == "imdb":
        return "review", (f"Write a {cue} user review (about {n} words) of a film you watched, for IMDB. "
                          f"Choose the film yourself.")
    if src == "yelp":
        return "review", (f"Write a Yelp review (about {n} words) of a local business you visited, giving it "
                          f"{cue}. Choose the business yourself.")
    if src == "plos-summary":
        return "abstract", (f"Write the author summary (about {n} words, one paragraph, for readers outside the "
                            f"field) of a research paper titled \"{cue}\".")
    if src == "enron-email":
        return "email", (f"Write a work email (about {n} words) to a colleague, with the subject line \"{cue}\". "
                         f"Give only the body, starting with the greeting.")
    if src == "newsgroups":
        return "forum", f"Write a post (about {n} words) for the Usenet newsgroup {cue}, as a regular there."
    raise ValueError(src)


def plan() -> int:
    if not OUT.exists():
        print("collect the human half first")
        return 1
    items = []
    for h in read_jsonl(OUT):
        n = min(about(word_count(h["text"])), 450)
        kind, text = instruction(h, n)
        for gen in GENERATORS:
            it = item(gen, "sealed", kind if n >= 150 else "short", h["subset"], f"sealed:{h['id']}", text,
                      kind, h["id"], n)
            items.append({**it, "family": h["source"]})
    write_jsonl(GEN / "plan.jsonl", items)
    print(f"wrote {len(items)} sealed AI items -> {GEN / 'plan.jsonl'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--refresh", action="store_true")
    sub.add_parser("plan")
    args = ap.parse_args()
    return collect(args.refresh) if args.cmd == "collect" else plan()


if __name__ == "__main__":
    sys.exit(main())
