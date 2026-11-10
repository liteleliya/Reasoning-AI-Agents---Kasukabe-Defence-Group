"""Event-driven scheduler: picks who speaks next and stops the session (spec section 4)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from blackboard import BoardState, EventStore
from protocol import SYSTEM, EventDraft, ProtocolError, Tag
from scheduler.recovery import (
    Opportunity,
    Recovery,
    Sidecar,
    Stop,
    TurnNote,
    TurnReason,
    TurnResult,
    challenged_reply,
)

CONSENSUS, IMPASSE, CAP = "consensus", "impasse", "cap"


class Agent(Protocol):
    """Anything that can look at the board and propose its next message (or pass with None).

    An agent may also offer `take_turn`, returning a `TurnResult` that says why it passed.
    """

    name: str

    async def act(self, question: str, board: BoardState) -> EventDraft | None: ...


def normalise(prediction: str) -> str:
    return " ".join(prediction.lower().split()).rstrip(".!")


def exact_consensus(predictions: Mapping[str, str]) -> bool:
    """Default consensus test: all predictions equal after normalising. Swap for a ROUGE rule."""
    return len({normalise(p) for p in predictions.values()}) == 1


def exact_distance(predictions: Mapping[str, str]) -> float:
    """Consensus distance: 1 - share of agents holding the most common normalised prediction."""
    if not predictions:
        return 1.0
    counts: dict[str, int] = {}
    for p in predictions.values():
        counts[normalise(p)] = counts.get(normalise(p), 0) + 1
    return 1 - max(counts.values()) / len(predictions)


@dataclass(frozen=True)
class SchedulerConfig:
    max_messages: int | None = None  # default 10 * N (spec section 4)
    impasse_window: int | None = None  # default 2 * N
    concurrency: int = 1  # agents allowed to think at once
    consensus: Callable[[Mapping[str, str]], bool] = exact_consensus
    distance: Callable[[Mapping[str, str]], float] = exact_distance
    stall_rule: bool = True  # impasse when a window brings no new best consensus distance
    recovery_budget: int = 1  # recovery attempts the checkpoint may spend per session


@dataclass
class SessionResult:
    session_id: str
    stop_reason: str
    state: BoardState
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (agent, reason)
    stop_detail: str = ""  # why the stop reason applied, see `Stop`
    decision_seq: int = -1  # last committed event when the stop was decided
    notes: list[TurnNote] = field(default_factory=list)  # passed turns, refused drafts, mismatches
    opportunity: Opportunity | None = None  # set when the board stalled and was diagnosed


class Scheduler:
    def __init__(
        self,
        store: EventStore,
        agents: Sequence[Agent],
        config: SchedulerConfig | None = None,
        *,
        recovery: Recovery | None = None,
        sidecar: Sidecar | None = None,
    ) -> None:
        names = [a.name for a in agents]
        if len(set(names)) != len(names) or SYSTEM in names:
            raise ValueError(f"agent names must be unique and not {SYSTEM!r}: {names}")
        if not agents:
            raise ValueError("need at least one agent")
        self.store = store
        self.agents = list(agents)
        self.config = config or SchedulerConfig()
        self.recovery = recovery
        self.sidecar = sidecar
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
        checkpointed = False  # the recovery checkpoint opens at most once per session

        while True:
            board = self.store.state(session_id)
            if board.seq != skip_seq:
                skip, skip_seq = set(), board.seq
            stop = self._stop(board)
            if stop is None:
                drafts = await self._next_drafts(question, board, skip, result.notes)
                if not drafts:  # every agent passed or was rejected on the same board
                    stop = Stop(IMPASSE, self._pass_detail(result.notes, board.seq))
            if stop is not None:
                if stop.reason == IMPASSE and not checkpointed:
                    checkpointed = True
                    if await self._checkpoint(question, board, stop, result):
                        continue  # a real recovery reply was posted; judge the new board
                await self._terminate(board, stop, result)
                return result
            for agent_name, draft in drafts:
                try:
                    event = await self.store.append(draft)
                except ProtocolError as exc:
                    result.rejected.append((agent_name, exc.reason))
                    result.notes.append(
                        TurnNote(board.seq, agent_name, TurnReason.INVALID_DRAFT, exc.reason)
                    )
                    skip.add(agent_name)
                else:
                    self._flag_mismatch(event, board, result.notes)
                if self.stop_reason(self.store.state(session_id)):
                    break

    async def _terminate(self, board: BoardState, stop: Stop, result: SessionResult) -> None:
        meta: dict = {"detail": stop.detail, "decision_seq": board.seq}
        if result.opportunity is not None:
            meta["recovery"] = result.opportunity.summary()
        await self.store.append(
            EventDraft(
                session_id=board.session_id,
                author=SYSTEM,
                tag=Tag.TERM,
                explanation=stop.reason,
                meta=meta,
            )
        )
        result.stop_reason, result.stop_detail, result.decision_seq = (
            stop.reason,
            stop.detail,
            board.seq,
        )
        result.state = self.store.state(board.session_id)

    def _flag_mismatch(self, event, board: BoardState, notes: list[TurnNote]) -> None:
        """Diagnostic only: a RATIFY should carry the prediction of the message it ratifies."""
        if event.tag is not Tag.RATIFY or event.reply_to is None:
            return
        target = next((e for e in board.events if e.seq == event.reply_to), None)
        if target is not None and not self.config.consensus(
            {"target": target.prediction, "ratify": event.prediction}
        ):
            detail = f"ratified #{target.seq} ({target.prediction!r}) with {event.prediction!r}"
            notes.append(TurnNote(event.seq, event.author, TurnReason.TAG_MISMATCH, detail))

    # --- recovery checkpoint --------------------------------------------------------------

    async def _checkpoint(
        self, question: str, board: BoardState, stop: Stop, result: SessionResult
    ) -> bool:
        """Diagnose the stalled board and try recovery once; True if it posted a real reply."""
        opp = self._diagnose(board, stop)
        result.opportunity = opp
        posted = False
        if opp.eligible and opp.skip_reason is None:
            assert self.recovery is not None
            draft = await self.recovery.attempt(question, board, opp)
            opp.outcome = "no_reply"
            if draft is not None:
                try:
                    await self.store.append(draft)
                except ProtocolError as exc:
                    opp.outcome = "reply_rejected"
                    result.rejected.append((draft.author, exc.reason))
                    result.notes.append(
                        TurnNote(board.seq, draft.author, TurnReason.INVALID_DRAFT, exc.reason)
                    )
                else:
                    opp.outcome = "reply_accepted"
                    posted = True
        if self.sidecar is not None:
            self.sidecar.write(opp)
        return posted

    def _diagnose(self, board: BoardState, stop: Stop) -> Opportunity:
        """Detect a replay target first; then apply the capability, budget and policy checks."""
        names = sorted(a.name for a in self.agents)
        msgs = [e for e in board.messages if e.author != SYSTEM]
        replies = [e for e in msgs if e.tag is not Tag.INIT]
        distance = self.config.distance(board.predictions)
        found = challenged_reply(board.events)
        enabled = sorted(a.name for a in self.agents if getattr(a, "counterfactual", False))
        skip: str | None = None
        if set(board.predictions) != set(names) or not set(names) <= {e.author for e in replies}:
            skip = "roster_incomplete"
        elif distance <= 0:
            skip = "no_disagreement"
        elif len(replies) < self.window or not _stalled(
            msgs, replies[-self.window :], self.config.distance
        ):
            skip = "no_full_window"
        elif found is None:
            skip = "no_challenged_reply"
        eligible = skip is None
        if eligible:
            assert found is not None
            if found[0].author not in enabled:
                skip = "not_enabled"
            elif self.config.recovery_budget <= 0:
                skip = "budget_exhausted"
            elif self.recovery is None:
                skip = "recovery_disabled"
        return Opportunity(
            session_id=board.session_id,
            seq=board.seq,
            detail=stop.detail,
            eligible=eligible,
            skip_reason=skip,
            roster=names,
            enabled=enabled,
            distance=distance,
            window=self.window,
            target=found[0].seq if found else None,
            challenger=found[1].seq if found else None,
            policy=getattr(self.recovery, "name", "none"),
            budget_remaining=self.config.recovery_budget,
        )

    @staticmethod
    def _pass_detail(notes: Sequence[TurnNote], seq: int) -> str:
        failed = (TurnReason.PARSE_FAILURE, TurnReason.MODEL_ERROR)
        return (
            "failed_turns"
            if any(n.seq == seq and n.reason in failed for n in notes)
            else ("all_passed")
        )

    # --- arbitration ----------------------------------------------------------------------

    def priority(self, board: BoardState) -> list[Agent]:
        """Order agents: no INIT yet first, then longest silent.

        Being challenged (a REFUTE or REJECT of your message since you last spoke) moves an agent
        N places up, but never ahead of someone silent for more than N messages longer, so two
        agents refuting each other cannot starve a third.
        """
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
            return (1, spoke - (len(self.agents) if challenged else 0), agent.name)

        return sorted(self.agents, key=key)

    async def _next_drafts(
        self, question: str, board: BoardState, skip: set[str], notes: list[TurnNote]
    ) -> list[tuple[str, EventDraft]]:
        """Ask agents in priority order, `concurrency` at a time, until someone speaks.

        Agents that pass are added to `skip`, so they are not asked again on the same board, and
        the reason for each passed turn is kept in `notes`.
        """
        ordered = [a for a in self.priority(board) if a.name not in skip]
        step = max(1, self.config.concurrency)
        for i in range(0, len(ordered), step):
            batch = ordered[i : i + step]
            turns = await asyncio.gather(*(self._ask(a, question, board) for a in batch))
            drafts = []
            for agent, turn in zip(batch, turns, strict=True):
                if turn.draft is not None:
                    drafts.append((agent.name, turn.draft))
                    continue
                skip.add(agent.name)
                notes.append(
                    TurnNote(board.seq, agent.name, turn.reason, turn.detail, turn.call_ids)
                )
            if drafts:
                return drafts
        return []

    async def _ask(self, agent: Agent, question: str, board: BoardState) -> TurnResult:
        async with self._sem:
            take_turn = getattr(agent, "take_turn", None)
            if take_turn is not None:
                return TurnResult.adapt(await take_turn(question, board))
            return TurnResult.adapt(await agent.act(question, board))

    # --- stopping -------------------------------------------------------------------------

    def stop_reason(self, board: BoardState) -> str | None:
        stop = self._stop(board)
        return stop.reason if stop else None

    def _stop(self, board: BoardState) -> Stop | None:
        msgs = [e for e in board.messages if e.author != SYSTEM]
        names = {a.name for a in self.agents}
        repliers = {e.author for e in msgs if e.tag is not Tag.INIT}
        if (
            names <= repliers
            and set(board.predictions) == names
            and self.config.consensus(board.predictions)
        ):
            return Stop(CONSENSUS, CONSENSUS)
        if len(msgs) >= self.max_messages:
            return Stop(CAP, "message_cap")
        replies = [e for e in msgs if e.tag is not Tag.INIT]
        if len(replies) >= self.window:
            recent = replies[-self.window :]
            if not _progress(msgs, recent):
                return Stop(IMPASSE, "no_progress")
            if self.config.stall_rule and _stalled(msgs, recent, self.config.distance):
                return Stop(IMPASSE, "debate_stall")
        return None


def _stalled(all_msgs: Sequence, recent: Sequence, distance) -> bool:
    """True if no message in `recent` reached a lower consensus distance than ever before.

    Catches oscillation (an agent flipping between two camps), where REVISEs keep coming but the
    board never gets closer to agreement (spec section 4, decision 12). Distances only count
    once every agent has replied at least once, so agreement among the opening INITs is not a
    "best" the discussion has to beat.
    """
    first = recent[0].seq
    agents = {e.author for e in all_msgs}
    repliers: set[str] = set()
    latest: dict[str, str] = {}
    best_before = best_in = float("inf")
    for e in all_msgs:
        latest[e.author] = e.prediction
        if e.tag is not Tag.INIT:
            repliers.add(e.author)
        if repliers != agents:
            continue  # discussion has not started for everyone yet
        d = distance(latest)
        if e.seq < first:
            best_before = min(best_before, d)
        else:
            best_in = min(best_in, d)
    return best_before != float("inf") and best_in >= best_before


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
