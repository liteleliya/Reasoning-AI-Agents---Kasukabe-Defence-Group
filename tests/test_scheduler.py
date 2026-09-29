"""A5: mock agents reach consensus and impasse deterministically."""

import asyncio

import pytest

from blackboard import BoardState, EventStore
from protocol import EventDraft, Tag
from scheduler import (
    CAP,
    CONSENSUS,
    IMPASSE,
    ConfusedAgent,
    FollowerAgent,
    Scheduler,
    SchedulerConfig,
    StubbornAgent,
)


def run(agents, config: SchedulerConfig | None = None, session: str = "s"):
    store = EventStore()
    result = asyncio.run(Scheduler(store, agents, config).run(session, "What is x?"))
    return result, store


def transcript(store: EventStore, session: str = "s") -> list[tuple]:
    return [(e.author, e.tag, e.reply_to, e.prediction) for e in store.events(session)]


def test_consensus_with_one_leader_and_followers() -> None:
    agents = [StubbornAgent("a", "x"), FollowerAgent("b", "y"), FollowerAgent("c", "z")]
    result, store = run(agents)
    assert result.stop_reason == CONSENSUS
    assert result.state.predictions == {"a": "x", "b": "x", "c": "x"}
    assert store.events("s")[-1].tag is Tag.TERM
    assert store.events("s")[-1].explanation == CONSENSUS
    assert any(e.tag is Tag.REVISE for e in store.events("s"))
    assert result.rejected == []


def test_impasse_between_two_stubborn_agents() -> None:
    result, store = run([StubbornAgent("a", "x"), StubbornAgent("b", "y")])
    assert result.stop_reason == IMPASSE
    assert result.state.predictions == {"a": "x", "b": "y"}
    assert {e.tag for e in store.events("s")[2:-1]} == {Tag.REFUTE}


def test_follower_oscillating_between_stubborn_agents_hits_the_cap() -> None:
    # REVISE counts as progress, so this oscillation is not an impasse under spec section 4.
    agents = [StubbornAgent("a", "x"), StubbornAgent("b", "y"), FollowerAgent("c", "z")]
    result, store = run(agents)
    assert result.stop_reason == CAP
    c_predictions = [e.prediction for e in store.events("s") if e.author == "c"][1:]
    assert set(c_predictions) == {"x", "y"}


def test_impasse_when_agents_only_reject() -> None:
    result, store = run([ConfusedAgent("a", "x"), ConfusedAgent("b", "y")])
    assert result.stop_reason == IMPASSE
    tags = {e.tag for e in store.events("s")}
    assert Tag.REJECT in tags and Tag.RATIFY not in tags


@pytest.mark.parametrize(
    "agents",
    [
        lambda: [StubbornAgent("a", "x"), FollowerAgent("b", "y"), FollowerAgent("c", "z")],
        lambda: [StubbornAgent("a", "x"), StubbornAgent("b", "y"), FollowerAgent("c", "z")],
    ],
)
def test_runs_are_deterministic(agents) -> None:
    first = transcript(run(agents())[1])
    for _ in range(3):
        assert transcript(run(agents())[1]) == first


def test_iteration_cap() -> None:
    agents = [StubbornAgent("a", "x"), StubbornAgent("b", "y"), StubbornAgent("c", "z")]
    result, store = run(agents, SchedulerConfig(max_messages=5, impasse_window=100))
    assert result.stop_reason == CAP
    assert len(store.events("s")) == 6  # 5 messages + TERM


def test_everyone_passing_is_an_impasse() -> None:
    result, store = run([StubbornAgent("a", "x")])
    assert result.stop_reason == IMPASSE
    assert [e.tag for e in store.events("s")] == [Tag.INIT, Tag.TERM]


def test_challenged_agent_speaks_first() -> None:
    agents = [StubbornAgent("a", "x"), StubbornAgent("b", "y"), StubbornAgent("c", "z")]
    store = EventStore()
    sched = Scheduler(store, agents)
    for name, answer in (("a", "x"), ("b", "y"), ("c", "z")):
        store.append_sync(
            EventDraft(
                session_id="s", author=name, tag=Tag.INIT, prediction=answer, explanation="init"
            )
        )
    store.append_sync(
        EventDraft(
            session_id="s", author="a", tag=Tag.REFUTE, reply_to=2, prediction="x", explanation="no"
        )
    )
    assert [a.name for a in sched.priority(store.state("s"))] == ["c", "b", "a"]


class BadAgent:
    """Always tries to reply to its own INIT, which the validator rejects."""

    name = "bad"

    async def act(self, question: str, board: BoardState) -> EventDraft | None:
        if "bad" not in board.latest:
            return EventDraft(
                session_id=board.session_id,
                author="bad",
                tag=Tag.INIT,
                prediction="q",
                explanation="init",
            )
        own = board.latest["bad"].seq
        return EventDraft(
            session_id=board.session_id,
            author="bad",
            tag=Tag.RATIFY,
            reply_to=own,
            prediction="q",
            explanation="me",
        )


def test_rejected_drafts_are_recorded_and_do_not_loop() -> None:
    result, _ = run([BadAgent(), StubbornAgent("a", "q")])
    assert result.rejected and all("own message" in r for _, r in result.rejected)
    assert result.stop_reason in (IMPASSE, CONSENSUS, CAP)


class SlowAgent(FollowerAgent):
    active = 0
    peak = 0

    async def act(self, question, board):
        SlowAgent.active += 1
        SlowAgent.peak = max(SlowAgent.peak, SlowAgent.active)
        await asyncio.sleep(0.001)
        SlowAgent.active -= 1
        return await super().act(question, board)


@pytest.mark.parametrize("cap", [1, 2])
def test_concurrency_cap(cap: int) -> None:
    SlowAgent.peak = 0
    agents = [StubbornAgent("a", "x")] + [SlowAgent(f"f{i}", f"y{i}") for i in range(4)]
    result, _ = run(agents, SchedulerConfig(concurrency=cap))
    assert result.stop_reason == CONSENSUS
    assert SlowAgent.peak <= cap


def test_rejects_bad_setup() -> None:
    with pytest.raises(ValueError):
        Scheduler(EventStore(), [StubbornAgent("a", "x"), StubbornAgent("a", "y")])
    with pytest.raises(ValueError):
        Scheduler(EventStore(), [StubbornAgent("system", "x")])
