"""The three conditions of the paired study (roadmap section 08).

All arms start from the same copied prefix and the same recovery checkpoint. They differ only in
what happens at the trigger: `standard` lets the challenged agent answer its challenger in the
ordinary way, `forward` asks it to rethink the challenge in a fresh live reply, and `replay`
replays its challenged reply on matched sandbox forks and adopts a replacement that helped.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from blackboard import BoardState, EventStore
from counterfactual.recovery import live_message
from protocol import EventDraft
from scheduler import Opportunity

ARMS = ("standard", "forward", "replay")


class ControlRecovery:
    """A control policy: one live reply from the challenged author, with or without a rethink."""

    def __init__(
        self, store: EventStore, authors: Mapping[str, Any], *, rethink: bool = False
    ) -> None:
        self.store = store
        self.authors = authors
        self.rethink = rethink
        self.name = "forward" if rethink else "standard"

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
        now = self.store.state(board.session_id)
        live = live_message(now, author.name, challenger)
        if live is None:
            opportunity.outcome = "stale_target"
            return None
        kwargs = {"rethink": True} if self.rethink else {}
        turn = await author.reply_to_target(question, now, live, **kwargs)
        draft = getattr(
            turn, "draft", turn
        )  # model agents return a TurnResult, scripted ones a draft
        reason = getattr(getattr(turn, "reason", None), "value", "ok")
        opportunity.intervention = {
            "arm": self.name,
            "reason": reason,
            "call_ids": list(getattr(turn, "call_ids", ())),
        }
        if draft is None:
            opportunity.outcome = "no_reply"
            return None
        return draft.model_copy(update={"meta": {**draft.meta, "intervention": self.name}})
