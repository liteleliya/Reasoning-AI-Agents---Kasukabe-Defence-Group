"""LLM clients (B1): one interface, a deterministic mock and an OpenAI-compatible backend.

Ollama (`http://127.0.0.1:11434/v1`) and vLLM (`http://127.0.0.1:8001/v1` in our Colab setup)
both serve the OpenAI chat-completions API, so `OpenAICompatibleClient` covers local and Colab runs.
Every call records its token usage under a label, so H3 can count rollback tokens separately
(`"<session>/<agent>"` for normal turns, `"rollback/<session>/<agent>"` for replays).

Smoke test: `uv run python -m agents.llm_client "Say hi in JSON"`.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from typing import Literal

import httpx
from pydantic import BaseModel

TAGS = ("RATIFY", "REVISE", "REFUTE", "REJECT")


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class TokenUsage(BaseModel):
    prompt: int = 0
    completion: int = 0
    estimated: bool = False  # True when the server did not report counts

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt=self.prompt + other.prompt,
            completion=self.completion + other.completion,
            estimated=self.estimated or other.estimated,
        )

    def as_event(self) -> dict[str, int]:
        return {"in": self.prompt, "out": self.completion}


class LLMResponse(BaseModel):
    text: str
    usage: TokenUsage
    model: str
    latency_s: float


Messages = Sequence[ChatMessage | dict]


def _coerce(messages: Messages) -> list[ChatMessage]:
    return [m if isinstance(m, ChatMessage) else ChatMessage(**m) for m in messages]


class BaseLLMClient(ABC):
    model: str

    def __init__(self) -> None:
        self.usage_log: list[tuple[str, TokenUsage]] = []

    async def complete(
        self,
        messages: Messages,
        *,
        temperature: float = 0.7,
        max_tokens: int = 512,
        seed: int | None = None,
        json_mode: bool = False,
        label: str = "",
    ) -> LLMResponse:
        response = await self._complete(
            _coerce(messages),
            temperature=temperature,
            max_tokens=max_tokens,
            seed=seed,
            json_mode=json_mode,
        )
        self.usage_log.append((label, response.usage))
        return response

    @abstractmethod
    async def _complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float,
        max_tokens: int,
        seed: int | None,
        json_mode: bool,
    ) -> LLMResponse: ...

    def total_usage(self, label_prefix: str | None = None) -> TokenUsage:
        total = TokenUsage()
        for label, usage in self.usage_log:
            if label_prefix is None or label.startswith(label_prefix):
                total = total + usage
        return total

    async def aclose(self) -> None:
        return None


class MockClient(BaseLLMClient):
    """Deterministic stand-in for a model.

    With `responder`, returns whatever it returns for the messages. Without, returns a PXP-shaped
    JSON reply chosen from a hash of (seed, last user message). Token counts are word counts.
    """

    def __init__(
        self,
        responder: Callable[[list[ChatMessage]], str] | None = None,
        seed: int = 0,
        model: str = "mock",
    ) -> None:
        super().__init__()
        self.responder = responder
        self.seed = seed
        self.model = model

    async def _complete(self, messages, *, temperature, max_tokens, seed, json_mode):
        if self.responder is not None:
            text = self.responder(messages)
        else:
            last = next((m.content for m in reversed(messages) if m.role == "user"), "")
            digest = hashlib.sha256(f"{self.seed}|{seed}|{last}".encode()).digest()
            k = digest[0] % 3
            text = json.dumps(
                {
                    "tag": TAGS[digest[1] % len(TAGS)],
                    "prediction": f"mock-answer-{k}",
                    "explanation": f"mock reasoning {digest[2]}",
                    "reply_to": None,
                }
            )
        usage = TokenUsage(
            prompt=sum(len(m.content.split()) for m in messages),
            completion=len(text.split()),
        )
        return LLMResponse(text=text, usage=usage, model=self.model, latency_s=0.0)


class LLMError(RuntimeError):
    pass


class OpenAICompatibleClient(BaseLLMClient):
    """Chat completions over HTTP for Ollama, vLLM or any OpenAI-compatible server.

    Retries connection errors, HTTP 429 and 5xx with exponential backoff (1 s, 2 s, 4 s ...).
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "EMPTY",
        timeout_s: float = 300,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__()
        self.model = model
        self.max_retries = max_retries
        self._sleep = sleep
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_s,
            transport=transport,
        )

    async def _complete(self, messages, *, temperature, max_tokens, seed, json_mode):
        body: dict = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if seed is not None:
            body["seed"] = seed
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        start = time.perf_counter()
        for attempt in range(self.max_retries + 1):
            try:
                r = await self._http.post("/chat/completions", json=body)
            except httpx.TransportError as exc:
                if attempt == self.max_retries:
                    raise LLMError(f"cannot reach {self._http.base_url}: {exc}") from exc
            else:
                if r.status_code == 429 or r.status_code >= 500:
                    if attempt == self.max_retries:
                        raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
                elif r.status_code >= 400:
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
                else:
                    return self._parse(r.json(), time.perf_counter() - start)
            await self._sleep(2**attempt)
        raise AssertionError("unreachable")

    def _parse(self, data: dict, latency: float) -> LLMResponse:
        text = data["choices"][0]["message"].get("content") or ""
        u = data.get("usage") or {}
        if "prompt_tokens" in u and "completion_tokens" in u:
            usage = TokenUsage(prompt=u["prompt_tokens"], completion=u["completion_tokens"])
        else:
            usage = TokenUsage(prompt=0, completion=len(text) // 4, estimated=True)
        return LLMResponse(
            text=text, usage=usage, model=data.get("model", self.model), latency_s=latency
        )

    async def aclose(self) -> None:
        await self._http.aclose()


def make_client(backend: str | None = None, **kwargs) -> BaseLLMClient:
    """Build a client; unset arguments come from LLM_BACKEND/_BASE_URL/_MODEL/_API_KEY."""
    backend = backend or os.environ.get("LLM_BACKEND", "mock")
    if backend == "mock":
        return MockClient(**kwargs)
    if backend == "openai":
        kwargs.setdefault("base_url", os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1"))
        kwargs.setdefault("model", os.environ.get("LLM_MODEL", "qwen2.5:7b-instruct"))
        kwargs.setdefault("api_key", os.environ.get("LLM_API_KEY", "EMPTY"))
        return OpenAICompatibleClient(**kwargs)
    raise ValueError(f"unknown backend {backend!r}; use 'mock' or 'openai'")


async def _main(args: argparse.Namespace) -> None:
    backend = args.backend or os.environ.get("LLM_BACKEND", "mock")
    kwargs = {}
    if backend == "openai":
        if args.base_url:
            kwargs["base_url"] = args.base_url
        if args.model:
            kwargs["model"] = args.model
    client = make_client(backend, **kwargs)
    try:
        r = await client.complete(
            [ChatMessage(role="user", content=args.prompt)], json_mode=args.json, max_tokens=200
        )
    finally:
        await client.aclose()
    print(r.text)
    estimated = " (estimated)" if r.usage.estimated else ""
    print(f"model={r.model} tokens={r.usage.as_event()}{estimated} latency={r.latency_s:.2f}s")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Send one prompt to the configured model.")
    p.add_argument("prompt")
    p.add_argument("--backend", choices=["mock", "openai"])
    p.add_argument("--base-url")
    p.add_argument("--model")
    p.add_argument("--json", action="store_true", help="ask for a JSON object")
    asyncio.run(_main(p.parse_args()))
