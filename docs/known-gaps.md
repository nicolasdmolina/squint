# Known gaps

## Status (2026-10-15): the trained classifier sets the verdict

The ModernBERT-base classifier from the 2026-10-14 overnight run (`calibration/classifier.json`,
report `classifier/reports/2026-10-14-min50.json`) now decides verdicts for texts of 50+ words.
Binoculars still drives the word marks. Held-out results at 50+ words, re-checked on the
server's CPU path with identical counts:

- False flags: **3 of 1,340** human texts (0.22%), **0 of 512** non-native.
- ChatGPT caught: **599 of 607** (98.7%). Claude caught: **478 of 537** (89%).
- 50–149 words: ChatGPT 97.7% caught, Claude 85% caught and 12.7% called "Likely human".
- 150+ words: 0 of 587 human texts flagged, ChatGPT 100%, Claude 94%.
- Under 50 words the classifier wrongly flagged 2.9% of human texts, so Squint shows
  "Too short to tell" there.

Gaps that remain:

- **Claude in short texts.** About 1 in 8 Claude texts of 50–149 words is called "Likely human".
- **Selection bias.** The 50-word minimum was chosen after seeing the evaluation results, and
  the evaluation sets were reused across runs. A fresh set of human essays is needed for an
  honest re-check before public launch.
- **Untested:** Gemini, edited or paraphrased AI text, and new model versions released after
  the training data was generated.
- Combining the classifier with Binoculars (flag if either says AI) was worse: 0.8% false flags
  and 1.4% for non-native writers. Not used.

The history below explains why the classifier was needed.

## Current AI text is mostly missed by Binoculars alone

### Full heldout result (2026-10-08, Falcon-7B pair, `calibration/report.json`)

At thresholds that keep false flags under 1% (0.28% overall, 0 of 470 non-native), on 1,061
human and 577 AI heldout samples:

- ChatGPT: **0 of 288** caught. Claude: **32 of 289** (11%).
- By length, AI text was caught 0% at 20–49 words, 1% at 50–149 and 18% at 150+.
- 95% of human and 90% of AI samples land in "Uncertain".
- On 100 human essays from four sources never used for tuning (college essays, CS224N
  abstracts, Hewlett student essays, Ghostbuster essays): **0 wrongly flagged**, 83 Uncertain.

The 60-text spot check below was more optimistic about Claude. The full run replaces it.
Binoculars on a 4-bit Falcon pair can't separate 2026 frontier-model writing from human
writing at a 1% false-flag rate, so the trained classifier is the main path, not an add-on.


**Status:** needed before public launch. Tracked locally in
`.scratch/squint-chatgpt-classifier/spec.md`.

### What we found (2026-10-08)

- Binoculars (Falcon-7B pair) separates **Claude** text from human writing well, but
  **ChatGPT (gpt-6.1) text scores inside the human range**. In a 60-text spot check at the
  ≤1% false-flag threshold, it caught **1 of 12** ChatGPT samples.
- Swapping in the Qwen2.5-3B pair did not help: separation was about the same.
- A quick style classifier (character + word TF-IDF, logistic regression) reached about 90%
  on held-out rows from the **same** sources. On human essays from sources it had never seen,
  it wrongly flagged **27%, 68% and 61%** of them. It learned the corpora, not AI
  writing, so it was not shipped.
- Gemini samples were not generated (the generation path was blocked), so Gemini is untested.

### What Squint does today

It runs pure Binoculars and reports the honest numbers. The accuracy page must state per-source
catch rates, including the ChatGPT gap. "Tuned on ChatGPT" must not be read as "catches
ChatGPT".

### The fix

Train a transformer classifier, such as ModernBERT-base or DeBERTa-v3, to run beside
Binoculars:

1. **Human data from many sources:** student essays, non-native essays, forums, news, fiction
   and academic writing, so it can't shortcut on topic or format.
2. **Thousands of current ChatGPT samples**, plus Claude and Gemini, generated from the same
   prompts as the human texts and including "write like a student" and paraphrased variants.
3. **Evaluate on held-out sources** that are entirely absent from training. The gate is
   ≤1% false flags overall and for non-native writers on those sources.
4. **Combine with Binoculars** using a calibrated rule fitted on the tune split. Keep the
   word-level "why" view from Binoculars.
5. **Retrain** whenever a new major model version ships, and record the generator versions
   in the accuracy report.

Training should run on a rented GPU or the MacBook, not the 16 GB mini. Inference for a
base-size model fits on the mini alongside Falcon only if Falcon has headroom, so measure that
first.
