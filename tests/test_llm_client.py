"""B1: LLM clients. The same calling code works on the mock and the HTTP backend."""

import asyncio
import json

import httpx
import pytest

from agents.llm_client import (
    ChatMessage,
    LLMError,
    MockClient,
    OpenAICompatibleClient,
    TokenUsage,
    make_client,
)

MSGS = [ChatMessage(role="system", content="be brief"), {"role": "user", "content": "what is x"}]


def run(coro):
    return asyncio.run(coro)


def test_mock_is_deterministic_and_counts_tokens() -> None:
    a = run(MockClient(seed=1).complete(MSGS))
    b = run(MockClient(seed=1).complete(MSGS))
    assert a.text == b.text
    assert set(json.loads(a.text)) == {"tag", "prediction", "explanation", "reply_to"}
    assert a.usage == TokenUsage(prompt=5, completion=len(a.text.split()))
    outs = {run(MockClient(seed=s).complete(MSGS)).text for s in range(10)}
    assert len(outs) > 1


def test_usage_log_and_labels() -> None:
    client = MockClient(responder=lambda m: "one two three")

    async def go():
        await client.complete(MSGS, label="s1/a")
        await client.complete(MSGS, label="rollback/s1/a")
        await client.complete(MSGS, label="s1/b")

    run(go())
    assert len(client.usage_log) == 3
    assert client.total_usage().completion == 9
    assert client.total_usage("rollback/").as_event() == {"in": 5, "out": 3}
    assert client.total_usage("s1/").completion == 6


def test_make_client(monkeypatch) -> None:
    assert isinstance(make_client("mock"), MockClient)
    with pytest.raises(ValueError):
        make_client("nope")
    monkeypatch.setenv("LLM_BACKEND", "openai")
    monkeypatch.setenv("LLM_MODEL", "qwen-test")
    client = make_client()
    assert isinstance(client, OpenAICompatibleClient) and client.model == "qwen-test"


def http_client(handler, **kw) -> OpenAICompatibleClient:
    async def no_sleep(_):
        return None

    return OpenAICompatibleClient(
        "http://test/v1", "m", transport=httpx.MockTransport(handler), sleep=no_sleep, **kw
    )


def ok(content: str = '{"a": 1}', usage: dict | None = None) -> httpx.Response:
    body = {"model": "m", "choices": [{"message": {"content": content}}]}
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


def test_http_request_and_token_parsing() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return ok(usage={"prompt_tokens": 12, "completion_tokens": 4})

    r = run(http_client(handler).complete(MSGS, seed=3, json_mode=True, temperature=0.2))
    assert seen["url"] == "http://test/v1/chat/completions"
    body = seen["body"]
    assert body["seed"] == 3 and body["temperature"] == 0.2
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][1] == {"role": "user", "content": "what is x"}
    assert r.usage == TokenUsage(prompt=12, completion=4)


def test_missing_usage_is_estimated() -> None:
    r = run(http_client(lambda req: ok("x" * 40)).complete(MSGS))
    assert r.usage.estimated and r.usage.completion == 10


def test_retries_then_succeeds_and_fails_on_4xx() -> None:
    calls = []

    def flaky(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else ok()

    assert run(http_client(flaky).complete(MSGS)).text == '{"a": 1}'
    assert len(calls) == 3

    with pytest.raises(LLMError, match="HTTP 400"):
        run(http_client(lambda req: httpx.Response(400, text="bad")).complete(MSGS))

    def down(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(LLMError, match="cannot reach"):
        run(http_client(down, max_retries=1).complete(MSGS))
