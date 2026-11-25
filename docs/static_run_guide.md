# Running the static-policy density study on a second machine

This is the matched control for the adaptive density run. Same 500 tasks, same model, same
settings; only `policy_learning` is `false`. To fit the time available it covers density levels 1
and 2 only (1,000 sessions at about 25 seconds each, so **about 7 hours**). Level 0 has no
counterfactual agent, so no policy is ever used there, and level 3 is not needed for this
comparison. The run is resumable.

Read [HANDOVER.md](../HANDOVER.md) first for the general setup. This page is the short version
for this one run. Use macOS commands; use `ollama` and `uv` from the repository root.

## 1. Get the code

```bash
git checkout main && git pull origin main
uv sync --locked
```

Check that `configs/proposal_density_static_l12_500.json` exists. It pins the model
(`qwen2.5:3b-instruct`), the dissenter persona, temperature 1.0 and sample seed 20261124. Do not
edit it: the adaptive run on the other machine used the same file except for `policy_learning`.

## 2. Install and check the model

Install Ollama for macOS and open the app, then:

```bash
ollama pull qwen2.5:3b-instruct
ollama list          # note the ID; the adaptive run used 357c53fb659c
ollama run qwen2.5:3b-instruct "Reply with READY"
```

If the ID differs, write the new ID in your notes and tell the owner. The tag is the same, but a
different build is a caveat for the comparison.

## 3. Point the client at Ollama

```bash
export LLM_BACKEND=openai
export LLM_BASE_URL=http://127.0.0.1:11434/v1
export LLM_MODEL=qwen2.5:3b-instruct
uv run python -m agents.llm_client --backend openai "Return a short readiness response"
```

Do this in the same Terminal tab you will use for the run.

## 4. Preflight with one session

The sampler downloads the MSCoRe files it needs on first use, so keep the network on and leave at
least 5 GB free.

```bash
uv run python -m bench.run configs/proposal_density_static_l12_500.json \
  --out results/proposal-density-static-l12-500 --limit 1
```

It should end with `1 trials` done and a session time of roughly 20 to 40 seconds. If it fails,
stop and send the error; do not start the full run.

## 5. Launch the full run

Keep the Mac plugged in and awake. `caffeinate -i` stops idle sleep for as long as the command runs.

```bash
caffeinate -i uv run python -m bench.run configs/proposal_density_static_l12_500.json \
  --out results/proposal-density-static-l12-500
```

- Use the **same `--out` folder** every time. If the run stops (power cut, closed lid, crash),
  run the same command again and it continues; it skips finished sessions.
- Do not run anything else on Ollama at the same time, and keep `--parallel` at its default of 1.
- Progress: `echo $(( $(wc -l < results/proposal-density-static-l12-500/shard-1-of-1/metrics.csv) - 1 )) / 1000`

## 6. Check it finished

```bash
wc -l results/proposal-density-static-l12-500/shard-1-of-1/metrics.csv   # expect 1001 (header + 1000)
```

The count must be 1001, with 500 rows at each of the two levels. (The `ablation_analysis` script
needs all four levels, so do not run it on this folder; the owner compares the two runs with the
policy comparison below.)

## 7. Send back

`results/` is git-ignored, so zip the whole folder and send it to the owner:

```bash
cd results && zip -r proposal-density-static-l12-500.zip proposal-density-static-l12-500
```

It must contain `metrics.csv`, `board.sqlite`, `calls.jsonl`, `run.json` and, if present, `policy_memory.json`. Also send the `ollama list` line for the model and the
machine's chip and memory. Do not send only the CSV.

## What the owner does next

The two runs are compared with
`uv run python -m bench.policy_ablation_analysis <static>/shard-1-of-1 <adaptive>/shard-1-of-1 --out results/proposal-policy-comparison --expected-per-level 500 --levels 1 2`,
which checks that both runs used the same 500 task IDs at levels 1 and 2 before it reports anything. The adaptive
policy's reward is lower disagreement distance, not correctness, so the comparison says whether
tactic selection changed agreement and cost, not whether answers became right.
