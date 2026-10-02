# Intelligible Blackboard Architecture with Counterfactual Agents

Reasoning Agents AI course project (2 people).

## Claim under test

On a shared blackboard where agents post predictions and explanations tagged with the
PXP protocol ([Baskar, Srinivasan, Bain, Coiera, arXiv:2301.01819](https://arxiv.org/abs/2301.01819);
reference implementation [karannb/interact](https://github.com/karannb/interact), MIT), agents that
can replay their own past messages with a different tag or explanation (counterfactual credit
assignment) break deadlocks faster and more cheaply than agents that cannot.

- **Independent variable:** share of counterfactual-enabled agents (0 / 33 / 67 / 100%; 3 agents with 0-3 counterfactual, or 6 agents).
- **H1:** convergence success rate within the iteration cap.
- **H2:** share of sessions ending Ultra-Strong (Strong = every interaction one-way intelligible; Ultra-Strong = Strong plus at least one REVISE).
- **H3:** total tokens per instance, including rollback tokens.
- **Tags:** RATIFY, REVISE, REFUTE, REJECT, plus INIT / TERM. Semantics are specified in [docs/spec_pxp_n.md](docs/spec_pxp_n.md).
- **Benchmarks:** MSCoRe (first), KramaBench subset (second), MedAgentBench (optional).

## Architecture

One append-only event log; every component reads from or writes to it.

```
            PEX agents (LLMClient)            Counterfactual sandbox
                    ^  |                       (copy slice, alter, replay,
                    |  v                        return credit delta)
 Scheduler <-> Blackboard core <------------------------^
               (validator, tag state machine,
                SQLite event log, snapshot at any seq)
                    |            ^
                    v            |
       FastAPI WebSocket    Benchmark engine
       -> React/D3 UI       (ingest, judge, runner, metrics CSV, plots)
```

Event record:

```json
{"seq": 0, "session_id": "", "author": "", "kind": "message|rollback_start|rollback_step|rollback_end",
 "tag": "", "reply_to": null, "prediction": "", "explanation": "", "counterfactual": false,
 "tokens": {"in": 0, "out": 0}}
```

## Repository layout

| Path | Contents | Tasks |
|---|---|---|
| `docs/spec_pxp_n.md` | PXP-N spec and decision log | A1 |
| `src/blackboard/` | Event log store, snapshots, write lock | A2 |
| `src/protocol/` | Schema, validator, tag state machine, intelligibility classifier | A3, A4 |
| `src/scheduler/` | Event-driven scheduler | A5 |
| `src/agents/` | LLMClient, prompts, PEX agent loop, consensus distance | B1-B3, B5 |
| `src/counterfactual/` | Rollback sandbox, credit assignment | B4, B6 |
| `src/server/` | FastAPI WebSocket | C1 |
| `src/bench/` | Ingestors, correctness rules, runner, metrics, plots | D1-D5 |
| `ui/` | Vite + React + D3 graph UI | C2-C4 |
| `tests/` | pytest suite | all |
| `results/` | Trial outputs (git-ignored except README) | D3-D5 |
| `paper/` | Final report | D6 |

## Division of work

- **Person 1 (Aadi, platform, MacBook Air, no CUDA):** A2-A5 blackboard, protocol, scheduler; C1-C4 server and UI; D1, D3, D5 ingest, metrics, plots.
- **Person 2 (agents and experiments, RTX 4050 laptop):** B1-B6 LLMClient, prompts, agent loop, sandbox, consensus metric, credit assignment; D2, D4 correctness rule, resumable runner.
- **Joint:** A1 spec, D6 paper.

Compute: Ollama locally, vLLM on Colab T4s. Both expose OpenAI-compatible endpoints, so one
`LLMClient` backend plus a deterministic mock covers everything. The runner writes each finished
trial to disk so Colab disconnects are resumable.

## Milestones

| Milestone | Scope | Target |
|---|---|---|
| M1 | Board + validator + scheduler with mock agents | ~4 Oct 2026 (flash talk 6 Oct) |
| M2 | Real 7B model, prompts, WebSocket, MSCoRe ingest | ~17 Oct |
| M3 | Rollback sandbox + graph UI | ~31 Oct |
| M4 | Benchmark runs, plots, paper | Nov (final deadline TBC, placeholder 21 Nov) |

## How to run

Requires [uv](https://docs.astral.sh/uv/) (it fetches Python 3.11 itself) and Node 24 for the UI.

```bash
uv sync                                  # Python env with runtime + dev dependencies
uv run pytest                            # tests
uv run ruff check . && uv run ruff format --check .
```

| What | Command |
|---|---|
| Mock agents on the board (M1 demo, terminal) | `uv run python -m scheduler.demo` |
| Server + live demo sessions | `uv run python -m server --demo` then open http://127.0.0.1:8000 |
| Build the UI the server serves | `cd ui && npm install && npm run build` |
| UI with hot reload (proxies to :8000) | `cd ui && npm run dev` then open http://localhost:5173 |
| Sample MSCoRe instances | `uv run python -m bench.mscore --n 5 --domains law finance` |
| Figures from a metrics CSV | `uv run python -m bench.plots results/metrics.csv --out results/figures` |
| One prompt to the configured model | `uv run python -m agents.llm_client "Say hi"` |
| Run (or resume) an experiment job | `uv run python -m bench.run configs/<job>.json --shard 1/1 --parallel 8` (`--mock` needs no model) |
| Prompt parse check (J1) | `uv run python -m bench.parse_check --n 50` |

The model is chosen by environment variables: `LLM_BACKEND=openai`, `LLM_BASE_URL` (Ollama
`http://127.0.0.1:11434/v1`, vLLM `http://127.0.0.1:8001/v1`) and `LLM_MODEL`.

### Code map (what exists)

| Module | Main entry points |
|---|---|
| `protocol` | `EventDraft`, `Event`, `Tag`, `check`/`validate`, `classify`, `choose_tag` |
| `blackboard` | `EventStore` (`append`, `state`, `snapshot`, `fork`, `subscribe`), `BoardState` |
| `scheduler` | `Scheduler`, `SchedulerConfig`, `Agent` protocol, mock agents |
| `agents` | `make_client` (mock / OpenAI-compatible, token counts), `PEXAgent`, prompts, `parse_pxp` |
| `counterfactual` | `replay` (sandbox, credit delta), `CounterfactualAgent` (credit assignment) |
| `server` | `create_app` (REST + `/ws`), `--demo` streamer |
| `bench` | `mscore` ingestor, `run` (resumable runner), `parse_check`, `metrics`, `plots` |
| `configs/` | Job configs: `j2_baseline.json`, `j3_prelim.json` |
| `ui/` | graph view, history scrubber, counterfactual split panel |

### MSCoRe notes

The HF repo now holds 166,276 instances in 8 domains, in Chinese. Open-ended QA (automotive,
automotive energy, e-commerce, pharmaceutical) is scored against a reference answer; law and
finance are single/multiple choice and construction is true/false, so consensus and correctness
are exact there. See `bench/mscore.py`.

### Troubleshooting

**macOS: `No module named 'scheduler'` (or `bench`, `server`) from `uv run python -m ...`.**
Something on the machine marked the files in `.venv` as hidden, and Python skips hidden `.pth`
files, so the editable install is ignored (pytest is unaffected). Fix:

```bash
chflags -R nohidden .venv
```

## Working agreement

- `main` is always green.
- One branch per task (e.g. `a2-blackboard-store`), linked to its issue.
- Every PR is reviewed by the other person before merge.
