# Three-arm paired runner

Roadmap section 08. A job config with `"arms": ["standard", "forward", "replay"]` runs this way:

    uv run python -m bench.run configs/paired_dev.json --mock --limit 6 --out results/paired-smoke
    uv run python -m bench.run configs/paired_dev.json            # real model, see docs/compute.md

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

`metrics.csv` (one row per completed arm, see `docs/metrics.md`), `board.sqlite` (prefix and arm
sessions), `calls.jsonl` (every model call, labelled by session), `opportunities.jsonl` (the
checkpoint record per session: eligibility, skip reason, outcome, replay details) and `run.json`.

## Cost accounting

`total_tokens` of an arm includes the prefix; `prefix_tokens` shows how much that was and
`intervention_calls` / `intervention_tokens` what was spent after the trigger. `allowance_calls`
(default 6) is the intervention allowance: the controls spend one call (two with a parse retry),
the replay arm one candidate (plus one repair) and four branch replies. `wall_time_s` is the
machine's actual time and is kept separate.

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
