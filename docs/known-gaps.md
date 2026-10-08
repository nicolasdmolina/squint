# Known gaps

## ChatGPT text is mostly missed (needs a trained classifier)

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
