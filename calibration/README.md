# Squint calibration

Builds the tuning set, fits `thresholds.json` and writes `report.json` for the server
(formats: `docs/calibration-format.md`, including its v1.1 amendments).

Committed: the scripts, `tests/`, this README, `thresholds.json`, `report.json`.
Not committed (gitignored): `data/` (dataset, scores, raw downloads) and `generated/`
(AI writing runs, logs, diagnostics).

## Pipeline

```
calibration/run_all.sh                                   # all stages, each resumable
SQUINT_PROFILE=falcon-7b calibration/run_all.sh score fit report
calibration/run_all.sh test                              # unit tests
```

| Stage | Script | Output |
|---|---|---|
| human | `fetch_human.py` | `data/human_base.jsonl` (+ `data/raw/` caches) |
| plan | `generate_ai.py plan` | `generated/plan.jsonl` |
| generate | `generate_ai.py run --source {chatgpt,claude,gemini}` | `generated/ai_<source>.jsonl`, `generated/status.json` |
| build | `build_dataset.py` | `data/all.jsonl`, `data/manifest.json` |
| score | `server/` `squint-score --resume` (profile from `SQUINT_PROFILE`) | `data/scores.jsonl` |
| fit | `fit_thresholds.py` | `thresholds.json`, `generated/fit-details.json` |
| report | `report.py` | `report.json`, `generated/report-details.json` |

Python scripts are standalone (`uv run --python 3.12 calibration/<script>.py`), standard
library only. Tests: `uv run --no-project --python 3.12 python -m unittest discover -s calibration/tests`.

## Human texts (all written before ChatGPT, 2022-11-30)

| Source | `subset` | Docs | Where from | Licence |
|---|---|---|---|---|
| PERSUADE 2.0, US grades 6-12, written 2010-2020 | `student` (ELL "No") | 200 (+45 reserved for mixed docs) | <https://github.com/scrosseye/persuade_corpus_2.0> (CSV streamed from the authors' Google Drive link; only the sample is kept) | CC BY-NC-SA 4.0 |
| PERSUADE 2.0, English-language learners | `non_native` (ELL "Yes", ELLIPSE essays excluded) | 60 | same | CC BY-NC-SA 4.0 |
| ELLIPSE, English-language learners grades 8-12, collected before Aug 2022 | `non_native` | 200 (+15 reserved) | <https://github.com/scrosseye/ELLIPSE-Corpus> | CC BY-NC-SA 4.0 |
| TOEFL91, TOEFL practice essays (Liang et al. 2023), written 2020 or earlier | `non_native` | 90 (1 duplicate dropped) | <https://github.com/Weixin-Liang/ChatGPT-Detector-Bias> `Data_and_Results/Human_Data/TOEFL_real_91` | Repo README shows an MIT badge, no LICENSE file; essays are third-party forum posts |
| Reuters 50-50 news, 1996-97, via Ghostbuster | `general` | 100 | <https://github.com/vivek3141/ghostbuster-data> `reuter/human` | CC BY 3.0 (Ghostbuster LICENSE); underlying articles © Reuters |
| r/WritingPrompts stories (scraped Oct 2022), via Ghostbuster | `general` | 100 | same, `wp/human` | CC BY 3.0 (Ghostbuster LICENSE); underlying stories by Reddit users |

These licences allow private, non-commercial research use. The raw texts stay in the
gitignored `data/`. Only aggregate numbers (`thresholds.json`, `report.json`) are
committed. Check the NC-SA terms before any commercial use.

Clean-up applied to human texts: newline and mojibake normalisation, exact-duplicate
removal, and only texts of 20-2,400 words are sampled. PERSUADE and ELLIPSE replace names with tokens
such as `Generic_Name` and `Generic_School`. Those tokens would make human text look
unusually surprising, so they are filled with ordinary names, consistently within each
essay (`meta.placeholders_filled`).

## AI texts

Written through Nicky's own logged-in CLIs, each app's default model, run one call at a
time from an empty temp directory with a minimal environment. That keeps the workspace
AGENTS.md/CLAUDE.md files out of the context. Each call asks for 5 long or 15 short pieces
and returns JSON. Batches are shuffled, so one call never holds several pieces on the
same prompt.

| `source` | CLI | Exact model id |
|---|---|---|
| chatgpt | `codex exec --ephemeral -s read-only --output-schema` | `gpt-6.1-sol` (codex, reasoning effort high) |
| claude | `claude -p --tools "" --strict-mcp-config --no-session-persistence` | `claude-opus-5-5` |
| gemini | `gemini` | none: blocked, see `generated/status.json` |

The plan (`generated/plan.jsonl`) has 241 items per source, and each one mirrors the
human prompts through `prompt_id`:
- 56 essays on the 14 PERSUADE prompts, in four request styles
- 40 essays on ELLIPSE topics (the assignment text is paraphrased)
- 15 TOEFL-style answers of about 100 words (`toefl-style:qNN`)
- 30 news articles written from the Reuters leads
- 30 stories written from the WritingPrompts prompts
- 10 blog posts
- 30 natively short pieces
- 30 essays paired with the reserved human essays to build mixed documents

On AI rows, `subset` names the topic family being mirrored (for example `non_native` means
an ELLIPSE or TOEFL topic). It does not describe the writer.

Rejected outputs:
- pieces under 20 words
- short pieces over 170 words, or long pieces under 120 words
- pieces containing Markdown
- refusals and requests for the source passages

A retried PERSUADE source-based essay gets one extra sentence saying the passages are
unavailable (`retry_note: true`). First attempts never get it.

Rows from the first two test calls, made while the CLI working directory was still inside
the workspace, are kept in `generated/excluded/` and were regenerated. Every raw call (prompt,
output, model id) is in `generated/<source>/call-*.json`.

## Dataset (`data/all.jsonl`)

- **Length buckets.** Every base document contributes its full text (counted as 150+ only
  when it has at least 160 words). It also contributes sentence-aligned excerpts of 23-46 and
  55-140 words. Human and AI texts are cut by the same procedure, plus natively short AI
  pieces.
- **Mixed documents.** A reserved human essay is spliced with an AI essay on the same
  prompt, by paragraph, in the patterns HA, AH, HAH or AHA. `spans` are Python string
  offsets. The manifest's `rows_with_non_bmp_chars` (0 so far) shows they equal UTF-16
  offsets.
- **Splits.** A document and all its excerpts land in the same split. The split is 50/50
  tune/heldout, stratified by label × source × subset × full-text bucket, with the fixed
  seed `squint-2026-10-07`.
- **Dropped rows.** AI news pieces and short pieces that copy a 10-word run from their human
  lead are dropped, along with exact duplicates.

Extra row fields beyond the format (the scorer ignores them):
- On every row: `group_id` (base document), `variant` (`full` / `excerpt` / `mixed`),
  `bucket`, `n_words` and `register`.
- On mixed rows: `mix_human_id`, `mix_ai_id` and `ai_word_share` (true AI share by words).

`data/manifest.json` has counts for every label × source × subset × split × bucket cell.

## Fitting and report

`fit_thresholds.py` uses the tune split and human/AI rows only. It drops failed score rows
and rows the scorer counts as under 20 words (format v1.1). The bucket comes from the
scorer's `word_count`, and fitting stops with an error if the scores come from more than
one model pair. The cutoff rules are in the format doc:
- `ai_below`: the 1% rule on all humans and on non-native alone, whichever is lower.
- `human_above`: the 5% rule on AI texts, clamped up to `ai_below`.
- `segment.flag_below`: the 1% rule on human windows.

Cutoffs are not rounded.

`report.py` scores the heldout split with the server's band rules. It adds `sample_counts`
to the contract shape. Wilson intervals, per-source numbers, the mixed-document "% AI"
error (measured by word index, as the server computes it) and window false flags go to
`generated/report-details.json`.
