"""T11: scripted deadlocks; standard agents stay stuck, the fixed message breaks each one, and the
sandbox credits replaying that fix as helpful (the B6 validation)."""

import asyncio

import pytest

from agents.scenarios import SCENARIOS
from blackboard import EventStore
from counterfactual import Alternative, replay
from protocol import Kind, Tag
from scheduler import Scheduler

WITH_FIX = [s for s in SCENARIOS.values() if s.fix is not None]


def run(scenario, fixed=False):
    store = EventStore()
    result = asyncio.run(Scheduler(store, scenario.agents(fixed)).run("s", scenario.question))
    return result, store


def transcript(store):
    return [(e.author, e.tag, e.reply_to, e.prediction) for e in store.events("s")]


def test_at_least_four_scenarios_with_a_control() -> None:
    assert len(SCENARIOS) >= 4
    assert any(s.fix is None for s in SCENARIOS.values())
    assert all(len(s.why.split()) >= 10 for s in SCENARIOS.values())


@pytest.mark.parametrize("scenario", WITH_FIX, ids=lambda s: s.name)
def test_standard_agents_deadlock(scenario) -> None:
    result, store = run(scenario)
    assert result.stop_reason in ("impasse", "cap"), transcript(store)
    assert len(set(result.state.predictions.values())) > 1


@pytest.mark.parametrize("scenario", WITH_FIX, ids=lambda s: s.name)
def test_the_fix_reaches_consensus_on_the_answer(scenario) -> None:
    result, store = run(scenario, fixed=True)
    assert result.stop_reason == "consensus", transcript(store)
    assert set(result.state.predictions.values()) == {scenario.answer}


def test_control_converges_either_way() -> None:
    control = SCENARIOS["control"]
    for fixed in (False, True):
        result, _ = run(control, fixed)
        assert result.stop_reason == "consensus"
        assert set(result.state.predictions.values()) == {control.answer}


@pytest.mark.parametrize("scenario", list(SCENARIOS.values()), ids=lambda s: s.name)
def test_deterministic(scenario) -> None:
    assert transcript(run(scenario)[1]) == transcript(run(scenario)[1])


@pytest.mark.parametrize("scenario", [s for s in WITH_FIX if s.fix.index > 0], ids=lambda s: s.name)
def test_sandbox_credits_replaying_the_fix(scenario) -> None:
    """Replay the fixed message on the real deadlocked board: the credit delta must be < 0."""
    _, finished = run(scenario)
    # replay on the board as it stood before TERM (nothing may follow TERM on a real board)
    term = next(e.seq for e in finished.events("s") if e.tag is Tag.TERM)
    store = finished.fork("s", term - 1)
    fix = scenario.fix
    mine = [
        e
        for e in store.events("s")
        if e.author == fix.author and e.kind is Kind.MESSAGE and not e.counterfactual
    ]
    target = mine[fix.index]
    before = [e.to_record() for e in store.events("s")]
    others = [a for a in scenario.agents() if a.name != fix.author]
    result = asyncio.run(
        replay(
            store,
            "s",
            target.seq,
            Alternative(Tag(fix.tag), fix.explanation, fix.prediction),
            others,
            scenario.question,
        )
    )
    assert result.credit_delta < 0, (result.distance_real, result.distance_replay)
    assert [e.to_record() for e in store.events("s")][: len(before)] == before
