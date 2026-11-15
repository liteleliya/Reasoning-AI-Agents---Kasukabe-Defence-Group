# Why the study uses a 3B model and a designated dissenter

The roadmap's study needs debates that stall with a challenged reply (the recovery checkpoint).
Screening prefix-only runs (about 20 s each, `bench.screen`) on development items:

| Setup | Prefixes | Started in disagreement | Ended in consensus | Checkpoint opened |
|---|---|---|---|---|
| 7B, default personas, T0.7 (first dev batch) | 12 | 0% | 75% | 0 |
| 7B, default personas, T1.0 | 38 | 21% | 95% | 0 |
| 7B, divergent personas, T1.0 | 38 | 16% | 100% | 0 |
| 7B, designated dissenter, T1.0 | 38 | 24% | 97% | 1 |
| 3B, default personas, T1.0 | 38 | 24% | 89% | 3 |
| **3B, designated dissenter, T1.0, window 4** | 38 | n/a | 79% | **6 (16%)** |

J3 (7B, 120 sessions) recorded zero rollbacks. With 7B, agents rarely disagree and give way within
one or two replies, so there is nothing for replay to recover from.

Consequences to state in the write-up:

- The study measures replay under a setup that was **chosen to produce stalls** (smaller model plus
  a designated dissenter), not under natural stall rates.
- Authored cases stall far more often than choice items (5 of 8 against 1 of 30 in the last screen),
  so the eligible set is dominated by authored cases.
- The setup was tuned on development items only; the held-out items were never screened.
- Open-ended items often end in "impasse" with every agent ratifying, because the lexical agreement
  check scores similar answers as different. They have no challenged reply, so they are never eligible.
