#!/usr/bin/env bash
# Squint calibration pipeline: dataset -> squint-score -> fit -> report.
#
#   calibration/run_all.sh                 # every stage, in order (each one resumable)
#   calibration/run_all.sh fit report      # only the named stages
#   SQUINT_PROFILE=falcon-7b calibration/run_all.sh score fit report
#
# SQUINT_PROFILE picks the model profile from server/squint.toml for the score stage (unset:
# the [models].profile default there). Thresholds are only valid for the pair that produced
# the scores; fit refuses a scores file that mixes pairs, so use a fresh --out per profile.
#
# Stages:
#   human     download + sample pre-ChatGPT human texts      -> data/human_base.jsonl
#   plan      AI writing plan mirroring the human prompts     -> generated/plan.jsonl
#   generate  AI texts via codex / claude / gemini CLIs       -> generated/ai_<source>.jsonl
#   build     excerpts, mixed docs, tune/heldout split        -> data/all.jsonl, data/manifest.json
#   score     server's batch scorer (same code path as app)   -> data/scores.jsonl
#   fit       thresholds from the tune split                  -> thresholds.json
#   report    accuracy on the heldout split                   -> report.json
#   test      unit tests for the scripts
#
# The generate stage uses Nicky's logged-in CLIs and never logs in; a source whose CLI fails
# auth is skipped and recorded in generated/status.json.
set -euo pipefail

CAL="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$CAL")"
PY=(uv run --python 3.12)
stages=("$@")
[ ${#stages[@]} -eq 0 ] && stages=(human plan generate build score fit report)

for stage in "${stages[@]}"; do
  echo "== $stage"
  case "$stage" in
    human)    "${PY[@]}" "$CAL/fetch_human.py" ;;
    plan)     "${PY[@]}" "$CAL/generate_ai.py" plan ;;
    generate)
      # sources run one after another; each source's calls are sequential with backoff
      for src in chatgpt claude gemini; do
        "${PY[@]}" "$CAL/generate_ai.py" run --source "$src" || echo "generate $src failed; continuing"
      done ;;
    build)    "${PY[@]}" "$CAL/build_dataset.py" ;;
    score)
      profile_args=()
      if [ -n "${SQUINT_PROFILE:-}" ]; then
        profile_args=(--profile "$SQUINT_PROFILE")
        echo "score: profile $SQUINT_PROFILE (from SQUINT_PROFILE)"
      else
        echo "score: SQUINT_PROFILE not set; using the [models].profile default in server/squint.toml"
      fi
      (cd "$ROOT/server" && uv run squint-score ${profile_args[@]+"${profile_args[@]}"} \
          --in ../calibration/data/all.jsonl --out ../calibration/data/scores.jsonl --resume) ;;
    fit)      "${PY[@]}" "$CAL/fit_thresholds.py" ;;
    report)   "${PY[@]}" "$CAL/report.py" ;;
    test)     (cd "$ROOT" && uv run --no-project --python 3.12 python -m unittest discover -s calibration/tests -v) ;;
    *) echo "unknown stage: $stage" >&2; exit 2 ;;
  esac
done
