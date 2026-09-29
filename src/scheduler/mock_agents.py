"""Deterministic mock agents for running the board without a model (A5 handoff)."""

from __future__ import annotations

from dataclasses import dataclass

from blackboard import BoardState
from protocol import SYSTEM, Event, EventDraft, Tag
from scheduler.core import normalise


def unanswered(board: BoardState, me: str) -> Event | None:
    """The latest real message by another agent that `me` has not replied to yet.

    RATIFY messages are skipped: agreement needs no answer, and answering it loops forever.
    """
    answered = {e.reply_to for e in board.messages if e.author == me}
    for e in reversed(board.messages):
        if e.author not in (me, SYSTEM) and e.seq not in answered and e.tag is not Tag.RATIFY:
            return e
    return None


@dataclass
class _MockAgent:
    name: str
    answer: str

    async def act(self, question: str, board: BoardState) -> EventDraft | None:
        if self.name not in board.latest:
            return self._draft(board, Tag.INIT, None, self.answer, f"{self.name} thinks so")
        target = unanswered(board, self.name)
        if target is None:
            return None
        return self.reply(board, target)

    def reply(self, board: BoardState, target: Event) -> EventDraft:
        raise NotImplementedError

    def _draft(
        self, board: BoardState, tag: Tag, reply_to: int | None, prediction: str, why: str
    ) -> EventDraft:
        return EventDraft(
            session_id=board.session_id,
            author=self.name,
            tag=tag,
            reply_to=reply_to,
            prediction=prediction,
            explanation=why,
        )


@dataclass
class StubbornAgent(_MockAgent):
    """Never changes its answer: RATIFY if the other agrees, else REFUTE."""

    def reply(self, board: BoardState, target: Event) -> EventDraft:
        mine = board.latest[self.name].prediction
        if normalise(target.prediction) == normalise(mine):
            return self._draft(board, Tag.RATIFY, target.seq, mine, "we agree")
        return self._draft(board, Tag.REFUTE, target.seq, mine, f"no, it is {mine}")


@dataclass
class FollowerAgent(_MockAgent):
    """Adopts whatever it replies to: RATIFY if already equal, else REVISE to that answer."""

    def reply(self, board: BoardState, target: Event) -> EventDraft:
        mine = board.latest[self.name].prediction
        if normalise(target.prediction) == normalise(mine):
            return self._draft(board, Tag.RATIFY, target.seq, mine, "we agree")
        return self._draft(board, Tag.REVISE, target.seq, target.prediction, "you convinced me")


@dataclass
class ConfusedAgent(_MockAgent):
    """REJECTs every message whose answer differs from its own; never learns."""

    def reply(self, board: BoardState, target: Event) -> EventDraft:
        mine = board.latest[self.name].prediction
        if normalise(target.prediction) == normalise(mine):
            return self._draft(board, Tag.RATIFY, target.seq, mine, "we agree")
        return self._draft(board, Tag.REJECT, target.seq, mine, "I cannot follow that")
