"""B4/B6: the sandbox never changes the real board; counterfactual agents break a deadlock."""

import asyncio
import json

import pytest

from agents.llm_client import MockClient
from agents.pex_agent import PEXAgent
from agents.prompts import persona_for
from blackboard import EventStore
from counterfactual import Alternative, CounterfactualAgent, replay, replay_target
from protocol import EventDraft, Kind, Tag, classify
from scheduler import Scheduler, StubbornAgent


def put(store, author, tag, reply_to=None, pred="x", expl="e", **kw):
    return store.append_sync(
        EventDraft(
            session_id="s",
            author=author,
            tag=tag,
            reply_to=reply_to,
            prediction=pred,
            explanation=expl,
            **kw,
        )
    )


def deadlocked_board() -> EventStore:
    store = EventStore()
    put(store, "a", Tag.INIT, pred="x")
    put(store, "b", Tag.INIT, pred="y")
    put(store, "a", Tag.REFUTE, 1, pred="x", expl="y is wrong")
    put(store, "b", Tag.REFUTE, 2, pred="y", expl="x is wrong")
    return store


def test_replay_leaves_real_history_identical_and_logs_rollback() -> None:
    store = deadlocked_board()
    before = [e.to_record() for e in store.events("s")]
    alt = Alternative(Tag.REVISE, "you are right, y", prediction="y", tokens={"in": 10, "out": 5})
    result = asyncio.run(replay(store, "s", 2, alt, [StubbornAgent("b", "y")], "Q?"))

    after = store.events("s")
    assert [e.to_record() for e in after[: len(before)]] == before  # byte-identical prefix
    assert [e.kind for e in after[len(before) :]] == [
        Kind.ROLLBACK_START,
        Kind.ROLLBACK_STEP,
        Kind.ROLLBACK_STEP,
        Kind.ROLLBACK_END,
    ]
    assert [e.tag for e in result.steps] == [Tag.REVISE, Tag.RATIFY]
    assert (result.distance_real, result.distance_replay) == (0.5, 0.0)
    assert result.credit_delta == -0.5
    assert after[-1].meta["credit_delta"] == -0.5
    state = store.state("s")
    assert state.predictions == {"a": "x", "b": "y"}  # the real board did not move
    assert state.rollback_tokens_in == 10 and state.open_rollback is None
    assert classify(after).label.value == "failed"  # rollbacks never count for H2


def test_replay_rejects_bad_targets() -> None:
    store = deadlocked_board()
    with pytest.raises(ValueError):
        asyncio.run(replay(store, "s", 0, Alternative(Tag.REVISE, "e"), [], "Q"))


def test_replay_target_picks_latest_challenged_reply_once() -> None:
    store = deadlocked_board()
    assert replay_target(store.state("s"), "a").seq == 2
    assert replay_target(store.state("s"), "b") is None  # nobody challenged b's reply yet
    asyncio.run(
        replay(store, "s", 2, Alternative(Tag.REVISE, "e", "y"), [StubbornAgent("b", "y")], "Q")
    )
    assert replay_target(store.state("s"), "a") is None  # already replayed


def stubborn_llm(messages) -> str:
    """Every agent defends its INIT; only a conceding REVISE makes the other ratify."""
    system, user = messages[0].content, messages[-1].content
    me = system.split("You are ", 1)[1].split(",", 1)[0]
    own = {"agent_a": "A", "agent_b": "B"}[me]
    if "board is empty" in user:
        return json.dumps({"tag": "INIT", "prediction": own, "explanation": f"{own} fits"})
    if "Write a different version" in user:
        return json.dumps({"tag": "REVISE", "prediction": "B", "explanation": "B is right"})
    shown_tag = user.split("Reply to message [", 1)[1].split("\n", 1)[1].split()[2]
    shown = user.split("Reply to message [", 1)[1].split(": ", 1)[1].split(" |")[0]
    if shown == own and shown_tag in ("REVISE", "RATIFY"):
        return json.dumps({"tag": "RATIFY", "prediction": own, "explanation": "agreed"})
    return json.dumps({"tag": "REFUTE", "prediction": own, "explanation": f"no, {own}"})


def run_pair(counterfactual: bool):
    client = MockClient(responder=stubborn_llm)
    store = EventStore()
    a = PEXAgent("agent_a", persona_for(0), client)
    b = PEXAgent("agent_b", persona_for(1), client)
    agents: list = [a, b]
    if counterfactual:
        agents[0] = CounterfactualAgent(a, store, lambda: agents)
    result = asyncio.run(Scheduler(store, agents).run("s", "A or B?"))
    return result, store, agents


def test_counterfactual_agent_breaks_a_deadlock_a_standard_agent_does_not() -> None:
    standard, _, _ = run_pair(counterfactual=False)
    assert standard.stop_reason in ("impasse", "cap")

    cf, store, agents = run_pair(counterfactual=True)
    assert cf.stop_reason == "consensus"
    assert cf.state.predictions == {"agent_a": "B", "agent_b": "B"}
    credit = agents[0].credit
    assert len(credit.replays) == 1 and credit.replays[0].credit_delta < 0
    assert credit.adopted == 1
    events = store.events("s")
    assert any(e.kind is Kind.ROLLBACK_END for e in events)
    adopted = [e for e in events if e.meta.get("adopted_counterfactual")]
    assert len(adopted) == 1 and adopted[0].tag is Tag.REVISE and not adopted[0].counterfactual
    assert cf.state.rollback_tokens_in > 0  # replay tokens are counted (H3)


def test_no_credit_leaves_a_note_and_answers_normally() -> None:
    def never_helps(messages) -> str:
        user = messages[-1].content
        if "board is empty" in user:
            me = messages[0].content.split("You are ", 1)[1].split(",", 1)[0]
            return json.dumps({"tag": "INIT", "prediction": me[-1].upper(), "explanation": "e"})
        if "Write a different version" in user:
            return json.dumps({"tag": "REVISE", "prediction": "Z", "explanation": "maybe Z"})
        mine = user.split("Your current prediction: ", 1)[1].split("\n", 1)[0]
        return json.dumps({"tag": "REFUTE", "prediction": mine, "explanation": "no"})

    client = MockClient(responder=never_helps)
    store = EventStore()
    a = PEXAgent("agent_a", persona_for(0), client)
    agents: list = [
        CounterfactualAgent(a, store, lambda: agents),
        PEXAgent("agent_b", persona_for(1), client),
    ]
    asyncio.run(Scheduler(store, agents).run("s", "Q"))
    cf = agents[0]
    assert cf.attempts == 1 and cf.credit.replays[0].credit_delta >= 0
    assert cf.credit.adopted == 0 and len(a.notes) == 1
