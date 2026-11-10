"""Matched sandbox branches (roadmap section 04).

To measure what a replacement reply changes, the original reply and the replacement are each
posted on their own fork of the board, taken just before the tested message, and the same two
peers answer the tested message directly. Both forks get fresh peers built by the same factory,
the same responder order and the same limits, so the only difference between them is the tested
message. The recorded main log is kept as a third, observational reference.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from agents.ledger import call_scope
from blackboard import BoardState, EventStore
from counterfactual.sandbox import Alternative, Distance, latest_predictions
from protocol import SYSTEM, Event, EventDraft, Kind, ProtocolError, Tokens
from scheduler import TurnResult, exact_distance

PEER_COUNT = 2  # the first version replays against exactly two peers


class Responder(Protocol):
    """A peer that can answer one given message, whatever the normal turn order would pick."""

    name: str

    async def reply_to_target(
        self, question: str, board: BoardState, target: Event
    ) -> TurnResult | EventDraft | None: ...


@dataclass
class BranchRun:
    label: str  # "original" or "replacement"
    steps: list[Event]  # the tested message, then the peers' replies; fork-local sequence numbers
    distance: float | None  # None unless every peer replied
    tokens: int  # spent by the peers on this branch
    complete: bool
    reason: str = ""  # why the branch is incomplete


@dataclass
class PairResult:
    replay_id: str
    target: Event
    challenger_seq: int | None
    original: BranchRun
    replacement: BranchRun
    distance_recorded: float  # what the recorded log shows over the same messages (reference)

    @property
    def complete(self) -> bool:
        return self.original.complete and self.replacement.complete

    @property
    def status(self) -> str:
        return "completed" if self.complete else "incomplete"

    @property
    def credit_delta(self) -> float | None:
        """Replacement minus original distance; negative = the replacement helped in the sandbox."""
        if not self.complete:
            return None
        assert self.original.distance is not None and self.replacement.distance is not None
        return self.replacement.distance - self.original.distance


async def replay_pair(
    store: EventStore,
    session_id: str,
    target_seq: int,
    alt: Alternative,
    make_peers: Callable[[], Sequence[Responder]],
    question: str,
    *,
    distance: Distance = exact_distance,
    challenger_seq: int | None = None,
    max_branch_tokens: int | None = None,
    reason: str = "",
) -> PairResult:
    """Run the original and the replacement on matched forks, then log both on the real store."""
    real = store.events(session_id)
    target = next((e for e in real if e.seq == target_seq), None)
    if target is None or target.kind is not Kind.MESSAGE or target.reply_to is None:
        raise ValueError(f"seq {target_seq} is not a reply message that can be replayed")

    original_draft = EventDraft(
        session_id=session_id,
        author=target.author,
        tag=target.tag,
        reply_to=target.reply_to,
        prediction=target.prediction,
        explanation=target.explanation,
    )
    # the replacement answers the same message as the original, whatever the model said
    replacement_draft = original_draft.model_copy(
        update={
            "tag": alt.tag,
            "prediction": alt.prediction if alt.prediction is not None else target.prediction,
            "explanation": alt.explanation,
        }
    )
    args = (store, session_id, target, make_peers, question, distance, max_branch_tokens)
    original = await _run_branch(*args, "original", original_draft)
    replacement = await _run_branch(*args, "replacement", replacement_draft)
    result = PairResult(
        replay_id=_next_replay_id(store, session_id),
        target=target,
        challenger_seq=challenger_seq,
        original=original,
        replacement=replacement,
        distance_recorded=_recorded_distance(real, target_seq, len(original.steps), distance),
    )
    _record_pair(store, session_id, result, alt.tokens, alt.call_ids, reason)
    return result


async def _run_branch(
    store: EventStore,
    session_id: str,
    target: Event,
    make_peers: Callable[[], Sequence[Responder]],
    question: str,
    distance: Distance,
    max_tokens: int | None,
    label: str,
    first: EventDraft,
) -> BranchRun:
    fork = store.fork(session_id, target.seq - 1)
    try:
        peers = sorted(make_peers(), key=lambda p: p.name)
        if len(peers) != PEER_COUNT:
            raise ValueError(f"a branch replays against exactly two peers, got {len(peers)}")
        tested = fork.append_sync(first)
        steps, tokens, why = [tested], 0, ""
        for peer in peers:
            if max_tokens is not None and tokens >= max_tokens:
                why = f"budget: {tokens} tokens spent before {peer.name} replied"
                break
            with call_scope(phase="branch", branch=label, session_id=session_id):
                turn = TurnResult.adapt(
                    await peer.reply_to_target(question, fork.state(session_id), tested)
                )
            if turn.draft is None:
                why = f"{peer.name}: {turn.reason}" + (f" ({turn.detail})" if turn.detail else "")
                break
            try:
                steps.append(fork.append_sync(turn.draft))
            except ProtocolError as exc:
                why = f"{peer.name}: invalid_draft ({exc.reason})"
                break
            tokens += turn.draft.tokens.in_ + turn.draft.tokens.out
        final = distance(fork.state(session_id).predictions) if not why else None
        return BranchRun(label, steps, final, tokens, not why, why)
    finally:
        fork.close()


def _recorded_distance(real: Sequence[Event], target_seq: int, count: int, distance: Distance):
    following = [
        e
        for e in real
        if e.seq >= target_seq
        and e.kind is Kind.MESSAGE
        and not e.counterfactual
        and e.author != SYSTEM
    ]
    return distance(latest_predictions([*real[:target_seq], *following[:count]]))


def _next_replay_id(store: EventStore, session_id: str) -> str:
    started = sum(1 for e in store.events(session_id) if e.kind is Kind.ROLLBACK_START)
    return f"{session_id}::replay-{started + 1}"


def _record_pair(
    store: EventStore,
    session_id: str,
    result: PairResult,
    candidate_tokens: Tokens,
    call_ids: Sequence[str],
    reason: str,
) -> None:
    """Append the replay to the real log as counterfactual events; the board does not move."""
    target, rid = result.target, result.replay_id
    store.append_sync(
        EventDraft(
            session_id=session_id,
            author=target.author,
            kind=Kind.ROLLBACK_START,
            reply_to=target.seq,
            counterfactual=True,
            explanation=reason or f"replay #{target.seq} against its replacement",
            tokens=candidate_tokens,  # the cost of producing the replacement
            meta={
                "replay_id": rid,
                "target_seq": target.seq,
                "challenger_seq": result.challenger_seq,
                "call_ids": list(call_ids),
            },
        )
    )
    for run in (result.original, result.replacement):
        for i, e in enumerate(run.steps):
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
                    meta={
                        "replay_id": rid,
                        "branch": run.label,
                        "fork_seq": e.seq,
                        "fork_reply_to": e.reply_to,
                        "tested": i == 0,
                        "call_ids": e.meta.get("call_ids", []),
                    },
                )
            )
    original, replacement = result.original, result.replacement
    store.append_sync(
        EventDraft(
            session_id=session_id,
            author=target.author,
            kind=Kind.ROLLBACK_END,
            counterfactual=True,
            explanation=_summary(result),
            meta={
                "replay_id": rid,
                "status": result.status,
                "reason": original.reason or replacement.reason,
                "target_seq": target.seq,
                "challenger_seq": result.challenger_seq,
                "distance_original": original.distance,
                "distance_replacement": replacement.distance,
                "distance_recorded": result.distance_recorded,
                "credit_delta": result.credit_delta,
                "branch_tokens": {"original": original.tokens, "replacement": replacement.tokens},
            },
        )
    )


def _summary(result: PairResult) -> str:
    if not result.complete:
        return f"replay incomplete: {result.original.reason or result.replacement.reason}"
    return f"consensus distance {result.original.distance:.2f} -> {result.replacement.distance:.2f}"


def record_failed_attempt(
    store: EventStore,
    session_id: str,
    target: Event,
    challenger_seq: int | None,
    reason: str,
    tokens: Tokens,
    call_ids: Sequence[str] = (),
) -> str:
    """Log a replay that never got a usable replacement, so the attempt is not lost."""
    rid = _next_replay_id(store, session_id)
    meta = {
        "replay_id": rid,
        "target_seq": target.seq,
        "challenger_seq": challenger_seq,
        "call_ids": list(call_ids),
    }
    store.append_sync(
        EventDraft(
            session_id=session_id,
            author=target.author,
            kind=Kind.ROLLBACK_START,
            reply_to=target.seq,
            counterfactual=True,
            explanation=f"replay #{target.seq} without a usable replacement",
            tokens=tokens,
            meta=meta,
        )
    )
    store.append_sync(
        EventDraft(
            session_id=session_id,
            author=target.author,
            kind=Kind.ROLLBACK_END,
            counterfactual=True,
            explanation=f"candidate failed: {reason}",
            meta={**meta, "status": "candidate_failed", "reason": reason, "credit_delta": None},
        )
    )
    return rid
