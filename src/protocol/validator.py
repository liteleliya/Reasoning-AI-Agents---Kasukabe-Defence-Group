"""PXP-N validator: checks a draft event against the session history (spec section 2)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from protocol.schema import REPLY_TAGS, SYSTEM, Event, EventDraft, Kind, Tag


class ProtocolError(ValueError):
    """Raised when an event is off-protocol. `reason` says why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)


# Replies a compatible agent could send to each tag (paper Prop. 5). Counted, not enforced.
_COMPATIBLE_REPLIES = {
    Tag.RATIFY: {Tag.RATIFY},
    Tag.REVISE: {Tag.RATIFY},
    Tag.REJECT: {Tag.REJECT},
}


def parse_event(record: Mapping[str, Any]) -> EventDraft:
    """Build a draft from a raw dict, turning schema errors into a ProtocolError."""
    try:
        return EventDraft.model_validate(dict(record))
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "event"
        raise ProtocolError(f"invalid {where}: {first['msg']}") from exc


def check(draft: EventDraft, history: Sequence[Event]) -> Verdict:
    """Validate `draft` as the next event after `history` (all from one session)."""
    try:
        warnings = _check(draft, history)
    except ProtocolError as exc:
        return Verdict(ok=False, reason=exc.reason)
    return Verdict(ok=True, warnings=tuple(warnings))


def validate(draft: EventDraft, history: Sequence[Event]) -> tuple[str, ...]:
    """Like `check`, but raises ProtocolError; returns warnings on success."""
    verdict = check(draft, history)
    if not verdict.ok:
        raise ProtocolError(verdict.reason)
    return verdict.warnings


def _check(draft: EventDraft, history: Sequence[Event]) -> list[str]:
    if history and history[0].session_id != draft.session_id:
        raise ProtocolError(
            f"session_id {draft.session_id!r} does not match session {history[0].session_id!r}"
        )
    if any(e.kind is Kind.MESSAGE and e.tag is Tag.TERM for e in history):
        raise ProtocolError("session already terminated")

    if draft.kind is Kind.MESSAGE:
        return _check_message(draft, history)
    _check_rollback(draft, history)
    return []


def _check_message(draft: EventDraft, history: Sequence[Event]) -> list[str]:
    by_seq = {e.seq: e for e in history}
    has_init = any(
        e.kind is Kind.MESSAGE and e.tag is Tag.INIT and e.author == draft.author for e in history
    )

    if draft.tag is Tag.TERM:
        if draft.author != SYSTEM:
            raise ProtocolError("only system may send TERM")
        if draft.reply_to is not None:
            raise ProtocolError("TERM must not have reply_to")
        return []
    if draft.author == SYSTEM:
        raise ProtocolError("system may only send TERM")
    if not draft.prediction.strip() or not draft.explanation.strip():
        raise ProtocolError("agent messages need a prediction and an explanation")

    if draft.tag is Tag.INIT:
        if draft.reply_to is not None:
            raise ProtocolError("INIT must not have reply_to")
        if has_init:
            raise ProtocolError(f"{draft.author} already sent INIT in this session")
        return []

    assert draft.tag in REPLY_TAGS
    if not has_init:
        raise ProtocolError(f"{draft.author} must send INIT before replying")
    if draft.reply_to is None:
        raise ProtocolError(f"{draft.tag} needs reply_to")
    target = by_seq.get(draft.reply_to)
    if target is None:
        raise ProtocolError(f"reply_to {draft.reply_to} does not exist")
    if target.kind is not Kind.MESSAGE:
        raise ProtocolError(f"reply_to {draft.reply_to} is a {target.kind}, not a message")
    if target.author == draft.author:
        raise ProtocolError("cannot reply to own message")
    if target.counterfactual and not draft.counterfactual:
        raise ProtocolError("cannot reply to a counterfactual message from the real board")

    allowed = _COMPATIBLE_REPLIES.get(target.tag)  # type: ignore[arg-type]
    if allowed is not None and draft.tag not in allowed:
        return [f"incompatible transition: {draft.tag} in reply to {target.tag}"]
    return []


def _check_rollback(draft: EventDraft, history: Sequence[Event]) -> None:
    open_rollback: Event | None = None
    for e in history:
        if e.kind is Kind.ROLLBACK_START:
            open_rollback = e
        elif e.kind is Kind.ROLLBACK_END:
            open_rollback = None

    if draft.kind is Kind.ROLLBACK_START:
        if open_rollback is not None:
            raise ProtocolError(f"rollback started at seq {open_rollback.seq} is still open")
        target = next((e for e in history if e.seq == draft.reply_to), None)
        if target is None or target.kind is not Kind.MESSAGE:
            raise ProtocolError("rollback_start must reply_to an existing message")
        if target.author != draft.author:
            raise ProtocolError("an agent may only roll back its own message")
        if target.counterfactual:
            raise ProtocolError("cannot roll back a counterfactual message")
        return

    if open_rollback is None:
        raise ProtocolError(f"{draft.kind} without an open rollback")
    if draft.kind is Kind.ROLLBACK_END and draft.author != open_rollback.author:
        raise ProtocolError("rollback_end must come from the agent that started the rollback")
