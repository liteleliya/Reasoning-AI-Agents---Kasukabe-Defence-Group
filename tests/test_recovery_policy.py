"""Roadmap section 05: a helpful replay becomes a real reply, and every cost is accounted for."""

import asyncio
import dataclasses

import pytest

from agents.ledger import call_scope
from agents.llm_client import MockClient
from agents.pex_agent import PEXAgent
from agents.prompts import persona_for
from blackboard import EventStore
from counterfactual import fixture as xy
from counterfactual.recovery import ReplayRecovery, live_message, outcomes
from protocol import Kind, Tag
from scheduler import CONSENSUS, IMPASSE, Scheduler
from tests.test_matched_branches import SpyStore, assert_closed, llm


def build(session="s", store=None, *, budget=1, responder=llm, max_branch_tokens=None, client=None):
    """The fixture debate stalls at #8; the replay recovery policy then gets its one attempt."""
    store = store or EventStore()
    client = client or MockClient(responder=responder)
    author = PEXAgent("A", persona_for(0), client, n_agents=3)

    def make_peers():
        return [PEXAgent(n, persona_for(i), client, n_agents=3) for i, n in ((1, "B"), (2, "C"))]

    recovery = ReplayRecovery(store, {"A": author}, make_peers, max_branch_tokens=max_branch_tokens)
    config = dataclasses.replace(xy.scheduler_config(), recovery_budget=budget)
    scheduler = Scheduler(store, xy.agents(enabled=("A",)), config, recovery=recovery)
    with call_scope(trial=session):
        result = asyncio.run(scheduler.run(session, xy.QUESTION))
    return result, store, client


def other_reply(session: str):
    """A's plain REFUTE of #7: an ordinary real reply, not an adopted one."""
    return xy.adoption_draft(session).model_copy(
        update={"tag": Tag.REFUTE, "prediction": "X", "meta": {}}
    )


def adopted_events(store, session="s"):
    return [e for e in store.events(session) if e.meta.get("adopted_counterfactual")]


def test_a_helpful_replay_is_adopted_as_a_real_reply_to_the_challenger() -> None:
    result, store, _ = build()
    opp = result.opportunity
    assert result.stop_reason == CONSENSUS and set(result.state.predictions.values()) == {"Y"}
    assert opp.outcome == "reply_accepted" and opp.replay["status"] == "completed"
    assert opp.replay["credit_delta"] == pytest.approx(-1 / 3)

    (adopted,) = adopted_events(store)
    assert (adopted.author, adopted.tag, adopted.reply_to) == ("A", Tag.REVISE, xy.CHALLENGER_SEQ)
    assert not adopted.counterfactual and "four-minute" in adopted.explanation
    assert adopted.meta["replay_id"] == opp.replay["replay_id"] == "s::replay-1"
    end = next(e for e in store.events("s") if e.kind is Kind.ROLLBACK_END)
    assert adopted.seq > end.seq  # the board only moves at the real reply
    assert store.snapshot("s", end.seq).predictions == {"A": "X", "B": "Y", "C": "Y"}
    term = store.events("s")[-1]
    assert term.meta["recovery"]["replay_id"] == "s::replay-1"


def test_simulated_agreement_adoption_and_final_consensus_are_separate_outcomes() -> None:
    result, _, _ = build()
    assert outcomes(result) == {
        "eligible": True,
        "attempted": True,
        "completed": True,
        "helpful": True,
        "simulated_agreement": True,
        "adopted": True,
        "final_consensus": True,
    }


def test_a_replacement_that_does_not_help_is_not_adopted() -> None:
    def respond(messages) -> str:
        if any("objection" in m.content for m in messages):
            return '{"tag": "REVISE", "prediction": "X", "explanation": "X, for another reason"}'
        return llm(messages)

    result, store, _ = build(responder=respond)
    assert result.opportunity.outcome == "not_helpful"
    assert result.opportunity.replay["credit_delta"] == 0.0
    assert adopted_events(store) == [] and result.stop_reason == IMPASSE
    assert outcomes(result)["completed"] and not outcomes(result)["helpful"]
    assert not outcomes(result)["adopted"] and not outcomes(result)["final_consensus"]
    assert any(e.kind is Kind.ROLLBACK_END for e in store.events("s"))  # the attempt is on record


def test_an_incomplete_comparison_is_not_adopted() -> None:
    result, store, _ = build(max_branch_tokens=1)
    assert result.opportunity.outcome == "incomplete"
    assert result.opportunity.replay["status"] == "incomplete"
    assert result.opportunity.replay["credit_delta"] is None
    assert adopted_events(store) == []
    assert (outcomes(result)["attempted"], outcomes(result)["completed"]) == (True, False)


def test_a_candidate_that_could_not_be_obtained_is_recorded_not_adopted() -> None:
    def respond(messages) -> str:
        asked_for_candidate = any("objection" in m.content for m in messages)
        return "not json" if asked_for_candidate else llm(messages)

    result, store, _ = build(responder=respond)
    assert result.opportunity.outcome == "candidate_failed"
    assert result.opportunity.replay["status"] == "candidate_failed"
    end = next(e for e in store.events("s") if e.kind is Kind.ROLLBACK_END)
    assert end.meta["status"] == "candidate_failed"
    assert adopted_events(store) == []


def test_an_exhausted_budget_makes_no_model_call_replay_or_event_after_term() -> None:
    result, store, client = build(budget=0)
    assert result.opportunity.skip_reason == "budget_exhausted"
    assert client.ledger.rows == []  # no extra model call
    events = store.events("s")
    assert not any(e.kind is not Kind.MESSAGE for e in events)  # no replay
    assert events[-1].tag is Tag.TERM and sum(e.tag is Tag.TERM for e in events) == 1
    assert result.stop_reason == IMPASSE and result.opportunity.outcome is None


def test_a_stale_target_is_recorded_and_nothing_is_posted(monkeypatch) -> None:
    import counterfactual.recovery as recovery

    real = recovery.attempt_replay

    async def attempt_then_move_on(store, board, *args, **kwargs):
        attempt = await real(store, board, *args, **kwargs)
        store.append_sync(other_reply(board.session_id))  # someone answered #7 meanwhile
        return attempt

    monkeypatch.setattr(recovery, "attempt_replay", attempt_then_move_on)
    result, store, _ = build()
    assert result.opportunity.outcome == "stale_target"
    assert adopted_events(store) == [] and result.stop_reason == IMPASSE


def test_the_live_message_is_the_challenger_or_something_newer_never_something_old() -> None:
    store = EventStore()
    for draft in xy.prefix_drafts("s"):
        store.append_sync(draft)
    board = store.state("s")
    challenger = board.events[xy.CHALLENGER_SEQ]
    assert live_message(board, "A", challenger).seq == xy.CHALLENGER_SEQ
    store.append_sync(other_reply("s"))
    assert live_message(store.state("s"), "A", challenger) is None  # answered; #2 is too old


def test_a_peer_failure_mid_replay_closes_the_forks_and_keeps_every_call() -> None:
    calls = []

    def respond(messages) -> str:
        calls.append(1)
        if len(calls) == 3:
            raise TimeoutError("peer timed out")
        return llm(messages)

    store = SpyStore()
    client = MockClient(responder=respond)
    with pytest.raises(TimeoutError):
        build(store=store, client=client)
    for fork in store.forks:
        assert_closed(fork)
    events = store.events("s")
    assert all(e.kind is Kind.MESSAGE for e in events) and len(events) == 9  # history unchanged
    assert store.state("s").predictions == {"A": "X", "B": "Y", "C": "Y"}
    assert [(r.call_id, r.status) for r in client.ledger.rows] == [
        ("call-1", "ok"),
        ("call-2", "ok"),
        ("call-3", "error"),
    ]
    assert [r.phase for r in client.ledger.rows] == ["candidate", "branch", "branch"]
    assert {r.branch for r in client.ledger.rows[1:]} == {"original"}


def test_two_sessions_in_one_store_keep_their_replays_and_calls_apart() -> None:
    store, client = EventStore(), MockClient(responder=llm)
    first, _, _ = build("s1", store, client=client)
    second, _, _ = build("s2", store, client=client)
    assert first.opportunity.replay["replay_id"] == "s1::replay-1"
    assert second.opportunity.replay["replay_id"] == "s2::replay-1"
    for session in ("s1", "s2"):
        ids = {e.meta.get("replay_id") for e in store.events(session) if e.meta.get("replay_id")}
        assert ids == {f"{session}::replay-1"}
        rows = client.ledger.for_trial(session)
        assert {r.session_id for r in rows} == {session} and len(rows) == 5
    assert not {r.call_id for r in client.ledger.for_trial("s1")} & {
        r.call_id for r in client.ledger.for_trial("s2")
    }
