"""Roadmap section 08: the standard and forward-repair control policies at the shared trigger."""

import asyncio
import json

from agents.llm_client import MockClient
from agents.pex_agent import PEXAgent
from agents.prompts import persona_for, reply_messages
from bench.arms import ARMS, ControlRecovery
from blackboard import EventStore
from counterfactual.fixture import (
    CHALLENGER_SEQ,
    QUESTION,
    TARGET_SEQ,
    agents,
    prefix_drafts,
    scheduler_config,
)
from protocol import Tag
from scheduler import IMPASSE, Scheduler


def test_arms_are_the_three_roadmap_conditions() -> None:
    assert ARMS == ("standard", "forward", "replay")


def board_with_prefix():
    store = EventStore()
    for draft in prefix_drafts("p"):
        store.append_sync(draft)
    return store


def test_the_rethink_instruction_is_only_added_on_request() -> None:
    store = board_with_prefix()
    board = store.state("p")
    target = board.events[CHALLENGER_SEQ]
    plain = reply_messages(persona_for(0), "A", QUESTION, board.events, target, "X")
    rethink = reply_messages(persona_for(0), "A", QUESTION, board.events, target, "X", rethink=True)
    assert "challenged" not in plain[-1]["content"]
    assert "challenged" in rethink[-1]["content"] and "change your answer" in rethink[-1]["content"]


def test_both_controls_ask_the_challenged_author_about_the_live_challenger() -> None:
    seen: list[str] = []

    def respond(messages) -> str:
        seen.append(messages[-1].content)
        return json.dumps({"tag": "REFUTE", "prediction": "X", "explanation": "still X"})

    for rethink in (False, True):
        store = board_with_prefix()
        author = PEXAgent("A", persona_for(0), MockClient(responder=respond), n_agents=3)
        policy = ControlRecovery(store, {"A": author}, rethink=rethink)
        assert policy.name == ("forward" if rethink else "standard")
        sched = Scheduler(store, agents(enabled=("A",)), scheduler_config(), recovery=policy)
        result = asyncio.run(sched.resume("p", QUESTION))
        opp = result.opportunity
        assert opp and opp.policy == policy.name
        assert (opp.target, opp.challenger) == (TARGET_SEQ, CHALLENGER_SEQ)
        assert opp.outcome == "reply_accepted"
        posted = store.events("p")[9]
        assert (posted.author, posted.reply_to) == ("A", CHALLENGER_SEQ)
        assert posted.meta["intervention"] == policy.name
        assert ("challenged" in seen[-1]) is rethink
        assert result.stop_reason == IMPASSE  # the control did not move anyone


def test_a_control_that_gets_no_usable_reply_says_why() -> None:
    store = board_with_prefix()
    author = PEXAgent("A", persona_for(0), MockClient(responder=lambda _: "not json"), n_agents=3)
    policy = ControlRecovery(store, {"A": author}, rethink=False)
    sched = Scheduler(store, agents(enabled=("A",)), scheduler_config(), recovery=policy)
    result = asyncio.run(sched.resume("p", QUESTION))
    assert result.opportunity.outcome == "no_reply"
    assert result.opportunity.intervention["reason"] == "parse_failure"
    assert store.events("p")[-1].tag is Tag.TERM


def test_an_author_the_policy_does_not_know_is_reported() -> None:
    store = board_with_prefix()
    policy = ControlRecovery(store, {}, rethink=False)
    sched = Scheduler(store, agents(enabled=("A",)), scheduler_config(), recovery=policy)
    result = asyncio.run(sched.resume("p", QUESTION))
    assert result.opportunity.outcome == "no_author"
