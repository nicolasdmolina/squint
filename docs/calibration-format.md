# Calibration formats (server ⇄ calibration)

The server's scorer and the calibration scripts share these files. Change this file first.

## 1. Dataset rows — `calibration/data/*.jsonl` (not committed)

```json
{"id": "persuade-00123", "text": "...", "label": "human | ai | mixed",
 "source": "persuade | ellipse | ghostbuster-news | chatgpt | claude | gemini | ...",
 "subset": "student | non_native | general",
 "split": "tune | heldout",
 "model_id": "exact model id for AI rows, else null",
 "prompt_id": "shared id linking AI rows to the human prompt/topic they mirror",
 "spans": [{"start": 0, "end": 640, "label": "human | ai"}]}
```

`spans` only for `mixed` rows (character offsets into `text`).

## 2. Batch scoring — `squint-score` (provided by `server/`)

```
cd server && uv run squint-score --in ../calibration/data/all.jsonl --out ../calibration/data/scores.jsonl
```

Reads dataset rows (needs `id`, `text`), writes one line per row, same order, using exactly the
code path the web app uses:

```json
{"id": "...", "word_count": 412, "token_count": 531, "score": 0.8123,
 "stats": {"top1_rate": 0.71, "top5_rate": 0.9, "mean_surprise": 1.9,
           "mean_expected_surprise": 2.4, "sentence_score_spread": 0.05},
 "segments": [{"word_start": 0, "word_end": 150, "start": 0, "end": 905, "score": 0.81}],
 "model_pair": {"observer": "...", "performer": "..."}}
```

`segments` uses `window_words`/`stride_words` from the thresholds file if present, else 150/75.
Supports `--resume` (skips ids already in `--out`) because full runs take a while.

## 3. Thresholds — `calibration/thresholds.json` (committed; read by the server)

```json
{
  "version": "2026-10-07",
  "model_pair": {"observer": "...", "performer": "..."},
  "buckets": {
    "20-49":  {"ai_below": 0.70, "human_above": 1.00},
    "50-149": {"ai_below": 0.80, "human_above": 0.97},
    "150+":   {"ai_below": 0.85, "human_above": 0.95}
  },
  "segment": {"window_words": 150, "stride_words": 75, "flag_below": 0.85},
  "medians": {
    "human": {"top1_rate": 0.38, "top5_rate": 0.66, "mean_surprise": 2.9, "sentence_score_spread": 0.11},
    "ai":    {"top1_rate": 0.66, "top5_rate": 0.88, "mean_surprise": 1.8, "sentence_score_spread": 0.05}
  }
}
```

Band rules (server): `score < ai_below` → `likely_ai`; `score > human_above` → `likely_human`;
otherwise `uncertain`. Bucket by word count. If the file is missing or its `model_pair` differs
from the loaded models, every verdict is `uncalibrated`.

Fitting rules (calibration, on the `tune` split only):
- `ai_below`: the highest cutoff where at most 1% of human texts in that bucket fall below it,
  computed on every human subset together **and** on `non_native` alone; take the lower of the two.
- `human_above`: the lowest cutoff where at most 5% of AI texts in that bucket score above it.
  If it ends up below `ai_below`, set it equal to `ai_below` (no uncertain zone).
- `segment.flag_below`: same 1% rule applied to human windows.

## 4. Accuracy report — `calibration/report.json` (committed; served at `/api/accuracy`)

The shape in `docs/api-contract.md` → "Accuracy report", computed on the `heldout` split only.

## v1.1 amendments (2026-10-08)

- `squint-score` segment `start`/`end` are UTF-16 code units.
- A row that fails to score is written as `{"id", "error", "score": null, "model_pair"}`; skip it.
- Rows under 20 words are still scored; the fitting and report scripts must drop them.
