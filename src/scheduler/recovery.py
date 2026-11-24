"""Turn results, recovery diagnostics and the opportunity sidecar (roadmap section 03).

The scheduler diagnoses a stalled board before it writes TERM and records what it found here. The
records are kept outside the event log, so they never count as real messages.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from blackboard import BoardState
from protocol import Event, EventDraft, Kind, Tag


class TurnReason(StrEnum):
    """Why a turn produced no message, or what was noted about it."""

    OK = "ok"
    NO_TARGET = "no_target"  # nothing left for the agent to answer
    PARSE_FAILURE = "parse_failure"  # the reply stayed unparseable after the repair retry
    MODEL_ERROR = "model_error"  # the model could not be reached or answered with an error
    CALL_ALLOWANCE = "call_allowance"  # a paired arm spent its post-checkpoint request budget
    PASSED = "passed"  # a plain agent returned None without saying why
    INVALID_DRAFT = "invalid_draft"  # the store refused the draft
    TAG_MISMATCH = "tag_mismatch"  # a RATIFY whose prediction differs from the one it ratifies


@dataclass(frozen=True)
class TurnResult:
    draft: EventDraft | None = None
    reason: TurnReason = TurnReason.OK
    detail: str = ""
    call_ids: tuple[str, ...] = ()

    @classmethod
    def adapt(cls, output: TurnResult | EventDraft | None) -> TurnResult:
        """Wrap what a plain agent returns (a draft, or None to pass) as a turn result."""
        if isinstance(output, cls):
            return output
        if output is None:
            return cls(None, TurnReason.PASSED)
        return cls(output)


@dataclass(frozen=True)
class TurnNote:
    """One diagnostic about a turn, taken on the board whose last event was `seq`."""

    seq: int
    agent: str
    reason: TurnReason
    detail: str = ""
    call_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Stop:
    reason: str  # consensus, impasse or cap: what consumers of TERM already read
    detail: str  # consensus, message_cap, no_progress, debate_stall, all_passed, failed_turns


@dataclass
class Opportunity:
    """What the checkpoint found when the board stalled, and what became of it."""

    session_id: str
    seq: int  # last committed event when the decision was taken
    detail: str
    eligible: bool
    skip_reason: str | None
    roster: list[str]
    enabled: list[str]
    distance: float
    window: int
    target: int | None
    challenger: int | None
    policy: str
    budget_remaining: int
    outcome: str | None = (
        None  # why the attempt ended; reply_accepted means a real reply was posted
    )
    replay: dict[str, Any] | None = None  # what the recovery policy found, if it ran a replay
    intervention: dict[str, Any] | None = None  # what a control policy asked for and got

    def to_record(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> dict[str, Any]:
        out = {"eligible": self.eligible, "skip_reason": self.skip_reason, "outcome": self.outcome}
        if self.replay:
            out["replay_id"] = self.replay["replay_id"]
        return out


class Recovery(Protocol):
    """A recovery policy the checkpoint may try once. It returns the real reply to post, if any."""

    name: str

    async def attempt(
        self, question: str, board: BoardState, opportunity: Opportunity
    ) -> EventDraft | None: ...


def challenged_reply(events: Sequence[Event]) -> tuple[Event, Event] | None:
    """The newest reply that another agent answered with REFUTE or REJECT, and its challenger.

    INITs cannot be targets, and a reply that already has a rollback is not available again. Of
    several challengers of the newest reply, the earliest by sequence number is returned.
    """
    messages = {e.seq: e for e in events if e.kind is Kind.MESSAGE and not e.counterfactual}
    replayed = {e.reply_to for e in events if e.kind is Kind.ROLLBACK_START}
    best: tuple[Event, Event] | None = None
    for e in messages.values():
        if e.tag not in (Tag.REFUTE, Tag.REJECT) or e.reply_to is None:
            continue
        target = messages.get(e.reply_to)
        if target is None or target.tag in (Tag.INIT, Tag.TERM) or target.seq in replayed:
            continue
        if target.author == e.author:
            continue
        if best is None or target.seq > best[0].seq:
            best = (target, e)
    return best


class Sidecar:
    """Appends one JSON line per opportunity, so runs can be inspected without the event log."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, opportunity: Opportunity) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(opportunity.to_record(), sort_keys=True) + "\n")


def load_opportunities(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Records by session id, in file order. A session with no entry has limited diagnostics."""
    out: dict[str, list[dict[str, Any]]] = {}
    for line in Path(path).read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            out.setdefault(record["session_id"], []).append(record)
    return out
