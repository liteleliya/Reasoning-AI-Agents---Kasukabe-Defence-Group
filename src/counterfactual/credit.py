"""Counterfactual agents and credit assignment (B6).

A `CounterfactualAgent` wraps an LLM agent. When one of its replies was answered with REFUTE or
REJECT, it may (within a budget) ask its model for an alternative version of that reply as a
REVISE, replay it in the sandbox against the other agents, and then:

- **positive credit** (the replay brought the agents closer, delta < 0): its next real message
  adopts the alternative, i.e. it posts that REVISE in reply to the message it now answers;
- **no credit** (delta >= 0): it carries a short note into its next prompt saying that conceding
  in that way would not have helped, and answers normally.

Rules (spec section 5): an agent only replays its own messages, at most `max_rollbacks` times per
session, and only once every agent has replied at least once.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from agents.parsing import PXPParseError, parse_pxp
from agents.pex_agent import PEXAgent
from agents.prompts import counterfactual_messages
from blackboard import BoardState, EventStore
from counterfactual.sandbox import Alternative, Distance, ReplayResult, replay
from protocol import Event, EventDraft, Kind, Tag, Tokens
from scheduler import Agent, exact_distance

log = logging.getLogger(__name__)


@dataclass
class CreditLog:
    replays: list[ReplayResult] = field(default_factory=list)
    adopted: int = 0  # alternatives posted for real after positive credit


def replay_target(board: BoardState, name: str) -> Event | None:
    """This agent's latest reply that someone answered with REFUTE or REJECT, if any."""
    msgs = board.messages
    challenged = {e.reply_to for e in msgs if e.tag in (Tag.REFUTE, Tag.REJECT)}
    mine = [e for e in msgs if e.author == name and e.tag not in (Tag.INIT, Tag.TERM)]
    already = {e.reply_to for e in board.events if e.kind is Kind.ROLLBACK_START}
    for e in reversed(mine):
        if e.seq in challenged and e.seq not in already:
            return e
    return None


class CounterfactualAgent:
    """Wraps a PEXAgent; same `name` and `act` interface, plus replays and credit."""

    def __init__(
        self,
        inner: PEXAgent,
        store: EventStore,
        others: Callable[[], Sequence[Agent]],
        *,
        max_rollbacks: int = 1,
        distance: Distance = exact_distance,
        new_tag: Tag = Tag.REVISE,
    ) -> None:
        self.inner = inner
        self.name = inner.name
        self.counterfactual = True
        self.store = store
        self.others = others
        self.max_rollbacks = max_rollbacks
        self.distance = distance
        self.new_tag = new_tag
        self.credit = CreditLog()
        self.attempts = 0  # replays tried, including ones whose alternative was unusable
        self._pending: Alternative | None = None

    # passthroughs used by the runner's metrics
    @property
    def failures(self) -> int:
        return self.inner.failures

    @property
    def unposted(self):
        return self.inner.unposted

    async def act(self, question: str, board: BoardState) -> EventDraft | None:
        if self._pending is not None:
            return self._adopt(board)
        if self._should_replay(board):
            target = replay_target(board, self.name)
            if target is not None:
                await self._replay(question, board, target)
                board = self.store.state(board.session_id)
                if self._pending is not None:
                    return self._adopt(board)
        return await self.inner.act(question, board)

    def _should_replay(self, board: BoardState) -> bool:
        if self.attempts >= self.max_rollbacks or board.open_rollback is not None:
            return False
        names = set(board.latest)
        repliers = {e.author for e in board.messages if e.tag is not Tag.INIT}
        return bool(names) and names <= repliers

    async def _alternative(
        self, question: str, board: BoardState, target: Event
    ) -> Alternative | None:
        msgs = counterfactual_messages(
            self.inner.persona,
            self.name,
            question,
            [e for e in board.events if e.seq < target.seq],
            target,
            self.new_tag.value,
            self.inner.n_agents,
        )
        r = await self.inner.client.complete(
            msgs,
            temperature=self.inner.temperature,
            max_tokens=self.inner.max_tokens,
            json_mode=True,
            label=f"rollback/{board.session_id}/{self.name}",
        )
        try:
            parsed = parse_pxp(r.text, allowed_tags=(self.new_tag.value,))
        except PXPParseError as err:
            log.warning("%s: unusable counterfactual (%s)", self.name, err.reason)
            self.inner.unposted = self.inner.unposted + r.usage
            return None
        return Alternative(
            tag=self.new_tag,
            explanation=parsed.explanation,
            prediction=parsed.prediction,
            tokens=Tokens(in_=r.usage.prompt, out=r.usage.completion),
        )

    async def _replay(self, question: str, board: BoardState, target: Event) -> None:
        self.attempts += 1
        alt = await self._alternative(question, board, target)
        if alt is None:
            return
        # replay against the plain agents, so nobody starts a nested replay inside the fork
        others = [getattr(a, "inner", a) for a in self.others() if a.name != self.name]
        result = await replay(
            self.store,
            board.session_id,
            target.seq,
            alt,
            others,
            question,
            distance=self.distance,
            reason=f"what if {self.name} had replied with {alt.tag}?",
        )
        self.credit.replays.append(result)
        if result.credit_delta < 0:
            self._pending = alt
        else:
            self.inner.notes.append(
                f"Replaying your message [{target.seq}] as a {alt.tag} ({alt.prediction}: "
                f"{alt.explanation[:120]}) would not have helped the group agree. "
                "Try a different argument instead."
            )

    def _adopt(self, board: BoardState) -> EventDraft | None:
        """Post the alternative for real, in reply to the message this agent should answer now."""
        from scheduler.mock_agents import unanswered

        alt, self._pending = self._pending, None
        target = unanswered(board, self.name)
        if alt is None or target is None:
            return None
        self.credit.adopted += 1
        return EventDraft(
            session_id=board.session_id,
            author=self.name,
            tag=alt.tag,
            reply_to=target.seq,
            prediction=alt.prediction or board.latest[self.name].prediction,
            explanation=alt.explanation,
            meta={"adopted_counterfactual": True},
        )
