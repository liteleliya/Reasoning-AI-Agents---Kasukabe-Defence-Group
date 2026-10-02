"""J1: how often does the model produce a usable PXP message? (B2's >=95% target)

    uv run python -m bench.parse_check --n 50 [--parallel 4] [--out DIR] [--mock]

Half the calls are opening (INIT) prompts, half are replies to another agent's opening with a
different answer. Each reply is parsed; on failure the agent's single repair retry is tried.
Writes one JSON line per call to `<out>/calls.jsonl` and prints a summary.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from agents.llm_client import BaseLLMClient, make_client
from agents.parsing import REPLY_TAGS, PXPParseError, parse_pxp, repair_messages
from agents.prompts import init_messages, persona_for, reply_messages
from bench.mscore import Instance, sample
from bench.run import REPO, JobConfig, mock_client, question_text
from blackboard import EventStore
from protocol import EventDraft, Tag


def prompts_for(i: int, inst: Instance) -> tuple[list[dict], tuple[str, ...], str]:
    persona, me = persona_for(i), "agent_a"
    q = question_text(inst)
    if i % 2 == 0:
        return init_messages(persona, me, q, 3), ("INIT",), "init"
    letters = [k for k, _ in inst.options] or ["A", "B"]
    store = EventStore()
    for author, letter in ((me, letters[0]), ("agent_b", letters[-1])):
        store.append_sync(
            EventDraft(
                session_id="p",
                author=author,
                tag=Tag.INIT,
                prediction=letter,
                explanation="初步判断 / first reading",
            )
        )
    board = store.state("p")
    msgs = reply_messages(persona, me, q, board.events, board.events[1], letters[0], 3)
    return msgs, REPLY_TAGS, "reply"


async def check_one(i: int, inst: Instance, client: BaseLLMClient) -> dict:
    msgs, allowed, kind = prompts_for(i, inst)
    record: dict = {"i": i, "kind": kind, "instance": inst.id, "persona": persona_for(i).name}
    tokens = 0
    for attempt in range(2):
        r = await client.complete(
            msgs, json_mode=True, seed=i, max_tokens=400, label=f"parse_check/{i}"
        )
        tokens += r.usage.prompt + r.usage.completion
        record[f"raw_{attempt}"] = r.text
        try:
            parsed = parse_pxp(r.text, allowed_tags=allowed)
        except PXPParseError as err:
            record[f"error_{attempt}"] = err.reason
            msgs = [*msgs, *repair_messages(r.text, err)]
            continue
        record.update(ok=True, first_try=attempt == 0, tag=parsed.tag, tokens=tokens)
        return record
    record.update(ok=False, first_try=False, tag=None, tokens=tokens)
    return record


async def run(
    n: int, parallel: int, out: Path, client: BaseLLMClient, instances: Sequence[Instance]
) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(max(1, parallel))

    async def one(i: int) -> dict:
        async with sem:
            return await check_one(i, instances[i % len(instances)], client)

    try:
        records = await asyncio.gather(*(one(i) for i in range(n)))
    finally:
        await client.aclose()
    with (out / "calls.jsonl").open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return list(records)


def summary(records: Sequence[dict]) -> str:
    n = len(records)
    first = sum(r["first_try"] for r in records)
    ok = sum(r["ok"] for r in records)
    by_kind = Counter((r["kind"], r["ok"]) for r in records)
    tags = Counter(r["tag"] for r in records if r["ok"] and r["kind"] == "reply")
    errors = Counter(r.get("error_0", "").split(":")[0] for r in records if "error_0" in r)
    lines = [
        f"valid on first try: {first}/{n} ({first / n:.0%})",
        f"valid after one retry: {ok}/{n} ({ok / n:.0%})   target >= 95%",
        f"by kind: init {by_kind['init', True]}/{by_kind['init', True] + by_kind['init', False]}"
        f", reply {by_kind['reply', True]}/{by_kind['reply', True] + by_kind['reply', False]}",
        "reply tags: " + (", ".join(f"{t} {c}" for t, c in tags.most_common()) or "none"),
        f"mean tokens per call: {sum(r['tokens'] for r in records) / n:.0f}",
    ]
    if errors:
        lines.append(
            "first-try errors: " + "; ".join(f"{e} x{c}" for e, c in errors.most_common(3))
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Measure the share of model replies that parse.")
    p.add_argument("--n", type=int, default=50)
    p.add_argument("--parallel", type=int, default=4)
    p.add_argument("--out", default=str(REPO / "results" / "runs" / "j1_parse"))
    p.add_argument(
        "--config",
        default=str(REPO / "configs" / "j2_baseline.json"),
        help="job config whose question sample to use",
    )
    p.add_argument("--mock", action="store_true", help="scripted model, no GPU")
    a = p.parse_args(argv)
    job = JobConfig.load(a.config)
    instances = sample(**{**job.sample, "n_per_group": max(1, a.n // 4)})
    client = mock_client() if a.mock else make_client()
    records = asyncio.run(run(a.n, a.parallel, Path(a.out), client, instances))
    print(summary(records))


if __name__ == "__main__":
    main()
