# Project documentation: Project Research

---

<!-- Consolidated from `research_protocol.md`; original section content preserved. -->

# Research protocol and limitations

## Research question

When a team of three language-model agents reaches a challenged disagreement, does replaying a
candidate replacement on matched counterfactual branches improve correct resolution compared with
an ordinary continuation or a forward rethink?

This is a course project based on prediction-and-explanation dialogue and the PXP tags in Baskar,
Srinivasan, Bain and Coiera (2023). PXP-N, the shared blackboard, checkpoint detector, paired
arms, authored cases and bounded replay are project adaptations, not claims that the paper's full
system has been reproduced.

## What counts as evidence

The primary unit is a case × seed. Each unit receives one shared no-intervention prefix and three
continuations: standard, forward rethink, and matched replay. The primary outcome is correct
recovery among units whose shared prefix opened a checkpoint. Agreement, automatic correctness,
blind rubric correctness, replay helpfulness in simulation, adoption, final consensus and token cost
are reported as separate quantities.

The primary dataset remains the frozen 24-case held-out study in `configs/paired_study.json`. Its
saved 3B run is a baseline. The `challenge` suite is a separate stress-test with six longer authored
cases containing competing requirements, arithmetic, deadlines and tempting unsafe alternatives.
It is not pooled with the held-out 24 or used to tune their result.

## Fixed controls

- One model build and one frozen prompt/config per run.
- The same saved prefix, case and seed are used for every arm.
- One shared cap of six model requests after the checkpoint covers candidate generation, repairs,
  both sandbox continuations and subsequent live turns.
- Replay branches use the same peer order, branch limits and answer comparator.
- Case acceptance keys are private. Agents receive public task facts and schema only.
- Open MSCoRe lexical agreement remains explicitly approximate; it is not human-verified semantic
  equivalence.
- The final paired result is interpreted by case-level paired differences. Small eligible samples
  are described by counts; bootstrap intervals are descriptive and not proof of an effect.

## Scoring and human review

Automatic case checks verify action keys, decisive values and explicit critical constraints. They do
not decide whether an explanation is persuasive. Use blinded rubric sheets to score conclusion,
evidence, constraints and justification. Double-score a balanced subset, reconcile differences, and
report both the automated result and the human-scored result. Keep `grading/private.json` away from
graders because it maps blind IDs to conditions and includes answer hints.

## Reproduction

Install the local project dependencies and run the unit suite before a model run. Use the documented
Ollama-compatible endpoint. The original baseline run is in `results/paired-study/`; a fresh
challenge run writes to its own folder:

```powershell
$env:LLM_BACKEND = "openai"
$env:LLM_BASE_URL = "http://127.0.0.1:11434/v1"
$env:LLM_MODEL = "qwen2.5:3b-instruct"
uv run python -m bench.run configs/challenge_paired.json --out results/challenge-paired
uv run python -m bench.paired_analysis results/challenge-paired/shard-1-of-1 --out results/challenge-paired/analysis
uv run python -m server --run-dir results/challenge-paired/shard-1-of-1
```

Model sampling is stochastic. Save the exact config, model build digest, run provenance, case
manifest, calls ledger, event database and metrics file with any result shared.

## Limitations to state in the report

The 3B/dissenter setting was selected after larger/default configurations produced few eligible
checkpoints. Therefore the study estimates recovery conditional on a deliberately disagreement-rich
setup; it does not estimate how often ordinary agents naturally stall. The baseline had only one
correct replay recovery and one correct standard recovery among 52 eligible prefixes, and replay
cost substantially more. That is inconclusive evidence, not a replay win. Authored answer-format
failures and allowance overruns in the baseline are recorded as study limitations; the revised
runner addresses these prospectively but does not retroactively repair the old measurements.

The new challenge suite is small and hand-authored. It is useful for controlled, inspectable cases,
not a representative sample of operational decisions. Avoid claiming general safety or reliable
real-world advice from these experiments.

---

<!-- Consolidated from `proposal_alignment.md`; original section content preserved. -->

# Proposal alignment and remaining scope

This note maps the professor's original proposal to the project as it currently exists. The proposal is a broad target, not a claim that every planned benchmark or experiment has been completed. The current project is a course-scale adaptation centered on an inspectable PXP blackboard and a paired test of recovery after disagreement.

## What is implemented

| Proposal component | Current implementation | Evidence and qualification |
|---|---|---|
| Shared blackboard with structured PXP messages | Append-only SQLite event store, event validation, board reconstruction, and the RATIFY, REVISE, REFUTE, and REJECT tags | `src/blackboard/`, `src/protocol/`; concurrency and protocol tests are in `tests/`. SQLite was chosen instead of Redis to keep the local experiment self-contained. |
| Deterministic/event-driven scheduler | Turn selection, consensus and impasse checks, message bounds, and checkpoint eligibility | `src/scheduler/`; scheduler and protocol tests. This is an event-driven local controller, not a distributed scheduler. |
| Local model broker and prompt matrix | OpenAI-compatible local client (used with Ollama), PEX parsing/repair, personas, and structured prompts | `src/agents/`; the final saved paired run used Qwen2.5 3B Instruct. Earlier 7B runs are exploratory and not a controlled size comparison. |
| Counterfactual rollback sandbox | Copies a saved prefix into isolated branches, compares original and replacement continuations, records rollback events and a distance delta, and may post a useful candidate as a real revision | `src/counterfactual/`; `docs/architecture_and_evaluation.md`; tests in `tests/test_counterfactual.py`, `tests/test_matched_branches.py`, and related files. The live history is not rewritten. |
| Real-time visualization and history inspection | FastAPI REST endpoints and a WebSocket event stream; React/D3 session timeline, event inspector, replay comparison, results view, and project guide | `src/server/app.py`, `ui/src/`; the interface supports both archived runs and a live demo stream. The frontend is already implemented and is intentionally unchanged by this comparison. |
| MSCoRe data ingestion | On-demand loader and parsers for the supported formats, stable item IDs, deterministic sampling, and local cache. The sequence-order format is included in the manifest. | `src/bench/mscore.py`, `tests/test_mscore.py`. The study uses a selected, frozen sample, not the full corpus. |
| Metrics and plots | Per-trial outcomes, agreement and correctness fields, tag and stop counts, rollback and token accounting, paired recovery analysis, and figures | `src/bench/`, `docs/architecture_and_evaluation.md`; the frozen result summary is in `results/paired-study/README.md`. |

## What was explored, and what the result means

The proposal suggests testing 0%, 33%, 66%, and 100% counterfactual-enabled agents. J3 did run the corresponding 0, 1, 2, and 3 enabled-agent settings with three agents per session. It covered 30 questions (120 sessions) and recorded zero rollbacks. It is therefore evidence that this earlier setup did not trigger the intervention, not evidence that counterfactual agents improved outcomes. See `docs/project_research.md` for the run history.

The later paired study asks a different question. It shares each case-seed prefix across standard continuation, forward rethink, and matched replay. It covers 24 cases, six seeds, and 144 prefixes, of which 52 opened a checkpoint. Replay and standard each had one automatically correct recovery among those 52; forward had none. Replay used more tokens. The study is inconclusive and should not be presented as a demonstrated replay benefit. The full caveats and trace audits are in `results/paired-study/README.md`.

These are two complementary project stages, not one factorial experiment. In particular, the final paired study does not compare 0/33/66/100% counterfactual-agent density, and J3 does not test the checkpoint recovery arms.

## Major proposal items not completed

| Proposal item | Status | Why it is a substantial extension |
|---|---|---|
| KramaBench integration | Task-file loader prototype implemented; official task execution/scoring not implemented | `src/bench/external.py` validates local workload JSON and preserves IDs and task metadata. It does not connect the benchmark data lake or official subtask evaluator. The output is explicitly a reference-answer proxy and must not be reported as an official score. |
| MedAgentBench integration | Task-file loader prototype implemented; interactive benchmark integration not implemented | The loader preserves task fields and keeps reference/grader data out of prompts. The project still lacks the pinned FHIR environment, task reset, GET/POST/FINISH action loop, and official evaluator. Plain text answers are not valid MedAgentBench runs. See `docs/experiments_and_benchmarks.md`. |
| 500 trials for every ablation condition | Protocol and config implemented; experiment not yet run | `configs/proposal_density_500.json` samples exactly 500 unique instances and applies all four density levels, totaling 2,000 sessions. It saves a shared manifest hash/IDs, resumable metrics and board events, and policy-memory state. Run instructions and analysis command are in `docs/experiments_and_benchmarks.md`. |
| Counterfactual-density ablation | Runnable study implemented; empirical success still untested | J3 had the density settings but zero rollbacks. The new follow-up records checkpoint opportunities, actual rollbacks, consensus, judged correctness, cost, and trace data across the four matched conditions. It cannot guarantee the trigger will fire. Do not call it a successful recovery study until results show informative eligible cases and are manually audited. |
| Learned changes to persistent prompts or voting weights | Persistent tactic selection and static-policy comparison implemented; weight/prompt-parameter learning not implemented | `src/counterfactual/policy.py` persists a separate online UCB-style memory per density condition. It learns which of three fixed argument tactics most reduced disagreement distance. The reward is agreement proximity rather than correctness. A matched static-policy config and comparator are provided, but neither experiment has yet been run. This tests adaptive tactic selection, not agent reliability weights or learned prompt parameters. |
| Broad cross-domain claims | Not supported | Current results are conditional on selected tasks, one final 3B model build, a disagreement-rich persona, and automatic scoring with known limitations. |

## Recommended boundary for the course submission

The implementation now prepares a substantially larger matched density study, and the external benchmark task-file adapters are an initial integration step. The 500-case-per-condition run has not been executed. Continue to distinguish implemented experiment machinery from empirical findings: the verified contribution today remains the event-sourced PXP system, inspectable local replay, paired recovery design, and transparent report of a weak/inconclusive result. Do not claim successful 500-case ablation, official KramaBench/MedAgentBench validation, or a proven recovery benefit until a frozen run has been completed, evaluated, and audited.

The run protocol, preflight, resume behavior, analysis outputs, and limits are described in `docs/experiments_and_benchmarks.md`. If compute is limited, complete the preflight and report trigger scarcity accurately rather than claiming a recovery benefit from a large number of uninformative sessions. Official cross-domain benchmark support remains separate work with environment and evaluator requirements detailed in `docs/experiments_and_benchmarks.md`.

---

<!-- Consolidated from `study_design_notes.md`; original section content preserved. -->

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
| **3B, designated dissenter, T1.0, window 4** | 38 | 24% | 79% | **6 (16%)** |

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

---

<!-- Consolidated from `compute.md`; original section content preserved. -->

# Experiment run history

This page records the purpose and scale of the project's main experiment stages. It is a historical summary, not a launcher guide. For the current local setup and commands, use the root `README.md` and `docs/experiments_and_benchmarks.md`.

| Stage | Purpose | Scope and outcome |
|---|---|---|
| J1 | Check whether model replies could be parsed as structured PXP messages | Early protocol and prompt smoke study. |
| J2 | Observe baseline multi-agent dialogue without counterfactual recovery | Early baseline for consensus, impasse, and dialogue behavior. |
| J3 | Explore whether the fraction of counterfactual-enabled agents affected dialogue | 30 questions × 0, 1, 2, or 3 enabled agents (0%, 33%, 66%, 100%) = 120 sessions. It recorded zero rollbacks, so it did not test the intervention's recovery effect. |
| Paired study | Compare standard continuation, forward rethink, and matched replay after a shared eligible checkpoint | 24 cases × 6 seeds = 144 prefixes and 432 arm outcomes. 52 prefixes opened an eligible checkpoint. This is the frozen 3B baseline; its result is inconclusive. |

J1, J2, and J3 are exploratory stages with earlier configurations. Do not pool their outcomes with the paired study or describe J3 as a successful counterfactual ablation. The final paired study uses a different unit and design: it compares post-checkpoint policies, rather than varying the number of enabled agents in a session.

The frozen run details, model identity, token accounting, outcome counts, and trace-level qualifications are in `results/paired-study/README.md`. Read `docs/project_research.md` for the difference between this completed scope and the broader professor proposal.
