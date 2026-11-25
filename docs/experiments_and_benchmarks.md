# Project documentation: Experiments And Benchmarks

---

<!-- Consolidated from `proposal_ablation.md`; original section content preserved. -->

# Proposal follow-up: 500-case counterfactual-density study

This run is the next empirical step after J3. It evaluates the same 500 frozen MSCoRe instances under four counterfactual-agent densities: 0/3, 1/3, 2/3, and 3/3. Every condition uses the same item IDs and model seed. The run therefore contains 2,000 sessions and supports matched, per-item comparisons.

It does **not** promise 500 rollbacks or 500 eligible checkpoints. Those are outcomes of the protocol, not the sample-size definition. If the model still rarely opens checkpoints, report that as a feasibility result; do not replace ineligible cases after seeing outcomes.

## What this study tests

The main independent variable is the number of agents wrapped by the counterfactual intervention. The study records, per session, checkpoint eligibility/opening, actual rollback events, termination reason, consensus, final correctness under the format-specific automatic judge, event counts, token use, wall time, and failures. The analysis verifies that all four conditions used the same 500 IDs before making paired summaries.

The config enables `policy_learning`. Each density condition has its own persistent memory that learns which of three counterfactual explanation tactics most reduced disagreement on earlier trials. The reward is reduction in the scheduler's disagreement distance. It rewards proximity to agreement; it does **not** reward correctness. The 0/3 condition is unaffected by this memory. Thus the main result estimates the combined effect of counterfactual density plus within-condition tactic adaptation. It cannot isolate the causal contribution of learning from the contribution of counterfactual agents.

The sample intentionally excludes the known malformed MSCoRe file `Automotive Value Chain/Easy/Supply Chain`. All source files selected by the manifest are cached locally in `data/mscore/`; task IDs and a SHA-256 manifest are written to `run.json`. Keep that manifest with the results.

## Prepare the local run

Run these commands from the repository root in PowerShell. Ollama must be installed and running locally. The dataset loader downloads the selected MSCoRe source files on first use and caches them under `data/mscore/`.

```powershell
uv sync
ollama pull qwen2.5:3b-instruct
ollama list
$env:LLM_BACKEND = "openai"
$env:LLM_BASE_URL = "http://127.0.0.1:11434/v1"
$env:LLM_MODEL = "qwen2.5:3b-instruct"
```

First run one actual session to confirm the model endpoint, parsing, and local dataset download. This writes under the same output folder; the full command resumes completed work rather than rerunning it.

```powershell
uv run python -m bench.run configs/proposal_density_500.json --out results/proposal-density-500 --limit 1
```

Confirm that the command finishes one session, `ollama ps` shows the model during generation, and the output directory contains `metrics.csv`, `board.sqlite`, `calls.jsonl`, and `run.json`. Then start the full run:

```powershell
uv run python -m bench.run configs/proposal_density_500.json --out results/proposal-density-500
```

Do not change the config, model tag, task cache, or output path mid-run. If interrupted, restart the **same command** with the same config and output path; finished trial keys are skipped. Keep the machine awake and Ollama available. `--parallel 1` is required by policy learning so the strategy-update order is reproducible; it is already the runner default. The wall time depends heavily on GPU/CPU and model response length. Plan for a long local job (potentially a day or more), not the earlier 144-prefix study duration.

When the runner reports all 2,000 sessions done, verify that `metrics.csv` has 2,000 data rows and that `run.json` records 500 manifest IDs. Keep the entire `results/proposal-density-500/shard-1-of-1/` directory, especially `policy_memory.json` and `run.json`, with the raw results.

## Analyze and validate the ablation

The analyzer refuses incomplete or mismatched conditions. It writes the table, paired comparisons, and figure to a separate analysis directory.

```powershell
uv run python -m bench.ablation_analysis results/proposal-density-500/shard-1-of-1 --out results/proposal-density-500/analysis --expected-per-level 500
```

Review `analysis.json` and `conditions.csv` for the four condition totals. Review `paired_vs_zero.csv` for paired case wins, losses, ties, and differences from 0/3. `density_outcomes.png` plots checkpoint, consensus, and correct-consensus rates. Independently inspect traces from both successful and unsuccessful cases in the blackboard database before writing conclusions; aggregate counts alone do not show whether a rollback addressed a substantive error.

In particular, report these outcomes separately:

- **Checkpoint opened:** the protocol reached an eligible recovery point or attempted replay. This is an opportunity/trigger measure.
- **Rollback:** an actual replacement branch was adopted. This is an intervention measure.
- **Correct consensus:** the session stopped in consensus and the selected final answer passed the configured automatic judge. This is the primary task outcome, subject to judge quality.
- **Consensus without correctness:** agreement did not imply correctness.
- **Counterfactual-only agreement gains:** closer agreement is a policy reward, not proof of improved task performance.

For open-ended MSCoRe answers, automatic text matching is approximate and can underrate valid paraphrases or accept superficial overlap. Results across this mix of domains/formats support claims only about this frozen sample, prompt/persona, model build, and automatic grading pipeline. Do not claim broad cross-domain generalization or a proven recovery benefit if the matched correct-consensus outcome does not support it.

## Separate policy-learning ablation

Because the main config turns policy learning on, it bundles two changes: enabling counterfactual agents and adapting the tactic across sessions. To measure learning separately, a static-policy control config is included. It uses the same 500 IDs, seeds, prompts, model, and four density values, changing only `policy_learning` to `false`. Run it as a separate 2,000-session job:

```powershell
uv run python -m bench.run configs/proposal_density_static_500.json --out results/proposal-density-static-500
uv run python -m bench.ablation_analysis results/proposal-density-static-500/shard-1-of-1 --out results/proposal-density-static-500/analysis --expected-per-level 500
uv run python -m bench.policy_ablation_analysis results/proposal-density-static-500/shard-1-of-1 results/proposal-density-500/shard-1-of-1 --out results/proposal-policy-comparison --expected-per-level 500
```

The comparison checks the two 500-ID manifests match at each density and writes paired wins/losses/ties for correct consensus, checkpoint, rollback, and consensus. Use density 1/3, 2/3, and 3/3 to discuss the adaptive-versus-static policy difference; density 0/3 is a control where policy selection is inactive. Keep this extra run separate from the primary result and state its additional 2,000-session cost. Do not compare only whichever density looks best after the first run.

If compute is limited, the first 2,000-session adaptive run answers the density question for a learned-policy bundle. Do not attribute its differences specifically to learning without running the static control.

## Current external-benchmark boundary

The repo includes task-file ingestion prototypes for KramaBench and MedAgentBench, but they do not amount to official benchmark evaluation. KramaBench requires its workload/data environment and subtask evaluator; the prototype has only reference-answer proxy metadata. MedAgentBench requires the pinned FHIR environment, action/tool loop, and authorized evaluator; loading its JSON tasks does not implement those pieces. Do not mix either prototype into the 500-task MSCoRe ablation or report its rows as official benchmark scores. See `external_benchmarks.md` for the setup and remaining integration requirements.

---

<!-- Consolidated from `external_benchmarks.md`; original section content preserved. -->

# External benchmark adapter status

The code can load local KramaBench workload JSON and MedAgentBench task JSON into the project's common `Instance` representation (`src/bench/external.py`). These adapters are for schema validation, task selection, and future integration. They are not wired into the normal experiment runner as official-scoring benchmarks because the project does not yet implement either benchmark's complete execution/evaluation contract.

## KramaBench

The loader expects one official workload JSON file per domain in a local workload directory. It preserves task IDs, query, answer type, named data sources, and subtask count. It keeps the reference answer out of the agent prompt. Its current evaluation label is `reference-answer-proxy`: the project does not yet connect the benchmark's data lake, execute the task-specific query/code workflow, or run the official subtask evaluator. A plain final-answer text match cannot substitute for that evaluation.

Before a KramaBench study can be claimed, pin a release/commit and its license, download the required data, select permitted tasks, implement a task runner that exposes the correct domain data/tools, use official subtask checks, and save source revision plus task manifest. Follow the upstream task and evaluation specifications at [KramaBench](https://github.com/mitdbg/KramaBench).

## MedAgentBench

The loader accepts the local official task JSON array and preserves task IDs, instructions, public context, task type, reference solution, and evaluation MRN in the loaded record. The private reference fields are never placed in `question_text`. The evaluation label is `interactive-environment-required`.

This repo does not yet implement the required FHIR-backed clinical state, action/tool protocol, task reset/isolation, or official evaluator. Sending only the natural-language instruction to the current agents is not a valid MedAgentBench trial, and scoring against `sol` as plain text would be invalid. To complete that integration, pin and launch the upstream Docker/FHIR setup, implement the benchmark's GET/POST/FINISH tool interaction and per-task reset, run the authorized reference evaluator, and preserve environment/image/task versions. See [MedAgentBench](https://github.com/stanfordmlgroup/MedAgentBench) for its current setup contract.

### Single-agent baseline harness (`bench.medagentbench`)

`src/bench/medagentbench.py` implements the upstream GET / POST / FINISH loop for **one** agent and scores it with the downloaded `refsol.py`. It is the baseline a debate adapter would be compared with; the multi-agent debate is not part of it. As upstream, a POST is parsed and recorded but never sent to the server, so FHIR state does not change and no reset is needed (`reset: not_required` in `run.json`). Each run saves `results.jsonl` (one line per task, with the full dialogue), `run.json` (upstream commit, task-file, function-catalogue and `refsol.py` hashes, image digest, model, limits) and is resumable.

Setup, all outside Git: clone `stanfordmlgroup/MedAgentBench`; download `refsol.py` from the link in its README (gated, never commit it); start Docker Desktop and the image (`docker run --rm -d --name medagentbench-fhir -p 8080:8080 jyxsu6/medagentbench:latest`, about two minutes to start, amd64 emulated on Apple Silicon). Then:

```bash
uv run python -m bench.medagentbench --upstream <checkout> --refsol <refsol.py> \
  --out results/medagent-smoke --ids task1_1 task2_1 task4_1 --image-digest <digest>
```

`--per-type N` picks the first N of each of the ten task types. A 3-task smoke run with `qwen2.5:3b-instruct` completed end to end (0/3 correct, two replies broke the one-action format); it validates the plumbing, not a score. Tests use a fake FHIR transport and a fake grader. A full 300-task run has not been done.

## Local loader tests

The adapter tests use synthetic task fixtures, require no network, and verify IDs, evaluation-mode labels, and that private answer fields are not placed in the prompt. Passing these tests only verifies file parsing and field handling; it does not establish benchmark validity or task performance.

---

<!-- Consolidated from `study_run.md`; original section content preserved. -->

# Running the paired study

## Requirements

| Need | Details |
|---|---|
| Python tooling | `uv` (`uv sync` installs everything) |
| A local LLM server | [Ollama](https://ollama.com), running |
| **The model** | **`qwen2.5:3b-instruct`**, pulled with `ollama pull qwen2.5:3b-instruct` (about 2 GB) |
| Hardware | An Apple Silicon Mac or a machine with a GPU; the study takes about 2 to 2.5 hours and keeps the machine busy |
| Environment | the three `export` lines below, set in the terminal that runs the study |

The frozen study uses the **3B** model, not the 7B build the pilots (J2, J3) used. The setup was
chosen because 7B debates almost never stall (see `docs/project_research.md`). Do not change the
model, personas, temperature or stall window in `configs/paired_study.json` once the run starts; a
resumed run must use the same build, and mixing builds invalidates the comparison.

## Run it

    git checkout feat/disagreement-screen
    uv sync
    ollama pull qwen2.5:3b-instruct
    export LLM_BACKEND=openai
    export LLM_BASE_URL=http://127.0.0.1:11434/v1
    export LLM_MODEL=qwen2.5:3b-instruct
    uv run python -m agents.llm_client --backend openai "Say hi"     # sanity check
    uv run python -m bench.run configs/paired_study.json --out results/paired-study

Without the exports the runner falls back to the **mock** model and produces meaningless results.

The run is resumable: stop it with Ctrl+C and rerun the same command; finished arms are skipped
and the saved prefixes are reused. Keep the machine awake and plugged in. Add `--limit 30` for a
short first look.

## What it does

24 held-out items x 6 seeds. For each, one shared prefix is played; the three arms (standard,
forward repair, replay) run only on prefixes that reach the recovery checkpoint (about 15 to 20 of
every 100). Details are in `docs/architecture_and_evaluation.md`.

## When it finishes

Results are in `results/paired-study/shard-1-of-1/` (`metrics.csv`, `board.sqlite`,
`opportunities.jsonl`, `calls.jsonl`, `run.json`). Make the tables and figures:

    uv run python -m bench.paired_analysis results/paired-study/shard-1-of-1 --out results/paired-study/analysis

and look at `analysis.json` (verification first), then share the whole `results/paired-study`
folder. To browse the sessions in the viewer:

    uv run python -m server --db results/paired-study/shard-1-of-1/board.sqlite \
      --metrics results/paired-study/shard-1-of-1/metrics.csv --source "paired study" --kind model

then open http://127.0.0.1:8000 (see `docs/viewer.md`).
