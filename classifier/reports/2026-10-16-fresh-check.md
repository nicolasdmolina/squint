# Fresh re-check, 2026-10-15/16

Classifier `modernbert-base-e1d93574b0af18b2` (calibration/classifier.json, version
2026-10-14-min50), scored on the server's CPU path with the live cutoffs
(Likely AI above 0.998849, Likely human below 0.995462). Every text has 50+ words. None of
the sources or prompts were used in training, tuning or the earlier evaluation; an
exact-prefix check found no overlap with the training dataset.

## Human writing (all written before ChatGPT)

| Set | Texts | Flagged as AI | Likely human |
|---|---|---|---|
| W&I learner essays, CEFR A | 200 | 0 | 100% |
| W&I learner essays, CEFR B | 200 | 0 | 100% |
| W&I learner essays, CEFR C | 200 | 0 | 100% |
| LOCNESS native student essays | 50 | 0 | 100% |
| HC3 Reddit ELI5 answers | 200 | 0 | 99% |
| HC3 finance answers | 150 | 0 | 100% |
| **All** | **1,000** | **0** | |

0 of 1,000 (95% upper bound about 0.3%); 0 of 600 non-native. The highest P(AI) among
them was 0.979, far under the cutoff. HC3 human answers come word-split ("does n't",
" ."); they were re-joined before scoring, which did not change the result.

## Current AI writing on the same fresh prompts

Generated 2026-10-15 with the usual driver (calibration/generate_ai.py) into
classifier/generated/fresh-eval/: HC3 ELI5 and finance questions, and 20 Write &
Improve-style tasks written plainly and "as a B1 learner". ChatGPT stopped at 75 of 120
pieces at the run's deadline.

| Generator | Set | Texts | Caught | Called Likely human |
|---|---|---|---|---|
| ChatGPT (gpt-6.1-sol) | all | 75 | 98.7% | 1.3% |
| Claude (opus-5-5) | ELI5 answers | 40 | 95% | 0% |
| Claude | finance answers | 40 | 92.5% | 7.5% |
| Claude | class essays | 20 | 95% | 5% |
| Claude | "as a B1 learner" | 20 | 65% | 30% |
| Claude | all | 120 | 89.2% | 8.3% |

These match the held-out numbers (ChatGPT 98.7%, Claude 89%), so the earlier results were
not just the classifier learning our own prompt set.

## Older ChatGPT is missed

The ChatGPT answers in HC3 (December 2022, GPT-3.5) were caught 1 of 350 times; 99% were
called Likely human. The classifier knows current model output, not AI writing in general.
Older or other models (Gemini, open models) should be treated as untested, and retraining
is needed when ChatGPT or Claude change noticeably.

## Weak spot

Claude asked to write like an intermediate English learner gets past it about a third of
the time. Adding more "write as a learner" samples to training is the obvious next step.

Licences: W&I and LOCNESS are for non-commercial research; the texts stay in
classifier/data/fresh/ (not in Git) and only aggregate numbers are reported here.
