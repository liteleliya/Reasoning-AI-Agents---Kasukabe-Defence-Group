# Analysing a paired run

    uv run python -m bench.paired_analysis <run dir> --out <dir> [--grades joined.csv] [--reps 2000]

`--grades` is the metrics file rejoined with rubric scores (`bench.grading rejoin`, see
`docs/cases.md`). Without it the automatic verdict is used; the verification report says how many
rows were graded by rubric, by the automatic check, or not at all.

## What it writes

| File | Content |
|---|---|
| `analysis.json` | verification report, outcome table, recovery funnel with reasons, paired comparisons, trace example ids |
| `outcome_table.csv` | one line per arm |
| `outcomes.png`, `funnel.png`, `paired.png` | outcome bars, replay funnel, paired rate differences |
| `inputs.json` | path, sha256 and row count of every input file, so a figure can be tied to its data |

## Definitions

- **Eligible**: the shared prefix reached an eligible recovery checkpoint. It is a property of the
  prefix, so every arm has the same eligible denominator.
- **Correct recovery**: eligible, the arm ended in consensus, and the final answer grades correct.
- **Terminal agreement**, **correctness** and **whether replay was attempted** are separate
  columns and are never inferred from each other (a replacement can help in the sandbox yet not be
  adopted, and an adopted reply can end in a wrong consensus).

## Paired comparison

Pairs are matched by case id and seed and kept only when both arms ran from an eligible prefix.
For replay against each control it reports wins, losses and ties on correct recovery, the rate
difference, and mean differences in total, intervention, input and output tokens and wall time.
The 95% interval resamples **case ids** with replacement and carries each case's seeds and arms
together. Fewer than 10 eligible pairs are flagged `small`: read the raw counts, not the interval.

## Before trusting the figures

Check `verification`: no duplicate trial keys, no unpaired case/seed units, and full-trial tokens at
least the posted tokens. Then open one row's session in the explorer and in SQLite and confirm that
its agreement, grade and recovery outcome match the table.

J3 is the historical pilot with zero rollbacks: if shown beside this study it supplies no estimate
of replay's effect.
