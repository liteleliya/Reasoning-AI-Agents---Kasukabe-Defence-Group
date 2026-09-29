"""Board state rebuilt from the event log. The log is the only source of truth."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from protocol.schema import SYSTEM, Event, Kind, Tag


@dataclass(frozen=True)
class BoardState:
    session_id: str
    seq: int = -1  # seq of the last event folded in; -1 for an empty board
    events: tuple[Event, ...] = ()
    latest: dict[str, Event] = field(default_factory=dict)  # last real message per agent
    terminated: bool = False
    stop_reason: str | None = None
    open_rollback: int | None = None  # seq of an unfinished rollback_start
    tokens_in: int = 0
    tokens_out: int = 0
    rollback_tokens_in: int = 0
    rollback_tokens_out: int = 0

    @property
    def agents(self) -> list[str]:
        return sorted(self.latest)

    @property
    def predictions(self) -> dict[str, str]:
        return {a: e.prediction for a, e in self.latest.items()}

    @property
    def messages(self) -> list[Event]:
        """Real (non-counterfactual) message events, in order."""
        return [e for e in self.events if e.kind is Kind.MESSAGE and not e.counterfactual]

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    @classmethod
    def replay(cls, session_id: str, events: Iterable[Event]) -> BoardState:
        state = cls(session_id=session_id)
        for event in events:
            state = state.apply(event)
        return state

    def apply(self, e: Event) -> BoardState:
        if e.session_id != self.session_id:
            raise ValueError(f"event from session {e.session_id!r} on board {self.session_id!r}")
        if e.seq != self.seq + 1:
            raise ValueError(f"expected seq {self.seq + 1}, got {e.seq}")
        latest = dict(self.latest)
        terminated, stop_reason, open_rb = self.terminated, self.stop_reason, self.open_rollback
        if e.kind is Kind.MESSAGE and e.tag is Tag.TERM:
            terminated, stop_reason = True, e.explanation or None
        elif e.kind is Kind.MESSAGE and not e.counterfactual and e.author != SYSTEM:
            latest[e.author] = e
        elif e.kind is Kind.ROLLBACK_START:
            open_rb = e.seq
        elif e.kind is Kind.ROLLBACK_END:
            open_rb = None
        rb = e.counterfactual
        return BoardState(
            session_id=self.session_id,
            seq=e.seq,
            events=(*self.events, e),
            latest=latest,
            terminated=terminated,
            stop_reason=stop_reason,
            open_rollback=open_rb,
            tokens_in=self.tokens_in + e.tokens.in_,
            tokens_out=self.tokens_out + e.tokens.out,
            rollback_tokens_in=self.rollback_tokens_in + (e.tokens.in_ if rb else 0),
            rollback_tokens_out=self.rollback_tokens_out + (e.tokens.out if rb else 0),
        )
