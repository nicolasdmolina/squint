# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Download and sample the human (pre-ChatGPT) texts for the Squint tuning set.

Writes calibration/data/human_base.jsonl: one row per *base* document (before length
variants), plus a small reserve of essays used only for mixed human/AI documents.

Sources (all written before ChatGPT's release on 2022-11-30; licences in README.md):
  persuade          PERSUADE 2.0 (grades 6-12, US), streamed from the authors' Google Drive
                    CSV (588 MB, never stored; only the sample is kept)
  ellipse           ELLIPSE corpus (English language learners, grades 8-12)
  toefl91           91 TOEFL practice essays (Liang et al. 2023, year <= 2020)
  ghostbuster-news  Reuters 50-50 news articles (1996-97) via the Ghostbuster data release
  ghostbuster-wp    r/WritingPrompts stories scraped Oct 2022 via the Ghostbuster data release

Usage: uv run calibration/fetch_human.py [--refresh]
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA_DIR, normalize_text, sentence_spans, stable_hash, word_count, write_jsonl  # noqa: E402

N_PERSUADE_STUDENT = 200
N_PERSUADE_ELL = 60
N_PERSUADE_MIX = 45
N_ELLIPSE = 200
N_ELLIPSE_MIX = 15
N_NEWS = 100
N_WP = 100
MAX_WORDS = 2400

PERSUADE_URL = ("https://drive.usercontent.google.com/download?"
                "id=13phHyDzIsb0MHyJr6q-B-qIa9P2tM135&export=download&confirm=t")
ELLIPSE_URL = "https://raw.githubusercontent.com/scrosseye/ELLIPSE-Corpus/main/ELLIPSE_Final_github_train.csv"
TOEFL_URL = ("https://raw.githubusercontent.com/Weixin-Liang/ChatGPT-Detector-Bias/main/"
             "Data_and_Results/Human_Data/TOEFL_real_91/data.json")
GB_RAW = "https://raw.githubusercontent.com/vivek3141/ghostbuster-data/master"
GB_API = "https://api.github.com/repos/vivek3141/ghostbuster-data/contents"

RAW_DIR = DATA_DIR / "raw"
UA = {"User-Agent": "squint-calibration/1.0 (private research)"}


def fetch(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


FIRST_NAMES = ["Maria", "James", "Ashley", "Carlos", "Emily", "David", "Jasmine", "Michael", "Sofia", "Kevin"]
TEACHERS = ["Mr. Smith", "Mrs. Johnson", "Ms. Garcia", "Mr. Brown", "Mrs. Davis"]
CITIES = ["Springfield", "Greenville", "Riverside", "Fairview", "Madison"]
SCHOOLS = ["Lincoln", "Washington", "Roosevelt", "Jefferson", "Franklin"]
_PLACEHOLDER = re.compile(r"\b(Generic_Name|Genric_Name|STUDENT_NAME|PROPER_NAME|TEACHER_NAME|Generic_City|"
                          r"LOCATION_NAME|Generic_School|SCHOOL_NAME|Generic_School_Name)\b")


def fill_placeholders(text: str, uid: str) -> tuple[str, bool]:
    """PERSUADE/ELLIPSE replace names with tokens like Generic_Name. Those tokens are rare
    strings a language model finds surprising, which would make the human essays look more
    human than real ones. Swap in ordinary names, consistently within an essay."""
    h = stable_hash("names", uid)
    pick = {
        "name": FIRST_NAMES[h % len(FIRST_NAMES)], "teacher": TEACHERS[h % len(TEACHERS)],
        "city": CITIES[h % len(CITIES)], "school": SCHOOLS[h % len(SCHOOLS)],
    }
    kind = {"Generic_Name": "name", "Genric_Name": "name", "STUDENT_NAME": "name", "PROPER_NAME": "name",
            "TEACHER_NAME": "teacher", "Generic_City": "city", "LOCATION_NAME": "city",
            "Generic_School": "school", "SCHOOL_NAME": "school", "Generic_School_Name": "school"}
    new, n = _PLACEHOLDER.subn(lambda m: pick[kind[m.group(1)]], text)
    return new, n > 0


def ok_len(text: str) -> bool:
    return 20 <= word_count(text) <= MAX_WORDS


def pick_balanced(items: list[dict], key: str, n: int, salt: str) -> list[dict]:
    """Round-robin over strata (sorted by name), lowest stable hash first -> deterministic,
    near-uniform across prompts."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        groups[it[key]].append(it)
    for g in groups.values():
        g.sort(key=lambda it: stable_hash(salt, it["_uid"]))
    out: list[dict] = []
    order = sorted(groups)
    i = 0
    while len(out) < n and any(groups.values()):
        g = groups[order[i % len(order)]]
        if g:
            out.append(g.pop(0))
        i += 1
    return out


# --- PERSUADE ----------------------------------------------------------------------------

def load_persuade() -> list[dict]:
    cache = RAW_DIR / "persuade_essays.jsonl.gz"
    if cache.exists():
        with gzip.open(cache, "rt", encoding="utf-8") as f:
            return [json.loads(l) for l in f]
    print("streaming PERSUADE 2.0 CSV (~588 MB, not stored)...", flush=True)
    csv.field_size_limit(sys.maxsize)
    req = urllib.request.Request(PERSUADE_URL, headers=UA)
    essays: dict[str, dict] = {}
    with urllib.request.urlopen(req, timeout=600) as resp:
        reader = csv.DictReader(io.TextIOWrapper(resp, encoding="utf-8", errors="replace", newline=""))
        for i, row in enumerate(reader):
            eid = row["essay_id_comp"]
            if eid in essays:
                continue
            essays[eid] = {
                "_uid": eid,
                "text": row["full_text"],
                "prompt_name": row["prompt_name"],
                "assignment": row["assignment"],
                "ell_status": row["ell_status"],
                "grade_level": row["grade_level"],
                "task": row["task"],
                "holistic_score": row["holistic_essay_score"],
            }
            if i % 50000 == 0:
                print(f"  rows {i}, essays {len(essays)}", flush=True)
    rows = list(essays.values())
    # keep a compact local cache of the essays only (much smaller than the CSV)
    with gzip.open(cache, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  PERSUADE essays: {len(rows)}")
    return rows


def persuade_rows() -> list[dict]:
    essays = load_persuade()
    for e in essays:
        e["text"], e["filled"] = fill_placeholders(normalize_text(e["text"]), e["_uid"])
    essays = [e for e in essays if ok_len(e["text"])]
    native = [e for e in essays if e["ell_status"].strip().lower() == "no"]
    # ELLIPSE re-uses ~450 PERSUADE ELL essays; keep the two sources disjoint
    ellipse_path = RAW_DIR / "ellipse_train.csv"
    if not ellipse_path.exists():
        ellipse_path.write_bytes(fetch(ELLIPSE_URL))
    ellipse_ids = {r["text_id_kaggle"].upper() for r in csv.DictReader(
        io.StringIO(ellipse_path.read_text(encoding="utf-8", errors="replace")))}
    ell = [e for e in essays if e["ell_status"].strip().lower() == "yes" and e["_uid"].upper() not in ellipse_ids]
    print(f"  PERSUADE usable: native {len(native)}, ELL {len(ell)}")
    student = pick_balanced(native, "prompt_name", N_PERSUADE_STUDENT + N_PERSUADE_MIX, "persuade-native")
    # mixed reserve: spread across prompts too (every 5th pick until filled)
    mix = pick_balanced(student, "prompt_name", N_PERSUADE_MIX, "persuade-mix")
    mix_ids = {m["_uid"] for m in mix}
    student = [s for s in student if s["_uid"] not in mix_ids]
    ell_pick = pick_balanced(ell, "prompt_name", N_PERSUADE_ELL, "persuade-ell")
    out = []
    for role, subset, group in (("pure", "student", student), ("mixed_reserve", "student", mix),
                                ("pure", "non_native", ell_pick)):
        for e in group:
            out.append({
                "id": f"persuade-{e['_uid'].lower()}",
                "text": e["text"], "label": "human", "source": "persuade", "subset": subset,
                "prompt_id": f"persuade:{slug(e['prompt_name'])}",
                "prompt_text": e["assignment"], "topic": e["prompt_name"], "role": role,
                "meta": {"grade": e["grade_level"], "ell_status": e["ell_status"], "task": e["task"],
                         "holistic_score": e["holistic_score"], "placeholders_filled": e["filled"]},
            })
    return out


# --- ELLIPSE -----------------------------------------------------------------------------

def ellipse_rows() -> list[dict]:
    path = RAW_DIR / "ellipse_train.csv"
    if not path.exists():
        path.write_bytes(fetch(ELLIPSE_URL))
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8", errors="replace"))))
    items = []
    for r in rows:
        t, filled = fill_placeholders(normalize_text(r["full_text"]), r["text_id_kaggle"])
        if ok_len(t):
            items.append({"_uid": r["text_id_kaggle"], "text": t, "prompt": r["prompt"], "filled": filled,
                          "grade": r["grade"], "overall": r["Overall"], "task": r["task"]})
    picked = pick_balanced(items, "prompt", N_ELLIPSE + N_ELLIPSE_MIX, "ellipse")
    mix = pick_balanced(picked, "prompt", N_ELLIPSE_MIX, "ellipse-mix")
    mix_ids = {m["_uid"] for m in mix}
    out = []
    for e in picked:
        out.append({
            "id": f"ellipse-{e['_uid']}", "text": e["text"], "label": "human", "source": "ellipse",
            "subset": "non_native", "prompt_id": f"ellipse:{slug(e['prompt'])}", "prompt_text": None,
            "topic": e["prompt"], "role": "mixed_reserve" if e["_uid"] in mix_ids else "pure",
            "meta": {"grade": e["grade"], "overall_proficiency": e["overall"], "task": e["task"],
                     "placeholders_filled": e["filled"]},
        })
    return out


# --- TOEFL91 -----------------------------------------------------------------------------

def toefl_rows() -> list[dict]:
    path = RAW_DIR / "toefl91.json"
    if not path.exists():
        path.write_bytes(fetch(TOEFL_URL))
    docs = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for i, d in enumerate(docs):
        t = normalize_text(d["document"])
        if ok_len(t):
            out.append({"id": f"toefl91-{i:03d}", "text": t, "label": "human", "source": "toefl91",
                        "subset": "non_native", "prompt_id": f"toefl91:{i:03d}", "prompt_text": None,
                        "topic": None, "role": "pure", "meta": {}})
    return out


# --- Ghostbuster: Reuters news and WritingPrompts ---------------------------------------

def gh_list(path: str) -> list[dict]:
    return json.loads(fetch(f"{GB_API}/{path}"))


def lead_sentence(text: str) -> str:
    spans = sentence_spans(text)
    return text[spans[0][0]:spans[0][1]] if spans else text[:300]


def news_rows() -> list[dict]:
    cache = RAW_DIR / "ghostbuster_news.json"
    if cache.exists():
        picked = json.loads(cache.read_text(encoding="utf-8"))
    else:
        authors = sorted(d["name"] for d in gh_list("reuter/human") if d["type"] == "dir")
        cands = [{"_uid": f"{a}-{n}", "author": a, "n": n} for a in authors for n in range(1, 21)]
        picked = pick_balanced(cands, "author", N_NEWS + 40, "news")  # spare for short/failed files
        for c in picked:
            c["text"] = fetch(f"{GB_RAW}/reuter/human/{c['author']}/{c['n']}.txt").decode("utf-8", "replace")
        cache.write_text(json.dumps(picked, ensure_ascii=False), encoding="utf-8")
    out = []
    for c in picked:
        t = normalize_text(c["text"])
        if not ok_len(t) or len(out) >= N_NEWS:
            continue
        out.append({"id": f"gbnews-{c['_uid'].lower()}", "text": t, "label": "human",
                    "source": "ghostbuster-news", "subset": "general",
                    "prompt_id": f"news:{c['_uid'].lower()}", "prompt_text": lead_sentence(t),
                    "topic": "news", "role": "pure", "meta": {"author": c["author"]}})
    return out


def wp_rows() -> list[dict]:
    cache = RAW_DIR / "ghostbuster_wp.json"
    if cache.exists():
        picked = json.loads(cache.read_text(encoding="utf-8"))
    else:
        names = [d["name"] for d in gh_list("wp/human") if d["name"].endswith(".txt")]
        cands = [{"_uid": n[:-4], "k": "all"} for n in names]
        cands.sort(key=lambda c: stable_hash("wp", c["_uid"]))
        picked = cands[: N_WP + 40]
        for c in picked:
            c["text"] = fetch(f"{GB_RAW}/wp/human/{c['_uid']}.txt").decode("utf-8", "replace")
            c["prompt"] = fetch(f"{GB_RAW}/wp/prompts/{c['_uid']}.txt").decode("utf-8", "replace").strip()
        cache.write_text(json.dumps(picked, ensure_ascii=False), encoding="utf-8")
    out = []
    for c in picked:
        t = normalize_text(c["text"])
        if not ok_len(t) or len(out) >= N_WP:
            continue
        out.append({"id": f"gbwp-{c['_uid']}", "text": t, "label": "human", "source": "ghostbuster-wp",
                    "subset": "general", "prompt_id": f"wp:{c['_uid']}", "prompt_text": c["prompt"],
                    "topic": "creative", "role": "pure", "meta": {}})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="ignore cached raw downloads")
    args = ap.parse_args()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if args.refresh:
        for p in RAW_DIR.iterdir():
            p.unlink()
    rows = []
    for name, fn in (("persuade", persuade_rows), ("ellipse", ellipse_rows), ("toefl91", toefl_rows),
                     ("ghostbuster-news", news_rows), ("ghostbuster-wp", wp_rows)):
        got = fn()
        print(f"{name}: {len(got)} rows", flush=True)
        rows.extend(got)
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "duplicate ids"
    seen, unique = set(), []
    for r in rows:  # exact duplicate texts (e.g. one TOEFL essay appears twice)
        key = re.sub(r"\s+", " ", r["text"]).strip().lower()
        if key in seen:
            print(f"dropping duplicate text {r['id']}")
            continue
        seen.add(key)
        unique.append(r)
    rows = unique
    n = write_jsonl(DATA_DIR / "human_base.jsonl", rows)
    print(f"wrote {n} human base docs -> {DATA_DIR / 'human_base.jsonl'}")


if __name__ == "__main__":
    main()
