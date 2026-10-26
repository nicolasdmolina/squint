# Roadmap

What stands between the current classifier and one that is good enough to rely on. Measured
gaps are in [`known-gaps.md`](known-gaps.md); this file is the work list. One ticket per
section, highest priority first. Status is one of `ready`, `in progress`, `waiting on Nicky`,
`parked`, or `done`.

## Target

Nicky's bar (2026-10-25): success rates similar to GPTZero. GPTZero's own benchmark claims
about 99% of AI text caught with under 1% of human text flagged; independent tests report
lower catch rates and 2–18% false flags depending on the writing. Squint's version of that
bar, on texts of 50+ words from ChatGPT and Claude:

- at least 97% of AI text caught for each generator
- at most 1% of human text flagged, for every kind of human writing including college essays
- both measured once on the sealed test (R5)

GPTZero covers many more AI models than Squint can generate locally; R6 and R7 close part
of that gap.

## R1. College-essay false flags

Status: ready

Every run since 10-14 wrongly flags 3.8–5.7% of the out-of-distribution college essays
(`ood-college-essay`, 70 essays scored at several lengths), against about 0.4% on the
held-out human sources. A student checking their own personal statement is the case most
likely to go wrong. No training source is first-person narrative of that kind.

- Hippocorpus (Microsoft, 2019–2020, about 6,800 first-person stories, CDLA-Permissive 2.0)
  is the closest open source. It needs a manual download from Microsoft Research Open Data;
  the Hugging Face copy is a loader script without the data.
- R2 adds informal first-person writing, which may help partly.

Done when: college-essay false flags are at or under 1.5% across two runs, with the other
human sources no worse.

## R2. Reddit as a human source

Status: in progress (2026-10-24). The first run with Reddit (2ba047ff) trained 776 of 1,006
steps on 10-25 before the window closed and finishes the next night.

300 posts and comments from Webis-TLDR-17 (2006–2016, CC BY 4.0), with matched ChatGPT and
Claude posts written from each post's tl;dr. `build_dataset.py` keeps the human rows out of
training until at least half as many matched AI rows exist, so the source never trains
one-sided.

Done when: a run that includes it is evaluated and compared with the 10-23 run.

## R3. Promote a learner-trained model

Status: done (2026-10-25). 10-18 (f37cef8b) is live; the previous model (e1d93574) stays in
`server/models/classifier/` for rollback. Its `human_below` is capped at `ai_above`, so the
classifier gives no "uncertain" band of its own.

The 10-18 run catches Claude writing as a B1 learner 90% of the time (live model: 65%), for
one extra false flag in 1,000 fresh human texts. See
[`../classifier/reports/2026-10-22-learner-check.md`](../classifier/reports/2026-10-22-learner-check.md).
The 10-23 run checked the same way: 80% on the learner set, 2 fresh human texts flagged, so
10-18 is still the best candidate. Later runs should be checked the same way before choosing.

## R4. Claude encyclopedia and abstract misses

Status: in progress (2026-10-25)

Broken down by kind (10-23 run, held-out, classifier-only cutoff), Claude's misses are not
mostly about length. Plain matched pieces in encyclopedia style are missed 16% of the time
(14 of 87) and research abstracts 8% (4 of 54); every other kind is at 6% or under, and
ChatGPT is at 5% or under everywhere. `wikipedia` and `arxiv` in `[human]` went from 300 to
600 on 10-25, so both generators write matched pieces for 300 more of each. Growing a
source keeps the rows already in use, so earlier matched AI rows and splits stay valid.

Done when: Claude's encyclopedic and academic misses are under 5% on held-out.

## R5. A sealed final test

Status: ready

The held-out sets have been looked at after every run, and the 50-word minimum was chosen
after seeing them. Before any claim that Squint is accurate, collect a new set (pre-ChatGPT
human writing from sources never used, plus fresh ChatGPT and Claude text), score it once
with the chosen model, and report that number unchanged.

## R6. Other AI models

Status: ready

The classifier knows current ChatGPT and Claude. 2022 ChatGPT is missed almost entirely, and
open models are untested. Open models can be run locally (llama.cpp is already installed for
Binoculars) without any login.

## R7. Gemini as a generator

Status: parked (2026-10-24, Nicky: not needed for now)

The Gemini CLI stopped working on this Mac: "This client is no longer supported for Gemini
Code Assist for individuals", with a pointer to Google's Antigravity products. Gemini was
dropped from `[generate].order` in `classifier/config.toml`; its plan items stay in
`plan.jsonl` and nothing is generated for them.

To pick it back up: get a working non-interactive Gemini route (a Gemini API key, or the
Antigravity CLI if it can run headless), add it to `calibration/generate_ai.py`, put
`gemini` back in `[generate].order`, and add a Gemini row to the fresh check. Until then
Squint should be treated as untested on Gemini text.
