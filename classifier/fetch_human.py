# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""More pre-ChatGPT human writing for the classifier, plus the out-of-distribution test sets.

  uv run classifier/fetch_human.py fetch [--only arxiv,wikipedia,...] [--refresh]
      -> classifier/data/human_extra.jsonl   (cached downloads in classifier/data/raw/)
  uv run classifier/fetch_human.py ood --from <dir with CollegeEssay_real_70.json ...>
      -> classifier/data/ood/<source>.jsonl + classifier/data/ood/PROVENANCE.json

The calibration set (calibration/data/human_base.jsonl) is used as is; this adds sources.
Every source, its licence and URL is listed in classifier/sources.json.

New sources (all written before ChatGPT, 2022-11-30):
  arxiv            arXiv abstracts (metadata snapshot 2021, CC0)            subset academic
  wikipedia        English Wikipedia, revision as of 2021-12-31 (CC BY-SA)   subset encyclopedic
  amazon-reviews   Amazon product reviews to 2013 (amazon_polarity)          subset review
  stackexchange    Stack Exchange answers 2012-2021, prose sites (CC BY-SA)  subset forum
  persuade (extra) more PERSUADE 2.0 essays, disjoint from the calibration sample and from
                   every ELLIPSE essay (ELLIPSE is a held-out source)
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clf_common import CAL_DATA, DATA_DIR, cal_module, load_config  # noqa: E402  (also puts calibration/ on sys.path)
from common import normalize_text, read_jsonl, stable_hash, word_count, write_json, write_jsonl  # noqa: E402

RAW_DIR = DATA_DIR / "raw"
OOD_DIR = DATA_DIR / "ood"
UA = {"User-Agent": "squint-classifier/1.0 (private research; non-commercial)"}
SEED = "squint-clf-human"
HF_ROWS = "https://datasets-server.huggingface.co/rows"
HF_INFO = "https://datasets-server.huggingface.co/info"
WIKI_API = "https://en.wikipedia.org/w/api.php"
SE_API = "https://api.stackexchange.com/2.3"
SE_SITES = ["workplace", "parenting", "cooking", "travel", "english", "history", "philosophy",
            "interpersonal", "academia", "money", "outdoors", "pets", "gardening", "writing"]
WIKI_CUTOFF = "2021-12-31T00:00:00Z"
SE_FROM, SE_TO = 1325376000, 1640995199  # 2012-01-01 .. 2021-12-31 UTC


def fetch(url: str, timeout: int = 60, tries: int = 4) -> bytes:
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={**UA, "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip" or data[:2] == b"\x1f\x8b":
                    data = gzip.decompress(data)
                return data
        except Exception as e:  # network hiccup or 429: back off, then give up loudly
            if k == tries - 1:
                raise
            wait = (20, 60, 180, 300)[k]
            print(f"  fetch failed ({e}); retry in {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def fetch_json(url: str, **kw) -> dict:
    return json.loads(fetch(url, **kw))


def cached_json(name: str, refresh: bool, make) -> object:
    path = RAW_DIR / name
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    obj = make()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return obj


def balanced(items: list[dict], key: str, n: int, salt: str) -> list[dict]:
    """Round-robin over strata, lowest stable hash first (deterministic, near-uniform)."""
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(str(it[key]), []).append(it)
    for g in groups.values():
        g.sort(key=lambda it: stable_hash(salt, it["_uid"], seed=SEED))
    out, order, i = [], sorted(groups), 0
    while len(out) < n and any(groups.values()):
        g = groups[order[i % len(order)]]
        if g:
            out.append(g.pop(0))
        i += 1
    return out


def row(source: str, uid: str, text: str, subset: str, prompt_id: str, prompt_text: str | None,
        topic: str | None, license_: str, meta: dict | None = None) -> dict:
    return {"id": f"{source}-{uid}", "text": text, "label": "human", "source": source, "subset": subset,
            "prompt_id": prompt_id, "prompt_text": prompt_text, "topic": topic, "role": "pure",
            "license": license_, "meta": meta or {}}


# --- arXiv abstracts ---------------------------------------------------------------------

def hf_rows(dataset: str, config: str, split: str, offset: int, length: int = 100) -> list[dict]:
    q = urllib.parse.urlencode({"dataset": dataset, "config": config, "split": split,
                                "offset": offset, "length": length})
    return [r["row"] for r in fetch_json(f"{HF_ROWS}?{q}")["rows"]]


def hf_blocks(dataset: str, config: str, split: str, n_blocks: int, salt: str) -> list[dict]:
    info = fetch_json(f"{HF_INFO}?dataset={urllib.parse.quote(dataset)}")["dataset_info"][config]
    total = info["splits"][split]["num_examples"]
    out = []
    for b in range(n_blocks):
        off = stable_hash(salt, b, seed=SEED) % max(1, total - 100)
        for k, r in enumerate(hf_rows(dataset, config, split, off)):
            out.append({**r, "_row": off + k})
        time.sleep(3)  # the free datasets-server API rate-limits quickly
    return out


def arxiv_rows(n: int, refresh: bool) -> list[dict]:
    raw = cached_json("arxiv_blocks.json", refresh,
                      lambda: hf_blocks("gfissore/arxiv-abstracts-2021", "default", "train", 20, "arxiv"))
    items = []
    for r in raw:
        text = re.sub(r"\s*\n\s*", " ", (r.get("abstract") or "")).strip()
        # LaTeX markup would be a trivial "human" cue the AI side never has; skip it
        if re.search(r"[$\\{}^_]", text) or not 80 <= word_count(text) <= 400:
            continue
        cat = (r.get("categories") or ["misc"])[0].split()[0].split(".")[0]
        items.append({"_uid": r["id"], "text": normalize_text(text), "title": re.sub(r"\s+", " ", r["title"]).strip(),
                      "cat": cat})
    picked = balanced(items, "cat", n, "arxiv-pick")
    return [row("arxiv", re.sub(r"[^A-Za-z0-9.]+", "_", p["_uid"]), p["text"], "academic",
                f"arxiv:{p['_uid']}", p["title"], p["cat"], "CC0 1.0 (arXiv metadata)", {"category": p["cat"]})
            for p in picked]


# --- Amazon reviews ----------------------------------------------------------------------

def amazon_rows(n: int, refresh: bool) -> list[dict]:
    raw = cached_json("amazon_blocks.json", refresh,
                      lambda: hf_blocks("fancyzhx/amazon_polarity", "amazon_polarity", "test", 8, "amazon"))
    items = []
    for r in raw:
        text = normalize_text(r.get("content") or "")
        if not 30 <= word_count(text) <= 400:
            continue
        items.append({"_uid": str(r["_row"]), "text": text, "title": (r.get("title") or "").strip(),
                      "polarity": "positive" if r.get("label") == 1 else "negative"})
    picked = balanced(items, "polarity", n, "amazon-pick")
    return [row("amazon-reviews", p["_uid"], p["text"], "review", f"review:{p['_uid']}",
                p["title"], p["polarity"], "Apache-2.0 (amazon_polarity card); reviews by Amazon users",
                {"polarity": p["polarity"]}) for p in picked]


# --- Wikipedia (revision as of the end of 2021) ------------------------------------------

class _WikiText(HTMLParser):
    """Text of top-level <p> elements, without footnote markers, styles or edit links."""
    SKIP = {"sup", "style", "script", "table", "math", "figure"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paras: list[str] = []
        self._p = None
        self._stack: list[str] = []  # open tags that started (or nest inside) a skipped region

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class") or ""
        if self._stack:
            if tag == self._stack[-1]:
                self._stack.append(tag)
        elif tag in self.SKIP or "mw-editsection" in cls or "noprint" in cls or "reference" in cls:
            self._stack.append(tag)
        elif tag == "p":
            self._p = []

    def handle_endtag(self, tag):
        if self._stack:
            if tag == self._stack[-1]:
                self._stack.pop()
        elif tag == "p" and self._p is not None:
            t = re.sub(r"\s+", " ", "".join(self._p)).strip()
            if t:
                self.paras.append(t)
            self._p = None

    @property
    def _skip(self) -> int:
        return len(self._stack)

    def handle_data(self, data):
        if self._p is not None and self._skip == 0:
            self._p.append(data)


def wiki_text(html_text: str) -> str:
    p = _WikiText()
    p.feed(html_text)
    out, words = [], 0
    for para in p.paras:
        para = re.sub(r"\[\d+\]|\[citation needed\]|\[[a-z]\]", "", para).strip()
        if word_count(para) < 15:
            continue
        out.append(para)
        words += word_count(para)
        if words >= 350:
            break
    return "\n\n".join(out)


def wiki_rows(n: int, refresh: bool) -> list[dict]:
    partial = RAW_DIR / "wikipedia_docs.partial.json"

    def make():
        # progress is kept in a partial file, so an interrupted or rate-limited run resumes
        state = json.loads(partial.read_text(encoding="utf-8")) if partial.exists() else {"docs": [], "seen": []}
        docs, seen, rounds = state["docs"], set(state["seen"]), 0

        def save():
            partial.write_text(json.dumps({"docs": docs, "seen": sorted(seen)}, ensure_ascii=False), encoding="utf-8")

        try:
            collect(docs, seen, rounds, save)
        except Exception as e:
            save()
            # Wikipedia rate-limits anonymous parse calls hard; half the target is enough to use
            if len(docs) < n // 2:
                raise
            print(f"  wikipedia: stopping early ({e}); using the {len(docs)} articles collected", flush=True)
        return docs

    def collect(docs, seen, rounds, save):
        while len(docs) < int(n * 1.3) and rounds < 120:
            rounds += 1
            q = urllib.parse.urlencode({"action": "query", "format": "json", "generator": "random",
                                        "grnnamespace": 0, "grnlimit": 50, "prop": "info"})
            pages = fetch_json(f"{WIKI_API}?{q}").get("query", {}).get("pages", {})
            for pg in pages.values():
                if pg["pageid"] in seen or pg.get("length", 0) < 6000 or "redirect" in pg:
                    continue
                seen.add(pg["pageid"])
                time.sleep(1.0)  # stay well under Wikipedia's anonymous rate limits
                q = urllib.parse.urlencode({"action": "query", "format": "json", "prop": "revisions",
                                            "pageids": pg["pageid"], "rvlimit": 1, "rvstart": WIKI_CUTOFF,
                                            "rvdir": "older", "rvprop": "ids|timestamp"})
                revs = next(iter(fetch_json(f"{WIKI_API}?{q}")["query"]["pages"].values())).get("revisions")
                if not revs:
                    continue  # article created after 2021
                time.sleep(1.0)
                q = urllib.parse.urlencode({"action": "parse", "format": "json", "formatversion": 2,
                                            "oldid": revs[0]["revid"], "prop": "text"})
                parsed = fetch_json(f"{WIKI_API}?{q}").get("parse", {})
                text = wiki_text(parsed.get("text", ""))
                if word_count(text) >= 100:
                    docs.append({"_uid": str(pg["pageid"]), "title": pg["title"], "revid": revs[0]["revid"],
                                 "timestamp": revs[0]["timestamp"], "text": text})
                save()  # per article, so a 429 mid-batch loses nothing
                if len(docs) >= int(n * 1.3):
                    break
            print(f"  wikipedia: {len(docs)} usable articles after {rounds} random batches", flush=True)
            time.sleep(2.0)

    raw = cached_json("wikipedia_docs.json", refresh, make)
    items = [{**d, "k": "all", "text": normalize_text(html.unescape(d["text"]))} for d in raw]
    picked = balanced(items, "k", n, "wiki-pick")
    return [row("wikipedia", p["_uid"], p["text"], "encyclopedic", f"wiki:{p['_uid']}", p["title"], None,
                "CC BY-SA 3.0 (Wikipedia text, revision before 2022)",
                {"revid": p["revid"], "timestamp": p["timestamp"]}) for p in picked]


# --- Stack Exchange answers ---------------------------------------------------------------

class _SEText(HTMLParser):
    """Paragraph and list-item text of an answer body; quotes and code are dropped."""
    SKIP = {"pre", "code", "blockquote", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._buf: list[str] | None = None
        self._skip = 0
        self.had_code = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
            self.had_code |= tag == "pre"
        elif tag in ("p", "li") and self._skip == 0:
            self._buf = []

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in ("p", "li") and self._buf is not None:
            t = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if t:
                self.parts.append(t)
            self._buf = None

    def handle_data(self, data):
        if self._buf is not None and self._skip == 0:
            self._buf.append(data)


def se_rows(n: int, refresh: bool) -> list[dict]:
    def make():
        out = []
        for site in SE_SITES:
            q = urllib.parse.urlencode({"site": site, "pagesize": 100, "order": "desc", "sort": "votes",
                                        "fromdate": SE_FROM, "todate": SE_TO, "filter": "withbody"})
            answers = fetch_json(f"{SE_API}/answers?{q}").get("items", [])
            qids = ";".join(sorted({str(a["question_id"]) for a in answers}))
            titles = {}
            if qids:
                q2 = urllib.parse.urlencode({"site": site, "pagesize": 100})
                for it in fetch_json(f"{SE_API}/questions/{qids}?{q2}").get("items", []):
                    titles[it["question_id"]] = html.unescape(it["title"])
            for a in answers:
                out.append({"site": site, "answer_id": a["answer_id"], "question_id": a["question_id"],
                            "created": a["creation_date"], "license": a.get("content_license"),
                            "title": titles.get(a["question_id"]), "body": a["body"]})
            print(f"  stackexchange {site}: {len(answers)} answers", flush=True)
            time.sleep(1.0)
        return out

    raw = cached_json("stackexchange_answers.json", refresh, make)
    items = []
    for a in raw:
        p = _SEText()
        p.feed(a["body"])
        text = normalize_text("\n\n".join(p.parts))
        if p.had_code or not a["title"] or not 60 <= word_count(text) <= 600 or a["created"] > SE_TO:
            continue
        items.append({"_uid": f"{a['site']}-{a['answer_id']}", "site": a["site"], "text": text,
                      "title": a["title"], "license": a["license"] or "CC BY-SA"})
    picked = balanced(items, "site", n, "se-pick")
    return [row("stackexchange", p["_uid"], p["text"], "forum", f"forum:{p['_uid']}", p["title"], p["site"],
                f"{p['license']} (Stack Exchange)", {"site": p["site"]}) for p in picked]


# --- Reddit posts and comments (Webis-TLDR-17, 2006-2016) ---------------------------------

# subreddits whose posts are mostly links, images or game jargon rather than prose
REDDIT_SKIP = {"pics", "funny", "gifs", "videos", "gaming", "leagueoflegends", "starcraft", "DotA2", "trees",
               "circlejerk", "pokemon", "Minecraft", "wow", "nfl", "nba", "soccer", "hockey", "baseball"}


def reddit_rows(n: int, refresh: bool) -> list[dict]:
    """First-person, informal writing by ordinary people. The posts' own tl;dr lines are the
    prompts for the matched AI rows (Webis strips them from the body)."""
    raw = cached_json("reddit_blocks.json", refresh,
                      lambda: hf_blocks("webis/tldr-17", "default", "train", 14, "reddit"))
    items = []
    for r in raw:
        sub = r.get("subreddit") or ""
        text = html.unescape(r.get("content") or "")
        summary = re.sub(r"\s+", " ", html.unescape(r.get("summary") or "")).strip()
        # links, markdown and edit notes are cues the AI side never has
        if sub in REDDIT_SKIP or re.search(r"https?://|www\.|\]\(|^\s*>|\b(edit|EDIT|Edit)\s*\d*:", text, re.M):
            continue
        text = normalize_text(re.sub(r"[ \t]*\n[ \t]*", "\n", text).strip())
        if not 80 <= word_count(text) <= 450 or not 4 <= word_count(summary) <= 60:
            continue
        items.append({"_uid": r.get("id") or str(r["_row"]), "_row": r["_row"], "text": text, "sub": sub,
                      "summary": summary})
    picked = balanced(items, "sub", n, "reddit-pick")
    return [row("reddit", str(p["_row"]), p["text"], "personal", f"reddit:{p['_row']}", p["summary"], p["sub"],
                "CC BY 4.0 (Webis-TLDR-17); posts by Reddit users", {"subreddit": p["sub"]}) for p in picked]


# --- PERSUADE extra -----------------------------------------------------------------------

def persuade_extra_rows(n_native: int, n_ell: int) -> list[dict]:
    """More PERSUADE essays: not in the calibration sample, not an ELLIPSE essay."""
    import csv
    import io

    cal_fh = cal_module("fetch_human")  # calibration/fetch_human.py

    cal_fh.RAW_DIR = CAL_DATA / "raw"
    essays = cal_fh.load_persuade()
    used = {r["id"] for r in read_jsonl(CAL_DATA / "human_base.jsonl")}
    ell_csv = CAL_DATA / "raw" / "ellipse_train.csv"
    ellipse = list(csv.DictReader(io.StringIO(ell_csv.read_text(encoding="utf-8", errors="replace"))))
    ellipse_ids = {r["text_id_kaggle"].upper() for r in ellipse}
    ellipse_texts = {re.sub(r"\W+", " ", r["full_text"]).strip().lower() for r in ellipse}
    native, ell = [], []
    for e in essays:
        if f"persuade-{e['_uid'].lower()}" in used or e["_uid"].upper() in ellipse_ids:
            continue
        text, filled = cal_fh.fill_placeholders(normalize_text(e["text"]), e["_uid"])
        if not cal_fh.ok_len(text) or re.sub(r"\W+", " ", e["text"]).strip().lower() in ellipse_texts:
            continue
        item = {**e, "text": text, "filled": filled}
        status = e["ell_status"].strip().lower()
        (native if status == "no" else ell if status == "yes" else []).append(item)
    out = []
    for subset, pool, k in (("student", native, n_native), ("non_native", ell, n_ell)):
        for e in cal_fh.pick_balanced(pool, "prompt_name", k, f"clf-persuade-{subset}"):
            out.append(row("persuade", e["_uid"].lower(), e["text"], subset,
                           f"persuade:{cal_fh.slug(e['prompt_name'])}", e["assignment"], e["prompt_name"],
                           "CC BY-NC-SA 4.0",
                           {"grade": e["grade_level"], "ell_status": e["ell_status"], "task": e["task"],
                            "placeholders_filled": e["filled"], "extra": True}))
    return out


# --- out-of-distribution test sets ---------------------------------------------------------

ASAP_FILL = {"PERSON": "Maria", "CAPS": "Smith", "LOCATION": "Springfield", "CITY": "Springfield",
             "STATE": "Ohio", "ORGANIZATION": "the company", "DATE": "last year", "TIME": "noon",
             "NUM": "three", "PERCENT": "20%", "MONEY": "$50", "MONTH": "May", "DR": "Dr. Lee", "EMAIL": "my email"}
OOD_SETS = {
    "ood-college-essay": ("CollegeEssay_real_70.json", "student",
                          "Liang et al. 2023, ChatGPT-Detector-Bias: Data_and_Results/Human_Data/CollegeEssay_real_70",
                          "https://github.com/Weixin-Liang/ChatGPT-Detector-Bias",
                          "Repo shows an MIT badge, no LICENSE file; essays are third-party"),
    "ood-cs224n": ("CS224N_real_145.json", "academic",
                   "Liang et al. 2023, ChatGPT-Detector-Bias: Data_and_Results/Human_Data/CS224N_real_145",
                   "https://github.com/Weixin-Liang/ChatGPT-Detector-Bias",
                   "Repo shows an MIT badge, no LICENSE file; abstracts by Stanford CS224N students"),
    "ood-hewlett": ("HewlettStudentEssay_real_88.json", "student",
                    "Liang et al. 2023 (from the Hewlett ASAP essays, US grades 7-10)",
                    "https://github.com/Weixin-Liang/ChatGPT-Detector-Bias",
                    "ASAP data terms (Kaggle, research use); @PERSON-style tokens filled with ordinary words"),
    "ood-gb-essay": ("gb_essay", "student", "Ghostbuster data release, essay/human",
                     "https://github.com/vivek3141/ghostbuster-data", "CC BY 3.0 (Ghostbuster LICENSE)"),
}


def fill_asap(text: str) -> tuple[str, bool]:
    new, k = re.subn(r"@([A-Z]+)\d*", lambda m: ASAP_FILL.get(m.group(1), m.group(0)), text)
    return new, k > 0


def import_ood(src_dir: Path) -> None:
    OOD_DIR.mkdir(parents=True, exist_ok=True)
    prov = {"imported_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "from": str(src_dir), "sets": {}}
    for name, (fname, subset, origin, url, lic) in OOD_SETS.items():
        path = src_dir / fname
        if path.is_dir():
            files = sorted(path.glob("*.txt"), key=lambda p: int(p.stem) if p.stem.isdigit() else p.stem)
            docs = [(f.stem, f.read_text(encoding="utf-8", errors="replace")) for f in files]
            digest = hashlib.sha256(b"".join(f.read_bytes() for f in files)).hexdigest()
        else:
            raw = path.read_bytes()
            docs = [(str(i), d["document"]) for i, d in enumerate(json.loads(raw))]
            digest = hashlib.sha256(raw).hexdigest()
        rows = []
        for uid, t in docs:
            text, filled = fill_asap(normalize_text(t)) if name == "ood-hewlett" else (normalize_text(t), False)
            if word_count(text) >= 20:
                rows.append({"id": f"{name}-{uid}", "text": text, "label": "human", "source": name,
                             "subset": subset, "prompt_id": f"{name}:{uid}", "prompt_text": None, "topic": None,
                             "role": "pure", "license": lic, "meta": {"placeholders_filled": filled}})
        write_jsonl(OOD_DIR / f"{name}.jsonl", rows)
        prov["sets"][name] = {"file": fname, "rows": len(rows), "sha256": digest, "origin": origin,
                              "url": url, "license": lic}
        print(f"{name}: {len(rows)} rows")
    prov["note"] = ("ood_human.jsonl in the same scratchpad is a 25-per-set sample of these four sets, "
                    "so it is not imported separately.")
    write_json(OOD_DIR / "PROVENANCE.json", prov)


# --- main --------------------------------------------------------------------------------

FETCHERS = ("persuade", "arxiv", "wikipedia", "amazon-reviews", "stackexchange", "reddit")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--only", default=",".join(FETCHERS))
    f.add_argument("--refresh", action="store_true", help="re-download instead of using data/raw caches")
    o = sub.add_parser("ood")
    o.add_argument("--from", dest="src", required=True, type=Path)
    args = ap.parse_args()
    if args.cmd == "ood":
        import_ood(args.src)
        return
    cfg = load_config()["human"]
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "human_extra.jsonl"
    existing = {}
    if out_path.exists():
        for r in read_jsonl(out_path):
            existing.setdefault(r["source"], []).append(r)
    want = [s.strip() for s in args.only.split(",") if s.strip()]
    failed = []
    for name in want:
        try:
            if name == "persuade":
                got = persuade_extra_rows(cfg["persuade_extra_native"], cfg["persuade_extra_ell"])
            elif name == "arxiv":
                got = arxiv_rows(cfg["arxiv"], args.refresh)
            elif name == "wikipedia":
                got = wiki_rows(cfg["wikipedia"], args.refresh)
            elif name == "amazon-reviews":
                got = amazon_rows(cfg["amazon_reviews"], args.refresh)
            elif name == "stackexchange":
                got = se_rows(cfg["stackexchange"], args.refresh)
            elif name == "reddit":
                got = reddit_rows(cfg["reddit"], args.refresh)
            else:
                raise SystemExit(f"unknown source {name}; choose from {FETCHERS}")
        except (OSError, ValueError, KeyError) as e:  # network or API trouble: keep the others
            print(f"{name}: FAILED ({e}); keeping its previous rows ({len(existing.get(name, []))})", flush=True)
            failed.append(name)
            continue
        # growing a source keeps the rows already in use (their matched AI rows and splits stay
        # valid) and only tops up with new picks
        kept = existing.get(name, [])
        if name != "persuade" and kept:
            ids = {r["id"] for r in kept}
            got = kept + [r for r in got if r["id"] not in ids][:max(0, len(got) - len(kept))]
        existing[name] = got
        print(f"{name}: {len(got)} rows", flush=True)
        save(out_path, existing)
    save(out_path, existing)
    if failed:
        raise SystemExit(f"failed sources: {failed} (rerun later; caches make reruns cheap)")


def save(out_path: Path, existing: dict[str, list[dict]]) -> None:
    rows = [r for name in sorted(existing) for r in existing[name]]
    seen, unique = set(), []
    for r in rows:
        key = re.sub(r"\s+", " ", r["text"]).strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(r)
    ids = [r["id"] for r in unique]
    assert len(ids) == len(set(ids)), "duplicate ids"
    write_jsonl(out_path, unique)
    print(f"wrote {len(unique)} rows -> {out_path}: {dict(Counter(r['source'] for r in unique))}", flush=True)


if __name__ == "__main__":
    main()
