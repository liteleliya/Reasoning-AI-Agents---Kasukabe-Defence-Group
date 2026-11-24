# Agent handover: Reasoning Agents course project

This file is written as working context for the next teammate/LLM agent. Read it before changing code. The owner explicitly said **work and commit only on `main`**: do not create, switch to, or check out any other branch. Do not touch anything inside `final_submission/`. Keep the existing frontend intact unless asked. Do not claim benchmark runs succeeded until raw results and official evaluation outputs exist.

## Project purpose

This is a local course-project adaptation inspired by the prediction-and-explanation (PXP) interaction model. Three language-model agents answer the same task, write predictions and explanations to an append-only shared blackboard, and communicate using structured tags. The system can identify a recovery checkpoint and use temporary counterfactual branches to compare an alternative reply with the original continuation. The research question is whether these interventions improve **correct** resolution after disagreement, at what cost, and under what conditions.

The project is not a full reproduction of the source paper. Agreement, correctness, checkpoint eligibility, rollback, adoption, and recovery are different outcomes. Do not present agreement or a recorded replay as proof of correctness.

## Existing implementation

- `src/protocol/`: event schemas, PXP tags, validation and intelligibility classification.
- `src/blackboard/`: append-only SQLite event store and board reconstruction.
- `src/scheduler/`: agent turn selection, consensus, stopping/impasse handling and recovery opportunity detection.
- `src/agents/`: local Ollama/OpenAI-compatible client, prompt construction, PXP parsing and agent behavior.
- `src/counterfactual/`: isolated matched replay branches, distance-based credit, adoption and persistent tactic policy memory.
- `src/bench/`: MSCoRe ingestion and deterministic sampling, authored cases, trial execution, metrics and analysis tools.
- `src/server/` and `ui/`: local results API and interactive frontend. The frontend is already built and should remain untouched for this task.
- `configs/proposal_density_500.json`: 500 matched items × 4 counterfactual densities = 2,000 sessions. Policy learning is enabled.
- `configs/proposal_density_static_500.json`: same sample/config with policy learning disabled; another 2,000 sessions.
- `src/bench/ablation_analysis.py`: verifies the four matched density groups and reports outcome/cost summaries.
- `src/bench/policy_ablation_analysis.py`: verifies static/adaptive task IDs match and reports matched win/loss/tie comparisons.
- `src/bench/external.py`: **task-file loaders only** for KramaBench and MedAgentBench. They are not end-to-end benchmark runners and must not be used to publish official benchmark scores.

The saved paired study is an inconclusive baseline, not a replay success claim. J3 tested 0/1/2/3 counterfactual agents but recorded no rollbacks. Consult `results/paired-study/README.md` and [project/research history](docs/project_research.md) for exact figures, caveats and historical run distinctions.

## Immediate priorities

1. Check local model and data prerequisites. A previous attempt found Ollama unreachable and Docker Desktop's Linux engine unavailable. The teammate must verify services rather than assume they started.
2. Complete a small parser/adapter smoke test for each external benchmark before any large run.
3. Implement real benchmark execution and evaluation for KramaBench and MedAgentBench; details below.
4. Run the two 2,000-session MSCoRe ablations only after a short end-to-end model smoke test and available compute/storage check.
5. Preserve complete raw result folders and analyze them with the supplied scripts. Audit representative traces and report uncertainty/limits.

## macOS setup: Python, Ollama/Qwen and Docker

Use macOS instructions throughout; do not copy the Windows/PowerShell commands from older notes. Work from the repository root. The teammate may use Homebrew if installed, otherwise use the official installers.

Install Apple's command line tools if absent, then install `uv` and project dependencies:

```bash
xcode-select --install  # only if the compiler tools are missing
brew install uv
uv sync --locked
```

Install Ollama for macOS from [ollama.com/download](https://ollama.com/download), open the Ollama app so its local service is running, then in Terminal pull and verify the project model:

```bash
ollama pull qwen2.5:3b-instruct
ollama list
ollama run qwen2.5:3b-instruct "Reply with READY"
```

Configure the OpenAI-compatible local endpoint in the same Terminal session used for runs:

```bash
export LLM_BACKEND=openai
export LLM_BASE_URL=http://127.0.0.1:11434/v1
export LLM_MODEL=qwen2.5:3b-instruct
uv run python -m agents.llm_client --backend openai "Return a short readiness response"
```

If `ollama` is not found, install/open the app or add its CLI as described by the current Ollama macOS instructions. Confirm the readiness request succeeds before starting a long run. `qwen2.5:3b-instruct` is the pinned project model tag; record the actual Ollama model/version returned locally in the run notes.

For MedAgentBench, install Docker Desktop for Mac, open it, and wait for the engine to finish starting. Verify it with `docker version` and `docker ps`. Apple Silicon may need Docker's x86_64 emulation for the upstream image; if `docker pull` or container startup reports an architecture/platform error, follow the benchmark's current supported Mac setup rather than silently switching to another image.

Do not run `nvidia-smi` on a MacBook; it is not a useful check on Apple Silicon. Check Activity Monitor or `ollama ps` while the model is loaded. Check free storage before dataset pulls and runs. The sampler downloads selected MSCoRe files on first use. Do not launch hours of runs until the small smoke run completes.

The 500-item sampler reads multiple cached MSCoRe source files and can download selected files on first use. Keep network access available for this preparation. Confirm disk space first. Do not launch a full study if the preflight request fails. Set a new output folder for a new configuration; resume an interrupted study only with the exact same config/model/output path. Policy learning requires serial execution (`--parallel 1`, the default).

## KramaBench: implementation plan

### Current boundary

`src/bench/external.py::load_kramabench` expects local per-domain workload JSON arrays containing task IDs, queries and reference answers. It preserves a few metadata fields and labels evaluation as `reference-answer-proxy`. It does **not** retrieve task data, run data-wrangling/code steps, expose tools to the agents, execute the reference pipeline, or run official subtask checks. Therefore it is not a valid KramaBench experiment by itself.

### Work the implementing agent must do

1. Pin the upstream repository commit/release and document its license/data-use terms. Obtain the official workload and required data lake from the upstream instructions. Keep large/private/raw data outside Git unless redistribution is explicitly allowed.
2. Audit actual files and schemas before bulk parsing. Check file encoding/BOM, whether each file is a JSON array, JSON Lines, or another format, required keys/types, missing/duplicate IDs, and task references to data files. Do not “fix” parser errors by silently dropping records. Save counts of parsed/rejected records with reasons and a deterministic task manifest.
3. Build a task adapter that gives each task access only to the files/data sources and operations allowed by the benchmark. The agent must be able to perform the required discover/read/transform/compute workflow; a plain text final-answer prompt is insufficient for tasks that require execution.
4. Invoke the official evaluator/subtask checks for each task. Keep benchmark answer keys and evaluator data out of agent prompts. Label any unofficial lightweight parser/score clearly as a pilot, not a benchmark result.
5. Add a KramaBench run config with pinned task IDs, concurrency/resource limits, timeout/error handling and output directory. Record upstream commit, dataset release/hash, task manifest/hash, model tag, prompt/config, evaluator version, per-task status, subtask scores, final score, token use, latency and failures.
6. Validate with a tiny set first: one task for every supported task/data shape, one intentionally malformed fixture, and known reference/evaluator cases. Then run a small model-backed pilot, manually audit traces, freeze the protocol, and only then scale.

### Expected commands after the adapter/evaluator is implemented

The existing repo does not yet have these KramaBench config/CLI files, so the next agent must create them and confirm their actual options before documenting commands as executable. Suggested interface:

```bash
# Prepare/pin local KramaBench workload and data using the upstream instructions.
uv run python -m bench.kramabench_prepare --source <local-upstream-checkout> --data-root <local-data-root>

# Validate schemas, paths, IDs and evaluator availability before model calls.
uv run python -m bench.kramabench_validate configs/kramabench_pilot.json

# First run a few pinned task IDs; then run the frozen full config.
uv run python -m bench.run configs/kramabench_pilot.json --out results/kramabench-pilot --limit 3
uv run python -m bench.run configs/kramabench_study.json --out results/kramabench-study
uv run python -m bench.kramabench_analysis results/kramabench-study/shard-1-of-1 --out results/kramabench-study/analysis
```

These are a proposed command contract, **not commands that work in the current checkout** until those modules/configs exist.

## MedAgentBench: implementation plan

### Current boundary

`src/bench/external.py::load_medagentbench` parses task JSON while keeping reference fields out of `question_text`. It does not start/reset FHIR state, execute tool actions, or score outcomes. Giving the current dialogue agents only the task text and scoring their final prose would not constitute a MedAgentBench run.

### Work the implementing agent must do

1. Follow the official MedAgentBench setup and pin the task JSON/tool catalog and Docker image/version. Confirm access to the official evaluator/reference solution. If the reference solution is gated/unavailable, do not fabricate an “official” score; either stop at adapter validation or clearly mark a separately justified proxy evaluation.
2. Start the FHIR environment and implement per-task state isolation/reset so one task cannot leak patient modifications into another. Add startup health checks, request timeouts, retries only for safe operations, and cleanup.
3. Implement the benchmark action contract: inject the official FHIR/tool catalog; parse model output as GET, POST with JSON body, or FINISH; validate syntax and allowed endpoints; execute the action against the local FHIR server; return the actual response to the agent; enforce the official turn limit. Preserve an action/event trace for every task.
4. Connect the official evaluator and its required task/MRN fields without exposing them to the model. Store raw predictions/actions separately from private gold material. Include evaluator version, image digest, task ID and reset status in provenance.
5. Validate all action types against a local disposable/mock FHIR server, including invalid method/URL/JSON, timeout, reset, no-op/read tasks, write tasks, and score agreement on public/authorized fixtures. Then test one real benchmark task end-to-end before the small pilot.

### Environment commands

Docker Desktop must be running. Confirm Docker first, then use the exact image/version required by the pinned official README. The upstream quick start currently documents:

```bash
docker pull jyxsu6/medagentbench:latest
docker run --rm -d --name medagentbench-fhir -p 8080:8080 jyxsu6/medagentbench:latest
docker ps
curl -i http://127.0.0.1:8080/
```

Check that the FHIR endpoint is ready before invoking the adapter. The official benchmark also requires its task workers/assigner and reference-solution setup; the FHIR container alone does not run an evaluation.

### Expected commands after the adapter/evaluator is implemented

The following configs/modules are not currently present. The implementing agent must create and test them, then adjust flags to match code:

```bash
uv run python -m bench.medagentbench_validate configs/medagentbench_pilot.json --fhir-base http://127.0.0.1:8080/fhir
uv run python -m bench.run configs/medagentbench_pilot.json --out results/medagentbench-pilot --limit 3
uv run python -m bench.run configs/medagentbench_study.json --out results/medagentbench-study
uv run python -m bench.medagentbench_analysis results/medagentbench-study/shard-1-of-1 --out results/medagentbench-study/analysis
```

Do not advertise these as runnable until implemented. Official setup details can change; follow and cite the [upstream MedAgentBench README](https://github.com/stanfordmlgroup/MedAgentBench).

## MSCoRe 2,000-session density study

This is prepared in the existing repo. It samples 500 unique task IDs, then uses those same cases with 0, 1, 2 or 3 counterfactual-enabled agents. This gives 500 cases per density and 2,000 sessions, with one model generation seed per case. It does not guarantee 500 disagreements, checkpoints, or rollbacks. The adaptive-policy run's reward is decreased disagreement distance, not answer correctness.

Set up Ollama as above, then preflight one real session. This command loads the chosen sample and tests the endpoint; retain the same output directory for resuming:

```bash
uv run python -m bench.run configs/proposal_density_500.json --out results/proposal-density-500 --limit 1
```

If it completes and outputs `metrics.csv`, `board.sqlite`, `calls.jsonl` and `run.json`, launch the whole run:

```bash
uv run python -m bench.run configs/proposal_density_500.json --out results/proposal-density-500
```

Then analyze and verify all four conditions:

```bash
uv run python -m bench.ablation_analysis results/proposal-density-500/shard-1-of-1 --out results/proposal-density-500/analysis --expected-per-level 500
```

### Separate policy-learning control

To isolate adaptive tactic selection from the density intervention, run the matched static config (same sample seed, task selection and model; only `policy_learning` differs):

```bash
uv run python -m bench.run configs/proposal_density_static_500.json --out results/proposal-density-static-500
uv run python -m bench.ablation_analysis results/proposal-density-static-500/shard-1-of-1 --out results/proposal-density-static-500/analysis --expected-per-level 500
uv run python -m bench.policy_ablation_analysis results/proposal-density-static-500/shard-1-of-1 results/proposal-density-500/shard-1-of-1 --out results/proposal-policy-comparison --expected-per-level 500
```

This is an additional 2,000 sessions. If compute permits only the adaptive run, call it a density study with learned tactic selection as part of the intervention bundle; do not claim the separate causal effect of learning.

## What to do when results finish

1. Preserve and share each complete `results/<study>/shard-1-of-1/` directory, plus the separate `analysis/` directory. Do not send only the CSV: `board.sqlite`, `calls.jsonl`, `run.json`, `policy_memory.json` (when present), and benchmark-specific raw traces are needed for audit/reproduction.
2. Check row counts and provenance/task manifest. For the density run, require 2,000 metrics rows and 500 unique manifest IDs. For the static/adaptive comparison, confirm the comparator reports matching task IDs and 500 paired cases per condition.
3. Review condition tables and paired comparisons. Report checkpoint, rollback, consensus, correct consensus, model failures, token cost and time separately. Agreement is not correctness; rollback count is not successful recovery.
4. Audit a sample of correct and incorrect outputs and every alleged rollback recovery. Check whether the intervention answered the cited disagreement, whether any adopted change is supported by evidence, and whether the automatic judge was appropriate. For open-ended answers, explain approximate lexical grading limitations.
5. For KramaBench, retain per-task tool/data traces, subtask outcomes and official evaluator output. For MedAgentBench, retain FHIR action traces, reset evidence, environment image/task versions, and official grader outputs. Exclude invalid/incomplete tasks transparently; never silently replace them after seeing outcomes.
6. Send results plus exact configs, task/data manifest hashes, model tag/build, upstream revisions, evaluator version, run logs, and known failures back to the owner. The owner will then evaluate the results and update the report.

## Documentation map

- [Project and research record](docs/project_research.md): research question, protocol, scope alignment, prior runs and limitations.
- [Architecture and evaluation](docs/architecture_and_evaluation.md): cases, PXP-adjacent evaluation, metrics, paired runner and replay fixture.
- [Experiment and benchmark guides](docs/experiments_and_benchmarks.md): 2,000-session instructions and external benchmark boundaries.
- [PXP-N specification](docs/spec_pxp_n.md): detailed event/tag semantics; retained separately because `system_description.md` links to it.
- [Viewer guide](docs/viewer.md): frontend run/navigation instructions. Do not change frontend for this handover.

`final_submission/` contains the submitted-report source/template and presentation script. Do not open it for edits, reformat it, regenerate it, or move/delete files there.
