"""Roadmap section 02: the toy X/Y/Y recovery fixture pins down scheduler, sandbox and metrics."""

import asyncio

import pytest

from blackboard import EventStore
from counterfactual import replay, replay_target
from counterfactual.fixture import (
    ALTERNATIVE,
    ANSWER,
    CHALLENGER_SEQ,
    OFF_SESSION,
    ON_SESSION,
    QUESTION,
    TARGET_SEQ,
    agents,
    build_handoff_db,
    prefix_drafts,
    scheduler_config,
)
from protocol import Kind, Tag
from scheduler import IMPASSE, Scheduler, exact_distance

SID = "fixture"

# (author, tag, reply_to, prediction) for messages #0-#8, as laid out in the roadmap
EXPECTED_PREFIX = [
    ("A", Tag.INIT, None, "X"),
    ("B", Tag.INIT, None, "Y"),
    ("C", Tag.INIT, None, "Y"),
    ("A", Tag.REFUTE, 1, "X"),
    ("B", Tag.REFUTE, 3, "Y"),
    ("C", Tag.RATIFY, 4, "Y"),
    ("A", Tag.REFUTE, 4, "X"),
    ("B", Tag.REFUTE, 6, "Y"),
    ("C", Tag.RATIFY, 7, "Y"),
]


def shape(events):
    return [(e.author, e.tag, e.reply_to, e.prediction) for e in events]


def stored_prefix() -> EventStore:
    store = EventStore()
    for draft in prefix_drafts(SID):
        store.append_sync(draft)
    return store


def test_prefix_has_two_answer_groups_and_one_third_disagreement() -> None:
    board = stored_prefix().state(SID)
    assert shape(board.events) == EXPECTED_PREFIX
    assert board.predictions == {"A": "X", "B": "Y", "C": "Y"}
    assert exact_distance(board.predictions) == pytest.approx(1 / 3)


def test_target_and_challenger_are_6_and_7() -> None:
    board = stored_prefix().state(SID)
    target = replay_target(board, "A")
    assert target is not None and target.seq == TARGET_SEQ == 6
    challenger = board.events[CHALLENGER_SEQ]
    assert challenger.author == "B" and challenger.reply_to == target.seq
    assert challenger.tag is Tag.REFUTE


def test_scheduler_with_scripted_policies_stalls_on_the_same_prefix() -> None:
    store = EventStore()
    result = asyncio.run(Scheduler(store, agents(), scheduler_config()).run(SID, QUESTION))
    events = store.events(SID)
    assert result.stop_reason == IMPASSE
    assert shape(events[:9]) == EXPECTED_PREFIX
    assert [e.explanation for e in events[:9]] == [d.explanation for d in prefix_drafts(SID)]
    assert events[9].tag is Tag.TERM and events[9].explanation == IMPASSE
    assert len(events) == 10


def test_replay_of_6_reaches_agreement_and_leaves_the_real_board_alone() -> None:
    store = stored_prefix()
    before = [e.to_record() for e in store.events(SID)]
    peers = [a for a in agents() if a.name != "A"]
    result = asyncio.run(replay(store, SID, TARGET_SEQ, ALTERNATIVE, peers, QUESTION))

    assert [e.tag for e in result.steps] == [Tag.REVISE, Tag.RATIFY, Tag.RATIFY]
    assert result.distance_real == pytest.approx(1 / 3)
    assert result.distance_replay == 0.0
    assert result.credit_delta == pytest.approx(-1 / 3)
    after = store.events(SID)
    assert [e.to_record() for e in after[: len(before)]] == before  # #0-#8 untouched
    assert [e.kind for e in after[len(before) :]] == [
        Kind.ROLLBACK_START,
        *[Kind.ROLLBACK_STEP] * 3,
        Kind.ROLLBACK_END,
    ]
    assert store.state(SID).predictions == {"A": "X", "B": "Y", "C": "Y"}


def test_alternative_concedes_the_four_minute_limit() -> None:
    assert ALTERNATIVE.tag is Tag.REVISE and ALTERNATIVE.prediction == ANSWER
    assert "four-minute" in ALTERNATIVE.explanation


def test_scripted_agent_a_with_the_alternative_reaches_the_known_answer() -> None:
    store = EventStore()
    result = asyncio.run(
        Scheduler(store, agents(fixed=True), scheduler_config()).run(SID, QUESTION)
    )
    assert result.stop_reason == "consensus"
    assert set(result.state.predictions.values()) == {ANSWER}


def test_handoff_db_holds_a_stalled_and_a_recovered_session(tmp_path) -> None:
    path = tmp_path / "fixture.sqlite"
    build_handoff_db(path).close()
    store = EventStore(path)
    assert store.sessions() == sorted([OFF_SESSION, ON_SESSION])

    off = store.state(OFF_SESSION)
    assert off.terminated and off.stop_reason == IMPASSE
    assert off.predictions == {"A": "X", "B": "Y", "C": "Y"}

    on = store.state(ON_SESSION)
    assert on.terminated and on.stop_reason == "consensus"
    assert set(on.predictions.values()) == {ANSWER}
    events = store.events(ON_SESSION)
    assert shape(events[:9]) == EXPECTED_PREFIX
    end = next(e for e in events if e.kind is Kind.ROLLBACK_END)
    assert end.meta["credit_delta"] == pytest.approx(-1 / 3, abs=1e-4)

    adopted = [e for e in events if e.meta.get("adopted_counterfactual")]
    assert len(adopted) == 1 and adopted[0].seq > end.seq
    assert (adopted[0].author, adopted[0].tag) == ("A", Tag.REVISE)
    assert adopted[0].reply_to == CHALLENGER_SEQ and not adopted[0].counterfactual
    assert "four-minute" in adopted[0].explanation
    # the real board only moves at the adopted reply, not during the sandbox branch
    assert store.snapshot(ON_SESSION, end.seq).predictions == {"A": "X", "B": "Y", "C": "Y"}
    assert store.snapshot(ON_SESSION, adopted[0].seq).predictions["A"] == ANSWER
