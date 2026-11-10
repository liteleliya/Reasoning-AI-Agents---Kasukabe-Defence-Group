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

from agents.ledger import call_scope
from agents.llm_client import LLMError, TokenUsage
from agents.parsing import PXPParseError, parse_pxp, repair_messages
from agents.pex_agent import PEXAgent
from agents.prompts import candidate_messages, counterfactual_messages
from blackboard import BoardState, EventStore
from counterfactual.branches import PairResult, Responder, record_failed_attempt, replay_pair
from counterfactual.sandbox import Alternative, Distance, ReplayResult, replay
from protocol import Event, EventDraft, Kind, ProtocolError, Tag, Tokens, validate
from scheduler import Agent, TurnResult, exact_distance, normalise

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
        opportunistic: bool = True,
    ) -> None:
        self.inner = inner
        self.name = inner.name
        self.counterfactual = True
        self.store = store
        self.others = others
        self.max_rollbacks = max_rollbacks
        self.distance = distance
        self.new_tag = new_tag
        self.opportunistic = opportunistic  # False: only the scheduler checkpoint triggers replays
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
        return (await self.take_turn(question, board)).draft

    async def take_turn(self, question: str, board: BoardState) -> TurnResult:
        if self._pending is not None:
            return TurnResult.adapt(self._adopt(board))
        if self._should_replay(board):
            target = replay_target(board, self.name)
            if target is not None:
                await self._replay(question, board, target)
                board = self.store.state(board.session_id)
                if self._pending is not None:
                    return TurnResult.adapt(self._adopt(board))
        return await self.inner.take_turn(question, board)

    def _should_replay(self, board: BoardState) -> bool:
        if not self.opportunistic:
            return False
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


# --- candidate replacement and the matched replay (roadmap section 04) -------------------------


@dataclass(frozen=True)
class Candidate:
    """The replacement reply asked of the target's author, or why none was obtained."""

    status: str  # "ok" or "failed"
    alternative: Alternative | None
    reason: str = ""
    tokens: Tokens = field(default_factory=Tokens)  # everything spent, failed calls included
    call_ids: tuple[str, ...] = ()


@dataclass
class ReplayAttempt:
    candidate: Candidate
    pair: PairResult | None  # None when no usable candidate was obtained
    replay_id: str = ""


async def generate_candidate(
    agent: PEXAgent,
    store: EventStore,
    board: BoardState,
    question: str,
    target: Event,
    challenger: Event,
    *,
    new_tag: Tag = Tag.REVISE,
) -> Candidate:
    """One attempt and at most one repair at a replacement for `target`, given its objection.

    The candidate always answers the message `target` answered, whatever reply_to the model gave.
    It must change the prediction or the explanation and pass the protocol validator on a fork of
    the board taken just before `target`.
    """
    msgs = candidate_messages(
        agent.persona,
        agent.name,
        question,
        [e for e in board.events if e.seq < target.seq],
        target,
        challenger,
        new_tag.value,
        agent.n_agents,
    )
    usage, call_ids = TokenUsage(), []

    def result(status: str, alt: Alternative | None, reason: str = "") -> Candidate:
        spent = Tokens(in_=usage.prompt, out=usage.completion)
        if alt is not None:
            alt = Alternative(alt.tag, alt.explanation, alt.prediction, spent, tuple(call_ids))
        return Candidate(status, alt, reason, spent, tuple(call_ids))

    for attempt in range(2):
        try:
            with call_scope(
                session_id=board.session_id,
                phase="candidate",
                agent=agent.name,
                parent_seq=target.seq,
                repair=attempt == 1,
            ):
                response = await agent.client.complete(
                    msgs,
                    temperature=agent.temperature,
                    max_tokens=agent.max_tokens,
                    seed=None if agent.seed is None else agent.seed + board.seq + 1,
                    json_mode=True,
                    label=f"candidate/{board.session_id}/{agent.name}",
                )
        except LLMError as err:
            log.warning("%s: model error while writing a candidate (%s)", agent.name, err)
            return result("failed", None, f"model_error: {err}")
        usage = usage + response.usage
        call_ids.append(response.call_id)
        try:
            return result("ok", _vet(agent, store, board, target, response.text, new_tag))
        except PXPParseError as err:  # also used for "unchanged" and "refused by the protocol"
            if attempt == 1:
                log.warning("%s: unusable candidate after repair (%s)", agent.name, err.reason)
                return result("failed", None, err.reason)
            msgs = [*msgs, *repair_messages(response.text, err)]
    raise AssertionError("unreachable")


def _vet(
    agent: PEXAgent, store: EventStore, board: BoardState, target: Event, text: str, tag: Tag
) -> Alternative:
    parsed = parse_pxp(text, allowed_tags=(tag.value,))
    if (normalise(parsed.prediction), normalise(parsed.explanation)) == (
        normalise(target.prediction),
        normalise(target.explanation),
    ):
        raise PXPParseError(
            "no change: the new message repeats your original prediction and reason"
        )
    draft = EventDraft(
        session_id=board.session_id,
        author=agent.name,
        tag=tag,
        reply_to=target.reply_to,
        prediction=parsed.prediction,
        explanation=parsed.explanation,
    )
    fork = store.fork(board.session_id, target.seq - 1)
    try:
        validate(draft, fork.events(board.session_id))
    except ProtocolError as exc:
        raise PXPParseError(f"invalid: {exc.reason}") from exc
    finally:
        fork.close()
    return Alternative(tag=tag, explanation=parsed.explanation, prediction=parsed.prediction)


async def attempt_replay(
    store: EventStore,
    board: BoardState,
    question: str,
    target: Event,
    challenger: Event,
    author: PEXAgent,
    make_peers: Callable[[], Sequence[Responder]],
    *,
    distance: Distance = exact_distance,
    new_tag: Tag = Tag.REVISE,
    max_branch_tokens: int | None = None,
) -> ReplayAttempt:
    """Get a candidate from `author`, run it against the original on matched forks and log it.

    A failed candidate is logged too (a rollback with no steps), so no attempt goes unrecorded.
    """
    session_id = board.session_id
    candidate = await generate_candidate(
        author, store, board, question, target, challenger, new_tag=new_tag
    )
    if candidate.alternative is None:
        replay_id = record_failed_attempt(
            store,
            session_id,
            target,
            challenger.seq,
            candidate.reason,
            candidate.tokens,
            candidate.call_ids,
        )
        return ReplayAttempt(candidate, None, replay_id)
    pair = await replay_pair(
        store,
        session_id,
        target.seq,
        candidate.alternative,
        make_peers,
        question,
        distance=distance,
        challenger_seq=challenger.seq,
        max_branch_tokens=max_branch_tokens,
        reason=f"what if {author.name} had replied with {new_tag} to answer #{challenger.seq}?",
    )
    return ReplayAttempt(candidate, pair, pair.replay_id)
