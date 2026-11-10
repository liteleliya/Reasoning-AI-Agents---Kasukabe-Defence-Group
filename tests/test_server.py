"""C1: REST reads and WebSocket streaming of blackboard events."""

import asyncio
import json

from fastapi.testclient import TestClient

from blackboard import EventStore
from protocol import EventDraft, Tag
from server import create_app
from server.catalog import describe_session
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
    (summary,) = c.get("/api/sessions").json()
    assert summary == {
        "session_id": "s",
        "seq": 2,
        "agents": ["a", "b"],
        "terminated": False,
        "stop_reason": None,
        **describe_session("s"),
    }
    assert summary["case_id"] == "s" and summary["condition"] is None
    events = c.get("/api/sessions/s/events").json()
    assert [e["seq"] for e in events] == [0, 1, 2]
    assert events[0]["tokens"] == {"in": 0, "out": 0}
    assert len(c.get("/api/sessions/s/events", params={"upto": 1}).json()) == 2
    snap = c.get("/api/sessions/s/snapshot", params={"at": 1}).json()
    assert snap["predictions"] == {"a": "a", "b": "b"}
    assert snap["intelligibility"]["label"] == "failed"
    assert c.get("/api/sessions/s/snapshot").json()["intelligibility"]["label"] == "strong"
    assert c.get("/api/sessions/nope/events").status_code == 404


def test_query_routes_select_sessions_with_reserved_characters() -> None:
    sid = "j3_prelim_hot-cf2|mscore|law/complex#2534|0"
    store = EventStore()
    store.append_sync(init(sid, "a"))
    store.append_sync(init(sid, "b"))
    store.append_sync(init("plain", "z"))
    c = client_with(store)
    assert sid in [s["session_id"] for s in c.get("/api/sessions").json()]
    events = c.get("/api/events", params={"session_id": sid}).json()
    assert [e["author"] for e in events] == ["a", "b"]
    assert len(c.get("/api/events", params={"session_id": sid, "upto": 0}).json()) == 1
    snap = c.get("/api/snapshot", params={"session_id": sid, "at": 0}).json()
    assert snap["session_id"] == sid and snap["predictions"] == {"a": "a"}
    assert c.get("/api/snapshot", params={"session_id": sid}).json()["seq"] == 1
    assert c.get("/api/events", params={"session_id": "nope"}).status_code == 404
    assert c.get("/api/snapshot", params={"session_id": "nope"}).status_code == 404
    assert c.get("/api/events").status_code == 422  # session_id is required


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


def test_session_list_joins_run_metrics_by_session_id() -> None:
    store = EventStore()
    store.append_sync(init("trial|mscore|Data2/Law/Single-choice/complex#7|0", "a"))
    store.append_sync(init("other", "a"))
    metrics = {
        "trial|mscore|Data2/Law/Single-choice/complex#7|0": {
            "instance_id": "Data2/Law/Single-choice/complex#7",
            "config": "run-cf2",
            "seed": "0",
            "n_agents": "3",
            "n_counterfactual": "2",
            "correct": "True",
        }
    }
    c = TestClient(create_app(store, serve_ui=False, metrics=metrics, source="J3"))
    by_id = {s["session_id"]: s for s in c.get("/api/sessions").json()}
    joined = by_id["trial|mscore|Data2/Law/Single-choice/complex#7|0"]
    assert (joined["condition"], joined["enabled_agents"], joined["correct"]) == (
        "run-cf2",
        2,
        True,
    )
    assert joined["source"] == "J3"
    assert by_id["other"]["correct"] is None and by_id["other"]["source"] == "J3"


def test_results_and_trial_lookup_come_from_the_runs_metrics() -> None:
    metrics = {
        "t1": {
            "config": "run-cf0",
            "n_counterfactual": "0",
            "n_agents": "3",
            "instance_id": "q1",
            "seed": "0",
            "model": "qwen",
            "session_id": "t1",
            "stop_reason": "consensus",
            "correct": "True",
            "rollbacks": "0",
            "total_tokens": "100",
        },
    }
    app = create_app(EventStore(), serve_ui=False, metrics=metrics, source="J3", kind="historical")
    c = TestClient(app)
    results = c.get("/api/results").json()
    assert results["run"]["label"] == "J3" and results["run"]["kind"] == "historical"
    assert results["totals"]["consensus"] == 1 and results["totals"]["correct_consensus"] == 1
    assert c.get("/api/trial", params={"session_id": "t1"}).json()["total_tokens"] == "100"
    assert c.get("/api/trial", params={"session_id": "nope"}).status_code == 404


def test_results_are_unavailable_without_a_metrics_file() -> None:
    c = client_with(EventStore())
    assert c.get("/api/results").status_code == 404
    assert c.get("/api/trial", params={"session_id": "x"}).status_code == 404


def test_case_route_serves_the_public_record_and_nothing_private() -> None:
    c = client_with(EventStore())
    body = c.get("/api/case", params={"case_id": "case:restore-p1"}).json()
    assert body["id"] == "restore-p1" and body["split"] == "dev"
    assert body["question"].startswith("How should service be restored")
    assert [e["id"] for e in body["evidence"]] == ["E1", "E2"]
    assert body["decisions"] == ["A", "B"]
    assert {f["name"] for f in body["fields"]} == {"downtime", "data_loss", "lag_check"}
    text = json.dumps(body).lower()
    for private in ("acceptable", "critical", "rubric", "conditions", "patterns"):
        assert private not in text


def test_case_route_reports_unknown_and_dataset_ids_as_missing() -> None:
    c = client_with(EventStore())
    assert c.get("/api/case", params={"case_id": "case:nope"}).status_code == 404
    assert (
        c.get("/api/case", params={"case_id": "Data2/Law/Single-choice/complex#9"}).status_code
        == 404
    )


def test_authored_sessions_get_a_readable_label() -> None:
    assert describe_session("job-cf0|authored|case:restore-p1|0")["label"] == "Case restore-p1"
