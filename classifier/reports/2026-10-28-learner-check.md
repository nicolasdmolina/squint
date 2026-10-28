# Learner samples: fresh re-check, 2026-10-28

Same check as [2026-10-22](2026-10-22-learner-check.md), for the runs since: the fresh sets
from the 10-16 check (detokenized humans, 981 texts; fresh ChatGPT and Claude pieces of 50+
words), scored on MPS in fp32 with each run's own classifier-only cutoff from its report.

| Model | Claude "as a B1 learner" caught (n=20) | Claude, all fresh (n=120) | ChatGPT, all fresh (n=75) | Fresh humans flagged (n=981) |
|---|---|---|---|---|
| f37cef8b (10-18, was live) | 100% | 96.7% | 98.7% | 1 (Reddit ELI5) |
| 2ba047ff (10-27, promoted) | 95% | 96.7% | 100% | 1 (Reddit ELI5) |
| 44101a1f (10-28) | 100% | 97.5% | 100% | 2 (both Reddit ELI5) |

The 10-18 learner number is 100% here against 90% on 10-22; the cause was not traced (this
run used the detokenized human file and each report's cutoff). With n=20 one text is 5
points, so the learner column cannot separate these runs.

Held-out reports (50+ words): 10-18 caught Claude 92.2%, ChatGPT 99.6%, flagged 4 of 1,340;
10-27 caught Claude 95.4%, ChatGPT 99.5%, flagged 3 of 1,340 and 0 of 512 non-native.

10-27 was promoted on 2026-10-28: better on held-out sources, equal on fresh humans and the
Claude fresh set. 10-28 flags one more fresh human and, on held-out sources, 7 of 1,340
humans and 2 of 512 non-native essays, so it waits for a later comparison. 10-18 stays in
`server/models/classifier/` for rollback.
