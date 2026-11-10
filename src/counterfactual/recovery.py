"""The replay recovery policy (roadmap section 05): turn a helpful replay into a real reply.

The scheduler's checkpoint hands this policy a stalled board. The policy gets a replacement from
the challenged agent, compares it with the original on matched forks and, only if the replacement
strictly lowers the sandbox disagreement, returns a real REVISE for the scheduler to post. Three
things stay separate: the sandbox reached agreement, the real reply was accepted by the store, and
the finished session reached consensus (and, offline, whether that consensus is correct).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from agents.pex_agent import PEXAgent
from blackboard import BoardState, EventStore
from counterfactual.branches import Responder
from counterfactual.credit import ReplayAttempt, attempt_replay
from counterfactual.sandbox import Distance
from protocol import SYSTEM, Event, EventDraft, Tag
from scheduler import CONSENSUS, Opportunity, SessionResult, exact_distance


class ReplayRecovery:
    """Replays the challenged reply once and adopts the replacement if it helped in the sandbox."""

    name = "replay"

    def __init__(
        self,
        store: EventStore,
        authors: Mapping[str, PEXAgent],
        make_peers: Callable[[], Sequence[Responder]],
        *,
        distance: Distance = exact_distance,
        new_tag: Tag = Tag.REVISE,
        max_branch_tokens: int | None = None,
    ) -> None:
        self.store = store
        self.authors = authors  # the model-backed agents that can write a replacement
        self.make_peers = make_peers
        self.distance = distance
        self.new_tag = new_tag
        self.max_branch_tokens = max_branch_tokens

    async def attempt(
        self, question: str, board: BoardState, opportunity: Opportunity
    ) -> EventDraft | None:
        by_seq = {e.seq: e for e in board.events}
        assert opportunity.target is not None and opportunity.challenger is not None
        target, challenger = by_seq[opportunity.target], by_seq[opportunity.challenger]
        author = self.authors.get(target.author)
        if author is None:
            opportunity.outcome = "no_author"
            return None

        attempt = await attempt_replay(
            self.store,
            board,
            question,
            target,
            challenger,
            author,
            self.make_peers,
            distance=self.distance,
            new_tag=self.new_tag,
            max_branch_tokens=self.max_branch_tokens,
        )
        opportunity.replay = _summary(attempt)
        pair = attempt.pair
        if pair is None or attempt.candidate.alternative is None:
            opportunity.outcome = "candidate_failed"
            return None
        if not pair.complete:
            opportunity.outcome = "incomplete"
            return None
        assert pair.credit_delta is not None
        if pair.credit_delta >= 0:
            opportunity.outcome = "not_helpful"
            return None

        now = self.store.state(board.session_id)  # the board as it is now, not at the checkpoint
        live = live_message(now, author.name, challenger)
        if live is None:
            opportunity.outcome = "stale_target"
            return None
        alt = attempt.candidate.alternative
        return EventDraft(
            session_id=board.session_id,
            author=author.name,
            tag=alt.tag,
            reply_to=live.seq,
            prediction=alt.prediction or now.latest[author.name].prediction,
            explanation=alt.explanation,
            meta={"adopted_counterfactual": True, "replay_id": attempt.replay_id},
        )


def live_message(board: BoardState, author: str, challenger: Event) -> Event | None:
    """The message `author` can still legitimately answer: the challenger, else something newer.

    Messages older than the challenger are never offered, and neither is anything `author` has
    already answered or a RATIFY, which needs no reply.
    """
    answered = {e.reply_to for e in board.messages if e.author == author}
    open_messages = [
        e
        for e in board.messages
        if e.seq >= challenger.seq
        and e.author not in (author, SYSTEM)
        and e.tag not in (Tag.RATIFY, Tag.TERM)
        and e.seq not in answered
    ]
    if not open_messages:
        return None
    return next((e for e in open_messages if e.seq == challenger.seq), open_messages[-1])


def _summary(attempt: ReplayAttempt) -> dict[str, Any]:
    pair, candidate = attempt.pair, attempt.candidate
    summary: dict[str, Any] = {
        "replay_id": attempt.replay_id,
        "status": pair.status if pair else "candidate_failed",
        "reason": "" if pair is None else (pair.original.reason or pair.replacement.reason),
        "candidate_tokens": candidate.tokens.in_ + candidate.tokens.out,
        "credit_delta": None,
        "distance_original": None,
        "distance_replacement": None,
        "simulated_agreement": False,
    }
    if pair is None:
        summary["reason"] = candidate.reason
        return summary
    summary.update(
        credit_delta=pair.credit_delta,
        distance_original=pair.original.distance,
        distance_replacement=pair.replacement.distance,
        simulated_agreement=pair.complete and pair.replacement.distance == 0.0,
    )
    return summary


def outcomes(result: SessionResult) -> dict[str, bool]:
    """The recovery funnel for one session, each stage on its own (nothing implies the next)."""
    opp = result.opportunity
    replay = (opp.replay if opp else None) or {}
    credit = replay.get("credit_delta")
    return {
        "eligible": bool(opp and opp.eligible),
        "attempted": bool(opp and opp.outcome is not None),
        "completed": replay.get("status") == "completed",
        "helpful": credit is not None and credit < 0,
        "simulated_agreement": bool(replay.get("simulated_agreement")),
        "adopted": bool(opp and opp.outcome == "reply_accepted"),
        "final_consensus": result.stop_reason == CONSENSUS,
    }
