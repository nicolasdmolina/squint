# Classifier (overnight pipeline)

A fine-tuned text classifier (ModernBERT-base) to sit next to Binoculars. Binoculars alone
misses most ChatGPT text at a 1% false-flag cap (see `docs/known-gaps.md`); this pipeline
gathers more human and AI writing, trains a classifier at night, and writes a pass/fail gate
report each morning. Ticket: `.scratch/squint-chatgpt-classifier/spec.md`.

**Not wired into the server or API yet.** See "Integration" at the end.

## Layout

| File | What it does |
|---|---|
| `config.toml` | Every setting: held-out sources, per-night call caps, model, training, gate. |
| `sources.json` | The human sources with URL, licence and role (train / holdout / ood). |
| `fetch_human.py` | Downloads the new human sources (stdlib). `fetch` writes `data/human_extra.jsonl`; `ood --from DIR` imports the OOD sets. Each source is cached in `data/raw/`; failures are retried on the next run. |
| `generate.py` | AI writing plan + runner. Reuses `calibration/generate_ai.py` (its CLI calls, batching, acceptance checks and auth/usage-limit stops) and only adds plan items and an output dir. |
| `build_dataset.py` | `data/dataset.jsonl` + `dataset-manifest.json` (dataset hash, counts). Excerpts are cut the same way as in calibration, so Binoculars scores can be joined by id. Fails on any split leakage. |
| `splits.py` | Source-held-out split, dedup and the leakage checker (unit-tested). |
| `train.py` | Fine-tuning on MPS: chunked 512-token inputs, checkpoints, resumable, SIGTERM-safe, deterministic. |
| `evaluate.py` | Predictions, cutoffs fitted on tune, per-source rates, gate. Writes `reports/<date>.json` + `.md`. |
| `thresholds.py` | Cutoff fitting at the false-flag cap, the Binoculars OR rule, Wilson intervals (unit-tested). |
| `guards.py` | Window maths and "is the machine busy" checks (unit-tested). |
| `nightly.py` | Orchestrates one night (run by `ops/nightly.sh` from launchd). |
| `modeling.py`, `textchunks.py`, `clf_common.py` | Shared helpers. |
| `tests/` | Unit tests (stdlib `unittest`). |

Gitignored working state: `data/`, `generated/`, `runs/`, `state/`, `.venv/`. Reports in
`reports/` hold only aggregate numbers and can be committed.

## Setup and commands

```sh
cd classifier && uv sync            # isolated env: torch, transformers, numpy, safetensors, sentencepiece
cd ..                               # commands below run from the project root
classifier/.venv/bin/python -m unittest discover -s classifier/tests -t classifier/tests

classifier/.venv/bin/python classifier/fetch_human.py fetch            # new human sources
classifier/.venv/bin/python classifier/generate.py plan                # extend the AI plan
classifier/.venv/bin/python classifier/generate.py run --source claude --limit-calls 2
classifier/.venv/bin/python classifier/build_dataset.py
classifier/.venv/bin/python classifier/train.py                        # resumes if interrupted
classifier/.venv/bin/python classifier/evaluate.py                     # newest finished run
```

Smoke test (CPU, tiny model, ~1 minute, leaves the real runs alone):

```sh
classifier/.venv/bin/python classifier/train.py --model prajjwal1/bert-tiny --device cpu \
  --limit-rows 200 --epochs 1 --max-length 256 --run-dir /tmp/smoke-run
classifier/.venv/bin/python classifier/evaluate.py --run-dir /tmp/smoke-run --device cpu \
  --limit-per-split 40 --reports-dir /tmp/smoke-reports
```

## Data

Human sources (details and licences in `sources.json`): PERSUADE (plus 800 extra essays, 300
by English learners), Reuters news and r/WritingPrompts via Ghostbuster, and four new pre-2022
sources: arXiv abstracts (CC0), Amazon reviews (Apache-2.0 card), Stack Exchange answers
2012-2021 (CC BY-SA) and Wikipedia article revisions from before 2022 (CC BY-SA 3.0;
Wikipedia rate-limits anonymous parsing, so this source fills in over several nights).

AI writing (`generate.py plan`), per generator (chatgpt via Codex, claude, gemini):

- **matched**: one piece per new human document, from the same prompt (arXiv title, article
  title, review title and star polarity, forum question), plus more news and stories.
- **student**: "write it the way a real grade-N student would" on PERSUADE and ELLIPSE topics.
- **nonnative**: "write as an English learner" on PERSUADE topics and TOEFL questions.
- **casual**: quick, informal replies and reviews.
- **paraphrase**: an existing AI piece paraphrased or "humanized" (three rewrite styles).

Per-night call caps are in `config.toml` (chatgpt 600, claude 300). Gemini is tried first
and drops out at once if its login is blocked (it currently is: Google retired the Gemini
CLI's free tier for individuals). The plan is append-only, so ids are stable and each night
resumes where the last one stopped.

## Splits

- **holdout**: `ellipse` and `toefl91` (both non-native; ELLIPSE is student essays). Their
  human texts and every AI piece written for their prompts are evaluation-only.
- **ood**: the four out-of-distribution human sets (college essays, CS224N abstracts, Hewlett
  essays, Ghostbuster essays). Evaluation-only.
- **train / tune / heldout**: everything else, 70/15/15, stratified by label, source family,
  generator and subset, with a fixed seed. Excerpts stay with their document, a paraphrase
  stays with its original, and duplicate texts are kept only in the more restrictive split.
  `build_dataset.py` refuses to write a dataset that fails the leakage checks.

Caveat: ELLIPSE essays come from the same research programme and student population as
PERSUADE (the training set's largest source). Holding it out is still meaningful, because no
ELLIPSE text or prompt is trained on, but it is less independent than TOEFL91 or the OOD sets.

## Gate (`evaluate.py`)

The cutoffs are fitted on the **tune** split only. The classifier-only cutoff allows at most
1% false flags on all tune humans and on the non-native tune humans (the stricter wins). The
combined rule (classifier P(AI) above t, or Binoculars score below b_cut) is fitted on the
tune rows that have a Binoculars score, catching as much AI as the same caps allow.

Both rules are then applied to text the model never trained or tuned on (the holdout and OOD
human sets, plus AI pieces written for the held-out prompts). The gate passes when:

- false flags ≤ 1% overall and for non-native writers, and
- the ChatGPT catch rate on held-out sources is ≥ 50%.

The report lists per-source and per-length rates with 95% Wilson intervals, the cutoffs, and
which rule (if any) passes.

Binoculars scores come from `calibration/data/scores-falcon-7b.jsonl` (calibration rows) and
`data/scores-extra-falcon-7b.jsonl` if present. Rows that are not in calibration have no score
yet: `evaluate.py` lists them in `runs/<run>/binoculars-needed.jsonl`, in squint-score's input
format. To complete the combined-rule numbers, score that list when the machine is free:

```sh
cd server && uv run --no-sync squint-score --profile falcon-7b \
  --in ../classifier/runs/<run>/binoculars-needed.jsonl \
  --out ../classifier/data/scores-extra-falcon-7b.jsonl --resume
```

## The night (`ops/nightly.sh` → `nightly.py`)

Per-user launchd agent `com.nickymolina.squint-nightly` starts at 23:00. The window ends at
09:30 (`SQUINT_NIGHTLY_START` / `SQUINT_NIGHTLY_END`). `caffeinate -i` keeps the Mac awake only
while the run is alive. It runs at normal priority: launchd's Background type made training
4x slower whenever other work was running (24-28 s/step against 6-9). One copy at a time (lock in `state/`). Log:
`~/Library/Logs/squint/nightly.log`. Stage outcomes are in `state/nightly.json`, and each
night's summary in `reports/<date>-night.json`.

| Stage | Time | Notes |
|---|---|---|
| fetch | 0-45 min, usually skipped | only while a human source is still missing |
| plan | seconds | |
| generate | whole window, in parallel | chatgpt ~150 s per call (≈160 calls a night, cap 600), claude ~65 s per call (cap 300), gemini skipped while its login is blocked. Stops 2 min before the window ends. |
| build | 1-3 min | skipped when an unfinished training run is waiting |
| train | rest of the night, minus a 45 min eval reserve | ModernBERT-base, bf16 on MPS, MPS memory capped (`mps_memory_fraction`). Checkpoints every 200 steps and on SIGTERM; the next night resumes. |
| evaluate | 10-45 min | newest finished run without a report |
| round 2 | build, train, evaluate again | when training finished and 3 h are left (`SQUINT_NIGHTLY_ROUNDS`, `SQUINT_NIGHTLY_MIN_ROUND_MIN`); uses what the generators wrote since, without waiting for them. Report: `reports/<date>-2.*` |

Heavy stages (train, evaluate) start only when Squint's `/api/status` shows no queued checks
and no loaded or loading models, no `squint-score` job is running, `memory_pressure` reports
≥ 20% free and ≥ 6 GB of disk is free. While a heavy stage runs these checks repeat every 60 s
(memory threshold 5%, since training uses memory itself). If Squint gets busy, the stage is
stopped with SIGTERM (it checkpoints) and restarted once the machine is free. At the window end
every child gets SIGTERM, then SIGKILL after 90 s. Settings: see the `nightly.py` docstring.

Install or remove (Nicky runs this himself):

```sh
ops/install-nightly.sh          # install; first run tonight at 23:00
ops/install-nightly.sh remove   # uninstall
```

Dry run with a short fake window and stub stages (touches nothing real):

```sh
SQUINT_NIGHTLY_START=$(date +%H:%M) SQUINT_NIGHTLY_END=$(date -v+4M +%H:%M) \
SQUINT_NIGHTLY_EVAL_RESERVE_MIN=1.5 SQUINT_NIGHTLY_POLL_S=5 SQUINT_NIGHTLY_GRACE_S=5 \
SQUINT_NIGHTLY_LOG_DIR=/tmp/squint-dry ops/nightly.sh --stub --state-dir /tmp/squint-dry/state --stub-guard ""
```

## Integration (later ticket)

What adding the classifier to Squint will need:

1. A passing gate report, and a chosen rule (combined or classifier-only) with its frozen cutoffs.
2. Export: `runs/<run>/final/` (safetensors + tokenizer, about 600 MB) copied to `models/`,
   with the cutoffs and dataset hash in a small JSON file next to it.
3. Server: load the classifier lazily next to the Binoculars pair (about 0.6 GB more on
   MPS), score texts with the same 512-token chunking and length-weighted mean as
   `modeling.predict_texts`, and apply the rule. Texts under 20 words stay "too short".
4. API and UI: a classifier probability and which signal fired. This changes
   `docs/api-contract.md` and `web/`, so it needs those owners' agreement.
5. Re-fit the cutoffs whenever either model changes; keep the gate as a CI or release check.
