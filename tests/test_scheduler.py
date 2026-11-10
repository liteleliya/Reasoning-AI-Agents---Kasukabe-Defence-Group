"""A5: mock agents reach consensus and impasse deterministically."""

import asyncio
import dataclasses

import pytest

from agents.scenarios import ScriptedAgent
from blackboard import BoardState, EventStore
from counterfactual import fixture as xy
from counterfactual import replay
from protocol import Event, EventDraft, Kind, Tag
from scheduler import (
    CAP,
    CONSENSUS,
    IMPASSE,
    ConfusedAgent,
    FollowerAgent,
    Scheduler,
    SchedulerConfig,
    StubbornAgent,
    TurnReason,
    TurnResult,
    challenged_reply,
    exact_distance,
    load_opportunities,
)
from scheduler.core import _stalled
from scheduler.recovery import Sidecar


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


# --- recovery checkpoint (roadmap section 03) -----------------------------------------------


class StubRecovery:
    """Records each attempt and answers with `make(session_id)` (None = no reply)."""

    name = "stub"

    def __init__(self, make=None) -> None:
        self.make = make
        self.calls: list = []

    async def attempt(self, question, board, opportunity) -> EventDraft | None:
        self.calls.append(opportunity)
        return self.make(board.session_id) if self.make else None


def fixture_run(
    *, enabled=("A",), recovery=None, config=None, sidecar=None, fixed=False, session="s"
):
    store = EventStore()
    scheduler = Scheduler(
        store,
        xy.agents(fixed=fixed, enabled=enabled),
        config or xy.scheduler_config(),
        recovery=recovery,
        sidecar=sidecar,
    )
    return asyncio.run(scheduler.run(session, xy.QUESTION)), store


def term_of(store: EventStore, session: str = "s") -> Event:
    terms = [e for e in store.events(session) if e.tag is Tag.TERM]
    assert len(terms) == 1  # TERM is appended exactly once
    return terms[0]


def test_early_consensus_opens_no_recovery_window() -> None:
    recovery = StubRecovery()
    store = EventStore()
    agents = [StubbornAgent("a", "x"), FollowerAgent("b", "y"), FollowerAgent("c", "z")]
    result = asyncio.run(Scheduler(store, agents, recovery=recovery).run("s", "Q"))
    assert result.stop_reason == CONSENSUS and result.opportunity is None
    assert recovery.calls == []
    assert term_of(store).meta["detail"] == CONSENSUS


def test_fixture_prefix_8_identifies_6_and_7() -> None:
    recovery = StubRecovery()
    result, store = fixture_run(recovery=recovery)
    opp = result.opportunity
    assert result.stop_reason == IMPASSE and result.stop_detail == "debate_stall"
    assert (opp.eligible, opp.skip_reason) == (True, None)
    assert (opp.target, opp.challenger, opp.seq) == (xy.TARGET_SEQ, xy.CHALLENGER_SEQ, 8)
    assert opp.distance == pytest.approx(1 / 3)
    assert opp.roster == ["A", "B", "C"] and opp.enabled == ["A"]
    assert (opp.policy, opp.budget_remaining) == ("stub", 1)
    assert recovery.calls == [opp]
    meta = term_of(store).meta
    assert (meta["detail"], meta["decision_seq"]) == ("debate_stall", 8)
    assert meta["recovery"] == {"eligible": True, "skip_reason": None, "outcome": "no_reply"}


@pytest.mark.parametrize(
    ("enabled", "budget", "recovery", "skip"),
    [
        ((), 1, StubRecovery(), "not_enabled"),
        (("A",), 0, StubRecovery(), "budget_exhausted"),
        (("A",), 1, None, "recovery_disabled"),
    ],
)
def test_skips_are_recorded_after_detection(enabled, budget, recovery, skip) -> None:
    config = dataclasses.replace(xy.scheduler_config(), recovery_budget=budget)
    result, store = fixture_run(enabled=enabled, recovery=recovery, config=config)
    opp = result.opportunity
    assert opp.eligible and opp.skip_reason == skip  # a target was found before the skip
    assert (opp.target, opp.challenger) == (xy.TARGET_SEQ, xy.CHALLENGER_SEQ)
    assert recovery is None or recovery.calls == []
    assert term_of(store).meta["recovery"]["skip_reason"] == skip


class FailingAgent:
    """Reports why it could not take its turn, like a PEXAgent whose model reply was unusable."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def take_turn(self, question, board) -> TurnResult:
        return TurnResult(None, TurnReason.PARSE_FAILURE, "bad json", ("call-1", "call-2"))

    async def act(self, question, board):
        return None


def test_init_only_failure_reports_failed_turns_not_a_debate_stall() -> None:
    store = EventStore()
    agents = [FailingAgent(n) for n in "abc"]
    result = asyncio.run(Scheduler(store, agents, recovery=StubRecovery()).run("s", "Q"))
    assert result.stop_reason == IMPASSE and result.stop_detail == "failed_turns"
    assert (result.opportunity.eligible, result.opportunity.skip_reason) == (
        False,
        "roster_incomplete",
    )
    assert [n.reason for n in result.notes] == [TurnReason.PARSE_FAILURE] * 3
    assert result.notes[0].call_ids == ("call-1", "call-2") and result.notes[0].detail == "bad json"
    assert [e.tag for e in store.events("s")] == [Tag.TERM]
    assert term_of(store).meta["detail"] == "failed_turns"


def test_legacy_agents_that_pass_are_noted_as_passed() -> None:
    result, _ = run([StubbornAgent("a", "x"), StubbornAgent("b", "x")])
    assert result.stop_reason == CONSENSUS
    store = EventStore()
    only_init = [ScriptedAgent("a", ("x", "e"), lambda me, t: (Tag.RATIFY, me, "e"))]
    result = asyncio.run(Scheduler(store, only_init).run("s", "Q"))
    assert result.stop_reason == IMPASSE and result.stop_detail == "all_passed"
    assert [(n.agent, n.reason) for n in result.notes] == [("a", TurnReason.PASSED)]


def test_cap_stops_before_any_extra_real_reply_or_recovery() -> None:
    recovery = StubRecovery(make=xy.adoption_draft)
    config = dataclasses.replace(xy.scheduler_config(), max_messages=9)
    result, store = fixture_run(recovery=recovery, config=config)
    assert result.stop_reason == CAP and result.opportunity is None
    assert recovery.calls == []
    assert len([e for e in store.events("s") if e.tag is not Tag.TERM]) == 9


def test_recovery_fires_once_and_term_is_appended_once() -> None:
    def stubborn_again(session_id: str) -> EventDraft:
        return EventDraft(
            session_id=session_id,
            author="A",
            tag=Tag.REFUTE,
            reply_to=xy.CHALLENGER_SEQ,
            prediction="X",
            explanation="still X",
        )

    recovery = StubRecovery(make=stubborn_again)
    result, store = fixture_run(recovery=recovery)
    assert len(recovery.calls) == 1
    assert result.stop_reason == IMPASSE and result.opportunity.outcome == "reply_accepted"
    assert store.events("s")[9].reply_to == xy.CHALLENGER_SEQ  # the recovery reply is real
    term_of(store)


def test_accepted_recovery_reply_can_reach_consensus() -> None:
    recovery = StubRecovery(make=xy.adoption_draft)
    result, store = fixture_run(recovery=recovery)
    assert result.stop_reason == CONSENSUS and set(result.state.predictions.values()) == {"Y"}
    assert result.opportunity.outcome == "reply_accepted"
    assert term_of(store).meta["recovery"]["outcome"] == "reply_accepted"


def test_refused_recovery_reply_is_recorded_and_not_appended() -> None:
    def off_protocol(session_id: str) -> EventDraft:
        return xy.adoption_draft(session_id).model_copy(update={"reply_to": 99})

    result, store = fixture_run(recovery=StubRecovery(make=off_protocol))
    assert result.opportunity.outcome == "reply_rejected"
    assert result.stop_reason == IMPASSE
    invalid = [n for n in result.notes if n.reason is TurnReason.INVALID_DRAFT]
    assert [n.seq for n in invalid] == [8] and "99" in invalid[0].detail
    assert len(store.events("s")) == 10  # prefix + TERM only


def test_store_rejection_is_noted_as_an_invalid_draft() -> None:
    class Bad:
        name = "bad"

        async def act(self, question, board):
            return EventDraft(
                session_id=board.session_id,
                author="bad",
                tag=Tag.INIT,
                reply_to=5,
                prediction="x",
                explanation="e",
            )

    result, _ = run([Bad()])
    assert result.rejected and result.notes[0].reason is TurnReason.INVALID_DRAFT
    assert result.notes[0].detail == result.rejected[0][1]


def test_ratify_with_a_different_prediction_is_flagged_not_blocked() -> None:
    ratify = lambda me, t: (Tag.RATIFY, me, "fine")  # noqa: E731
    agents = [ScriptedAgent("a", ("x", "e"), ratify), ScriptedAgent("b", ("y", "e"), ratify)]
    result, store = run(agents)
    mismatches = [n for n in result.notes if n.reason is TurnReason.TAG_MISMATCH]
    assert {n.agent for n in mismatches} == {"a", "b"}
    assert "ratified #1" in mismatches[0].detail
    assert any(e.tag is Tag.RATIFY for e in store.events("s"))  # still posted


def test_challenged_reply_picks_the_newest_and_skips_replayed_targets() -> None:
    store = EventStore()
    for draft in xy.prefix_drafts("s"):
        store.append_sync(draft)
    target, challenger = challenged_reply(store.events("s"))
    assert (target.seq, challenger.seq) == (6, 7)
    peers = [a for a in xy.agents() if a.name != "A"]
    asyncio.run(replay(store, "s", 6, xy.ALTERNATIVE, peers, xy.QUESTION))
    assert [e.kind for e in store.events("s")][9] is Kind.ROLLBACK_START
    target, challenger = challenged_reply(store.events("s"))
    assert (target.seq, challenger.seq) == (4, 6)  # 6 was replayed, so the next newest


def test_challenged_reply_ignores_inits_and_ratifies() -> None:
    store = EventStore()
    for draft in xy.prefix_drafts("s")[:3]:
        store.append_sync(draft)
    assert challenged_reply(store.events("s")) is None  # only INITs
    assert challenged_reply([]) is None


def test_opportunities_are_written_to_a_sidecar_keyed_by_session_and_seq(tmp_path) -> None:
    sidecar = Sidecar(tmp_path / "side" / "opportunities.jsonl")
    fixture_run(recovery=StubRecovery(), sidecar=sidecar, session="s1")
    fixture_run(recovery=None, sidecar=sidecar, session="s2")
    records = load_opportunities(sidecar.path)
    assert set(records) == {"s1", "s2"}
    first = records["s1"][0]
    assert (first["seq"], first["target"], first["challenger"]) == (8, 6, 7)
    assert first["policy"] == "stub" and records["s2"][0]["skip_reason"] == "recovery_disabled"
