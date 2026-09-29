"""Event-driven scheduler: picks who speaks next and stops the session (spec section 4)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from blackboard import BoardState, EventStore
from protocol import SYSTEM, EventDraft, ProtocolError, Tag

CONSENSUS, IMPASSE, CAP = "consensus", "impasse", "cap"


class Agent(Protocol):
    """Anything that can look at the board and propose its next message (or pass with None)."""

    name: str

    async def act(self, question: str, board: BoardState) -> EventDraft | None: ...


def normalise(prediction: str) -> str:
    return " ".join(prediction.lower().split()).rstrip(".!")


def exact_consensus(predictions: Mapping[str, str]) -> bool:
    """Default consensus test: all predictions equal after normalising. Swap for a ROUGE rule."""
    return len({normalise(p) for p in predictions.values()}) == 1


@dataclass(frozen=True)
class SchedulerConfig:
    max_messages: int | None = None  # default 10 * N (spec section 4)
    impasse_window: int | None = None  # default 2 * N
    concurrency: int = 1  # agents allowed to think at once
    consensus: Callable[[Mapping[str, str]], bool] = exact_consensus


@dataclass
class SessionResult:
    session_id: str
    stop_reason: str
    state: BoardState
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (agent, reason)


class Scheduler:
    def __init__(
        self, store: EventStore, agents: Sequence[Agent], config: SchedulerConfig | None = None
    ) -> None:
        names = [a.name for a in agents]
        if len(set(names)) != len(names) or SYSTEM in names:
            raise ValueError(f"agent names must be unique and not {SYSTEM!r}: {names}")
        if not agents:
            raise ValueError("need at least one agent")
        self.store = store
        self.agents = list(agents)
        self.config = config or SchedulerConfig()
        n = len(agents)
        self.max_messages = self.config.max_messages or 10 * n
        self.window = self.config.impasse_window or 2 * n
        self._sem = asyncio.Semaphore(max(1, self.config.concurrency))

    async def run(self, session_id: str, question: str) -> SessionResult:
        if self.store.state(session_id).seq >= 0:
            raise ValueError(f"session {session_id!r} already has events")
        result = SessionResult(session_id, "", self.store.state(session_id))
        skip: set[str] = set()  # agents that passed or were rejected on the current board
        skip_seq = -1

        while True:
            board = self.store.state(session_id)
            if board.seq != skip_seq:
                skip, skip_seq = set(), board.seq
            reason = self.stop_reason(board)
            if reason is None:
                drafts = await self._next_drafts(question, board, skip)
                if not drafts:
                    reason = IMPASSE  # every agent passed or was rejected on the same board
            if reason is not None:
                term = EventDraft(
                    session_id=session_id, author=SYSTEM, tag=Tag.TERM, explanation=reason
                )
                await self.store.append(term)
                result.stop_reason = reason
                result.state = self.store.state(session_id)
                return result
            for agent_name, draft in drafts:
                try:
                    await self.store.append(draft)
                except ProtocolError as exc:
                    result.rejected.append((agent_name, exc.reason))
                    skip.add(agent_name)
                if self.stop_reason(self.store.state(session_id)):
                    break

    # --- arbitration ----------------------------------------------------------------------

    def priority(self, board: BoardState) -> list[Agent]:
        """Order agents: no INIT yet, then challenged since they last spoke, then longest silent."""
        by_seq = {e.seq: e for e in board.messages}
        last_spoke: dict[str, int] = {}
        for e in board.messages:
            last_spoke[e.author] = e.seq

        def key(agent: Agent) -> tuple[int, int, str]:
            spoke = last_spoke.get(agent.name, -1)
            if spoke < 0:
                return (0, -1, agent.name)  # has not sent INIT yet
            replies = [
                e
                for e in board.messages
                if e.seq > spoke
                and e.reply_to is not None
                and by_seq[e.reply_to].author == agent.name
            ]
            challenged = any(e.tag in (Tag.REFUTE, Tag.REJECT) for e in replies)
            return (1 if challenged else 2, spoke, agent.name)

        return sorted(self.agents, key=key)

    async def _next_drafts(
        self, question: str, board: BoardState, skip: set[str]
    ) -> list[tuple[str, EventDraft]]:
        """Ask agents in priority order, `concurrency` at a time, until someone speaks.

        Agents that pass are added to `skip`, so they are not asked again on the same board.
        """
        ordered = [a for a in self.priority(board) if a.name not in skip]
        step = max(1, self.config.concurrency)
        for i in range(0, len(ordered), step):
            batch = ordered[i : i + step]
            outputs = await asyncio.gather(*(self._ask(a, question, board) for a in batch))
            drafts = [(a.name, d) for a, d in zip(batch, outputs, strict=True) if d is not None]
            skip.update(a.name for a, d in zip(batch, outputs, strict=True) if d is None)
            if drafts:
                return drafts
        return []

    async def _ask(self, agent: Agent, question: str, board: BoardState) -> EventDraft | None:
        async with self._sem:
            return await agent.act(question, board)

    # --- stopping -------------------------------------------------------------------------

    def stop_reason(self, board: BoardState) -> str | None:
        msgs = [e for e in board.messages if e.author != SYSTEM]
        names = {a.name for a in self.agents}
        repliers = {e.author for e in msgs if e.tag is not Tag.INIT}
        if (
            names <= repliers
            and set(board.predictions) == names
            and self.config.consensus(board.predictions)
        ):
            return CONSENSUS
        if len(msgs) >= self.max_messages:
            return CAP
        replies = [e for e in msgs if e.tag is not Tag.INIT]
        if len(replies) >= self.window and not _progress(msgs, replies[-self.window :]):
            return IMPASSE
        return None


def _progress(all_msgs: Sequence, recent: Sequence) -> bool:
    """True if any recent message ratified, revised, or changed its author's prediction."""
    previous: dict[str, str] = {}
    recent_seqs = {e.seq for e in recent}
    for e in all_msgs:
        if e.seq in recent_seqs:
            if e.tag in (Tag.RATIFY, Tag.REVISE):
                return True
            if e.author in previous and normalise(previous[e.author]) != normalise(e.prediction):
                return True
        previous[e.author] = e.prediction
    return False
