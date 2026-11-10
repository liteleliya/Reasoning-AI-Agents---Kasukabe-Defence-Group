"""Productive revisions (roadmap section 07), kept apart from the Strong/Ultra-Strong labels.

A reply is a productive revision when it answers a challenge (a REFUTE or REJECT), changes its
author's answer in a way the comparator sees, gives reasoning other than the author's previous
explanation, and
the group's distance is lower at the reply or within the next three real messages, or the session
ends in consensus inside that window.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from blackboard import BoardState
from protocol import Event, Kind, Tag

CHALLENGES = (Tag.REFUTE, Tag.REJECT)
WINDOW = 3


def _equal(a: str, b: str) -> bool:
    return a == b


def productive_revisions(
    events: Sequence[Event],
    distance: Callable[[Mapping[str, str]], float],
    *,
    same: Callable[[str, str], bool] = _equal,
    window: int = WINDOW,
) -> int:
    """How many replies in `events` are productive revisions."""
    states: list[BoardState] = []
    state = BoardState(session_id=events[0].session_id if events else "")
    for event in events:
        state = state.apply(event)
        states.append(state)
    index = {e.seq: n for n, e in enumerate(events)}
    real = [n for n, e in enumerate(events) if _is_real_reply(e)]
    count = 0
    for pos, n in enumerate(real):
        event = events[n]
        target = events[index[event.reply_to]] if event.reply_to in index else None
        if target is None or target.tag not in CHALLENGES:
            continue
        before = states[n - 1].latest.get(event.author)
        if before is None or same(before.prediction, event.prediction):
            continue
        if event.explanation.strip() == before.explanation.strip():  # no new reasoning
            continue
        baseline = distance(states[n - 1].predictions)
        span = real[pos : pos + 1 + window]
        count += any(distance(states[m].predictions) < baseline for m in span) or (
            _ends_in_consensus(events, real[pos + 1 :], n, window)
        )
    return count


def _is_real_reply(event: Event) -> bool:
    return (
        event.kind is Kind.MESSAGE
        and not event.counterfactual
        and event.author != "system"
        and event.tag is not Tag.INIT
    )


def _ends_in_consensus(events: Sequence[Event], later: Sequence[int], n: int, window: int) -> bool:
    """Did a consensus TERM arrive after at most `window` further real replies?"""
    term = next((m for m in range(n + 1, len(events)) if events[m].tag is Tag.TERM), None)
    if term is None or events[term].explanation != "consensus":
        return False
    return sum(1 for m in later if m < term) <= window
