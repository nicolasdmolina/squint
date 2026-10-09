# Squint

A private web app that checks whether text was likely written by AI, and shows why.

It runs [Binoculars](https://arxiv.org/abs/2401.12070) locally on the Mac mini: two related
language models (Falcon-7B and Falcon-7B-Instruct, 4-bit) read the text, and the app compares
how predictable each word was against how predictable the models expected it to be.

- **Verdict**: Likely human / Uncertain / Likely AI, with the raw score. From 20 words; low
  confidence under 150 words.
- **% of text that looks AI-written**: from 150 words, using overlapping ~150-word windows.
- **Show me why**: word-level heat map, hover any word for the model's top 5 guesses and where
  the actual word ranked, per-sentence and per-paragraph leanings, plain-English reasons.
- **Tuned on** Claude and ChatGPT output against student essays, general prose and
  non-native English essays. Thresholds keep wrongly flagged human text at or below about 1%.

Status: in development. Private only; going public at `squint.nickymolina.com` waits for the
accuracy report and Nicky's OK.

## Known gaps

- **Current AI text is mostly missed.** At under 1% false flags, Binoculars caught 0 of 288
  ChatGPT and 32 of 289 Claude heldout samples. The fix is a trained classifier, built
  overnight on the mini (`classifier/`). See
  [`docs/known-gaps.md`](docs/known-gaps.md).
- **Gemini is untested.** Its samples have not been generated yet.

## Layout

| Path | What |
| --- | --- |
| `docs/api-contract.md` | The API between the web UI and the server. Change it first. |
| `server/` | Python service: Binoculars scoring, verdicts, queue, password, rate limit. |
| `web/` | The web UI. |
| `calibration/` | Building the tuning set, fitting thresholds, the accuracy report. Data is not committed. |
| `ops/` | Background service and tunnel templates. |

Nothing users submit is stored. Model files and datasets stay out of Git.
