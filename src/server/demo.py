"""Demo sessions written slowly into the store, so the UI can be watched live."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from blackboard import BoardState, EventStore
from protocol import EventDraft, Kind, Tag
from scheduler import ConfusedAgent, FollowerAgent, Scheduler, StubbornAgent


@dataclass
class Paced:
    """Wraps an agent and waits `delay` seconds before each move."""

    inner: object
    delay: float

    @property
    def name(self) -> str:
        return self.inner.name  # type: ignore[attr-defined]

    async def act(self, question: str, board: BoardState) -> EventDraft | None:
        await asyncio.sleep(self.delay)
        return await self.inner.act(question, board)  # type: ignore[attr-defined]


def _scenarios():
    return {
        "consensus": [StubbornAgent("a", "x"), FollowerAgent("b", "y"), FollowerAgent("c", "z")],
        "impasse": [StubbornAgent("a", "x"), StubbornAgent("b", "y")],
        "reject-loop": [ConfusedAgent("a", "x"), ConfusedAgent("b", "y")],
    }


async def scripted_rollback(store: EventStore, session: str, delay: float) -> None:
    """A hand-scripted session with one counterfactual replay, until the real sandbox (B4) lands."""

    async def put(**kw) -> None:
        await asyncio.sleep(delay)
        await store.append(EventDraft(session_id=session, **kw))

    tok = {"in": 120, "out": 30}
    await put(author="a", tag=Tag.INIT, prediction="x", explanation="x because p", tokens=tok)
    await put(author="b", tag=Tag.INIT, prediction="y", explanation="y because q", tokens=tok)
    await put(
        author="a", tag=Tag.REFUTE, reply_to=1, prediction="x", explanation="q is wrong", tokens=tok
    )
    await put(
        author="b", tag=Tag.REFUTE, reply_to=2, prediction="y", explanation="p is wrong", tokens=tok
    )
    await put(
        author="a",
        kind=Kind.ROLLBACK_START,
        reply_to=2,
        counterfactual=True,
        explanation="what if I had explained p instead of attacking q?",
    )
    await put(
        author="a",
        kind=Kind.ROLLBACK_STEP,
        tag=Tag.REVISE,
        reply_to=1,
        prediction="x",
        explanation="p holds; here is the derivation",
        counterfactual=True,
        tokens=tok,
    )
    await put(
        author="b",
        kind=Kind.ROLLBACK_STEP,
        tag=Tag.RATIFY,
        prediction="x",
        explanation="with that derivation, x",
        counterfactual=True,
        tokens=tok,
    )
    await put(
        author="a",
        kind=Kind.ROLLBACK_END,
        counterfactual=True,
        explanation="consensus distance 0.5 -> 0.0",
        meta={"credit_delta": -0.5},
    )
    await put(
        author="a",
        tag=Tag.REFUTE,
        reply_to=3,
        prediction="x",
        explanation="p holds; here is the derivation",
        tokens=tok,
    )
    await put(
        author="b", tag=Tag.REVISE, reply_to=8, prediction="x", explanation="agreed, x", tokens=tok
    )
    await put(author="a", tag=Tag.RATIFY, reply_to=9, prediction="x", explanation="x", tokens=tok)
    await put(author="system", tag=Tag.TERM, explanation="consensus")


async def run_demo(store: EventStore, delay: float = 0.8, loop_forever: bool = False) -> None:
    round_ = 0
    while store.state(f"demo-consensus-{round_}" if round_ else "demo-consensus").seq >= 0:
        round_ += 1  # an existing db already holds earlier demo rounds
    while True:
        suffix = f"-{round_}" if round_ else ""
        for name, agents in _scenarios().items():
            paced = [Paced(a, delay) for a in agents]
            await Scheduler(store, paced).run(f"demo-{name}{suffix}", "What is x?")
        await scripted_rollback(store, f"demo-rollback{suffix}", delay)
        round_ += 1
        if not loop_forever:
            return
