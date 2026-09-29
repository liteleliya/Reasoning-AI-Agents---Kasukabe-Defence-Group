"""C1: REST reads and WebSocket streaming of blackboard events."""

import asyncio

from fastapi.testclient import TestClient

from blackboard import EventStore
from protocol import EventDraft, Tag
from server import create_app
from server.demo import run_demo


def init(session: str, author: str) -> EventDraft:
    return EventDraft(
        session_id=session, author=author, tag=Tag.INIT, prediction=author, explanation="e"
    )


def client_with(store: EventStore) -> TestClient:
    return TestClient(create_app(store, serve_ui=False))


def test_rest_endpoints() -> None:
    store = EventStore()
    store.append_sync(init("s", "a"))
    store.append_sync(init("s", "b"))
    store.append_sync(
        EventDraft(
            session_id="s", author="b", tag=Tag.RATIFY, reply_to=0, prediction="a", explanation="ok"
        )
    )
    c = client_with(store)
    assert c.get("/api/sessions").json() == [
        {
            "session_id": "s",
            "seq": 2,
            "agents": ["a", "b"],
            "terminated": False,
            "stop_reason": None,
        }
    ]
    events = c.get("/api/sessions/s/events").json()
    assert [e["seq"] for e in events] == [0, 1, 2]
    assert events[0]["tokens"] == {"in": 0, "out": 0}
    assert len(c.get("/api/sessions/s/events", params={"upto": 1}).json()) == 2
    snap = c.get("/api/sessions/s/snapshot", params={"at": 1}).json()
    assert snap["predictions"] == {"a": "a", "b": "b"}
    assert snap["intelligibility"]["label"] == "failed"
    assert c.get("/api/sessions/s/snapshot").json()["intelligibility"]["label"] == "strong"
    assert c.get("/api/sessions/nope/events").status_code == 404


def test_websocket_sends_backlog_then_live_events() -> None:
    store = EventStore()
    store.append_sync(init("s", "a"))
    store.append_sync(init("other", "z"))
    c = client_with(store)
    with c.websocket_connect("/ws?session_id=s") as ws:
        assert ws.receive_json() == {"type": "event", "event": store.events("s")[0].to_record()}
        assert ws.receive_json() == {"type": "synced"}
        store.append_sync(init("other", "y"))  # filtered out
        store.append_sync(init("s", "b"))
        frame = ws.receive_json()
        assert frame["event"]["seq"] == 1 and frame["event"]["author"] == "b"


def test_websocket_all_sessions_and_from_seq() -> None:
    store = EventStore()
    for a in ("a", "b", "c"):
        store.append_sync(init("s", a))
    c = client_with(store)
    with c.websocket_connect("/ws?from_seq=2") as ws:
        assert ws.receive_json()["event"]["author"] == "c"
        assert ws.receive_json() == {"type": "synced"}


def test_demo_writes_valid_sessions_including_a_rollback() -> None:
    store = EventStore()
    asyncio.run(run_demo(store, delay=0))
    sessions = store.sessions()
    assert {"demo-consensus", "demo-impasse", "demo-reject-loop", "demo-rollback"} <= set(sessions)
    rb = store.state("demo-rollback")
    assert rb.terminated and rb.stop_reason == "consensus"
    assert rb.rollback_tokens_in > 0
    asyncio.run(run_demo(store, delay=0))  # a second run on the same db does not collide
    assert "demo-consensus-1" in store.sessions()
