# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Generate the AI side of the Squint tuning set through Nicky's own CLI logins.

  chatgpt -> `codex exec`   (ChatGPT login; whatever model codex's config defaults to)
  claude  -> `claude -p`    (Claude Code login; default model, all tools disabled)
  gemini  -> `gemini -p`    (Gemini CLI login; default model)

Every item mirrors a human prompt/topic (same `prompt_id`). Several pieces are requested
per call as JSON to save quota. Calls are sequential per source, with backoff. Raw call
records go to calibration/generated/<source>/; accepted pieces to generated/ai_<source>.jsonl.
The run is resumable: finished ids are skipped. An auth failure stops that source and is
recorded in generated/status.json; this script never logs in or touches credentials.

Usage:
  uv run calibration/generate_ai.py plan                      # write generated/plan.jsonl
  uv run calibration/generate_ai.py run --source chatgpt      # generate (resumable)
  uv run calibration/generate_ai.py run --source claude --limit-calls 2
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA_DIR, GEN_DIR, iter_chunks, read_jsonl, stable_hash, word_count, write_jsonl  # noqa: E402

SOURCES = ("chatgpt", "claude", "gemini")
CLI = {
    "chatgpt": os.environ.get("SQUINT_CODEX", str(Path.home() / ".local/bin/codex")),
    "claude": os.environ.get("SQUINT_CLAUDE", str(Path.home() / ".local/bin/claude")),
    "gemini": os.environ.get("SQUINT_GEMINI", str(Path.home() / ".local/node/bin/gemini")),
}
LONG_BATCH = 5
SHORT_BATCH = 15
# kinds whose prompts carry a whole text (paraphrase / "humanize" requests) get smaller batches
KIND_BATCH = {"paraphrase": 3}
# long kinds in batching order; kinds from other plans (classifier/) follow, sorted
LONG_KIND_ORDER = ("essay", "news", "creative", "blog")
CALL_TIMEOUT_S = 900
BACKOFF_S = (30, 120, 300)
# subscription usage limits: stop the source instead of retrying into the wall
LIMIT_PATTERNS = re.compile(
    r"hit your (session|usage|weekly) limit|usage limit|rate[ _-]?limit(ed)?|quota|"
    r"api_error_status\"?:\s*429|too many requests|resets? (at )?\d", re.I)
AUTH_PATTERNS = re.compile(
    r"IneligibleTier|not logged in|please log ?in|login required|run .*login|unauthori[sz]ed|"
    r"invalid api key|authentication (failed|required)|Error authenticating|OAuth token", re.I)

# ---------------------------------------------------------------------------------------
# Prompts. ELLIPSE ships only topic names, so these are short paraphrased assignments.

ELLIPSE_ASSIGNMENTS = {
    "Distance learning": "Some schools let students attend classes from home through online or video classes. Would students benefit from distance learning? Take a position and support it.",
    "Career commitment": "Some people think students should commit to a career at a young age, such as in high school. Do you agree or disagree?",
    "Success and failure": "Winston Churchill said that success consists of going from failure to failure without loss of enthusiasm. What role does failure play in success?",
    "Being busy": "Some people believe staying busy all the time is the best way to get things done; others think it is important to take time to relax. Which is better?",
    "Positive attitudes": "Is a positive attitude the key to success in life? Explain your view.",
    "Impact of technology": "Has technology had a positive or a negative effect on people's lives? Explain your opinion.",
    "Trying something beyond what you have mastered": "Ralph Waldo Emerson wrote, 'Unless you try to do something beyond what you have already mastered, you will never grow.' Do you agree?",
    "First impressions": "Are first impressions almost impossible to change? Take a position and explain.",
    "Three-year high school program": "Some schools let students graduate from high school in three years by taking classes in the summer and evenings. Is this a good idea?",
    "Individuality": "'To be yourself in a world that is constantly trying to make you something else is the greatest accomplishment.' Do you agree?",
    "Four-day work week": "Some businesses use a four-day work week with longer days. Should schools adopt a four-day week too?",
    "Working with a group or alone": "Do students learn more when they work in groups or when they work alone? Explain.",
    "Self-reliance": "Is it better to rely on yourself to make decisions, or to seek guidance from experts and people with authority?",
    "Lunch menus": "Your principal wants to change the school lunch menu to healthier food. Write a letter to the principal giving your opinion.",
    "Influences of character": "Do people form their character from outside influences, or do they choose their own character traits? Explain.",
    "Extended school day": "Some schools are thinking about making the school day two hours longer. Do you agree with this idea?",
    "Year-round school": "Should students go to school all year with shorter breaks instead of a long summer vacation?",
    "Influencing behavior": "Is setting a good example the best way to influence how other people behave?",
    "Cell phones in classrooms": "Should students be allowed to use their phones in class for learning?",
    "Internships and shadowing": "Should high school students have to complete an internship or job shadowing before they graduate?",
    "Enjoyable educational activities": "Describe learning activities that are both fun and useful, and explain why they work.",
    "Praising student work": "Should teachers praise students' work even when it is not their best, to build their self-esteem?",
    "Afterschool homework club": "Should schools require students to attend an after-school homework club?",
    "Imagination": "Albert Einstein said that imagination is more important than knowledge. Do you agree?",
    "Curfews for teenagers": "Some towns have curfews that keep teenagers at home at night. Are curfews a good idea?",
    "Spending time outdoors": "Do young people spend enough time outdoors? Explain the benefits of spending time outside.",
    "Controlling extracurricular involvement": "Should schools limit how many extracurricular activities a student can join?",
    "Seeking multiple opinions": "When people ask for advice, they often talk to more than one person. Why can seeking multiple opinions help someone make a better choice?",
    "Creative arts requirement": "Should high school students be required to take at least one class in the arts, such as music, drama or painting?",
    "Community service": "Should students be required to do community service?",
    "Places to visit": "Describe a place you think everyone should visit and explain why.",
    "Letter to employer": "Write a letter to a possible employer explaining why you would be a good person to hire for a summer job.",
    "Cell phones at school": "Should students be allowed to bring cell phones to school?",
    "Talents and skills": "Is it better to focus on developing one talent or to learn many different skills?",
    "Mandatory extracurricular activities": "Your principal has decided that every student must take part in at least one extracurricular activity. Do you agree?",
    "Lessons with elementary school students": "Should older students spend time teaching or tutoring younger elementary school students?",
    "Grades for extracurricular activities": "Should students need at least a B average to take part in sports and other extracurricular activities?",
    "Future accomplishments": "What do you hope to accomplish in the next ten years, and how will you do it?",
    "Benefits of a problem": "Can a problem be a good thing? Explain how facing a problem can benefit a person.",
    "Benefits of a good attitude": "What are the benefits of having a good attitude at school or at work?",
    "Learning from the experience of others": "Is it better to learn from your own experience or from the experience of other people?",
    "Honesty": "Is honesty always the best policy? Explain your opinion.",
    "Setting our aim": "Michelangelo said the greater danger is not setting our aim too high and falling short, but setting it too low and reaching it. Do you agree?",
    "Summer projects": "Should summer projects for students be designed by teachers or by the students themselves?",
}

# The TOEFL91 essays ship without their questions; these are classic TOEFL-style questions.
TOEFL_QUESTIONS = [
    "Do you prefer to cook at home or to eat at restaurants?",
    "Is it better to have a few close friends or a large number of friends?",
    "Do you prefer to live in a big city or in a small town?",
    "Should university students be required to attend classes, or should attendance be optional?",
    "Is it better to study alone or with a group of classmates?",
    "Do you agree that young people today are more helpful to their communities than in the past?",
    "Should parents give children an allowance, or should children earn their own money?",
    "Is it better to travel alone or with a tour group?",
    "Do you agree that teachers should be paid according to how well their students perform?",
    "Is it more important for a job to pay well or to be enjoyable?",
    "Do you prefer to read books on paper or on a screen?",
    "Should high school students be required to learn a foreign language?",
    "Do you agree that it is better to plan your free time carefully than to be spontaneous?",
    "Is it a good idea for students to take a gap year before university?",
    "Do you prefer to get news from newspapers, television or the internet?",
    "Do you agree that technology has made people less social?",
    "Should governments spend more money on public parks or on public transportation?",
    "Is it better to work for a large company or a small company?",
    "Do you agree that people learn more from failure than from success?",
    "Should children start learning to use computers at a very young age?",
]

FORMAT_RULES = (
    "Formatting rules for every piece: plain text only; separate paragraphs with a blank line; "
    "no Markdown (no headings, bold, italics or bullet lists); no title line unless the request "
    "asks for one; no preamble, notes or commentary before or after the piece.")

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
        "required": ["id", "text"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------------------
# Plan


def build_plan(human: list[dict]) -> list[dict]:
    """Deterministic per-source item plan mirroring the human prompts."""
    pure = [h for h in human if h["role"] == "pure"]
    persuade_prompts = {}
    for h in human:
        if h["source"] == "persuade":
            persuade_prompts.setdefault(h["prompt_id"], (h["topic"], h["prompt_text"]))
    pp = sorted(persuade_prompts.items())                      # 15 prompts
    ell = sorted({h["topic"] for h in human if h["source"] == "ellipse"})
    news = sorted([h for h in pure if h["source"] == "ghostbuster-news"], key=lambda h: h["id"])
    wp = sorted([h for h in pure if h["source"] == "ghostbuster-wp"], key=lambda h: h["id"])
    reserve = sorted([h for h in human if h["role"] == "mixed_reserve"], key=lambda h: h["id"])

    def ell_pid(topic: str) -> str:
        return "ellipse:" + re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")

    plan: list[dict] = []
    for si, src in enumerate(SOURCES):
        items: list[dict] = []

        def add(kind, subset, prompt_id, instruction, register, role="pure", target=None, mix_with=None):
            items.append({"source": src, "kind": kind, "subset": subset, "prompt_id": prompt_id,
                          "instruction": instruction, "register": register, "role": role,
                          "target_words": target, "mix_with": mix_with})

        # 60 student essays on the PERSUADE prompts (4 per prompt, varied request styles)
        for pi, (pid, (topic, assignment)) in enumerate(pp):
            for v in range(4):
                style = (pi + v + si) % 4
                n = (250, 350, 450, 600)[(pi * 3 + v + si) % 4]
                grade = (7, 8, 9, 10, 11, 12)[(pi + v) % 6]
                if style == 0:
                    ins = f"Write an essay responding to this assignment.\n\nAssignment: {assignment}"
                    tgt = None
                elif style == 1:
                    ins = f"Write a {n}-word essay for this assignment: {assignment}"
                    tgt = n
                elif style == 2:
                    ins = f"I'm in grade {grade}. Write my essay for this assignment (about {n} words): {assignment}"
                    tgt = n
                else:
                    ins = f"Write a five-paragraph argumentative essay on the following prompt.\n\n{assignment}"
                    tgt = None
                add("essay", "student", pid, ins, "student_essay", target=tgt)

        # 40 essays on ELLIPSE topics (non-native comparison prompts)
        order = sorted(ell, key=lambda t: stable_hash("ell-topic", src, t))
        for k, topic in enumerate(order[:40]):
            a = ELLIPSE_ASSIGNMENTS.get(topic, f"Write about: {topic}.")
            n = (250, 350, 450)[(k + si) % 3]
            if k % 2 == 0:
                ins = f"Write an essay of about {n} words answering this prompt: {a}"
            else:
                ins = f"Write a student essay for this prompt. {a}"
            add("essay", "non_native", ell_pid(topic), ins, "student_essay", target=n if k % 2 == 0 else None)

        # 15 TOEFL-style short essays (~100 words, like the TOEFL91 human set)
        qs = sorted(TOEFL_QUESTIONS, key=lambda q: stable_hash("toefl", src, q))[:15]
        for k, q in enumerate(qs):
            add("short", "non_native", f"toefl-style:q{TOEFL_QUESTIONS.index(q):02d}",
                f"Answer this TOEFL writing question in about 100 words: {q}", "short_answer", target=100)

        # 30 news articles from the human Reuters leads (same prompt_id as the human article)
        nsel = sorted(news, key=lambda h: stable_hash("news-pick", src, h["id"]))[:30]
        for k, h in enumerate(nsel):
            n = (300, 450, 600)[(k + si) % 3]
            add("news", "general", h["prompt_id"],
                f"Write a news article of about {n} words, in your own words, reporting the story "
                f"summed up by this lead: \"{h['prompt_text']}\"", "news", target=n)

        # 30 short stories from the human WritingPrompts prompts
        wsel = sorted(wp, key=lambda h: stable_hash("wp-pick", src, h["id"]))[:30]
        for k, h in enumerate(wsel):
            if k % 2 == 0:
                ins = f"Write a short story for this writing prompt: {h['prompt_text']}"
                tgt = None
            else:
                n = (400, 600)[(k // 2) % 2]
                ins = f"Write a {n}-word story based on this prompt: {h['prompt_text']}"
                tgt = n
            add("creative", "general", h["prompt_id"], ins, "creative", target=tgt)

        # 10 blog posts on the student topics (general register)
        for k in range(10):
            pid, (topic, _a) = pp[(k * 3 + si) % len(pp)]
            add("blog", "general", pid,
                f"Write a blog post (about 400 words) for a general audience about: {topic.lower()}.",
                "blog", target=400)

        # 30 natively short pieces across all three families (20-140 words)
        for k in range(30):
            fam = k % 3
            if fam == 0:
                pid, (topic, assignment) = pp[(k + si * 5) % len(pp)]
                q = assignment if len(assignment) < 400 else topic
                ins = (f"In two or three sentences, give your opinion on this: {q}" if k % 2 == 0 else
                       f"Write one short paragraph (about 80 words) answering: {q}")
                add("short", "student", pid, ins, "short_answer", target=40 if k % 2 == 0 else 80)
            elif fam == 1:
                topic = order[(40 + k) % len(order)]
                a = ELLIPSE_ASSIGNMENTS.get(topic, topic)
                ins = (f"Answer briefly, in about 50 words: {a}" if k % 2 == 0 else
                       f"Write a paragraph of about 120 words on this question: {a}")
                add("short", "non_native", ell_pid(topic), ins, "short_answer", target=50 if k % 2 == 0 else 120)
            else:
                if k % 2 == 0:
                    h = nsel[k % len(nsel)]
                    ins = f"Write a brief news item of about 70 words, in your own words, on this story: \"{h['prompt_text']}\""
                    add("short", "general", h["prompt_id"], ins, "short_news", target=70)
                else:
                    h = wsel[k % len(wsel)]
                    ins = f"Write a very short story (under 100 words) for this prompt: {h['prompt_text']}"
                    add("short", "general", h["prompt_id"], ins, "short_story", target=90)

        # mixed-document AI parts: one essay per reserved human essay, same prompt
        half = len(reserve) // 2
        mine = reserve[:half] if src == "chatgpt" else reserve[half:] if src == "claude" else reserve[:half]
        for h in mine:
            if h["source"] == "persuade":
                a = h["prompt_text"]
            else:
                a = ELLIPSE_ASSIGNMENTS.get(h["topic"], h["topic"])
            add("essay", h["subset"], h["prompt_id"],
                f"Write an essay responding to this assignment.\n\nAssignment: {a}", "student_essay",
                role="mixed_part", mix_with=h["id"])

        for i, it in enumerate(items):
            it["id"] = f"{src}-{i:04d}"
        plan.extend(items)
    return plan


# ---------------------------------------------------------------------------------------
# CLI calls


# Source-based PERSUADE assignments refer to passages we cannot supply. Models usually write
# the essay anyway; when one asked for the passages instead (a rejected answer), the retry
# gets this one extra sentence. First attempts never carry it.
SOURCE_BASED = re.compile(r"\b(passages?|articles?|sources?)\b", re.I)
RETRY_NOTE = ("(The passages or articles this assignment mentions are not available. Write the "
              "complete essay anyway, as a student would, from general knowledge.)")


def instruction_for(item: dict, hint_ids: set[str] | frozenset = frozenset()) -> str:
    if item["id"] in hint_ids and item["kind"] == "essay" and SOURCE_BASED.search(item["instruction"]):
        return f"{item['instruction']}\n{RETRY_NOTE}"
    return item["instruction"]


def batch_prompt(items: list[dict], hint_ids: set[str] | frozenset = frozenset()) -> str:
    parts = [
        f"Please complete each of the following {len(items)} writing requests. Treat every request "
        "as a separate, independent task and write each piece exactly as you would if it were the "
        "only thing you had been asked.",
        FORMAT_RULES,
        'Return the result as a JSON object of the form {"items": [{"id": "<request id>", "text": '
        '"<the piece>"}]} with exactly one entry per request, in the same order. Output only the JSON.',
    ]
    for it in items:
        parts.append(f"Request {it['id']}:\n{instruction_for(it, hint_ids)}")
    return "\n\n".join(parts)


def prior_rejects(call_dir: Path, plan_by_id: dict[str, dict]) -> set[str]:
    """Ids that some earlier successful call answered with a rejected piece."""
    out: set[str] = set()
    for f in call_dir.glob("call-*.json"):
        try:
            rec = json.loads(f.read_text())
            if not rec.get("ok"):
                continue
            got = {g["id"]: g["text"] for g in parse_items(rec["text"])}
        except (ValueError, KeyError, TypeError):
            continue
        for i, t in got.items():
            if i in plan_by_id and acceptable(plan_by_id[i], clean_piece(t)):
                out.add(i)
    return out


def clean_env() -> dict:
    """Run the CLIs as a fresh login shell would: no inherited agent-session variables."""
    keep = {k: os.environ[k] for k in ("HOME", "USER", "LOGNAME", "PATH", "SHELL", "TMPDIR") if k in os.environ}
    keep.update({"LANG": "en_US.UTF-8", "TERM": "xterm-256color", "NO_COLOR": "1"})
    return keep


def run_cli(source: str, prompt: str, workdir: Path) -> dict:
    """Returns {ok, text, model_id, stderr, auth_error}."""
    workdir.mkdir(parents=True, exist_ok=True)
    env = clean_env()
    if source == "chatgpt":
        schema = workdir / "schema.json"
        schema.write_text(json.dumps(OUTPUT_SCHEMA))
        last = workdir / "last.txt"
        if last.exists():
            last.unlink()
        cmd = [CLI["chatgpt"], "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only",
               "--color", "never", "-C", str(workdir), "--output-schema", str(schema), "-o", str(last), prompt]
        p = subprocess.run(cmd, cwd=workdir, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=CALL_TIMEOUT_S)
        both = p.stdout + "\n" + p.stderr
        m = re.search(r"^model:\s*(\S+)", both, re.M)
        eff = re.search(r"^reasoning effort:\s*(\S+)", both, re.M)
        model = m.group(1) if m else None
        if model and eff:
            model = f"{model} (codex, reasoning effort {eff.group(1)})"
        text = last.read_text(encoding="utf-8") if last.exists() else ""
        return {"ok": p.returncode == 0 and bool(text.strip()), "text": text, "model_id": model,
                "stderr": both[-4000:], "auth_error": bool(AUTH_PATTERNS.search(both)) and p.returncode != 0}
    if source == "claude":
        cmd = [CLI["claude"], "-p", "--tools", "", "--strict-mcp-config", "--no-session-persistence",
               "--output-format", "json", prompt]
        p = subprocess.run(cmd, cwd=workdir, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=CALL_TIMEOUT_S)
        model, text, is_err = None, "", True
        try:
            j = json.loads(p.stdout)
            text = j.get("result") or ""
            is_err = bool(j.get("is_error"))
            usage = j.get("modelUsage") or {}
            if usage:
                model = max(usage, key=lambda k: usage[k].get("outputTokens", 0))
        except json.JSONDecodeError:
            pass
        both = p.stdout[-2000:] + "\n" + p.stderr[-2000:]
        return {"ok": p.returncode == 0 and not is_err and bool(text.strip()), "text": text, "model_id": model,
                "stderr": both, "auth_error": bool(AUTH_PATTERNS.search(both)) and (p.returncode != 0 or is_err)}
    if source == "gemini":
        cmd = [CLI["gemini"], "--skip-trust", "-o", "json", "-p", prompt]
        p = subprocess.run(cmd, cwd=workdir, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=CALL_TIMEOUT_S)
        model, text = None, ""
        try:
            j = json.loads(p.stdout)
            text = j.get("response") or ""
            models = (j.get("stats") or {}).get("models") or {}
            if models:
                model = max(models, key=lambda k: (models[k].get("tokens") or {}).get("candidates", 0))
        except json.JSONDecodeError:
            pass
        both = p.stdout[-2000:] + "\n" + p.stderr[-2000:]
        return {"ok": p.returncode == 0 and bool(text.strip()), "text": text, "model_id": model,
                "stderr": both, "auth_error": bool(AUTH_PATTERNS.search(both)) and p.returncode != 0}
    raise ValueError(source)


def parse_items(text: str) -> list[dict]:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    start = t.find("{")
    end = t.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object in output")
    obj = json.loads(t[start:end + 1])
    items = obj["items"] if isinstance(obj, dict) else obj
    return [{"id": str(i["id"]), "text": str(i["text"])} for i in items]


def clean_piece(text: str) -> str:
    t = text.replace("\r\n", "\n").strip()
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t


def acceptable(item: dict, text: str) -> str | None:
    """None if fine, else a reason. Checks only gross failures; never edits the prose."""
    w = word_count(text)
    if w < 20:
        return f"too short ({w} words)"
    if item["kind"] == "short" and w > 170:
        return f"short item too long ({w} words)"
    # long pieces must reach 120 words, or 70% of a smaller target (abstracts ask for 80-110)
    floor = min(120, int(0.7 * item["target_words"])) if item.get("target_words") else 120
    if item["kind"] != "short" and w < floor:
        return f"long item too short ({w} words)"
    if re.search(r"^\s*(#{1,6} |\*\*|- |\* )", text, re.M):
        return "markdown formatting"
    meta = r"as an ai|i can't help|i cannot help" + ("" if item["kind"] == "abstract" else r"|language model")
    if re.search(meta, text, re.I):  # abstracts may legitimately be about language models
        return "refusal or meta text"
    return None


def load_status(gen_dir: Path = GEN_DIR) -> dict:
    p = gen_dir / "status.json"
    return json.loads(p.read_text()) if p.exists() else {}


def save_status(source: str, entry: dict, gen_dir: Path = GEN_DIR) -> None:
    """Merge this source's entry into status.json (several sources run in parallel)."""
    p = gen_dir / "status.json"
    st = load_status(gen_dir)
    st[source] = entry
    tmp = p.with_suffix(f".{source}.tmp")
    tmp.write_text(json.dumps(st, indent=2) + "\n")
    tmp.replace(p)


def plan_batches(todo: list[dict]) -> list[list[dict]]:
    """Group pending items into calls: long kinds together (fixed order first), then short."""
    long_items = [it for it in todo if it["kind"] != "short"]
    short_items = [it for it in todo if it["kind"] == "short"]
    kinds = list(LONG_KIND_ORDER) + sorted({it["kind"] for it in long_items} - set(LONG_KIND_ORDER))
    batches = []
    for kind in kinds:
        # shuffle (deterministically) so one call never holds several pieces on one prompt
        same = sorted([it for it in long_items if it["kind"] == kind], key=lambda it: stable_hash("batch", it["id"]))
        batches += list(iter_chunks(same, KIND_BATCH.get(kind, LONG_BATCH)))
    short_items = sorted(short_items, key=lambda it: stable_hash("batch", it["id"]))
    batches += list(iter_chunks(short_items, SHORT_BATCH))
    return batches


def run_source(source: str, limit_calls: int | None, max_rounds: int, gen_dir: Path = GEN_DIR,
               should_stop=None) -> None:
    """Generate `source`'s pending plan items from gen_dir/plan.jsonl into gen_dir/ai_<source>.jsonl.
    gen_dir defaults to calibration/generated; classifier/ passes its own. should_stop() is
    checked before every call, so a caller can end the run cleanly at a deadline."""
    plan = [it for it in read_jsonl(gen_dir / "plan.jsonl") if it["source"] == source]
    out_path = gen_dir / f"ai_{source}.jsonl"
    done = {r["id"]: r for r in read_jsonl(out_path)} if out_path.exists() else {}
    call_dir = gen_dir / source
    call_dir.mkdir(parents=True, exist_ok=True)
    # run the CLIs from an empty directory outside the workspace so no project AGENTS.md /
    # CLAUDE.md / GEMINI.md context is loaded into the writing requests
    workdir = Path(tempfile.gettempdir()) / "squint-gen-cwd" / source
    calls = 0
    st = dict(load_status(gen_dir).get(source, {}))
    hint_ids = prior_rejects(call_dir, {it["id"]: it for it in plan}) - set(done)
    for rnd in range(max_rounds):
        todo = [it for it in plan if it["id"] not in done]
        if not todo:
            break
        batches = plan_batches(todo)  # keeps registers together inside a batch
        print(f"[{source}] round {rnd + 1}: {len(todo)} items in {len(batches)} calls", flush=True)
        for batch in batches:
            if limit_calls is not None and calls >= limit_calls:
                return
            if should_stop is not None and should_stop():
                print(f"[{source}] stop requested; ending cleanly", flush=True)
                return
            prompt = batch_prompt(batch, hint_ids)
            res = None
            for attempt in range(len(BACKOFF_S) + 1):
                t0 = time.time()
                try:
                    res = run_cli(source, prompt, workdir)
                except subprocess.TimeoutExpired:
                    res = {"ok": False, "text": "", "model_id": None, "stderr": "timeout", "auth_error": False}
                res["seconds"] = round(time.time() - t0, 1)
                calls += 1
                rec = {"at": now(), "source": source, "ids": [b["id"] for b in batch], "attempt": attempt,
                       "prompt": prompt, **res}
                (call_dir / f"call-{int(time.time() * 1000)}.json").write_text(json.dumps(rec, indent=1))
                if res["auth_error"]:
                    st.update({"blocked": True, "reason": res["stderr"][-600:], "at": now()})
                    save_status(source, st, gen_dir)
                    print(f"[{source}] AUTH BLOCKER - stopping this source:\n{res['stderr'][-600:]}", flush=True)
                    return
                if res["ok"]:
                    break
                if LIMIT_PATTERNS.search(res["stderr"] + res.get("text", "")):
                    st.update({"rate_limited": True, "reason": (res["stderr"] or res["text"])[-600:], "at": now()})
                    save_status(source, st, gen_dir)
                    print(f"[{source}] USAGE LIMIT - stopping; rerun later to resume:\n{res['stderr'][-400:]}", flush=True)
                    return
                wait = BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)]
                print(f"[{source}] call failed (attempt {attempt + 1}); sleeping {wait}s: {res['stderr'][-300:]!r}", flush=True)
                time.sleep(wait)
            if not res or not res["ok"]:
                print(f"[{source}] giving up on batch {[b['id'] for b in batch]} this round", flush=True)
                continue
            try:
                got = {g["id"]: g["text"] for g in parse_items(res["text"])}
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
                print(f"[{source}] unparseable output ({e}); will retry items", flush=True)
                continue
            new = 0
            for it in batch:
                if it["id"] not in got:
                    continue
                text = clean_piece(got[it["id"]])
                why = acceptable(it, text)
                if why:
                    print(f"[{source}] reject {it['id']}: {why}", flush=True)
                    hint_ids.add(it["id"])
                    continue
                sent = instruction_for(it, hint_ids)
                done[it["id"]] = {
                    "id": it["id"], "text": text, "label": "ai", "source": source, "subset": it["subset"],
                    "model_id": res["model_id"], "prompt_id": it["prompt_id"], "register": it["register"],
                    "kind": it["kind"], "role": it["role"], "mix_with": it["mix_with"],
                    "instruction": sent, "retry_note": sent != it["instruction"],
                    "target_words": it["target_words"],
                    "generated_at": now(), "batch_size": len(batch),
                }
                new += 1
            write_jsonl(out_path, done.values())
            st.update({"blocked": False, "rate_limited": False, "model_id": res["model_id"], "done": len(done), "planned": len(plan),
                       "calls": st.get("calls", 0) + 1, "at": now()})
            save_status(source, st, gen_dir)
            print(f"[{source}] +{new} ({len(done)}/{len(plan)}) model={res['model_id']} {res['seconds']}s", flush=True)
            time.sleep(3)  # be gentle with rate limits


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan")
    r = sub.add_parser("run")
    r.add_argument("--source", required=True, choices=SOURCES)
    r.add_argument("--limit-calls", type=int, default=None)
    r.add_argument("--max-rounds", type=int, default=3)
    args = ap.parse_args()
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    if args.cmd == "plan":
        human = read_jsonl(DATA_DIR / "human_base.jsonl")
        plan = build_plan(human)
        write_jsonl(GEN_DIR / "plan.jsonl", plan)
        from collections import Counter
        print(Counter((p["source"], p["kind"], p["role"]) for p in plan))
        print(f"wrote {len(plan)} planned items")
    else:
        run_source(args.source, args.limit_calls, args.max_rounds)


if __name__ == "__main__":
    main()
