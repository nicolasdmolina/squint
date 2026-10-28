# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""AI writing for the classifier, through the same CLI driver as calibration.

  uv run classifier/generate.py plan                         # (re)build classifier/generated/plan.jsonl
  uv run classifier/generate.py run --source chatgpt [--limit-calls 600] [--deadline EPOCH]

The CLI calls, batching, acceptance checks, backoff, auth/usage-limit stops and status records
are calibration/generate_ai.py's; this file only writes a bigger plan and points the driver at
classifier/generated/. It never logs in or touches credentials.

The plan is append-only: items already in plan.jsonl keep their ids, so a night's run resumes
where the last one stopped and finished pieces stay joined to their plan item. Items:
  matched     one per human document of the new sources (arXiv abstract from the title,
              encyclopedia section from the article title, product review from the review title
              and polarity, forum answer from the question), plus more news and stories from the
              calibration leads that the calibration plan did not use
  student     "write it the way a real grade-N student would" on PERSUADE and ELLIPSE topics
  nonnative   "write as an English learner" on PERSUADE topics and TOEFL questions
  learner     "write as a CEFR A2/B1/B2 learner whose first language is X" on PERSUADE and ELLIPSE
              topics, varied in task type; added 2026-10-16 because Claude imitating a B1 learner
              got past the classifier about a third of the time (reports/2026-10-16-fresh-check.md)
  casual      quick casual replies (forum comment / message register)
  paraphrase  an existing AI piece, paraphrased or "humanized" (rewritten to sound human);
              it keeps its origin's group, so it always lands in the origin's split
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clf_common import CAL_DATA, CAL_GEN, DATA_DIR, GEN_DIR, load_config  # noqa: E402
from common import read_jsonl, stable_hash, word_count, write_jsonl  # noqa: E402

import generate_ai as g  # noqa: E402  (calibration/generate_ai.py)

SEED = "squint-clf-plan"
GRADES = (6, 7, 8, 9, 10, 11, 12)
L1S = ("Spanish", "Mandarin Chinese", "Arabic", "Vietnamese", "Korean", "Portuguese", "Hindi", "Japanese")
PARAPHRASE_STYLES = (
    "Paraphrase the following text. Keep its meaning, length and paragraphing, but change the wording "
    "throughout.",
    "Rewrite the following text so it reads as if a person wrote it, not an AI: vary the sentence "
    "lengths, drop stock phrases and tidy transitions, keep the content and roughly the length.",
    "Rewrite the following so it sounds like a real student wrote it quickly: plainer words, less "
    "polish, the same points and roughly the same length.",
)

# prompt_id prefix -> the human source whose prompts the item mirrors (used by the split)
FAMILY_OF_PREFIX = {"persuade": "persuade", "ellipse": "ellipse", "toefl-style": "toefl91", "toefl91": "toefl91",
                    "news": "ghostbuster-news", "wp": "ghostbuster-wp", "arxiv": "arxiv", "wiki": "wikipedia",
                    "review": "amazon-reviews", "forum": "stackexchange", "reddit": "reddit",
                    "blog": "blogs"}


def family_of(prompt_id: str) -> str:
    return FAMILY_OF_PREFIX.get(prompt_id.split(":", 1)[0], "other")


def h8(*parts) -> str:
    return f"{stable_hash(*parts, seed=SEED) & 0xFFFFFFFF:08x}"


def about(n: int) -> int:
    return max(20, int(round(n / 10.0)) * 10)


def item(gen: str, variant: str, kind: str, subset: str, prompt_id: str, instruction: str, register: str,
         key: str, target: int | None = None, origin_id: str | None = None) -> dict:
    fam = family_of(prompt_id)
    return {"id": f"{gen}-x{variant[:3]}-{h8(gen, variant, key)}", "source": gen, "kind": kind, "subset": subset,
            "prompt_id": prompt_id, "instruction": instruction, "register": register, "role": "pure",
            "target_words": target, "mix_with": None, "family": fam, "variant": variant, "origin_id": origin_id}


def matched_items(gen: str, extra: list[dict], cal_human: list[dict]) -> list[dict]:
    out = []
    for h in sorted(extra, key=lambda h: h["id"]):
        n = word_count(h["text"])
        src, t = h["source"], h.get("prompt_text")
        if src == "arxiv":
            out.append(item(gen, "matched", "abstract", "academic", h["prompt_id"],
                            f"Write the abstract (about {about(n)} words, one paragraph) for a research paper "
                            f"titled \"{t}\".", "abstract", h["id"], about(n)))
        elif src == "wikipedia":
            out.append(item(gen, "matched", "encyclopedic", "encyclopedic", h["prompt_id"],
                            f"Write the opening section of an encyclopedia article about \"{t}\", about "
                            f"{about(max(n, 150))} words, in a neutral encyclopedic tone.", "encyclopedic",
                            h["id"], about(max(n, 150))))
        elif src == "amazon-reviews":
            pol = h.get("topic") or "positive"
            tgt = min(about(n), 140)
            out.append(item(gen, "matched", "short", "review", h["prompt_id"],
                            f"Write a {pol} customer review of a product, as posted on Amazon, under the review "
                            f"title \"{t}\". About {tgt} words; give only the review text.", "review", h["id"], tgt))
            out.append(item(gen, "casual", "short", "review", h["prompt_id"],
                            f"Write a quick, casual {pol} Amazon review titled \"{t}\", the way an ordinary "
                            f"shopper types one on their phone (about {min(tgt, 80)} words). Only the review text.",
                            "review", h["id"], min(tgt, 80)))
        elif src == "stackexchange":
            site = h.get("topic") or "a Q&A"
            long_ = n >= 150
            tgt = min(about(n), 400) if long_ else min(about(n), 140)
            out.append(item(gen, "matched", "forum" if long_ else "short", "forum", h["prompt_id"],
                            f"Write an answer (about {tgt} words) to this question posted on the {site} Stack "
                            f"Exchange site: \"{t}\"", "forum", h["id"], tgt))
            if stable_hash("casual", gen, h["id"], seed=SEED) % 2 == 0:
                out.append(item(gen, "casual", "short", "forum", h["prompt_id"],
                                f"Reply to this question the way someone would in a quick, casual forum comment "
                                f"(2-5 sentences, conversational): \"{t}\"", "casual", h["id"], 70))
        elif src == "reddit":
            sub = h.get("topic") or "AskReddit"
            tgt = min(about(n), 400)
            out.append(item(gen, "matched", "forum" if tgt >= 150 else "short", "personal", h["prompt_id"],
                            f"Write a Reddit post or comment for r/{sub} (about {tgt} words), in the first person, "
                            f"that gets across this: \"{t}\". Write it the way a regular user types it, and give "
                            f"only the post text.", "personal", h["id"], tgt))
        elif src == "blogs":
            field = h.get("topic")
            who = f"someone who works in {field.lower()}" if field and field != "Student" else \
                "a student" if field == "Student" else "an ordinary person"
            tgt = min(about(n), 400)
            out.append(item(gen, "matched", "blog" if tgt >= 150 else "short", "personal", h["prompt_id"],
                            f"Write an entry (about {tgt} words) for your own personal blog, in the first person, "
                            f"as {who} writing about their own life. Write about what this opening line is "
                            f"about, in your own words without repeating it: \"{t}\". Write it as one single "
                            f"paragraph with no line breaks, and give only the entry text.", "personal",
                            h["id"], tgt))
    # news and stories from calibration leads the calibration plan did not use for this generator
    cal_plan_pids = {p["prompt_id"] for p in read_jsonl(CAL_GEN / "plan.jsonl")
                     if p["source"] == gen} if (CAL_GEN / "plan.jsonl").exists() else set()
    for src, k in (("ghostbuster-news", 70), ("ghostbuster-wp", 70)):
        pool = sorted([h for h in cal_human if h["source"] == src and h["role"] == "pure"
                       and h["prompt_id"] not in cal_plan_pids], key=lambda h: stable_hash("lead", gen, h["id"], seed=SEED))
        for i, h in enumerate(pool[:k]):
            n = (300, 450, 600)[i % 3]
            if src == "ghostbuster-news":
                ins = (f"Write a news article of about {n} words, in your own words, reporting the story summed up "
                       f"by this lead: \"{h['prompt_text']}\"")
                out.append(item(gen, "matched", "news", "general", h["prompt_id"], ins, "news", h["id"], n))
            else:
                ins = f"Write a story of about {n} words for this writing prompt: {h['prompt_text']}"
                out.append(item(gen, "matched", "creative", "general", h["prompt_id"], ins, "creative", h["id"], n))
    return out


def student_items(gen: str, cal_human: list[dict]) -> list[dict]:
    out = []
    persuade = {}
    for h in cal_human:
        if h["source"] == "persuade":
            persuade.setdefault(h["prompt_id"], (h["topic"], h["prompt_text"]))
    for pid, (topic, assignment) in sorted(persuade.items()):
        for v in range(8):
            grade = GRADES[stable_hash("grade", gen, pid, v, seed=SEED) % len(GRADES)]
            n = (200, 300, 400, 500)[v % 4]
            ins = (f"Write this essay the way a typical grade-{grade} student would actually write it for "
                   f"class: plain vocabulary, uneven paragraphs, a few small mistakes, no polished "
                   f"transitions. About {n} words.\n\nAssignment: {assignment}")
            out.append(item(gen, "student", "essay", "student", pid, ins, "student_essay", f"{pid}|{v}", n))
        for v in range(3):
            l1 = L1S[stable_hash("l1", gen, pid, v, seed=SEED) % len(L1S)]
            q = assignment if len(assignment) < 500 else topic
            ins = (f"Write an essay (about 300 words) as a high-school English learner whose first language is "
                   f"{l1} would write it: simple sentences, some grammar and word-choice errors, but clear "
                   f"ideas.\n\nAssignment: {q}")
            out.append(item(gen, "nonnative", "essay", "non_native", pid, ins, "student_essay", f"{pid}|nn{v}", 300))
    ell_topics = sorted({h["topic"] for h in cal_human if h["source"] == "ellipse"})
    for topic in ell_topics:
        a = g.ELLIPSE_ASSIGNMENTS.get(topic, f"Write about: {topic}.")
        pid = "ellipse:" + re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")  # as generate_ai.ell_pid
        for v in range(2):
            grade = GRADES[stable_hash("ell-grade", gen, topic, v, seed=SEED) % len(GRADES)]
            ins = (f"Write a student essay (about {(250, 350)[v]} words) the way a real grade-{grade} student "
                   f"would write it, not a polished model answer. Prompt: {a}")
            out.append(item(gen, "student", "essay", "non_native", pid, ins, "student_essay", f"{topic}|{v}",
                            (250, 350)[v]))
    for qi, q in enumerate(g.TOEFL_QUESTIONS):
        l1 = L1S[stable_hash("toefl-l1", gen, qi, seed=SEED) % len(L1S)]
        ins = (f"Answer this TOEFL writing question in about 120 words, as a test taker whose first language is "
               f"{l1} would: {q}")
        out.append(item(gen, "nonnative", "short", "non_native", f"toefl-style:q{qi:02d}", ins, "short_answer",
                        f"toefl|{qi}", 120))
    return out


LEVELS = (
    ("A2", "short simple sentences, a small vocabulary, frequent grammar mistakes (verb forms, articles, "
           "plurals) and some spelling mistakes"),
    ("B1", "mostly simple sentences with some longer ones, everyday vocabulary used a little wrongly at "
           "times, regular grammar and spelling mistakes, and ideas that are clear but not well organised"),
    ("B2", "generally correct but plain writing with occasional errors in prepositions, articles and word "
           "choice, a few awkward phrases translated from the first language"),
)
LEARNER_FORMS = ("an essay for English class", "a short opinion piece for a school website",
                 "an answer in an English exam", "a letter to the school principal")


def learner_items(gen: str, cal_human: list[dict]) -> list[dict]:
    """English learners at a given CEFR level and first language. ELLIPSE topics land in the held-out
    split (family ellipse), so the evaluation measures these on prompts the model never trained on."""
    out = []
    topics = {}
    for h in cal_human:
        if h["source"] == "persuade":
            topics.setdefault(h["prompt_id"], h["prompt_text"] if len(h["prompt_text"]) < 500 else h["topic"])
    for topic in sorted({h["topic"] for h in cal_human if h["source"] == "ellipse"}):
        pid = "ellipse:" + re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
        topics.setdefault(pid, g.ELLIPSE_ASSIGNMENTS.get(topic, f"Write about: {topic}."))
    for pid, task in sorted(topics.items()):
        for v in range(6 if pid.startswith("persuade") else 2):
            h = stable_hash("learner", gen, pid, v, seed=SEED)
            level, how = LEVELS[h % len(LEVELS)]
            l1 = L1S[(h >> 8) % len(L1S)]
            form = LEARNER_FORMS[(h >> 16) % len(LEARNER_FORMS)]
            n = (150, 200, 250, 300)[(h >> 24) % 4]
            ins = (f"Write {form} (about {n} words) exactly as a real {level}-level English learner whose first "
                   f"language is {l1} would write it: {how}. Do not write a polished answer and do not "
                   f"exaggerate the mistakes.\n\nTask: {task}")
            out.append(item(gen, "learner", "essay", "non_native", pid, ins, "student_essay", f"{pid}|lea{v}", n))
    return out


def paraphrase_items(gen: str, pool: list[dict], have: int, limit: int) -> list[dict]:
    out = []
    pool = sorted(pool, key=lambda r: stable_hash("para", gen, r["id"], seed=SEED))
    for r in pool:
        if have + len(out) >= limit:
            break
        n = word_count(r["text"])
        if n < 40 or n > 900:
            continue
        style = PARAPHRASE_STYLES[stable_hash("style", gen, r["id"], seed=SEED) % len(PARAPHRASE_STYLES)]
        ins = f"{style}\n\nText:\n{r['text']}"
        kind = "paraphrase" if n >= 140 else "short"
        out.append(item(gen, "paraphrase", kind, r.get("subset") or "general", r["prompt_id"], ins,
                        r.get("register") or "paraphrase", r["id"], min(n, 170) if kind == "short" else n,
                        origin_id=r["id"]))
    return out


def ai_pool() -> list[dict]:
    """Accepted pure AI pieces from calibration and from this pipeline (paraphrase origins)."""
    rows = []
    for d in (CAL_GEN, GEN_DIR):
        for p in sorted(d.glob("ai_*.jsonl")):
            rows += [r for r in read_jsonl(p) if r.get("role") == "pure" and "-xpar-" not in r["id"]]
    return rows


def build_plan(existing: list[dict], cfg: dict) -> list[dict]:
    cal_human = read_jsonl(CAL_DATA / "human_base.jsonl")
    extra_path = DATA_DIR / "human_extra.jsonl"
    extra = [h for h in read_jsonl(extra_path) if h["source"] != "persuade"] if extra_path.exists() else []
    have = {it["id"] for it in existing}
    plan = list(existing)
    pool = ai_pool()
    for gen in g.SOURCES:
        new = matched_items(gen, extra, cal_human) + student_items(gen, cal_human) + learner_items(gen, cal_human)
        plan += [it for it in new if it["id"] not in have]
        have |= {it["id"] for it in new}
        n_para = sum(1 for it in plan if it["source"] == gen and it["variant"] == "paraphrase")
        para = [it for it in paraphrase_items(gen, pool, n_para, cfg["generate"]["paraphrase_per_generator"])
                if it["id"] not in have]
        plan += para
        have |= {it["id"] for it in para}
    ids = [it["id"] for it in plan]
    assert len(ids) == len(set(ids)), "duplicate plan ids"
    return plan


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan")
    r = sub.add_parser("run")
    r.add_argument("--source", required=True, choices=g.SOURCES)
    r.add_argument("--limit-calls", type=int, default=None, help="default: the per-night cap in config.toml")
    r.add_argument("--max-rounds", type=int, default=None)
    r.add_argument("--deadline", type=float, default=None, help="unix time; no new call starts after it")
    args = ap.parse_args()
    cfg = load_config()
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    plan_path = GEN_DIR / "plan.jsonl"
    if args.cmd == "plan":
        existing = read_jsonl(plan_path) if plan_path.exists() else []
        plan = build_plan(existing, cfg)
        write_jsonl(plan_path, plan)
        print(json.dumps({f"{s}|{v}": n for (s, v), n in sorted(Counter((p["source"], p["variant"]) for p in plan).items())}))
        print(f"wrote {len(plan)} planned items ({len(plan) - len(existing)} new) -> {plan_path}")
        return
    if not plan_path.exists():
        raise SystemExit("no plan yet: run `generate.py plan` first")

    def on_term(signum, frame):  # unwinds out of subprocess.run, which then kills the CLI child
        raise SystemExit(75)

    signal.signal(signal.SIGTERM, on_term)
    cap = args.limit_calls if args.limit_calls is not None else cfg["generate"]["caps"].get(args.source)
    rounds = args.max_rounds or cfg["generate"]["max_rounds"]
    margin = 60.0  # do not start a call in the last minute before the deadline

    def should_stop() -> bool:
        return args.deadline is not None and time.time() > args.deadline - margin

    g.run_source(args.source, cap, rounds, gen_dir=GEN_DIR, should_stop=should_stop)


if __name__ == "__main__":
    main()
