"""A2: append-only store. Concurrent writes stay consistent; state at seq N rebuilds from log."""

import asyncio
import sqlite3
import threading
from pathlib import Path

import pytest

from blackboard import BoardState, EventStore
from protocol import EventDraft, Kind, ProtocolError, Tag


def msg(session: str, author: str, tag: Tag, reply_to: int | None = None, **kw) -> EventDraft:
    return EventDraft(
        session_id=session,
        author=author,
        tag=tag,
        reply_to=reply_to,
        prediction=kw.pop("prediction", f"{author}-answer"),
        explanation=kw.pop("explanation", "reason"),
        **kw,
    )


def open_session(store: EventStore, session: str, agents=("a", "b", "c")) -> None:
    for agent in agents:
        store.append_sync(msg(session, agent, Tag.INIT))


def test_concurrent_writes_from_threads_and_tasks() -> None:
    store = EventStore()
    for s in ("s1", "s2"):
        open_session(store, s)
    per_writer = 40

    def thread_writer(session: str, author: str, target: int) -> None:
        for _ in range(per_writer):
            store.append_sync(msg(session, author, Tag.REFUTE, target))

    async def task_writer(session: str, author: str, target: int) -> None:
        for _ in range(per_writer):
            await store.append(msg(session, author, Tag.REFUTE, target))

    async def run_tasks() -> None:
        await asyncio.gather(
            task_writer("s1", "c", 0), task_writer("s2", "c", 0), task_writer("s2", "a", 2)
        )

    threads = [
        threading.Thread(target=thread_writer, args=("s1", "a", 1)),
        threading.Thread(target=thread_writer, args=("s1", "b", 2)),
        threading.Thread(target=thread_writer, args=("s2", "b", 0)),
    ]
    for t in threads:
        t.start()
    asyncio.run(run_tasks())
    for t in threads:
        t.join()

    for s in ("s1", "s2"):
        seqs = [e.seq for e in store.events(s)]
        assert seqs == list(range(3 + 3 * per_writer))
        assert store.state(s) == store.snapshot(s)
    assert store.sessions() == ["s1", "s2"]


def test_state_at_any_seq_is_rebuilt_from_log(tmp_path: Path) -> None:
    path = tmp_path / "board.sqlite"
    store = EventStore(path)
    open_session(store, "s")
    history = [store.state("s")]
    for draft in [
        msg("s", "a", Tag.REFUTE, 1, prediction="x", tokens={"in": 10, "out": 3}),
        msg("s", "b", Tag.REVISE, 3, prediction="x", tokens={"in": 12, "out": 4}),
        msg("s", "c", Tag.RATIFY, 4, prediction="x"),
        EventDraft(session_id="s", author="system", tag=Tag.TERM, explanation="consensus"),
    ]:
        store.append_sync(draft)
        history.append(store.state("s"))
    store.close()

    reopened = EventStore(path)
    for expected in history:
        rebuilt = reopened.snapshot("s", expected.seq)
        assert rebuilt == expected
        assert rebuilt == BoardState.replay("s", reopened.events("s")[: expected.seq + 1])

    final = reopened.state("s")
    assert final.terminated and final.stop_reason == "consensus"
    assert final.predictions == {"a": "x", "b": "x", "c": "x"}
    assert (final.tokens_in, final.tokens_out) == (22, 7)
    assert reopened.snapshot("s", 3).predictions["b"] == "b-answer"


def test_log_is_append_only() -> None:
    store = EventStore()
    open_session(store, "s")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store._conn.execute("UPDATE events SET prediction = 'hacked'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store._conn.execute("DELETE FROM events")
    assert [e.prediction for e in store.events("s")] == ["a-answer", "b-answer", "c-answer"]


def test_off_protocol_event_is_rejected_and_not_stored() -> None:
    store = EventStore()
    open_session(store, "s")
    with pytest.raises(ProtocolError, match="own message"):
        store.append_sync(msg("s", "a", Tag.RATIFY, 0))
    assert store.state("s").seq == 2 and len(store.events("s")) == 3


def test_warnings_are_recorded_in_meta() -> None:
    store = EventStore()
    open_session(store, "s", ("a", "b"))
    store.append_sync(msg("s", "a", Tag.RATIFY, 1))
    event = store.append_sync(msg("s", "b", Tag.REFUTE, 2))
    assert event.meta["warnings"] == ["incompatible transition: REFUTE in reply to RATIFY"]


def test_rollback_tokens_are_counted_separately() -> None:
    store = EventStore()
    open_session(store, "s", ("a", "b"))
    store.append_sync(msg("s", "a", Tag.REFUTE, 1, tokens={"in": 5, "out": 5}))

    def rb(kind: Kind, author: str, **kw) -> EventDraft:
        return EventDraft(session_id="s", author=author, kind=kind, counterfactual=True, **kw)

    store.append_sync(rb(Kind.ROLLBACK_START, "a", reply_to=2))
    assert store.state("s").open_rollback == 3
    store.append_sync(rb(Kind.ROLLBACK_STEP, "b", tag=Tag.RATIFY, tokens={"in": 7, "out": 2}))
    store.append_sync(rb(Kind.ROLLBACK_END, "a"))
    s = store.state("s")
    assert s.open_rollback is None
    assert (s.rollback_tokens_in, s.rollback_tokens_out) == (7, 2)
    assert s.total_tokens == 19
    assert s.predictions["b"] == "b-answer"  # rollback steps never change the real board


def test_fork_is_isolated_and_listeners_fire() -> None:
    store = EventStore()
    seen = []
    unsubscribe = store.subscribe(seen.append)
    open_session(store, "s", ("a", "b"))
    store.append_sync(msg("s", "a", Tag.REFUTE, 1))
    unsubscribe()

    fork = store.fork("s", upto=1)
    fork.append_sync(msg("s", "b", Tag.RATIFY, 0))
    assert [e.seq for e in fork.events("s")] == [0, 1, 2]
    assert fork.events("s")[2].tag is Tag.RATIFY
    assert store.events("s")[2].tag is Tag.REFUTE
    assert [e.seq for e in seen] == [0, 1, 2]
