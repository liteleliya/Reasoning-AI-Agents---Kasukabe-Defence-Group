"""Roadmap section 05: one ledger row for every model request, kept even when the call fails."""

import asyncio

import pytest

from agents.ledger import CallLedger, call_scope, load_ledger
from agents.llm_client import LLMError, LLMResponse, MockClient, TokenUsage
from agents.pex_agent import PEXAgent
from agents.prompts import persona_for
from blackboard import EventStore
from protocol import EventDraft, Tag


def ask(client: MockClient) -> LLMResponse:
    return asyncio.run(client.complete([{"role": "user", "content": "one two three"}]))


def test_every_request_gets_a_row_with_the_scope_fields() -> None:
    client = MockClient()
    with call_scope(
        trial="t1", session_id="s", phase="candidate", agent="A", parent_seq=6, repair=True
    ):
        response = ask(client)
    (row,) = client.ledger.rows
    assert (row.call_id, row.trial, row.session_id) == (response.call_id, "t1", "s")
    assert (row.phase, row.agent, row.parent_seq, row.repair) == ("candidate", "A", 6, True)
    assert (row.status, row.usage) == ("ok", "reported")
    assert row.prompt_tokens == 3 and row.completion_tokens == response.usage.completion


def test_scopes_nest_default_to_debate_and_reset() -> None:
    client = MockClient()
    with call_scope(trial="t"):
        with call_scope(phase="branch", branch="original"):
            ask(client)
        ask(client)
    ask(client)
    assert [(r.phase, r.branch, r.trial) for r in client.ledger.rows] == [
        ("branch", "original", "t"),
        ("debate", "", "t"),
        ("debate", "", ""),
    ]
    assert [r.call_id for r in client.ledger.for_trial("t")] == ["call-1", "call-2"]


def test_a_failed_call_stays_in_the_ledger_with_missing_usage() -> None:
    def respond(messages) -> str:
        if respond.calls:
            raise LLMError("server down")
        respond.calls += 1
        return '{"tag": "INIT"}'

    respond.calls = 0
    client = MockClient(responder=respond)
    ask(client)
    with pytest.raises(LLMError):
        ask(client)
    ok, failed = client.ledger.rows
    assert (failed.call_id, failed.status, failed.usage) == ("call-2", "error", "missing")
    assert failed.prompt_tokens is None and "server down" in failed.detail
    assert ok.status == "ok"


def test_usage_the_server_did_not_report_is_marked_estimated() -> None:
    class Estimating(MockClient):
        async def _complete(self, *args, **kwargs) -> LLMResponse:
            response = await super()._complete(*args, **kwargs)
            return response.model_copy(
                update={"usage": TokenUsage(prompt=0, completion=5, estimated=True)}
            )

    client = Estimating()
    ask(client)
    assert client.ledger.rows[0].usage == "estimated"


def test_rows_are_written_as_json_lines(tmp_path) -> None:
    client = MockClient()
    client.ledger = CallLedger(tmp_path / "out" / "calls.jsonl")
    with call_scope(trial="t", session_id="s"):
        ask(client)
        ask(client)
    assert load_ledger(tmp_path / "out" / "calls.jsonl") == client.ledger.rows


def test_a_pex_agent_tags_its_calls_and_posts_their_ids_on_the_draft() -> None:
    queue = ["not json", '{"tag": "REFUTE", "prediction": "B", "explanation": "no"}']
    client = MockClient(responder=lambda messages: queue.pop(0))
    agent = PEXAgent("a", persona_for(0), client)
    store = EventStore()
    for author, pred in (("a", "B"), ("b", "C")):
        store.append_sync(
            EventDraft(
                session_id="s", author=author, tag=Tag.INIT, prediction=pred, explanation="e"
            )
        )
    turn = asyncio.run(agent.take_turn("Q", store.state("s")))
    first, second = client.ledger.rows
    assert turn.draft.meta["call_ids"] == [first.call_id, second.call_id]
    assert (first.repair, second.repair) == (False, True)
    assert {(r.phase, r.agent, r.session_id, r.parent_seq) for r in (first, second)} == {
        ("debate", "a", "s", 1)
    }
