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
chosen because 7B debates almost never stall (see `docs/study_design_notes.md`). Do not change the
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
every 100). Details are in `docs/paired_runner.md`.

## When it finishes

Results are in `results/paired-study/shard-1-of-1/` (`metrics.csv`, `board.sqlite`,
`opportunities.jsonl`, `calls.jsonl`, `run.json`). Make the tables and figures:

    uv run python -m bench.paired_analysis results/paired-study/shard-1-of-1 --out results/paired-study/analysis

and look at `analysis.json` (verification first), then share the whole `results/paired-study`
folder. To browse the sessions in the viewer:

    uv run python -m server --db results/paired-study/shard-1-of-1/board.sqlite \
      --metrics results/paired-study/shard-1-of-1/metrics.csv --source "paired study" --kind model

then open http://127.0.0.1:8000 (see `docs/viewer.md`).
