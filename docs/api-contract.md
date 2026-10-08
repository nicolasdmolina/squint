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
