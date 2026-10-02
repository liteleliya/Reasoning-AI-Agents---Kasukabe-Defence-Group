"""A5: mock agents reach consensus and impasse deterministically."""

import asyncio

import pytest

from blackboard import BoardState, EventStore
from protocol import Event, EventDraft, Tag
from scheduler import (
    CAP,
    CONSENSUS,
    IMPASSE,
    ConfusedAgent,
    FollowerAgent,
    Scheduler,
    SchedulerConfig,
    StubbornAgent,
    exact_distance,
)
from scheduler.core import _stalled


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


def test_follower_oscillating_between_stubborn_agents_is_an_impasse() -> None:
    # REVISEs keep coming, but consensus distance never improves: the stall rule stops it.
    agents = [StubbornAgent("a", "x"), StubbornAgent("b", "y"), FollowerAgent("c", "z")]
    result, store = run(agents)
    assert result.stop_reason == IMPASSE
    assert len(store.events("s")) < 15  # well under the 30-message cap
    c_predictions = [e.prediction for e in store.events("s") if e.author == "c"][1:]
    assert set(c_predictions) == {"x", "y"}


def test_without_the_stall_rule_oscillation_runs_to_the_cap() -> None:
    agents = [StubbornAgent("a", "x"), StubbornAgent("b", "y"), FollowerAgent("c", "z")]
    result, _ = run(agents, SchedulerConfig(stall_rule=False))
    assert result.stop_reason == CAP


def test_exact_distance() -> None:
    assert exact_distance({"a": "X.", "b": "x", "c": "y"}) == pytest.approx(1 / 3)
    assert exact_distance({"a": "x", "b": "x"}) == 0
    assert exact_distance({}) == 1


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


def test_two_agents_refuting_each_other_do_not_starve_a_third() -> None:
    store = EventStore()
    agents = [StubbornAgent("a", "x"), StubbornAgent("b", "y"), StubbornAgent("c", "z")]
    sched = Scheduler(store, agents)

    def put(author, tag, reply_to=None, pred="p"):
        store.append_sync(
            EventDraft(
                session_id="s",
                author=author,
                tag=tag,
                reply_to=reply_to,
                prediction=pred,
                explanation="e",
            )
        )

    put("a", Tag.INIT)
    put("b", Tag.INIT)
    put("c", Tag.INIT)
    put("a", Tag.RATIFY, 1)  # seq 3: a speaks, then goes quiet
    for i in range(4):  # b and c refute each other, seqs 4-7
        put("b" if i % 2 == 0 else "c", Tag.REFUTE, 3 + i if i else 2)
    assert sched.priority(store.state("s"))[0].name == "a"


def test_stall_ignores_agreement_among_inits() -> None:
    # Everyone opens with the same answer, then the discussion moves; that is not a stall.
    msgs = []
    for seq, (author, tag, pred) in enumerate(
        [
            ("a", Tag.INIT, "B"),
            ("b", Tag.INIT, "B"),
            ("c", Tag.INIT, "B"),
            ("a", Tag.RATIFY, "B"),
            ("b", Tag.REFUTE, "B"),
            ("c", Tag.REFUTE, "C"),
            ("b", Tag.REVISE, "C"),
            ("c", Tag.REFUTE, "C"),
        ]
    ):
        msgs.append(
            Event(
                seq=seq,
                session_id="s",
                author=author,
                tag=tag,
                prediction=pred,
                explanation="e",
                reply_to=None if tag is Tag.INIT else 0,
            )
        )
    replies = [m for m in msgs if m.tag is not Tag.INIT]
    assert not _stalled(msgs, replies[-3:], exact_distance)
