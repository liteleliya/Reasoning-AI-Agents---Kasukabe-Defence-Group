"""Roadmap section 08: a copied prefix can be continued by the same turn loop."""

import asyncio

import pytest

from blackboard import EventStore
from counterfactual.fixture import QUESTION, agents, prefix_drafts, scheduler_config
from scheduler import IMPASSE, Scheduler

SRC = "prefix"


def stalled_store() -> EventStore:
    store = EventStore()
    for draft in prefix_drafts(SRC):
        store.append_sync(draft)
    return store


def test_copy_session_keeps_seq_and_rebinds_the_session_id() -> None:
    store = stalled_store()
    copied = store.copy_session(SRC, "arm-a", upto=5)
    assert copied == 6
    events = store.events("arm-a")
    assert [e.seq for e in events] == list(range(6))
    assert {e.session_id for e in events} == {"arm-a"}
    assert [(e.author, e.tag, e.prediction) for e in events] == [
        (e.author, e.tag, e.prediction) for e in store.events(SRC, 5)
    ]
    assert store.state("arm-a").predictions == store.snapshot(SRC, 5).predictions
    assert len(store.events(SRC)) == 9  # the source is untouched


def test_copy_session_refuses_a_session_that_already_has_events() -> None:
    store = stalled_store()
    store.copy_session(SRC, "arm", upto=3)
    with pytest.raises(ValueError, match="already has events"):
        store.copy_session(SRC, "arm", upto=3)
    with pytest.raises(ValueError, match="no session"):
        store.copy_session("missing", "other", upto=0)


def test_resume_continues_a_copied_prefix_to_the_same_stall_as_a_fresh_run() -> None:
    store = stalled_store()
    store.copy_session(SRC, "arm", upto=8)
    resumed = asyncio.run(Scheduler(store, agents(), scheduler_config()).resume("arm", QUESTION))
    fresh_store = EventStore()
    fresh = asyncio.run(Scheduler(fresh_store, agents(), scheduler_config()).run("fresh", QUESTION))
    assert resumed.stop_reason == fresh.stop_reason == IMPASSE
    assert [(e.author, e.tag, e.prediction) for e in store.events("arm")] == [
        (e.author, e.tag, e.prediction) for e in fresh_store.events("fresh")
    ]


def test_resume_needs_a_prefix_and_refuses_a_finished_session() -> None:
    store = stalled_store()
    sched = Scheduler(store, agents(), scheduler_config())
    with pytest.raises(ValueError, match="no events"):
        asyncio.run(sched.resume("empty", QUESTION))
    asyncio.run(sched.run("done", QUESTION))
    with pytest.raises(ValueError, match="already ended"):
        asyncio.run(sched.resume("done", QUESTION))
