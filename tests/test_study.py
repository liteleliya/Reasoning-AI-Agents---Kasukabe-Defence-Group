"""The paired-study API derives its claims from saved rows, never browser-side heuristics."""

from fastapi.testclient import TestClient

from blackboard import EventStore
from server import create_app
from server.study import build_study_report


def row(arm: str, *, stop="impasse", correct="False", outcome="", credit="", tokens="100"):
    return {
        "trial_key": f"pilot-{arm}|authored|case:restore-p1|0",
        "config": f"pilot-{arm}",
        "benchmark": "authored",
        "domain": "operations",
        "instance_id": "case:restore-p1",
        "seed": "0",
        "session_id": f"session-{arm}",
        "arm": arm,
        "checkpoint": "opened",
        "stop_reason": stop,
        "correct": correct,
        "rubric_pass": "",
        "recovery_outcome": outcome,
        "credit_delta": credit,
        "total_tokens": tokens,
        "wall_time_s": "1.0",
    }


ROWS = [
    row("standard"),
    row("forward"),
    row("replay", stop="consensus", correct="True", outcome="reply_accepted", credit="-0.33", tokens="200"),
]


def test_study_report_keeps_arms_paired_and_quality_fields_explicit() -> None:
    report = build_study_report(ROWS)
    assert report is not None
    assert [r["arm"] for r in report["outcomes"]] == ["standard", "forward", "replay"]
    assert report["funnel"][-1] == {"stage": "correct_recovery", "count": 1}
    (unit,) = report["units"]
    assert unit["checkpoint"] == "opened"
    assert unit["arms"]["replay"]["session_id"] == "session-replay"
    assert report["integrity"]["grading"] == {"rubric": 0, "automatic": 3, "missing": 0}
    assert report["integrity"]["authored_answers"] == {"total": 0, "unresolved": 0}


def test_study_endpoint_exists_only_for_a_paired_run() -> None:
    metrics = {r["session_id"]: r for r in ROWS}
    paired = TestClient(create_app(EventStore(), serve_ui=False, metrics=metrics))
    assert paired.get("/api/study").json()["units"][0]["case_id"] == "case:restore-p1"
    plain = TestClient(create_app(EventStore(), serve_ui=False))
    assert plain.get("/api/study").status_code == 404
