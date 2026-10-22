# Learner samples: fresh re-check, 2026-10-22

The 2026-10-16 fresh check found Claude writing "as a B1 learner" was caught only 65% of the
time. Learner prompts (variant `learner`, commit 118b2fe) were generated on 2026-10-17 and
went into the 10-18 and 10-19 training runs. This scores the same fresh sets as the 10-16
check with each run's own cutoffs (classifier-only `ai_above`, `human_below` as promote.py
would set it). Scored on MPS in fp32; the 10-16 numbers for the live model reproduce exactly.

| Model | Claude "as a B1 learner" caught (n=20) | Claude, all fresh (n=120) | ChatGPT, all fresh (n=75) | Fresh humans flagged (n=1,000) |
|---|---|---|---|---|
| live e1d93574 (10-14) | 65% | 89.2% | 98.7% | 0 |
| f37cef8b (10-18) | 90% | 96.7% | 98.7% | 1 (Reddit ELI5) |
| e63ce997 (10-19) | 100% | 94.2% | 100% | 3 (2 Reddit ELI5, 1 finance) |

Held-out false flags in the nightly reports: live 3/1,340, 10-18 4/1,340, 10-19 6/1,340.

10-18 fixes most of the learner gap for one extra false flag on fresh humans. 10-19 closes it
fully but flags three fresh human texts and does worse on Claude's ELI5 answers. Both are small
samples. For 10-18, the `human_below` rule lands at the `ai_above` cutoff, so it has no
"uncertain" band; promote.py would give every 50+ word text a firm verdict.
