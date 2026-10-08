# Squint server

FastAPI service that runs Binoculars locally (llama.cpp on Metal), turns the numbers into the
result described in `../docs/api-contract.md`, and serves the built web UI from `../web/dist/`.
It is one process with a single scoring worker. Results stay in memory for 10 minutes and nothing
users submit is written to disk.

## Commands

```sh
cd server
uv sync                                  # Python 3.12 venv + deps (llama-cpp-python builds with Metal)
uv run squint-models list                # profiles and which model files are present
uv run squint-models download --profile qwen2.5-0.5b-standin   # refuses if < 5 GB would stay free
uv run squint-models verify              # load the pair, compare vocabularies, score a sample
uv run squint-server                     # http://127.0.0.1:8017 (refuses if the port is taken)
uv run pytest                            # tests; real-model tests skip when files are absent
uv run squint-score --in ../calibration/data/all.jsonl --out ../calibration/data/scores.jsonl [--resume]
```

`squint-score` follows `../docs/calibration-format.md` §2 and uses the same `score_text` +
`Analysis` code as the web app. `--resume` skips ids already in `--out` (and drops a half-written
last line); `--overwrite` starts again; `--limit N` scores the first N rows.

## Model pair

The pair is chosen in `squint.toml` (`[models].profile`, or `SQUINT_PROFILE`). Each profile names
the observer and performer GGUF files, the Hugging Face `tokenizer.json` (used for offsets and
token ids, as in the reference code), display labels and context/batch sizes.

| Profile | Observer / performer | Disk | Use |
| --- | --- | --- | --- |
| `falcon-7b` | `mradermacher/falcon-7b-GGUF` + `mradermacher/falcon-7b-instruct-GGUF`, `Q4_K_M` | 2 × 4.98 GB | production |
| `qwen2.5-0.5b-standin` | `mradermacher/Qwen2.5-0.5B(-Instruct)-GGUF`, `Q8_0` | 2 × 0.51 GB | development |

Switching to Falcon needs no code change:

1. `uv run squint-models download --profile falcon-7b --dry-run`, then without `--dry-run`
   (about 10 GB; it refuses if less than 5 GB would remain free).
2. `uv run squint-models verify --profile falcon-7b`
3. Set `[models].profile = "falcon-7b"` (or `SQUINT_PROFILE=falcon-7b`) and restart.
4. Re-run calibration: `thresholds.json` only applies when its `model_pair` equals the profile's
   labels. Until then every verdict is `uncalibrated`.

Expected memory with the Falcon Q4_K_M pair: about 10 GB of weights plus a few hundred MB of
Metal buffers and logits, roughly 11–11.5 GB peak. Metal's working-set limit on the 16 GB mini
is 12.7 GB, so close other heavy apps while it is loaded. The pair unloads after 10 idle minutes.

## Configuration

`squint.toml` holds server settings and limits. Environment overrides: `SQUINT_CONFIG`,
`SQUINT_PROFILE`, `SQUINT_HOST`, `SQUINT_PORT`, `SQUINT_IDLE_UNLOAD_S`, `SQUINT_RESULT_TTL_S`,
`SQUINT_CALIBRATION_DIR`, `SQUINT_WEB_DIST`, `SQUINT_KEYCHAIN_SERVICE`, `SQUINT_LOG_LEVEL`.

Password: if a Keychain generic-password item `squint-password` exists, it is read once at
startup (`security find-generic-password -s squint-password -w`) and every API call except
session/login/logout needs the signed session cookie. Without the item the app runs in private
mode (`password_required: false`). The server never creates the item. If the Keychain can't be
read for another reason (locked, access denied) the server refuses to start rather than run open.
Sessions are signed with a per-process key, so restarting signs everyone out.

Rate limits: 30 analyses per hour per client (`CF-Connecting-IP`, else the socket address);
5 failed logins per 15 minutes per client, 50 per hour overall.

## How scoring works

- Tokens: the Hugging Face tokenizer gives ids and character offsets; both models run over the
  same ids in one forward pass each (windows of 2048 tokens with 512 tokens of overlap for long
  texts), in micro-batches whose logits are reduced right away to per-token surprise, expected
  surprise (observer/performer cross-entropy), rank and top-5.
- The global score is exactly the reference `Binoculars.compute_score` for an unpadded text:
  mean performer NLL over tokens 1..n-1 divided by mean cross-entropy over positions 0..n-1.
  Spans (sentences, paragraphs, 150-word segments) use Σ surprise / Σ expected surprise.
- Token 0 has no context and is unscored (`null` surprise/rank, empty `top`, `signal` 0).
- Display tokens merge byte-level pieces of one character (emoji, CJK, combining marks) and tile
  the text; offsets are UTF-16 code units.
- `signal` = tanh((c·expected − surprise) / 2) where c is the middle of the bucket's thresholds
  (the paper's thresholds while uncalibrated); `signal_smooth` uses a 7-token weighted window.

## Layout

| Path | What |
| --- | --- |
| `src/squint/app.py` | Routes, auth, limits, static files |
| `src/squint/jobs.py` | Single-worker queue, lazy load, idle unload, result expiry |
| `src/squint/backend.py` | llama.cpp pair and the Binoculars reductions |
| `src/squint/analysis.py` | Result and `squint-score` rows from per-token numbers |
| `src/squint/textproc.py` | Tokenizer, display tokens, UTF-16 offsets, sentences, paragraphs |
| `src/squint/calibration.py`, `reasons.py` | Thresholds, bands, reason text |
| `src/squint/extract.py` | .docx / .pdf / .txt text extraction, in memory |
| `src/squint/cli.py` | `squint-server`, `squint-score`, `squint-models` |
| `models/` | Model files (not in Git) |
