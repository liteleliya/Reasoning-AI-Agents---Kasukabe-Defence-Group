# Intelligible Blackboard with Counterfactual Agents

**CS F407 Artificial Intelligence course project · Kasukabe Defence Group**

Intelligible Blackboard is a local, inspectable multi-agent system. Three language-model agents answer the same task, publish their predictions and explanations to a shared blackboard, and respond to one another using structured dialogue moves. When their debate reaches a qualifying disagreement, the system can compare ordinary continuation with two recovery strategies, including a counterfactual replay. The project asks whether replay helps the group reach a *correct* answer after such a checkpoint.

This is a course-project adaptation inspired by Baskar et al.'s prediction-and-explanation interaction model; it is not a full reproduction of that paper. The final paired run is an inconclusive baseline: standard continuation and replay each produced one correct recovery among 52 eligible checkpoints, while replay used substantially more tokens. We report this as a result, not as evidence that replay improves reasoning.

**Repository:** [liteleliya/Reasoning-AI-Agents---Kasukabe-Defence-Group](https://github.com/liteleliya/Reasoning-AI-Agents---Kasukabe-Defence-Group)<br>
**Research and protocol:** [docs/project_research.md](docs/project_research.md) · **Handover:** [HANDOVER.md](HANDOVER.md) · **Final submission files:** [final_submission/](final_submission/) · **Results overview:** [results/README.md](results/README.md)

For a direct comparison with the professor's original project proposal—including completed components, scope adaptations, and substantial future work—see [docs/project_research.md](docs/project_research.md).

## Start here

The main experience has three parts:

1. The **Project guide** explains the research question, the interaction protocol, and project vocabulary.
2. The **Results** page summarizes the saved study, including checkpoint frequency, arm outcomes, replay decisions, cost, and evidence-quality caveats.
3. **Explore runs** lets you select a case and inspect its event-by-event timeline, board state, and counterfactual branch.

The project runs locally. Agent requests go to a model server such as Ollama on the same machine; the viewer reads saved experiment outputs. It does not require a hosted model API for the documented setup.

## The idea in plain language

Imagine three reviewers answering the same decision question. Each reviewer writes down an answer and a reason. Other reviewers can agree, challenge the answer, propose a new one, or decline to adopt a suggestion. Every message is saved to a shared board with a link to the message it addresses.

The research comparison begins only after a prefix reaches the study's checkpoint rule. That same saved prefix is then copied into three arms:

| Arm | What happens after the shared prefix |
|---|---|
| **Standard** | The challenged agent replies through the ordinary dialogue policy. |
| **Forward rethink** | The challenged agent is asked to reconsider the challenge in a new live reply. |
| **Counterfactual replay** | The system compares the original challenged message with a replacement on matched temporary branches, then may adopt a helpful replacement into the live dialogue. |

The question is not simply whether the agents agree. We separately record whether they agree, whether the final answer passes the automatic check or human rubric, whether a replay candidate is adopted, and how much computation it costs.

## Project vocabulary

| Term | Meaning in this project |
|---|---|
| **Blackboard** | The shared, append-only record of messages, branch markers, and task state. Agents read the board and add their next message to it. |
| **PXP** | Prediction-and-explanation protocol. Each message contains a prediction, an explanation, a dialogue tag, and a reference to the message being answered. |
| **RATIFY** | Keep the current prediction and explicitly accept the other agent's reasoning. |
| **REFUTE** | Challenge a specific part of another contribution, give corrective information, and keep the agent's own answer. A refute is a recorded challenge, not a guarantee that the challenged answer is wrong. |
| **REVISE** | Change the prediction in response to the discussion. A revision is useful when it addresses the evidence or challenge that prompted it. |
| **REJECT** | Decline another contribution without adopting it. Repeated rejection can indicate that the discussion is not progressing. |
| **Consensus** | The scheduler's agreement condition has been met. Consensus does not imply correctness. |
| **Impasse** | The run stopped without consensus under its stopping rules. It is a termination state, not a grade. |
| **Checkpoint / eligibility** | A shared prefix has met the configured rule for entering recovery. It is counted once per case and seed, not once per arm. |
| **Counterfactual branch** | A temporary copy used to test an alternative message. Branch events are labelled counterfactual and do not silently rewrite the live history. |
| **Replay** | Run matched branches for the original and replacement messages with the same peers and reply limits; compare the resulting board distance. |
| **Credit / helpfulness** | The difference between the replacement and original branch outcomes. A negative distance delta means the replacement brought predictions closer under the configured comparator. It is not a factual correctness score. |
| **Adopted / accepted** | A replay candidate was accepted as a live reply (`reply_accepted`). Adoption is a process outcome; the final answer can still be wrong. |
| **Rollback** | A logged start, step, or end operation that marks a temporary replay. The run's `rollbacks` field counts replay operations, not recovered answers. |
| **Recovery** | What an arm does after an eligible checkpoint. The analysis tracks attempted, completed, helpful, adopted, and correct recovery as distinct stages. |
| **Correct recovery** | The prefix was eligible, the arm ended in consensus, and the final answer was graded correct. This is the primary outcome. |
| **Intelligibility** | A computed label about how inspectable the message/reply relationships are. It is not a human rating of whether someone understood the debate. |
| **Percentage point (pp)** | The arithmetic difference between two percentages. For example, a change from 10% to 12% is +2 pp, not +2%. |
| **Seed** | A reproducibility input used to vary a run. Each case-seed pair is one matched experimental unit. |

The interface's detailed glossary is available from **Project guide**.

## What is implemented

### Architecture

- `src/protocol/` defines the event schema, validation rules, dialogue tags, and intelligibility classification.
- `src/blackboard/` stores the append-only SQLite event history and reconstructs board snapshots.
- `src/scheduler/` chooses agent turns, enforces stopping rules, and detects recovery opportunities.
- `src/agents/` contains the model client, prompting, PXP parsing, and agent loop.
- `src/counterfactual/` creates matched temporary branches, records replay events, and assigns branch credit.
- `src/bench/` loads cases, runs resumable experiments, checks answers, records metrics, and produces paired analyses.
- `src/server/` serves the saved sessions, summaries, case briefs, and React frontend through a local FastAPI server.
- `ui/` contains the React, TypeScript, and D3 project guide, results dashboard, and interactive trace explorer.
- `data/cases/public/` contains public task statements. `data/cases/grading/` contains the separate scoring rules for team-authored cases.
- `configs/` defines the paired baseline, a small development setup, and a separate challenge-suite setup.

The event history is the source of truth. A message event records who spoke, the tag, the reply target, prediction, explanation, and token usage. Replay operations are explicit event kinds. A snapshot can therefore show the board at a chosen sequence without treating the counterfactual branch as a live answer.

### Current saved results

The frozen 3B paired baseline has **144 case-seed prefixes** and **432 arm outcomes** (three arms per prefix). A checkpoint opened on **52 of 144 prefixes**. Among those 52 eligible prefixes, correct recovery was **1/52 for standard**, **0/52 for forward rethink**, and **1/52 for replay**. Replay was adopted on 10 attempts, but only one replay recovery passed the automatic correctness check. Replay used a mean of 19,578.9 full-trial tokens per eligible item, compared with 13,449.8 for standard.

Replay versus standard had one win, one loss, and 50 ties on correct recovery; the observed rate difference was 0.0 pp. The run is inconclusive and shows no evidence of a replay advantage. It was deliberately configured with a disagreement-rich dissenter persona, so its checkpoint rate should not be read as the natural stall rate of ordinary agents. The automatic checks are not human rubric scores; the final run has no human rubric grades. See [results/paired-study/README.md](results/paired-study/README.md) for the full account, and [docs/project_research.md](docs/project_research.md) for limitations and interpretation rules.

J1, J2, J3, and the paired baseline are historical stages. They used different configurations and, in some cases, different questions or model sizes. Do not combine their results into one model-size comparison. The separate challenge suite is also not part of the frozen baseline.

## Requirements

- Windows, macOS, or Linux.
- Python 3.11. The repository pins dependencies through `uv.lock`.
- [`uv`](https://docs.astral.sh/uv/) for Python environment and command management.
- Node.js 24 and npm for building or running the React frontend.
- [Ollama](https://ollama.com/download) for local model inference when running model-backed experiments.
- Enough memory and disk space for the selected model. The saved final paired model was a quantized Qwen2.5 3B Instruct build; a Qwen2.5 7B model was used in earlier exploratory runs.

## Create the local environment

From the repository root:

```powershell
uv sync --locked
```

Build the user interface once so the Python server can serve its production files:

```powershell
Set-Location ui
npm ci
npm run typecheck
npm run build
Set-Location ..
```

The Python checks are available when you want to validate a code change:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

The UI checks are `npm run typecheck`, `npm test`, and `npm run build` from `ui/`.

## Run local models with Ollama

The model client uses Ollama's local OpenAI-compatible endpoint. The final saved paired run used the exact tag `qwen2.5:3b-instruct`, with a 3.09B parameter Q4_K_M model build. This is a **3B-parameter Qwen2.5 model**, not a 2.5B-parameter model. Earlier J2/J3 exploratory runs used the Qwen2.5 7B family. Since those runs used different setups, they do not isolate the causal effect of changing model size.

Ollama provides multiple Qwen2.5 instruction model sizes, including 1.5B, 3B, and 7B. Choose according to local memory, but record the exact tag and quantization in any new study. The smaller models are useful for checking the pipeline; their results must not be merged with the saved 3B study. Consult the [Ollama Qwen2.5 model library](https://ollama.com/library/qwen2.5) for available tags.

Install the final study model and verify that Ollama can invoke it:

```powershell
ollama pull qwen2.5:3b-instruct
ollama run qwen2.5:3b-instruct
```

Exit the interactive prompt, then set the API endpoint and model for commands that do not pin a model in their config:

```powershell
$env:LLM_BACKEND = "openai"
$env:LLM_BASE_URL = "http://127.0.0.1:11434/v1"
$env:LLM_MODEL = "qwen2.5:3b-instruct"
```

The default Ollama server usually runs in the background. If it is not available, start `ollama serve` in a separate terminal. To use another Ollama model, pull that exact model tag and set `LLM_MODEL`. A job configuration with a non-empty `model` field overrides `LLM_MODEL`; `configs/paired_study.json` intentionally pins the model used for the saved baseline.

## Run a fresh experiment

### 1. Check the pipeline without using a model

This short mock run is for verifying that case loading, the paired runner, event writing, and metrics output are wired correctly. It is not research evidence:

```powershell
uv run python -m bench.run configs/paired_dev.json --mock --limit 6 --out results/dev-smoke
```

The `--out` option creates a `shard-1-of-1` subfolder. The runner saves completed trials as it goes and skips completed trial keys when rerun at the same path. Use a new output folder for a new experiment; reusing an old folder resumes it.

### 2. Run the development configuration with a local model

The development config does not pin a model, so it uses `LLM_MODEL`:

```powershell
uv run python -m bench.run configs/paired_dev.json --limit 6 --out results/dev-qwen3b
```

The first run should be small. Check the saved `run.json`, `metrics.csv`, and event database before starting a full study.

### 3. Run the full paired study

The saved study config covers the held-out split, three item types, six seeds, and three matched arms. It is a substantial local computation. Start the frozen baseline in a fresh output directory with Ollama running:

```powershell
uv run python -m bench.run configs/paired_study.json --out results/paired-study-rerun
```

For a different model, make a separate copy of the JSON config, change its `name` and `model`, and write to a separate output directory. Keep the cases, seeds, prompt/persona setup, scheduler rules, and sampling parameters fixed if the goal is to compare models. The historical 7B runs are not that controlled comparison.

### Run the proposal follow-up density ablation

The new MSCoRe follow-up draws one fixed set of 500 unique items, then runs each item at 0, 1, 2, and 3 counterfactual-enabled agents. This is 500 matched cases per condition, 2,000 model sessions total, one generation seed per item. The protocol also enables persistent per-condition tactic selection; it rewards lower disagreement distance, not correctness. Follow the preflight, resume, model, output, and interpretation instructions in [docs/experiments_and_benchmarks.md](docs/experiments_and_benchmarks.md).

```powershell
uv run python -m bench.run configs/proposal_density_500.json --out results/proposal-density-500
uv run python -m bench.ablation_analysis results/proposal-density-500/shard-1-of-1 --out results/proposal-density-500/analysis --expected-per-level 500
```

This run is not evidence of 500 checkpoints or successful rollbacks. The final report should keep checkpoint, rollback, consensus, and judged-correct outcomes distinct. For policy-learning claims, run the included `configs/proposal_density_static_500.json` control and the comparison command in the ablation guide.

### External benchmark adapters

KramaBench and MedAgentBench task-file loaders are prototypes for local files, not official benchmark integrations. They are deliberately not included in the MSCoRe study command above. See [docs/experiments_and_benchmarks.md](docs/experiments_and_benchmarks.md) for the remaining data-environment and scoring requirements.

To run the separate four-seed authored challenge suite:

```powershell
uv run python -m bench.run configs/challenge_paired.json --out results/challenge-paired
```

Keep challenge results separate from the held-out baseline. Do not modify an existing frozen config or output folder after a run and then describe it as the same experiment.

### 4. Analyze the run

For a single-shard run, generate its aggregate tables, paired comparisons, and figures:

```powershell
uv run python -m bench.paired_analysis results/paired-study-rerun/shard-1-of-1 --out results/paired-study-rerun/analysis
```

The report includes a recovery funnel, correct-recovery outcomes, paired win/loss/tie counts, descriptive case-bootstrap intervals, token/time costs, and verification checks. The bootstrap interval is descriptive; it is not proof that one policy is better.

## View the results and use the frontend

### Production frontend served with the saved run

Build `ui/dist/` as described above. Then, from the repository root:

```powershell
uv run python -m server --run-dir results/paired-study
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). For a new one-shard run, substitute its parent output directory, such as `results/paired-study-rerun`. The server reads the board database and metrics from its shard folder and serves the saved study analysis when available.

### Frontend development mode

Keep the Python server running in one terminal. In another terminal:

```powershell
Set-Location ui
npm run dev
```

Open the local Vite URL printed in the terminal (normally `http://127.0.0.1:5173`). The Vite configuration forwards API and WebSocket requests to the Python server on port 8000.

### Navigation

- **Project guide:** read the research question, workflow, vocabulary, and the distinction between process counts and answer-quality outcomes.
- **Results:** start with the checkpoint and correct-recovery cards. Compare the standard, forward, and replay arms; read the replay funnel and paired comparison; use the case-by-seed matrix to open a specific session. `Adopted` means accepted into the live answer, not graded correct.
- **Explore runs:** search or filter the recorded sessions in the left rail and select a case. The event graph shows which agent spoke, its dialogue tag, and the reply link. Use **Previous**, **Play**, **Next**, **First challenge**, **Termination**, and the sequence slider to move through the trace. Select a graph event or event-list entry to inspect its prediction and explanation. The right-hand panels show the selected event, board snapshot, whole-session outcome, and recorded counterfactual replay when one exists.

## Results folder and data handling

`results/README.md` summarizes the pilot sequence and links to the final paired baseline. The repository keeps small aggregate outputs and figures reviewable. Full local run folders remain useful for reproducing the interactive viewer, but raw SQLite boards, model call logs, grader mapping files, and the large cached MSCoRe download are intentionally ignored by `.gitignore`. Do not publish `results/paired-study/grading/private.json`: it maps blinded responses to conditions and contains automatic hints. If a result needs to be shared for independent analysis, share the complete run securely with the team and keep the private grading map away from blinded graders.

The final report and a 2:30 presentation script are in [`final_submission/`](final_submission/). The original course template is preserved in `final_submission/Project_Sub_Template/`; `final_report.tex` is a separate copy that follows its layout.

## References

- A. Baskar, A. Srinivasan, M. Bain, and E. Coiera. “A Model for Intelligible Interaction Between Agents That Predict and Explain.” arXiv:2301.01819, 2023/2024. [Paper](https://arxiv.org/abs/2301.01819).
- Y. Lei et al. “MSCoRe: A Benchmark for Multi-Stage Collaborative Reasoning in LLM Agents.” arXiv:2509.17628, 2025. [Paper](https://arxiv.org/abs/2509.17628) · [Dataset](https://huggingface.co/datasets/032564yn/MSCoRe).
- Qwen Team. “Qwen2.5 Technical Report.” arXiv:2412.15115, 2024. [Paper](https://arxiv.org/abs/2412.15115).
- Ollama. [Qwen2.5 model tags](https://ollama.com/library/qwen2.5) and [OpenAI-compatible API](https://ollama.com/blog/openai-compatibility).
