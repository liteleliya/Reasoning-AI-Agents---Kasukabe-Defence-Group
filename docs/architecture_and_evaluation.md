# Project documentation: Architecture And Evaluation

---

<!-- Consolidated from `metrics.md`; original section content preserved. -->

# Per-trial metrics CSV

One row per finished trial (one instance x config x seed), written by `bench.metrics.MetricsWriter`.
The file is append-only and fsynced per row; `trial_key` is unique and is what a resumed run skips.

| Column | Meaning |
|---|---|
| `trial_key` | `config|benchmark|instance_id|seed` |
| `config` | Name of the experiment config (e.g. `cf-33`) |
| `benchmark`, `domain`, `instance_id` | Which question |
| `seed` | Random seed of the trial |
| `model` | Model id used by the agents |
| `n_agents`, `n_counterfactual`, `cf_share` | Independent variable: share of counterfactual-enabled agents |
| `session_id` | Session in the event log (for drilling into the UI) |
| `stop_reason` | `consensus`, `impasse` or `cap` |
| `converged` | H1: `stop_reason == consensus` |
| `answer` | The session's final answer: the consensus answer, else the most common latest prediction |
| `correct` | Judge verdict on the consensus answer (D2); empty if not judged |
| `messages` | Agent messages including INIT (no system, no rollback events) |
| `cycles` | Reply messages / `n_agents` (rounds of discussion) |
| `ratify`, `refute`, `revise`, `reject` | Tag counts over real messages |
| `rollbacks` | Number of `rollback_start` events |
| `incompatible` | Messages that broke the compatible-agent transitions (validator warnings) |
| `rejected` | Agent messages the validator refused (off-protocol) |
| `failed_replies` | Model replies still unparseable after one repair retry (the agent passed) |
| `intelligibility` | H2: `ultra_strong`, `strong` or `failed` (spec section 3) |
| `tokens_in`, `tokens_out` | Tokens of events on the board, including rollback events |
| `unposted_tokens` | Tokens of failed replies that never reached the board |
| `total_tokens` | H3: `tokens_in + tokens_out + unposted_tokens` |
| `rollback_tokens_in`, `rollback_tokens_out` | Of which spent inside counterfactual replays |
| `wall_time_s` | Wall-clock time of the trial |
| `stop_detail` | Why the stop reason applied: `consensus`, `message_cap`, `no_progress`, `debate_stall`, `all_passed` or `failed_turns` (spec section 4.1) |
| `decision_seq` | Last committed event when the stop was decided |
| `ledger_calls` | Model calls in the trial's call ledger (`calls.jsonl`); empty when no ledger was kept |
| `ledger_tokens_in`, `ledger_tokens_out` | Tokens over every call, including calls that failed to parse, were refused or were spent in the sandbox |
| `ledger_unposted_tokens` | Of those, tokens of calls no event lists in `meta.call_ids` |
| `ledger_missing` | Calls whose usage is unknown (they failed before a reply); they add no tokens |
| `agreement_basis` | How agreement was decided: `exact` (letters, judgment), `key` (authored decision key) or `approximate` (open QA lexical overlap; not a verified key) |
| `productive_revisions` | Replies that answer a challenge with a supported change and lower the group's distance within the next three real replies (or by a consensus stop). Separate from the Strong/Ultra-Strong `intelligibility` label |
| `arm` | `standard`, `forward` or `replay` in a three-arm paired trial; blank otherwise |
| `checkpoint` | `opened` if the shared prefix reached an eligible recovery checkpoint, else `none` (all arms then share the ordinary terminal outcome) |
| `skip_reason` | Why the checkpoint did not open or the policy did not run |
| `recovery_outcome` | What the arm's policy ended with (`reply_accepted`, `not_helpful`, `no_reply`, ...) |
| `credit_delta` | Replay arm: replacement minus original distance on the matched forks (unrounded) |
| `prefix_tokens` | Model tokens spent on the shared prefix; already inside `total_tokens` of every arm |
| `intervention_calls`, `intervention_tokens` | Model calls and tokens spent after the shared trigger |
| `grading_tokens` | Offline grading cost; never part of `total_tokens` |

With a ledger, `total_tokens` is `ledger_tokens_in + ledger_tokens_out`: every call once. The board
tokens (`tokens_in`, `tokens_out`) are the subtotal of calls that events list in `meta.call_ids`,
so `total_tokens = tokens_in + tokens_out + ledger_unposted_tokens`. Calls with estimated usage are
included; the ledger row marks them `estimated`. Without a ledger the old definition applies.
The identity holds for the checkpoint recovery path; the older opportunistic replay posts its
tokens without call ids, so for those runs `ledger_unposted_tokens` also counts calls that are on
the board, and only `total_tokens` is exact.

A `metrics.csv` written before these columns existed has a different header: the writer refuses
to append to it, so write a resumed run to a new folder.

## Call ledger (`calls.jsonl`)

One JSON line per model request, written at the client boundary, so failed and unparseable calls
are kept.

| Field | Meaning |
|---|---|
| `call_id` | `call-<n>`, unique within one client |
| `trial`, `session_id` | Which trial and session the call belongs to |
| `phase` | `debate`, `candidate` or `branch` |
| `branch` | `original` or `replacement` for branch calls |
| `repair` | The retry sent after an unusable reply |
| `parent_seq` | The message the call was made to answer |
| `agent` | Who made the call |
| `status` | `ok` or `error` |
| `usage` | `reported`, `estimated` or `missing` |
| `prompt_tokens`, `completion_tokens` | Null when usage is missing |
| `latency_s`, `detail` | Latency, and the error text for failed calls |

---

<!-- Consolidated from `paired_runner.md`; original section content preserved. -->

# Three-arm paired runner

Roadmap section 08. A job config with `"arms": ["standard", "forward", "replay"]` runs this way:

    uv run python -m bench.run configs/paired_dev.json --mock --limit 6 --out results/paired-smoke
    uv run python -m bench.run configs/paired_dev.json            # real model, see docs/project_research.md

## What happens per (item, seed)

1. **Prefix.** The question is played with no intervention until the scheduler's recovery
   checkpoint (a stalled, disagreeing board with a challenged reply). That session
   (`<job>-prefix|...`) is saved as it is, once, and reused on resume.
2. **Arms.** Each arm gets its own session (`<job>-<arm>|...`) holding a copy of the prefix with
   the same sequence numbers, and the scheduler's turn loop (`Scheduler.resume`) continues it:

   | Arm | At the trigger |
   |---|---|
   | `standard` | the challenged author answers its challenger in the ordinary way |
   | `forward` | the same, with a prompt saying the reply was challenged and asking it to rethink |
   | `replay` | the reply is replayed on two matched sandbox forks; a helpful replacement is adopted as a real reply |

3. **No eligible checkpoint.** If the prefix agreed or capped before stalling, all three arms share
   the ordinary terminal outcome (`checkpoint = none`, no intervention calls).

Everything is serial: agents are asked one at a time and `--parallel` must stay 1.

## Output folder

`metrics.csv` (one row per completed arm, see `docs/architecture_and_evaluation.md`), `board.sqlite` (prefix and arm
sessions), `calls.jsonl` (every model call, labelled by session), `opportunities.jsonl` (the
checkpoint record per session: eligibility, skip reason, outcome, replay details) and `run.json`.

## Cost accounting

`total_tokens` of an arm includes the prefix; `prefix_tokens` shows how much that was and
`intervention_calls` / `intervention_tokens` what was spent after the trigger. `allowance_calls`
(default 6) is a shared hard limit on model requests after the checkpoint. It covers the control
response or replay candidate, repairs, both sandbox branches and subsequent live turns. A blocked
request is recorded as `skipped`, never sent to the model, and excluded from model-call and token
totals. `wall_time_s` is the machine's actual time and is kept separate.

## Resume

Rerunning the same command skips arms that already have a row and reuses the saved prefix, so the
remaining arms start from the identical state. A session left half-finished by a crash is
ignored and the arm restarts in a new session (`~r1`).

## Restoring agent state

Agents are rebuilt from the same config (persona, temperature, per-agent seed). The only
turn-affecting state they carry is the credit-assignment `notes` list, which is empty at the
checkpoint because the legacy opportunistic replay is not used here.

## Smoke test order

1. The scripted case (`tests/test_paired.py`) runs offline.
2. A development batch (`configs/paired_dev.json`: authored, choice and open dev items) on the real
   model. Check the prefix is identical across arms, the controls stay inside the allowance, and
   each arm has one row joined to its board.
3. If few checkpoints open, read `skip_reason` and `opportunities.jsonl` before scaling.

---

<!-- Consolidated from `recovery_fixture.md`; original section content preserved. -->

# Recovery fixture (X/Y/Y)

A toy three-agent case that pins down the scheduler, sandbox, metrics and viewer with one trace.
Code: `src/counterfactual/fixture.py`. Tests: `tests/test_recovery_fixture.py`. It is not part of
the benchmark.

**Case.** Service must be restored within a four-minute downtime limit. Plan X takes six minutes,
Plan Y takes two. The known answer is Y. A insists on X; B and C defend Y.

## The stalled prefix (messages #0-#8)

| Seq | Author | Tag | Replies to | Prediction | Meaning |
|---|---|---|---|---|---|
| 0-2 | A, B, C | INIT | - | X, Y, Y | two answer groups |
| 3 | A | REFUTE | 1 | X | |
| 4 | B | REFUTE | 3 | Y | |
| 5 | C | RATIFY | 4 | Y | every agent has now replied; disagreement is 1/3 |
| 6 | A | REFUTE | 4 | X | **replay target** |
| 7 | B | REFUTE | 6 | Y | **challenger** of #6 |
| 8 | C | RATIFY | 7 | Y | with a three-reply window the board stalls |

Replacing #6 with a REVISE that accepts the four-minute limit gives Y/Y/Y in the sandbox, so the
credit is 0 - 1/3 = -1/3 (negative means the alternative helps).

## Demo database

```bash
uv run python -m counterfactual.fixture --db results/roadmap_fixture.sqlite
uv run python -m server --db results/roadmap_fixture.sqlite
```

Both sessions are produced by the normal scheduler with the same scripted agents. Only the
recovery policy differs, so the checkpoint, the matched branches and the adoption are the real
ones (the model is a scripted stub that proposes the known replacement).

| Session | What happens |
|---|---|
| `toy-recovery-xy-off` | #0-#8, then TERM `impasse` (#9, `detail: debate_stall`, recovery skipped as `recovery_disabled`). Predictions stay X/Y/Y. |
| `toy-recovery-xy-on` | #0-#8, rollback #9-#16, A's real REVISE answering #7 (#17), TERM `consensus` (#18). |

In the `on` session the rollback is `rollback_start` (#9), the original branch (#10-#12: A's copied
reply, then B and C refute it), the replacement branch (#13-#15: A's REVISE, then B and C ratify it)
and `rollback_end` (#16, distances 1/3 and 0, credit -1/3). The real board is X/Y/Y at every
sequence up to #16 and Y/Y/Y from #17: the sandbox branches never move it, only the adopted real
reply does.

## Event fields used here

The full record is in [spec_pxp_n.md](spec_pxp_n.md) section 2; the replay events are described in
section 5.1. For this fixture:

| Field | Values in the fixture |
|---|---|
| `kind` | `message` for #0-#8, the adopted reply and TERM; `rollback_start`, six `rollback_step`s and `rollback_end` for the replay |
| `reply_to` | the real message replied to; on `rollback_start` it is the replayed target (6). Rollback steps have none. |
| `counterfactual` | `true` on every rollback event, `false` on the adopted reply |
| `meta` on `rollback_step` | `replay_id`, `branch` (`original` or `replacement`), `fork_seq` and `fork_reply_to` (fork-local, not real sequence numbers), `tested`, `call_ids` |
| `meta` on `rollback_end` | `replay_id`, `status`, `credit_delta` (-1/3), `distance_original` (1/3), `distance_replacement` (0), `distance_recorded`, `target_seq`, `challenger_seq`, `branch_tokens` |
| `meta` on the adopted reply | `adopted_counterfactual: true` and the `replay_id` it came from |
| TERM `explanation` | the stop reason: `impasse` or `consensus` |
| TERM `meta` | `detail`, `decision_seq` and a `recovery` summary (`eligible`, `skip_reason`, `outcome`, `replay_id`) |

---

<!-- Consolidated from `cases.md`; original section content preserved. -->

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

---

<!-- Consolidated from `analysis.md`; original section content preserved. -->

# Analysing a paired run

    uv run python -m bench.paired_analysis <run dir> --out <dir> [--grades joined.csv] [--reps 2000]

`--grades` is the metrics file rejoined with rubric scores (`bench.grading rejoin`, see
`docs/architecture_and_evaluation.md`). Without it the automatic verdict is used; the verification report says how many
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
