# Squint API contract (v1)

The web UI and the Python server meet here. Change this file first, then both sides.
All endpoints are same-origin under `/api`. JSON in, JSON out. Errors use
`{"error": {"code": "<snake_case>", "message": "<human sentence>"}}` with a matching HTTP status.

## Session (shared password)

- `GET /api/session` → `{"authenticated": bool, "password_required": bool}`
  - `password_required` is false in private/local mode (no password configured).
- `POST /api/login` `{"password": "..."}` → `204` and an HttpOnly, SameSite=Lax session cookie; `401 bad_password` otherwise.
  Login attempts are rate limited (`429 rate_limited`).
- `POST /api/logout` → `204`.
- Every other endpoint returns `401 auth_required` when a password is required and the cookie is missing.

## Status

`GET /api/status`

```json
{
  "model_state": "unloaded | loading | ready",
  "queue_length": 0,
  "model_pair": {"observer": "Falcon-7B (4-bit)", "performer": "Falcon-7B-Instruct (4-bit)"},
  "calibration": {"version": "2026-10-07", "ready": true},
  "limits": {"min_words": 20, "percent_min_words": 150, "max_words": 2500, "checks_per_hour": 30}
}
```

`calibration.ready` is false until thresholds have been fitted; the UI then shows a
"not tuned yet" notice and the server returns `verdict.band = "uncalibrated"`.

## Extract text from a file

`POST /api/extract` (multipart, field `file`, .docx / .pdf / .txt, max 10 MB)
→ `{"text": "...", "filename": "essay.docx", "word_count": 812}`.
The UI puts the text in the editor so the user can review it before analyzing.
Errors: `415 unsupported_file`, `413 file_too_large`, `422 no_text_found`.

## Analyze (queued job)

`POST /api/analyze` `{"text": "..."}` → `202 {"job_id": "j_...", "position": 0}`
Errors: `422 too_short` (< 20 words), `422 too_long` (> 2500 words), `429 rate_limited` (`retry_after_s`).

`GET /api/jobs/{job_id}` → poll every ~500 ms:

```json
{"job_id": "j_...", "status": "queued | loading_model | scoring | done | error",
 "position": 2, "result": null, "error": null}
```

`loading_model` means the first check after idle is waiting for the models (≈10–30 s).
Results are kept in memory for 10 minutes, then dropped. Nothing is written to disk.

## Result

```json
{
  "word_count": 412,
  "token_count": 531,
  "model_pair": {"observer": "...", "performer": "..."},
  "verdict": {
    "band": "likely_human | uncertain | likely_ai | uncalibrated",
    "label": "Likely AI",
    "confidence": "normal | low",
    "length_bucket": "20-49 | 50-149 | 150+",
    "score": 0.8123,
    "thresholds": {"ai_below": 0.8536, "human_above": 0.9500},
    "ai_percent": 64,
    "explanation": "One or two plain sentences on why this band."
  },
  "reasons": [
    {"kind": "predictability", "text": "71% of words were the model's first guess. In our human samples the median is 38%.", "weight": "strong | moderate | weak"}
  ],
  "stats": {
    "top1_rate": 0.71, "top5_rate": 0.9, "mean_surprise": 1.9, "mean_expected_surprise": 2.4,
    "sentence_score_spread": 0.05
  },
  "tokens": [
    {"i": 0, "start": 0, "end": 3, "text": "The",
     "surprise": 2.1, "expected_surprise": 3.0,
     "signal": 0.42, "signal_smooth": 0.31,
     "rank": 3,
     "top": [{"text": "This", "p": 0.21}, {"text": "In", "p": 0.12}, {"text": "The", "p": 0.09}, {"text": "A", "p": 0.05}, {"text": "As", "p": 0.04}],
     "sentence": 0}
  ],
  "sentences": [
    {"i": 0, "start": 0, "end": 118, "token_start": 0, "token_end": 24, "score": 0.79, "lean": "ai | neutral | human", "paragraph": 0}
  ],
  "paragraphs": [
    {"i": 0, "start": 0, "end": 640, "score": 0.82, "lean": "ai | neutral | human"}
  ],
  "segments": [
    {"start": 0, "end": 905, "word_start": 0, "word_end": 150, "score": 0.81, "flagged": true}
  ],
  "timing_ms": {"queue": 0, "load": 0, "score": 2140}
}
```

Field rules:

- `start`/`end` are character offsets into the exact submitted text (UTF-16 code units, so
  JavaScript `text.slice(start, end)` works). Tokens tile the text with no gaps or overlaps
  except leading/trailing whitespace; the UI renders the original text, wrapping token ranges.
- Binoculars score: lower = more AI-like. `score = Σ surprise / Σ expected_surprise` over a span
  (`surprise` = performer negative log-likelihood of the actual token, nats; `expected_surprise` =
  cross-entropy between observer and performer next-token distributions at that position).
- `signal` ∈ [-1, 1] per token for the heat map: positive = more predictable than the model
  expected (AI-like), negative = more surprising (human-like). `signal_smooth` is the same over a
  small window, for a calmer default view.
- `rank` = 1-based rank of the actual token in the performer's distribution (1 = the model's top
  guess). `top` = performer's five most likely tokens at that position.
- `lean` on sentences/paragraphs is a visual hint only, never a verdict; short spans are noisy.
- `verdict.ai_percent` = share of words inside `flagged` segments; `null` below 150 words, in
  which case `segments` is empty.
- `verdict.confidence` is `low` below 150 words.
- `reasons` are generated from numbers in `stats` against calibration medians; no LLM writes them.

## Accuracy report

`GET /api/accuracy` → the latest calibration report for the "How accurate is this?" page:

```json
{
  "version": "2026-10-07", "model_pair": {"observer": "...", "performer": "..."},
  "held_out": {"human": 420, "ai": 450},
  "false_flag_rate": {"overall": 0.008, "non_native": 0.009, "by_length": {"20-49": 0.0, "50-149": 0.006, "150+": 0.01}},
  "catch_rate": {"overall": 0.83, "by_source": {"chatgpt": 0.86, "claude": 0.79, "gemini": 0.84}, "by_length": {"20-49": 0.2, "50-149": 0.61, "150+": 0.9}},
  "uncertain_rate": {"human": 0.12, "ai": 0.1},
  "notes": ["Edited or paraphrased AI text was not tested; expect misses there."]
}
```

Returns `404 not_calibrated` before the first calibration run.

## v1.1 amendments (from the server build, accepted 2026-10-08)

1. The first token has no context, so it is never scored: `surprise`, `expected_surprise` and
   `rank` are `null`, `top` is `[]`, `signal`/`signal_smooth` are `0`.
2. When uncalibrated: `verdict.band = "uncalibrated"`, `label = "Not tuned yet"`,
   `verdict.thresholds = null`, `ai_percent = null`; `segments` are still returned with `flagged: false`.
3. `429 rate_limited` carries `retry_after_s` inside the `error` object and a `Retry-After` header.
4. Extra error codes: `400 invalid_request`, `400` missing upload field, `404 job_not_found`,
   `413 too_long` (JSON body over 1 MB), `503 busy` (queue full). Job-level `error.code` can be
   `model_unavailable`, `scoring_failed`, `too_long`, `too_short`.
5. `stats.sentence_score_spread` may be `null` (fewer than two sentences with ≥ 8 scored tokens).
6. `token_count` counts model tokens; `tokens[]` are display tokens (pieces of one character, such as
   an emoji, are merged), so `tokens.length` can be smaller than `token_count`.
7. The document `score` keeps the reference implementation's last-position term, so it can differ
   very slightly from Σ surprise / Σ expected_surprise over `tokens`.

## v1.2 amendments (trained classifier, 2026-10-15)

When `calibration/classifier.json` is present and valid (written by `classifier/promote.py`),
a ModernBERT classifier trained on human, ChatGPT and Claude writing sets the verdict. Without
it, the server behaves as in v1.1.

1. New band `too_short` (label "Too short to tell") for texts under `classifier.min_words`
   (50). The classifier is not run; tokens, sentences and reasons are still returned.
2. From 50 words: `likely_ai` when P(AI) > `ai_above`, `likely_human` when P(AI) <
   `human_below`, otherwise `uncertain`. The Binoculars `score` and `thresholds` are still
   returned for the word view but no longer set the band.
3. New verdict fields: `detector` (`"classifier"` or `"binoculars"`) and `classifier`
   (`{ai_probability, ai_above, human_below, min_words, version}`, or `null` under Binoculars).
   `ai_probability` is `null` for `too_short`.
4. `segments[].flagged` comes from running the classifier on each 150-word segment
   (P(AI) > `ai_above`); `ai_percent` follows from those flags. `segments[].score` stays the
   Binoculars score.
5. `reasons` starts with a `detector` reason when the classifier is on.
6. `GET /api/status` adds `"classifier": {"version": "...", "ready": true, "min_words": 50}`
   (`{"version": null, "ready": false, "min_words": null}` when it is off).
7. `GET /api/accuracy` adds `classifier`: `{version, model, min_words, held_out, by_length}`
   from `classifier.json`. `held_out` has `false_flags`, `false_flags_non_native` and
   `chatgpt_catch` as `{n, flagged, rate, ci95}`; `by_length[bucket]` has `humans`,
   `false_flag`, `humans_likely_human` and per generator `{n, caught, called_human}`.
8. The classifier runs on the CPU, loads with the model pair on the first check and unloads
   with it. If it fails to load, the server falls back to Binoculars verdicts.
