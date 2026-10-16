# Squint

A private web app that checks whether text was likely written by AI, and shows why.

Everything runs locally on the Mac mini, with two methods:

- A **trained classifier** (ModernBERT-base fine-tuned on human, ChatGPT and Claude writing,
  built in `classifier/`) gives the verdict.
- [Binoculars](https://arxiv.org/abs/2401.12070) gives the word-level view: two related
  language models (Falcon-7B and Falcon-7B-Instruct, 4-bit) read the text, and the app compares
  how predictable each word was against how predictable the models expected it to be.

What you get:

- **Verdict**: Likely human / Uncertain / Likely AI, from 50 words; "Too short to tell" under
  50; low confidence under 150 words.
- **% of text that looks AI-written**: from 150 words, by running the classifier on
  overlapping ~150-word windows.
- **Show me why**: word-level heat map, hover any word for the model's top 5 guesses and where
  the actual word ranked, per-sentence and per-paragraph leanings, plain-English reasons.
- **Tested on** held-out human writing (including 512 non-native English essays) and ChatGPT
  and Claude output. At 50+ words it wrongly flagged 3 of 1,340 human texts (0 non-native),
  and caught 599 of 607 ChatGPT and 478 of 537 Claude samples.

Status: in development. Private only; going public at `squint.nickymolina.com` waits for the
accuracy report and Nicky's OK.

## Known gaps

- **Some Claude writing gets through**, mostly under 150 words (about 85% caught there,
  94% at 150+). Binoculars alone missed nearly all current AI text, which is why the trained
  classifier now gives the verdict. See [`docs/known-gaps.md`](docs/known-gaps.md).
- **Edited or paraphrased AI text** has not been tested.
- The 50-word minimum was chosen after looking at the evaluation results, and the evaluation
  sets were reused across runs, so a fresh test set would give a more honest number.
- **Gemini is untested.** Its samples have not been generated yet.

## Layout

| Path | What |
| --- | --- |
| `docs/api-contract.md` | The API between the web UI and the server. Change it first. |
| `server/` | Python service: Binoculars scoring, verdicts, queue, password, rate limit. |
| `web/` | The web UI. |
| `calibration/` | Building the tuning set, fitting thresholds, the accuracy report, and `classifier.json` (the promoted classifier's cutoffs). Data is not committed. |
| `classifier/` | Overnight classifier training, evaluation and `promote.py`. Weights go to `server/models/` (not committed). |
| `ops/` | Background service and tunnel templates. |

Nothing users submit is stored. Model files and datasets stay out of Git.
