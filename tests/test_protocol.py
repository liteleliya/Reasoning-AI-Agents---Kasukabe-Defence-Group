"""A3: schema and validator. Off-protocol messages are rejected with a reason."""

import pytest

from protocol import Event, EventDraft, Kind, ProtocolError, Tag, check, parse_event, validate

S = "s-1"


def draft(author: str, tag: Tag | None, reply_to: int | None = None, **kw) -> EventDraft:
    kw.setdefault("prediction", "42")
    kw.setdefault("explanation", "because")
    return EventDraft(session_id=S, author=author, tag=tag, reply_to=reply_to, **kw)


def build(*drafts: EventDraft) -> list[Event]:
    history: list[Event] = []
    for d in drafts:
        validate(d, history)
        history.append(Event.from_draft(d, len(history)))
    return history


def opening() -> list[Event]:
    return build(draft("a", Tag.INIT), draft("b", Tag.INIT))


def rejected(d: EventDraft, history: list[Event]) -> str:
    verdict = check(d, history)
    assert not verdict.ok
    return verdict.reason


# --- schema -----------------------------------------------------------------------------


def test_record_round_trip_uses_in_alias() -> None:
    d = draft("a", Tag.INIT, tokens={"in": 5, "out": 2})
    record = d.to_record()
    assert record["tokens"] == {"in": 5, "out": 2}
    assert record["kind"] == "message" and record["tag"] == "INIT"
    assert parse_event(record) == d


@pytest.mark.parametrize(
    ("record", "fragment"),
    [
        ({"session_id": S, "author": "a", "kind": "message"}, "need a tag"),
        ({"session_id": S, "author": "a", "tag": "AGREE"}, "tag"),
        ({"session_id": S, "author": "a", "tag": "INIT", "tokens": {"in": -1}}, "tokens.in"),
        ({"session_id": S, "author": "a", "tag": "INIT", "colour": "red"}, "colour"),
        ({"session_id": "", "author": "a", "tag": "INIT"}, "session_id"),
        ({"session_id": S, "author": "a", "kind": "rollback_start"}, "counterfactual"),
    ],
)
def test_schema_errors_become_protocol_errors(record: dict, fragment: str) -> None:
    with pytest.raises(ProtocolError) as exc:
        parse_event(record)
    assert fragment in exc.value.reason


# --- messages ---------------------------------------------------------------------------


def test_valid_exchange_passes() -> None:
    h = build(draft("a", Tag.INIT), draft("b", Tag.INIT), draft("a", Tag.REFUTE, 1))
    assert check(draft("b", Tag.REVISE, 2), h).ok


def test_off_protocol_messages_are_rejected_with_reasons() -> None:
    h = opening()
    assert "already sent INIT" in rejected(draft("a", Tag.INIT), h)
    assert "INIT must not have reply_to" in rejected(draft("c", Tag.INIT, 0), h)
    assert "must send INIT before replying" in rejected(draft("c", Tag.REFUTE, 0), h)
    assert "needs reply_to" in rejected(draft("a", Tag.REFUTE), h)
    assert "does not exist" in rejected(draft("a", Tag.REFUTE, 9), h)
    assert "own message" in rejected(draft("a", Tag.RATIFY, 0), h)
    assert "prediction and an explanation" in rejected(draft("a", Tag.RATIFY, 1, explanation=""), h)
    assert "only system may send TERM" in rejected(draft("a", Tag.TERM), h)
    assert "system may only send TERM" in rejected(draft("system", Tag.RATIFY, 0), h)
    other = EventDraft(
        session_id="s-2", author="a", tag=Tag.RATIFY, reply_to=1, prediction="x", explanation="y"
    )
    assert "does not match session" in rejected(other, h)


def test_nothing_after_term() -> None:
    h = opening()
    term = EventDraft(session_id=S, author="system", tag=Tag.TERM, explanation="cap")
    h.append(Event.from_draft(term, len(h)))
    assert "already terminated" in rejected(draft("a", Tag.RATIFY, 1), h)
    assert "TERM must not have reply_to" in rejected(
        EventDraft(session_id=S, author="system", tag=Tag.TERM, reply_to=0), h[:-1]
    )


def test_incompatible_transition_is_a_warning_not_an_error() -> None:
    h = build(draft("a", Tag.INIT), draft("b", Tag.INIT), draft("a", Tag.RATIFY, 1))
    verdict = check(draft("b", Tag.REFUTE, 2), h)
    assert verdict.ok
    assert verdict.warnings == ("incompatible transition: REFUTE in reply to RATIFY",)
    assert check(draft("b", Tag.RATIFY, 2), h).warnings == ()


# --- rollbacks --------------------------------------------------------------------------


def rb(kind: Kind, author: str, reply_to: int | None = None, tag: Tag | None = None) -> EventDraft:
    return EventDraft(
        session_id=S, author=author, kind=kind, tag=tag, reply_to=reply_to, counterfactual=True
    )


def test_rollback_lifecycle() -> None:
    h = build(
        draft("a", Tag.INIT),
        draft("b", Tag.INIT),
        draft("a", Tag.REFUTE, 1),
        rb(Kind.ROLLBACK_START, "a", 2),
        rb(Kind.ROLLBACK_STEP, "a", tag=Tag.REVISE),
        rb(Kind.ROLLBACK_STEP, "b", tag=Tag.RATIFY),
        rb(Kind.ROLLBACK_END, "a"),
    )
    assert h[-1].kind is Kind.ROLLBACK_END


def test_rollback_rules() -> None:
    h = build(draft("a", Tag.INIT), draft("b", Tag.INIT))
    assert "own message" in rejected(rb(Kind.ROLLBACK_START, "a", 1), h)
    assert "existing message" in rejected(rb(Kind.ROLLBACK_START, "a", 7), h)
    assert "without an open rollback" in rejected(rb(Kind.ROLLBACK_END, "a"), h)
    h = build(draft("a", Tag.INIT), draft("b", Tag.INIT), rb(Kind.ROLLBACK_START, "a", 0))
    assert "still open" in rejected(rb(Kind.ROLLBACK_START, "a", 0), h)
    assert "agent that started" in rejected(rb(Kind.ROLLBACK_END, "b"), h)


def test_real_board_cannot_reply_to_counterfactual_message() -> None:
    h = build(draft("a", Tag.INIT), draft("b", Tag.INIT, counterfactual=True))
    assert "counterfactual" in rejected(draft("a", Tag.RATIFY, 1), h)
    assert check(draft("a", Tag.RATIFY, 1, counterfactual=True), h).ok
