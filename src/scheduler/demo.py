"""M1 demo: mock agents on the blackboard reaching consensus, impasse and the cap.

Run with `uv run python -m scheduler.demo [--db board.sqlite]`.
"""

from __future__ import annotations

import argparse
import asyncio

from blackboard import EventStore
from scheduler import ConfusedAgent, FollowerAgent, Scheduler, StubbornAgent

SCENARIOS = {
    "consensus": lambda: [
        StubbornAgent("a", "x"),
        FollowerAgent("b", "y"),
        FollowerAgent("c", "z"),
    ],
    "impasse": lambda: [StubbornAgent("a", "x"), StubbornAgent("b", "y")],
    "reject-loop": lambda: [ConfusedAgent("a", "x"), ConfusedAgent("b", "y")],
    "oscillation": lambda: [
        StubbornAgent("a", "x"),
        StubbornAgent("b", "y"),
        FollowerAgent("c", "z"),
    ],
}


async def main(db: str) -> None:
    store = EventStore(db)
    for name, make_agents in SCENARIOS.items():
        session = f"demo-{name}"
        if store.state(session).seq >= 0:
            session += f"-{len(store.sessions())}"
        result = await Scheduler(store, make_agents()).run(session, "What is x?")
        print(f"\n== {name}: stopped on {result.stop_reason.upper()} ==")
        for e in store.events(session):
            reply = f"-> {e.reply_to}" if e.reply_to is not None else ""
            print(f"  [{e.seq:>2}] {e.author:<6} {e.tag or e.kind:<7} {reply:<6} {e.prediction}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=":memory:", help="SQLite file to keep the log in")
    asyncio.run(main(parser.parse_args().db))
