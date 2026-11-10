# Cases, agreement and grading

Roadmap sections 06 and 07. Everything here runs offline once the dataset files are cached.

## Layout

| Path | Seen by agents? | Holds |
|---|---|---|
| `data/cases/public/<id>.json` | yes | question, context, labelled evidence (`E1`, `E2`, ...), the decision vocabulary and the values to state |
| `data/cases/grading/<id>.json` | **no** | acceptable decisions, material conditions (regex hints), fatal errors, required evidence, rubric version |
| `data/cases/splits.json` | no | the dev and held-out item ids (authored, choice, open) |

A case is two files with the same id. `bench.cases.load_cases()` checks the pair against each other
(every acceptable decision is in the vocabulary, every critical rule names a real field, every
pattern compiles) and hashes both folders into a manifest `version`. `run.json` records that
version and a hash of `splits.json`.

Twelve authored cases: four development (`restore-p1`, its unbounded variant, `patch-window`,
`refund-window`) and eight held-out. The toy X/Y/Y recovery fixture is not part of them.

## What an agent answers

The prompt is rendered by `bench.cases.question_for` from the public record only. The
`prediction` is the decision, then each requested value:

    B; downtime=2 min; data_loss=30 s; lag_check=before

and the explanation carries the justification and the evidence IDs cited.

## Agreement

`bench.authored.judge(case, grading)` gives the scheduler's `same_answer` and the automatic
verdict. Durations become seconds and amounts lose currency marks, so `2 min` equals `120 s`.
Two answers agree when the decision and every field marked `decisive` match, so
"B, but only after checking lag" differs from plain B when `lag_check` is decisive. A missing or
invalid required part is **unresolved** and agrees with nothing, itself included. The scheduler and
both sandbox forks use this same comparator.

`agreement_basis` in `metrics.csv` says how each trial's agreement was decided: `exact`, `key`
(authored) or `approximate` (open QA, lexical overlap only).

## Automatic check versus rubric

The automatic check (`correct`) is only: the decision is acceptable and no fatal rule fires. It
does not read the justification. The rubric does.

## Grading workflow

1. `uv run python -m bench.grading export configs/<job>.json --run <run dir> --out <dir> --double 12`
2. Give graders `sheet.csv` (and `sheet_double.csv` to two people). They see a grading ID, the
   public prompt, the answer and its explanation, never the condition, session or verdict.
   Score conclusion, evidence, constraints and justification as 0, 1 or 2, and set `critical`
   to yes when a fatal error is present.
3. A response passes at **6 of 8 with no critical violation**. Freeze this rule after development.
4. `bench.grading.reconcile` lists what the two graders disagree on; resolve it by changing the
   rubric or evidence, not by averaging.
5. `uv run python -m bench.grading rejoin --run <run dir> --private <dir>/private.json --scores
   <scores.csv> --out <joined.csv>` adds `rubric_total`, `rubric_pass`, `rubric_critical`.

`private.json` also holds prefilled hints (conditions matched, evidence IDs not cited, fatal rules
fired). Keep it away from graders.

## Productive revisions

`productive_revisions` counts replies that answer a REFUTE or REJECT with a new answer and new
reasoning, where the group's distance falls within the reply and the next three real replies (or a
consensus stop comes first). Strong and Ultra-Strong labels are unchanged.

## Items from the dataset

`uv run python -m bench.splits` ranks items by a hash of their id and picks 8 held-out and a few
development items per kind, round-robin over groups. Open items are only pre-screened (reference
length); a person still reads them for sufficient evidence before the list is frozen. The open pool
is the cached automotive Easy stages: `Automotive Value Chain/Easy/Supply Chain` is invalid JSON
at the source, and each file is about 30 MB, so other domains are added on demand.

## Before the held-out run

Have two people grade a correct, a plausible wrong and a paraphrased response for each case type
and fix any disagreement in the rubric first. Do not choose held-out cases by how much replay
activity they showed.
