# Results and reproducibility map

This directory contains the frozen evidence used in the dashboard and final report. `project_results.json` is the compact cross-project summary consumed by the local web app. Raw task outputs, run manifests and analysis artifacts are retained beside it so the summary can be audited. The files under `archive/` are historical screening logs and snapshots; they are not part of the final statistical comparisons.

## Main results

| Experiment | Evidence | Main observation | Status |
|---|---|---|---|
| Paired recovery baseline | `paired-study/` | 52/144 prefixes opened a checkpoint. Correct recovery was 1/52 for standard continuation, 0/52 for forward rethink and 1/52 for replay; replay used more tokens. | Complete, inconclusive |
| Stage 2 adaptive density | `proposal-density-adaptive-500/` | 1,680/2,000 sessions. Densities 0/3, 1/3 and 2/3 have 500 each; 3/3 has 180/500 and is partial. | Partial |
| Stage 3 static density | `proposal-density-static-250/` | 1,000 sessions, 250 at each density from 0/3 to 3/3. | Complete |
| Matched policy comparison | `stage2-matched-250/` and `proposal-policy-comparison-250/` | Shared task IDs are compared at densities 0/3, 1/3 and 2/3 only. Adaptive-minus-static correct-consensus differences are +1.2, +0.8 and +0.4 percentage points; the comparison is descriptive, not proof of a policy benefit. | Complete for eligible levels |
| MedAgentBench baseline | `medagentbench-30/` | 30 tasks, three from each of ten task types; official `refsol.py` grader scored 0/30 correct, with 28 invalid-action stops and two completed-but-incorrect results. | Complete baseline |

The adaptive reward reduces disagreement distance rather than optimizing answer correctness, and updates depend on run order. The adaptive and static runs are not a randomized causal experiment. Stage 2's partial 3/3 condition is excluded from matched comparisons. MedAgentBench is a separate single-agent FHIR tool-use benchmark, not an evaluation of multi-agent recovery. The zero score identifies action-format compliance as a first repair target; it is not evidence about clinical capability.

## Contents to retain

- `project_results.json`: frozen aggregate counts, comparisons, provenance summary and limitations used by the dashboard.
- `proposal-density-adaptive-500/shard-1-of-1/metrics.csv`, `run.json`, `policy_memory.json`, `board.sqlite`, and `calls.jsonl`: adaptive task outcomes, model/config provenance, learned tactic state and inspectable traces. The run is resumable from its saved state, but this partial run is treated as a completed observation, not resumed for the submitted comparison.
- `proposal-density-adaptive-500/analysis/`: condition totals, paired outcomes and plot. Stage 2 analysis uses only the three completed levels.
- `proposal-density-static-250/shard-1-of-1/`: complete static-policy run with task metrics, manifest and traces.
- `proposal-density-static-250/analysis/`: static condition summary and plot.
- `stage2-matched-250/shard-1-of-1/metrics.csv`: the exact 750 adaptive rows matching Stage 3's 250 task IDs at each of levels 0--2.
- `proposal-policy-comparison-250/`: paired wins, losses, ties and effect summaries for checkpoint, rollback, consensus and correct-consensus.
- `medagentbench-30/results.jsonl`: per-task status, interaction history and official grader outcome; `run.json` records task-file and grader hashes, upstream revision, model and FHIR image digest.
- `paired-study/`: prior frozen paired replay baseline and its trace/answer audits.
- `archive/`: prior checkpoint snapshots, model-screen traces, legacy summaries and historical bundle copies. These artifacts explain development history but are not included in the current claims.

## Recreate the reported analyses

Run from the repository root in the project's Python environment:

```powershell
uv run python -m bench.ablation_analysis results/proposal-density-adaptive-500/shard-1-of-1 --out results/proposal-density-adaptive-500/analysis --expected-per-level 500 --levels 0 1 2
uv run python -m bench.ablation_analysis results/proposal-density-static-250/shard-1-of-1 --out results/proposal-density-static-250/analysis --expected-per-level 250
uv run python -m bench.policy_ablation_analysis results/proposal-density-static-250/shard-1-of-1 results/stage2-matched-250/shard-1-of-1 --out results/proposal-policy-comparison-250 --expected-per-level 250 --levels 0 1 2
```

The MedAgentBench task grading was done by the saved official `refsol.py` run harness. Do not recompute it with a generic text matcher. The per-task output and its run metadata are in `medagentbench-30/`.

The local viewer can open the saved paired study with:

```powershell
uv run python -m server --run-dir results/paired-study
```

The Results page reads `project_results.json`; Explore runs is backed by the saved blackboard data for the selected run. Keep grader answer maps private if present; never publish a file named `grading/private.json`.
