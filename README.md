# Squint

Checks whether text was likely written by AI, and shows why.

Try it at **[squint.nickymolina.com](https://squint.nickymolina.com)**. The site runs the
classifier only (verdict, % AI, flagged passages; up to 500 words). The full version with the
word-level heat map runs on your own Mac: see [Run it on your Mac](#run-it-on-your-mac).

Squint uses two methods, both running locally:

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
  and Claude output. At 50+ words it wrongly flagged 4 of 1,340 human texts (1 of 512 non-native),
  and caught 744 of 747 ChatGPT and 674 of 731 Claude samples.

Status: live as a public preview. The accuracy target in [`docs/roadmap.md`](docs/roadmap.md)
(GPTZero-level: at least 97% of AI text caught, at most 1% of any kind of human writing flagged)
is not met yet; college essays are the main gap below.

## Run it on your Mac

Needs an Apple Silicon Mac. The word heat map needs 16 GB of memory and about 11 GB of disk;
with less memory Squint runs the classifier only.

A packaged `Squint.app` is coming on the [releases page](https://github.com/nicolasdmolina/squint/releases).
To run from source now, see [`server/README.md`](server/README.md).

## Known gaps

- **College essays are sometimes flagged.** About 4–6% of a set of 70 real college essays were
  wrongly flagged as AI, against about 0.4% for other human writing. Don't use Squint alone to
  judge a personal statement. See R1 in [`docs/roadmap.md`](docs/roadmap.md).
- **Some Claude writing gets through**, mostly under 150 words (about 90% caught there,
  95% at 150+). Binoculars alone missed nearly all current AI text, which is why the trained
  classifier now gives the verdict. See [`docs/known-gaps.md`](docs/known-gaps.md).
- **Edited or paraphrased AI text** has not been tested.
- **Older or other AI models** are mostly missed: 2022-era ChatGPT answers got through almost
  every time. A fresh re-check on new sources matched the main results for current ChatGPT
  and Claude, with 0 of 1,000 new human texts flagged.
- **Gemini is untested.** Its samples have not been generated yet.

## Layout

| Path | What |
| --- | --- |
| `docs/api-contract.md` | The API between the web UI and the server. Change it first. |
| `server/` | Python service: Binoculars scoring, verdicts, queue, rate limit, `preview` mode for the public site. |
| `web/` | The web UI. |
| `calibration/` | Building the tuning set, fitting thresholds, the accuracy report, and `classifier.json` (the promoted classifier's cutoffs). Data is not committed. |
| `classifier/` | Overnight classifier training, evaluation and `promote.py`. Weights go to `server/models/` (not committed). |
| `ops/` | Background service, tunnel and edge Worker (`ops/edge/`) for the public site. |

Nothing users submit is stored. Model files and datasets stay out of Git.

## License and credits

Code: MIT ([`LICENSE`](LICENSE)). Classifier weights: CC BY-NC-SA 4.0, following the most
restrictive training source. Every model and dataset is credited in
[`MODEL_LICENSE.md`](MODEL_LICENSE.md).

Built by Nicky Molina.
