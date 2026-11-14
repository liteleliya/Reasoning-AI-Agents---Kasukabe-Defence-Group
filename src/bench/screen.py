"""Screen an agent setup for real disagreement before spending a study run on it.

    uv run python -m bench.screen configs/<job>.json --out results/screen/<name> [--limit n]

Plays only the shared prefix of every (item, seed): about one debate each, no arms. Each row says
how far the agents disagreed on their opening answers, how the debate ended and whether the
recovery checkpoint opened. Held-out items are never screened, so the setup is tuned on development
items only and the study's questions stay untouched.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from agents.ledger import CallLedger
from agents.llm_client import BaseLLMClient, make_client
from bench.cases import DEFAULT_ROOT
from bench.paired import RosterFactory, _prefix, _trial, model_roster
from bench.run import JobConfig, groups, job_client_args, job_instances, judging, mock_client
from bench.splits import Splits
from blackboard import EventStore
from protocol import Kind, Tag
from scheduler import Sidecar

FIELDS = (
    "config",
    "instance_id",
    "seed",
    "init_groups",
    "init_distance",
    "stop_reason",
    "checkpoint",
    "skip_reason",
    "messages",
    "challenged_replies",
    "repair_calls",
    "wall_time_s",
)


def heldout_ids(root: str | Path = DEFAULT_ROOT) -> set[str]:
    """Every held-out item id as the runner names it, authored cases as `case:<id>`."""
    splits = Splits.load(Path(root) / "splits.json")
    return {
        *splits.choice.heldout,
        *splits.open.heldout,
        *(f"case:{c}" for c in splits.authored["heldout"]),
    }


def _row(trial, store: EventStore, sid: str, job: JobConfig, calls, wall: float) -> dict:
    events = store.events(sid)
    same, _ = judging(trial.instance.format, trial.instance)
    opens = {e.author: e.prediction for e in events if e.kind is Kind.MESSAGE and e.tag is Tag.INIT}
    parts = groups(opens, same)
    term = events[-1]
    recovery = term.meta.get("recovery") or {}
    opened = bool(recovery.get("eligible")) and recovery.get("skip_reason") is None
    return {
        "config": job.name,
        "instance_id": trial.instance.id,
        "seed": trial.meta.seed,
        "init_groups": len(parts),
        "init_distance": 1 - max(len(g) for g in parts) / len(opens) if opens else 1.0,
        "stop_reason": term.explanation,
        "checkpoint": "opened" if opened else "none",
        "skip_reason": recovery.get("skip_reason") or "",
        "messages": sum(1 for e in events if e.kind is Kind.MESSAGE and e.author != "system"),
        "challenged_replies": sum(1 for e in events if e.tag in (Tag.REFUTE, Tag.REJECT)),
        "repair_calls": sum(1 for c in calls if c.repair),  # replies the parser had to retry
        "wall_time_s": round(wall, 3),
    }


async def screen(
    job: JobConfig,
    out: Path,
    *,
    client: BaseLLMClient | None = None,
    roster: RosterFactory = model_roster,
    instances=None,
    limit: int | None = None,
    log: Callable[[str], None] = print,
) -> list[dict]:
    """Play the unfinished prefixes of the job's non-held-out items; returns the rows added."""
    out.mkdir(parents=True, exist_ok=True)
    client = client or make_client(**job_client_args(job))
    client.ledger = CallLedger(out / "calls.jsonl")
    held = heldout_ids()
    items = [i for i in (instances if instances is not None else job_instances(job))]
    kept = [i for i in items if i.id not in held]
    if len(kept) != len(items):
        log(f"left out {len(items) - len(kept)} held-out items")
    path = out / "screen.csv"
    done = _done(path)
    store, sidecar = EventStore(out / "board.sqlite"), Sidecar(out / "opportunities.jsonl")
    units = sorted(((i, s) for s in job.seeds for i in kept), key=lambda u: (u[0].id, u[1]))
    rows: list[dict] = []
    try:
        for inst, seed in units:
            trial = _trial(job, inst, seed, "prefix")
            if (inst.id, str(seed)) in done:
                continue
            if limit is not None and len(rows) >= limit:
                break
            start = time.perf_counter()
            sid = await _prefix(trial, store, client, job, roster, sidecar)
            calls = client.ledger.for_trial(sid)
            row = _row(trial, store, sid, job, calls, time.perf_counter() - start)
            _append(path, row)
            rows.append(row)
            log(
                f"{inst.id[-34:]} seed {seed}: {row['init_groups']} opening answers, "
                f"{row['stop_reason']}, checkpoint {row['checkpoint']}"
            )
    finally:
        store.close()
        await client.aclose()
    return rows


def _done(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    with path.open(newline="") as f:
        return {(r["instance_id"], r["seed"]) for r in csv.DictReader(f)}


def _append(path: Path, row: dict) -> None:
    fresh = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if fresh:
            writer.writeheader()
        writer.writerow(row)


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Shares of prefixes that began in disagreement, reached consensus or opened a checkpoint."""
    n = len(rows)

    def share(hit) -> float | None:
        return sum(hit(r) for r in rows) / n if n else None

    return {
        "prefixes": n,
        "initial_disagreement": share(lambda r: float(r["init_distance"]) > 0),
        "consensus": share(lambda r: r["stop_reason"] == "consensus"),
        "checkpoint_opened": share(lambda r: r["checkpoint"] == "opened"),
    }


def main(argv: Sequence[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Screen a setup for real disagreement.")
    p.add_argument("config")
    p.add_argument("--out", required=True)
    p.add_argument("--mock", action="store_true")
    p.add_argument("--limit", type=int)
    a = p.parse_args(argv)
    job = JobConfig.load(a.config)
    out = Path(a.out)
    asyncio.run(screen(job, out, client=mock_client() if a.mock else None, limit=a.limit))
    with (out / "screen.csv").open(newline="") as f:
        print(json.dumps(summarize(list(csv.DictReader(f))), indent=2))


if __name__ == "__main__":
    main()
