"""Roadmap section 04: the original and replacement replies get the same simulated continuation."""

import asyncio
import dataclasses
import json
import sqlite3

import pytest

from agents.llm_client import LLMError, MockClient
from agents.pex_agent import PEXAgent
from agents.prompts import persona_for
from blackboard import EventStore
from counterfactual import Alternative, attempt_replay, generate_candidate
from counterfactual import fixture as xy
from counterfactual.branches import replay_pair
from protocol import Kind, Tag, Tokens
from scheduler import challenged_reply

SID = "s"


def shape(events):
    return [(e.author, e.tag, e.reply_to, e.prediction) for e in events]


def prefix_store(*sessions: str, store: EventStore | None = None) -> EventStore:
    store = store or EventStore()
    for session in sessions or (SID,):
        for draft in xy.prefix_drafts(session):
            store.append_sync(draft)
    return store


def peers():
    return [a for a in xy.agents() if a.name != "A"]


def pair(store, alt=xy.ALTERNATIVE, make_peers=peers, session=SID, **kw):
    return asyncio.run(
        replay_pair(
            store,
            session,
            xy.TARGET_SEQ,
            alt,
            make_peers,
            xy.QUESTION,
            challenger_seq=xy.CHALLENGER_SEQ,
            **kw,
        )
    )


def test_a_copy_of_the_original_gives_identical_continuations_and_zero_credit() -> None:
    store = prefix_store()
    original = store.events(SID)[xy.TARGET_SEQ]
    same = Alternative(original.tag, original.explanation, original.prediction)
    result = pair(store, same)
    assert result.complete
    assert shape(result.original.steps) == shape(result.replacement.steps)
    assert result.original.distance == result.replacement.distance
    assert result.credit_delta == 0.0


def test_the_known_replacement_scores_minus_one_third() -> None:
    result = pair(prefix_store())
    assert shape(result.original.steps) == [
        ("A", Tag.REFUTE, 4, "X"),
        ("B", Tag.REFUTE, 6, "Y"),  # the peers answer the tested message directly
        ("C", Tag.REFUTE, 6, "Y"),
    ]
    assert shape(result.replacement.steps) == [
        ("A", Tag.REVISE, 4, "Y"),  # bound to the original reply's target
        ("B", Tag.RATIFY, 6, "Y"),
        ("C", Tag.RATIFY, 6, "Y"),
    ]
    assert result.original.distance == pytest.approx(1 / 3)
    assert result.replacement.distance == 0.0
    assert result.credit_delta == pytest.approx(-1 / 3)
    assert result.distance_recorded == pytest.approx(1 / 3)  # the observational third reference
    assert result.status == "completed"


def test_the_real_board_is_identical_before_and_after_both_forks() -> None:
    store = prefix_store()
    before = [e.to_record() for e in store.events(SID)]
    result = pair(store)
    after = store.events(SID)
    assert [e.to_record() for e in after[: len(before)]] == before
    assert [e.kind for e in after[len(before) :]] == [
        Kind.ROLLBACK_START,
        *[Kind.ROLLBACK_STEP] * 6,
        Kind.ROLLBACK_END,
    ]
    assert store.state(SID).predictions == {"A": "X", "B": "Y", "C": "Y"}
    assert result.replay_id == f"{SID}::replay-1"


def test_rollback_events_carry_replay_id_branch_labels_and_unrounded_distances() -> None:
    store = prefix_store()
    result = pair(store)
    start, *steps, end = store.events(SID)[9:]
    assert start.meta == {
        "replay_id": result.replay_id,
        "target_seq": 6,
        "challenger_seq": 7,
    }
    assert (start.author, start.reply_to, start.counterfactual) == ("A", 6, True)
    assert [s.meta["branch"] for s in steps] == ["original"] * 3 + ["replacement"] * 3
    assert [s.meta["fork_seq"] for s in steps] == [6, 7, 8, 6, 7, 8]
    assert [s.meta["tested"] for s in steps] == [True, False, False] * 2
    assert all(s.meta["replay_id"] == result.replay_id for s in steps)
    assert end.meta["status"] == "completed"
    assert end.meta["distance_original"] == result.original.distance
    assert end.meta["distance_replacement"] == result.replacement.distance
    assert end.meta["credit_delta"] == result.credit_delta  # stored unrounded
    assert end.meta["distance_recorded"] == result.distance_recorded


class Silent:
    """A peer whose model gave no usable reply."""

    name = "C"

    async def reply_to_target(self, question, board, target):
        return None


def test_a_missing_peer_reply_makes_the_comparison_incomplete() -> None:
    store = prefix_store()
    result = pair(store, make_peers=lambda: [peers()[0], Silent()])
    assert not result.complete and result.status == "incomplete"
    assert result.credit_delta is None
    assert "C" in result.original.reason and "C" in result.replacement.reason
    end = store.events(SID)[-1]
    assert end.meta["status"] == "incomplete" and end.meta["credit_delta"] is None
    assert store.state(SID).predictions == {"A": "X", "B": "Y", "C": "Y"}


class Costly(xy.RotatingAgent):
    async def reply_to_target(self, question, board, target):
        draft = await super().reply_to_target(question, board, target)
        return draft.model_copy(update={"tokens": Tokens(in_=10, out=5)})


def costly():
    return [Costly(**{f.name: getattr(a, f.name) for f in dataclasses.fields(a)}) for a in peers()]


def test_branch_tokens_are_counted_and_a_budget_makes_both_branches_incomplete() -> None:
    store = prefix_store()
    result = pair(store, make_peers=costly)
    assert result.complete and result.original.tokens == result.replacement.tokens == 30
    state = store.state(SID)
    assert (state.rollback_tokens_in, state.rollback_tokens_out) == (40, 20)

    store = prefix_store()
    result = pair(store, make_peers=costly, max_branch_tokens=15)
    assert not result.complete
    assert "budget" in result.original.reason and "budget" in result.replacement.reason
    assert len(result.original.steps) == len(result.replacement.steps) == 2


class SpyStore(EventStore):
    def __init__(self) -> None:
        super().__init__()
        self.forks: list[EventStore] = []

    def fork(self, session_id: str, upto: int) -> EventStore:
        fork = super().fork(session_id, upto)
        self.forks.append(fork)
        return fork


def assert_closed(store: EventStore) -> None:
    with pytest.raises(sqlite3.ProgrammingError):
        store.events(SID)


def test_both_forks_are_closed_after_success() -> None:
    store = prefix_store(store=SpyStore())
    pair(store)
    assert len(store.forks) == 2
    for fork in store.forks:
        assert_closed(fork)


class Crashing:
    name = "C"

    async def reply_to_target(self, question, board, target):
        raise TimeoutError("peer timed out")


def test_a_peer_failure_closes_the_forks_and_leaves_the_history_alone() -> None:
    store = prefix_store(store=SpyStore())
    before = [e.to_record() for e in store.events(SID)]
    with pytest.raises(TimeoutError):
        pair(store, make_peers=lambda: [peers()[0], Crashing()])
    assert store.forks
    for fork in store.forks:
        assert_closed(fork)
    assert [e.to_record() for e in store.events(SID)] == before


def test_replay_ids_and_branch_events_do_not_leak_across_sessions() -> None:
    store = prefix_store("s1", "s2")
    first = pair(store, session="s1")
    second = pair(store, session="s2")
    assert first.replay_id == "s1::replay-1" and second.replay_id == "s2::replay-1"
    for session, own in (("s1", first), ("s2", second)):
        ids = {e.meta.get("replay_id") for e in store.events(session) if e.counterfactual}
        assert ids == {own.replay_id}


def test_the_target_must_be_a_reply_and_exactly_two_peers_must_answer() -> None:
    store = prefix_store()
    with pytest.raises(ValueError, match="reply"):
        asyncio.run(replay_pair(store, SID, 0, xy.ALTERNATIVE, peers, xy.QUESTION))
    with pytest.raises(ValueError, match="two peers"):
        pair(store, make_peers=lambda: peers()[:1])


# --- candidate generation --------------------------------------------------------------------

GOOD = {"tag": "REVISE", "prediction": "Y", "explanation": "The four-minute limit is binding."}


def author_agent(responder) -> PEXAgent:
    return PEXAgent("A", persona_for(0), MockClient(responder=responder), n_agents=3)


def candidate(agent, store=None, target_override=None):
    store = store or prefix_store()
    board = store.state(SID)
    target = target_override or board.events[xy.TARGET_SEQ]
    challenger = board.events[xy.CHALLENGER_SEQ]
    return asyncio.run(generate_candidate(agent, store, board, xy.QUESTION, target, challenger))


def test_the_candidate_prompt_shows_the_original_reply_and_the_objection() -> None:
    seen = []

    def respond(messages) -> str:
        seen.append(messages[-1].content)
        return json.dumps({**GOOD, "reply_to": 99})  # the model's reply_to is ignored

    result = candidate(author_agent(respond))
    assert result.status == "ok" and result.alternative.prediction == "Y"
    assert result.alternative.tag is Tag.REVISE
    prompt = seen[0]
    assert "[6] A REFUTE" in prompt and "objection" in prompt and "[7] B REFUTE" in prompt
    assert "[6] A REFUTE (to 4)" not in prompt.split("You posted")[0]  # the board stops before it
    assert len(result.call_ids) == 1


def test_an_unparseable_candidate_gets_one_repair() -> None:
    queue = ["not json", json.dumps(GOOD)]
    result = candidate(author_agent(lambda messages: queue.pop(0)))
    assert result.status == "ok" and len(result.call_ids) == 2
    assert result.tokens.out > 0


def test_a_candidate_that_changes_nothing_fails_after_one_repair() -> None:
    original = prefix_store().events(SID)[xy.TARGET_SEQ]
    same = json.dumps(
        {"tag": "REVISE", "prediction": original.prediction, "explanation": original.explanation}
    )
    calls = []
    result = candidate(author_agent(lambda messages: calls.append(1) or same))
    assert result.status == "failed" and "no change" in result.reason
    assert len(calls) == 2 and result.alternative is None  # one attempt plus one repair


def test_a_model_error_fails_the_candidate_and_keeps_the_calls_made() -> None:
    def respond(messages) -> str:
        raise LLMError("cannot reach the server")

    result = candidate(author_agent(respond))
    assert result.status == "failed" and "model_error" in result.reason


def test_a_candidate_the_protocol_refuses_fails() -> None:
    store = prefix_store()
    stale = store.events(SID)[xy.TARGET_SEQ].model_copy(update={"reply_to": 40})
    result = candidate(author_agent(lambda messages: json.dumps(GOOD)), store, stale)
    assert result.status == "failed" and "reply_to 40 does not exist" in result.reason


def llm(messages) -> str:
    system, user = messages[0].content, messages[-1].content
    me = system.split("You are ", 1)[1].split(",", 1)[0]
    if "objection" in user:
        return json.dumps(GOOD)
    own = {"A": "X", "B": "Y", "C": "Y"}[me]
    shown = user.split("Reply to message [", 1)[1].split(": ", 1)[1].split(" |")[0]
    tag = "RATIFY" if shown == own else "REFUTE"
    return json.dumps({"tag": tag, "prediction": own, "explanation": f"{me} holds {own}"})


def run_attempt(store, responder):
    client = MockClient(responder=responder)
    board = store.state(SID)
    author = PEXAgent("A", persona_for(0), client, n_agents=3)

    def make_peers():
        return [PEXAgent(n, persona_for(i), client, n_agents=3) for i, n in ((1, "B"), (2, "C"))]

    return asyncio.run(
        attempt_replay(
            store,
            board,
            xy.QUESTION,
            board.events[xy.TARGET_SEQ],
            board.events[xy.CHALLENGER_SEQ],
            author,
            make_peers,
        )
    )


def test_attempt_replay_runs_candidate_then_both_branches_with_model_agents() -> None:
    store = prefix_store()
    attempt = run_attempt(store, llm)
    assert attempt.candidate.status == "ok" and attempt.pair.complete
    assert attempt.pair.credit_delta == pytest.approx(-1 / 3)
    events = store.events(SID)
    assert events[9].tokens.out > 0  # the candidate's cost sits on rollback_start
    assert store.state(SID).rollback_tokens_out > 0
    assert store.state(SID).predictions == {"A": "X", "B": "Y", "C": "Y"}


def test_a_failed_candidate_is_recorded_without_replay_steps() -> None:
    store = prefix_store()
    attempt = run_attempt(store, lambda messages: "not json")
    assert attempt.pair is None and attempt.candidate.status == "failed"
    start, end = store.events(SID)[9:]
    assert (start.kind, end.kind) == (Kind.ROLLBACK_START, Kind.ROLLBACK_END)
    assert end.meta["status"] == "candidate_failed" and end.meta["reason"]
    assert start.tokens.out > 0 and start.meta["replay_id"] == end.meta["replay_id"]
    target, _ = challenged_reply(store.events(SID))
    assert target.seq != xy.TARGET_SEQ  # a failed attempt still uses up the target
