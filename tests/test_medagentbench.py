"""MedAgentBench harness: the upstream action loop, the grader hook and resumable output."""

import asyncio

import httpx
import pytest

from agents.llm_client import MockClient
from bench.medagentbench import (
    COMPLETED,
    INVALID_ACTION,
    ROUND_LIMIT,
    Fhir,
    MedAgentError,
    Outcome,
    load_grader,
    parse_action,
    run_all,
    run_task,
    select,
    summarize,
)

CASE = {"id": "task1_1", "instruction": "What is the MRN?", "context": "", "sol": ["S1"]}
FAKE_REFSOL = """
import json
from .utils import *

def task1(case_data, results, fhir_api_base):
    if any(t.role == "agent" and "POST" in t.content for t in results.history):
        return False
    try:
        return json.loads(results.result) == case_data["sol"]
    except Exception:
        return False

def task2(case_data, results, fhir_api_base):
    return send_get_request(fhir_api_base + "Patient")["data"] == "ok"
"""


def fhir(seen: list | None = None) -> Fhir:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        if request.url.path.endswith("/metadata"):
            return httpx.Response(200, text="{}")
        if "boom" in request.url.path:
            return httpx.Response(500, text="no")
        return httpx.Response(200, text="ok", headers={"Content-Type": "application/fhir+json"})

    return Fhir("http://fhir.test/fhir/", transport=httpx.MockTransport(handler))


def scripted(*replies: str) -> MockClient:
    it = iter(replies)
    return MockClient(responder=lambda _: next(it))


def play(client, case=CASE, **kw):
    return asyncio.run(run_task(client, case, [{"name": "GET {api_base}/Patient"}], fhir(), **kw))


def test_parse_action_strips_fences_and_dispatches() -> None:
    assert parse_action("```tool_code\nGET http://x/Patient?a=1\n```").kind == "GET"
    assert parse_action("POST http://x/Obs\n{}").kind == "POST"
    assert parse_action("FINISH([1])").kind == "FINISH"
    assert parse_action("I think the answer is 1").kind == "INVALID"


def test_get_then_finish_completes_and_records_the_dialogue() -> None:
    seen: list[str] = []
    client = scripted("GET http://fhir.test/fhir/Patient?name=x", 'FINISH(["S1"])')
    run = asyncio.run(run_task(client, CASE, [], fhir(seen)))
    assert run.status == COMPLETED and run.result == '["S1"]' and run.rounds == 2
    assert seen == ["http://fhir.test/fhir/Patient?name=x&_format=json"]
    assert [t.role for t in run.history] == ["user", "agent", "user", "agent"]
    assert "Here is the response from the GET request:\nok." in run.history[2].content
    assert "S1" not in run.history[0].content  # the reference never reaches the prompt


def test_post_is_accepted_but_not_sent_and_bad_json_is_flagged() -> None:
    seen: list[str] = []
    client = scripted('POST http://fhir.test/fhir/Obs\n{"a": 1}', "POST http://x\nnot json", "x")
    run = asyncio.run(run_task(client, CASE, [], fhir(seen)))
    assert seen == []
    assert run.history[2].content.startswith("POST request accepted and executed successfully")
    assert run.history[4].content == "Invalid POST request"
    assert run.status == INVALID_ACTION


def test_a_get_error_goes_back_to_the_model() -> None:
    client = scripted("GET http://fhir.test/fhir/boom?x=1", "FINISH([])")
    run = play(client)
    assert run.history[2].content.startswith("Error in sending the GET request")
    assert run.status == COMPLETED


def test_round_limit_stops_a_looping_agent() -> None:
    run = play(MockClient(responder=lambda _: "GET http://fhir.test/fhir/Patient?a=1"), max_round=3)
    assert run.status == ROUND_LIMIT and run.rounds == 3 and run.result is None


def test_grader_scores_through_the_downloaded_refsol(tmp_path) -> None:
    path = tmp_path / "refsol.py"
    path.write_text(FAKE_REFSOL)
    grade = load_grader(path, fhir())
    ok = Outcome([], '["S1"]')
    assert grade(CASE, ok) is True
    assert grade(CASE, Outcome([], '["other"]')) is False
    posted = Outcome([type("T", (), {"role": "agent", "content": "POST x"})()], '["S1"]')
    assert grade(CASE, posted) is False
    assert grade({"id": "task2_1"}, ok) is True  # the grader may query the live server
    with pytest.raises(MedAgentError):
        grade({"id": "task9_1"}, ok)
    with pytest.raises(MedAgentError):
        load_grader(tmp_path / "missing.py", fhir())


def test_run_all_writes_one_line_per_task_and_resumes(tmp_path) -> None:
    path = tmp_path / "refsol.py"
    path.write_text(FAKE_REFSOL)
    grade = load_grader(path, fhir())
    other = {**CASE, "id": "task1_2"}
    out = tmp_path / "out"
    client = scripted('FINISH(["S1"])', "nonsense")
    rows = asyncio.run(run_all(client, [CASE, other], [], fhir(), grade, out, log=lambda _: None))
    assert [(r["task_id"], r["correct"]) for r in rows] == [("task1_1", True), ("task1_2", False)]
    again = asyncio.run(
        run_all(scripted(), [CASE, other], [], fhir(), grade, out, log=lambda _: None)
    )
    assert again == []  # nothing is re-run
    summary = summarize(out / "results.jsonl")
    assert summary["tasks"] == 2 and summary["correct"] == 1
    assert summary["by_type"] == {"task1": {"n": 2, "correct": 1}}
    assert summary["statuses"] == {COMPLETED: 1, INVALID_ACTION: 1}
    assert len((out / "results.jsonl").read_text().splitlines()) == 2


def test_select_by_id_by_type_and_unknown() -> None:
    cases = [{"id": f"task{t}_{n}"} for t in (1, 2) for n in (1, 2, 3)]
    assert [c["id"] for c in select(cases, ["task2_3"], None)] == ["task2_3"]
    assert [c["id"] for c in select(cases, None, 2)] == ["task1_1", "task1_2", "task2_1", "task2_2"]
    assert len(select(cases, None, None)) == 6
    with pytest.raises(MedAgentError):
        select(cases, ["task9_9"], None)


def test_health_check_reports_a_down_server() -> None:
    down = Fhir(
        "http://fhir.test/fhir/",
        transport=httpx.MockTransport(lambda r: httpx.Response(503, text="")),
    )
    assert down.healthy() is False and fhir().healthy() is True
