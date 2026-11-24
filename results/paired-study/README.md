Paired study result handoff

The frozen 3B run completed on 18 November 2026. All 144 prefixes and 432 arm outcomes are saved. The run opened 52 checkpoints across 17 distinct cases. Replay and standard debate each produced one automatically correct recovery on those 52 eligible prefixes. Forward repair produced none. Replay used more tokens. The trace audits also identify problems in how authored answers are matched and how the scheduler stops after adoption.

Run details

The run used feat/disagreement-screen at revision 2c3e189dbdc7bfc4d5210887d2baa7abc0d3c242, configs/paired_study.json, Qwen2.5 3B Instruct, Q4_K_M, dissenter personas, temperature 1.0, max_tokens 400, impasse_window 4 and seeds 0 through 5. All execution was serial on the RTX 4050 laptop through Ollama 0.40.5. The model digest is 357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b.

The study ran from 02:43:35 to 03:42:39 IST on 18 November 2026, taking 59 minutes and 4 seconds. Download and setup time are separate. There was one uninterrupted study invocation, with 1,732 model calls and no transport errors. All calls have reported token usage. There were 78 repair calls. No study code, prompts or configuration were edited during the run.

Checkpoint counts use prefixes, not arm outcomes. The 92 prefixes that did not open a checkpoint contribute the same ordinary outcome to each of the three arms.

| Case type | Prefixes | Eligible checkpoints | Rate |
|---|---:|---:|---:|
| Authored decision cases | 48 | 35 | 72.9% |
| MSCoRe open QA | 48 | 16 | 33.3% |
| MSCoRe choice | 48 | 1 | 2.1% |
| Total | 144 | 52 | 36.1% |

Outcome comparison

Correctness below uses the existing automatic checks. No independent human rubric scores have been supplied.

| Arm | Total outcomes | Consensus on all items | Automatically correct consensus on all items | Consensus on eligible items | Correct recovery on eligible items | Mean full-trial tokens on eligible items |
|---|---:|---:|---:|---:|---:|---:|
| Standard | 144 | 71 | 29 | 2 of 52 | 1 of 52 | 13,449.8 |
| Forward repair | 144 | 70 | 28 | 1 of 52 | 0 of 52 | 13,234.4 |
| Replay | 144 | 71 | 29 | 2 of 52 | 1 of 52 | 19,578.9 |

Replay versus standard has one win, one loss and 50 ties on correct recovery. The net rate difference is zero percentage points, with a case-bootstrap 95% interval of approximately -5.4 to +5.8 percentage points. The mean token difference is +6,129.2 per eligible item. Replay versus forward has one win and 51 ties, a +1.9 percentage-point difference with an interval from zero to approximately +6.5 points, and +6,344.5 tokens per eligible item. These results provide little evidence of improved correct recovery.

The replay funnel is 52 attempted, 51 completed comparisons, 10 helpful comparisons, 10 accepted real revisions and one automatically correct recovery. Forty-one attempts were not helpful and one comparison was incomplete. The legacy intelligibility classifier labels all 144 outcomes in each arm as failed, with zero Strong or Ultra-Strong outcomes. The productive-revision counts are 104 for standard, 95 for forward and 100 for replay. Those counts describe the implemented rules and do not measure human understanding.

Trace findings to investigate

1. Many authored checkpoints include unresolved answer keys. At the checkpoint, 30 of 35 eligible authored prefixes have at least one prediction rejected by the authored answer-key parser. Only five have valid keys for every agent. Some agents agreed on the same malformed text, which the comparator treats as unresolved. For example, contractor-access answers began with exception=no rather than one of the allowed action tokens extend, exception or revoke. Checkpoints therefore cannot all be interpreted as substantive disagreements.

2. The single automatically correct replay recovery also needs this qualification. Its session is paired_study-replay|authored|case:rollback-release|4. At the prefix checkpoint, two agents wrote rolloak and rollbak, which do not match the allowed action rollback. The saved trace is useful for inspecting an executed replay and adoption. Review the representation repair before attributing that outcome to improved reasoning.

3. A helpful historical branch often did not transfer to the live board. Across the ten accepted revisions, the live disagreement score improved immediately in four, stayed the same in five and worsened in one, under the configured comparators. Eight ended immediately in impasse with no subsequent peer reply. One ended in automatically incorrect consensus. The correct rollback-release trace received one further real peer reply and then reached consensus. The detailed before and after predictions are in analysis/adoption_audit.json.

4. The six-call allowance is not enforced by the runner. Three replay arms used seven calls after the checkpoint. Their session IDs are listed in analysis/verification_independent.json. Treat the recorded costs as observed costs and qualify claims about a strictly equal call cap.

The next development tests should validate an authored answer key before counting a prediction as a resolved position, distinguish malformed answers from substantive disagreement, and exercise a bounded follow-up after adoption before applying the old stall window. These are proposals for a separately frozen follow-up run. The original metrics and experiment settings in this folder are preserved.

Interpretation and accounting

The study setup was selected on development cases to produce stalls. The checkpoint rates above describe this selected 3B-and-dissenter setup on held-out cases. The older 7B screens used different cases, so they do not isolate a causal effect of model size.

Open QA agreement is approximate lexical matching, and its automatic correctness check uses text overlap. Authored automatic scoring checks a decision and critical rules. Full evidence and explanation quality require the rubric review.

Full-trial token totals in metrics.csv include the shared prefix in every hypothetical arm. Summing those rows yields 3,920,097 tokens. The actual call ledger contains 1,698,939 tokens, since each prefix was computed once. Overall median wall times in outcome_table.csv mostly measure copying terminal prefixes into arms. Use the execution metadata for total machine runtime and the paired differences for time after the checkpoint.

The per-row model cells are blank because of the existing paired runner. run.json and operations/model.json record the pinned model. No human grades are implied by the automatic verdicts.

Files for the teammate

shard-1-of-1 contains the original metrics.csv, board.sqlite, calls.jsonl, opportunities.jsonl and run.json. analysis contains the prescribed analysis.json, outcome_table.csv, figures and inputs.json, plus the independent integrity checks, prefix inventory, eligible cost and intelligibility table, adoption audit and answer-key audit. The independent checks found no missing outcomes, duplicate keys, mismatched shared prefixes, terminal-event or token-reconciliation errors. SQLite integrity is OK.

grading/sheet.csv contains 432 blinded responses. grading/sheet_double.csv contains a 24-response subset for double scoring. Keep grading/private.json away from graders, since it maps responses to conditions and contains automatic hints.

operations records the frozen config, exact model build, dataset checksums, execution times, logs and a reproducible verification script. Code and config hashes were checked against their starting values.

Run the existing analysis again from the project root with

    uv run python -m bench.paired_analysis results/paired-study/shard-1-of-1 --out results/paired-study/analysis

The original numeric analysis and its figures were generated by that command's module. Supplementary audits are separately named and leave the original rows intact. Use analysis/inputs.json and file_checksums.sha256 to tie the outputs to their inputs.

