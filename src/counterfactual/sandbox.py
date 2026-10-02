"""Retrospective sandbox (B4): replay one past message differently, in isolation (spec section 5).

The real board is never modified by the replay itself: the sandbox forks the store up to the
message before the target, posts the altered message on the fork, lets every other agent answer
once, measures the consensus distance, and only then appends a read-only record of what happened
to the real log as `rollback_start`, `rollback_step`* and `rollback_end` events.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from blackboard import EventStore
from protocol import SYSTEM, Event, EventDraft, Kind, ProtocolError, Tag, Tokens
from scheduler import Agent, exact_distance

Distance = Callable[[Mapping[str, str]], float]


@dataclass(frozen=True)
class Alternative:
    tag: Tag
    explanation: str
    prediction: str | None = None  # None = keep the original prediction
    tokens: Tokens = field(default_factory=Tokens)  # cost of producing the alternative


@dataclass
class ReplayResult:
    target: Event
    steps: list[Event]  # on the fork: the altered message, then one reply per other agent
    distance_replay: float
    distance_real: float
    tokens: int

    @property
    def credit_delta(self) -> float:
        """Negative = the alternative would have brought the agents closer together."""
        return self.distance_replay - self.distance_real


def _latest(events: Sequence[Event]) -> dict[str, str]:
    latest: dict[str, str] = {}
    for e in events:
        if e.kind is Kind.MESSAGE and not e.counterfactual and e.author != SYSTEM and e.tag:
            latest[e.author] = e.prediction
    return latest


async def replay(
    store: EventStore,
    session_id: str,
    target_seq: int,
    alt: Alternative,
    others: Sequence[Agent],
    question: str,
    *,
    distance: Distance = exact_distance,
    reason: str = "",
) -> ReplayResult:
    """Replay `target_seq` as `alt` against `others`, then log the rollback on the real store."""
    real = store.events(session_id)
    target = next((e for e in real if e.seq == target_seq), None)
    if target is None or target.kind is not Kind.MESSAGE or target.tag in (Tag.INIT, Tag.TERM):
        raise ValueError(f"seq {target_seq} is not a reply message that can be replayed")

    fork = store.fork(session_id, target_seq - 1)
    altered = EventDraft(
        session_id=session_id,
        author=target.author,
        tag=alt.tag,
        reply_to=target.reply_to,
        prediction=alt.prediction if alt.prediction is not None else target.prediction,
        explanation=alt.explanation,
        tokens=alt.tokens,
    )
    steps = [fork.append_sync(altered)]
    for agent in sorted(others, key=lambda a: a.name):
        if agent.name == target.author:
            continue
        draft = await agent.act(question, fork.state(session_id))
        if draft is None:
            continue
        try:
            steps.append(fork.append_sync(draft))
        except ProtocolError:
            continue  # an off-protocol reply simply does not happen in the replay
    fork.close()

    distance_replay = distance(_latest([*real[:target_seq], *steps]))
    # what really happened over the same number of messages from the target on
    following = [
        e
        for e in real
        if e.seq >= target_seq
        and e.kind is Kind.MESSAGE
        and not e.counterfactual
        and e.author != SYSTEM
    ]
    distance_real = distance(_latest([*real[:target_seq], *following[: len(steps)]]))
    result = ReplayResult(
        target=target,
        steps=steps,
        distance_replay=distance_replay,
        distance_real=distance_real,
        tokens=sum(e.tokens.in_ + e.tokens.out for e in steps),
    )
    _record(store, session_id, result, reason)
    return result


def _record(store: EventStore, session_id: str, result: ReplayResult, reason: str) -> None:
    author = result.target.author
    store.append_sync(
        EventDraft(
            session_id=session_id,
            author=author,
            kind=Kind.ROLLBACK_START,
            reply_to=result.target.seq,
            counterfactual=True,
            explanation=reason or f"replay seq {result.target.seq} as {result.steps[0].tag}",
        )
    )
    for e in result.steps:
        store.append_sync(
            EventDraft(
                session_id=session_id,
                author=e.author,
                kind=Kind.ROLLBACK_STEP,
                tag=e.tag,
                prediction=e.prediction,
                explanation=e.explanation,
                counterfactual=True,
                tokens=e.tokens,
                meta={"fork_seq": e.seq, "fork_reply_to": e.reply_to},
            )
        )
    store.append_sync(
        EventDraft(
            session_id=session_id,
            author=author,
            kind=Kind.ROLLBACK_END,
            counterfactual=True,
            explanation=f"consensus distance {result.distance_real:.2f} -> "
            f"{result.distance_replay:.2f}",
            meta={
                "credit_delta": round(result.credit_delta, 4),
                "distance_real": round(result.distance_real, 4),
                "distance_replay": round(result.distance_replay, 4),
                "target_seq": result.target.seq,
            },
        )
    )
