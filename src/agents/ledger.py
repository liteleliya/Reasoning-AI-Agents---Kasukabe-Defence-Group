"""Call ledger: one row for every request that reaches a model client (roadmap section 05).

Rows are written at the client boundary, so calls whose reply could not be parsed, whose draft the
store refused, or that failed outright are all kept. Which calls ended up on the board is not
decided here: events list the calls behind them in `meta["call_ids"]`, and every other row is an
unposted call.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

_SCOPE: ContextVar[Mapping[str, Any]] = ContextVar("llm_call_scope", default=MappingProxyType({}))
_BUDGET: ContextVar[CallBudget | None] = ContextVar("llm_call_budget", default=None)


class CallBudgetExceeded(RuntimeError):
    """Raised before a request reaches the model when an arm has spent its allowance."""


@dataclass
class CallBudget:
    """A shared request allowance for one intervention continuation.

    The paired study compares intervention policies under the same post-checkpoint request
    allowance.  This object lives in a context variable so candidate generation, both sandbox
    branches and later live deliberation draw from exactly the same pool.
    """

    limit: int
    used: int = 0
    blocked: int = 0

    def reserve(self) -> None:
        if self.used >= self.limit:
            self.blocked += 1
            raise CallBudgetExceeded(f"call allowance exhausted ({self.used}/{self.limit})")
        self.used += 1


@contextmanager
def call_scope(**fields: Any) -> Iterator[None]:
    """Label the model calls made inside the block: trial, session_id, phase, branch, agent, ...

    Scopes nest, and each block adds to or overrides what the enclosing ones set. They follow the
    running task, so concurrent trials sharing one client do not mix their labels.
    """
    token = _SCOPE.set({**_SCOPE.get(), **fields})
    try:
        yield
    finally:
        _SCOPE.reset(token)


@contextmanager
def call_budget(limit: int) -> Iterator[CallBudget]:
    """Cap model requests made by the current async task and all nested helpers.

    A blocked request is recorded by the client as ``skipped`` but is never sent to the model and
    therefore does not consume the experimental allowance.
    """
    if limit < 0:
        raise ValueError("call allowance must be non-negative")
    budget = CallBudget(limit)
    token = _BUDGET.set(budget)
    try:
        yield budget
    finally:
        _BUDGET.reset(token)


def current_scope() -> dict[str, Any]:
    return dict(_SCOPE.get())


def current_budget() -> CallBudget | None:
    return _BUDGET.get()


@dataclass
class CallRecord:
    call_id: str  # unique within one client
    trial: str = ""
    session_id: str = ""
    phase: str = "debate"  # debate, candidate or branch (the Phase-7 arms add their own)
    branch: str = ""  # original or replacement, for branch calls
    repair: bool = False  # the retry sent after an unusable reply
    parent_seq: int | None = None  # the message the call was made to answer
    agent: str = ""
    status: str = "ok"  # ok, error, or skipped (a local allowance blocked the request)
    usage: str = "reported"  # reported, estimated or missing
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_s: float | None = None
    detail: str = ""

    @property
    def tokens(self) -> int:
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)


class CallLedger:
    """Rows in call order; with a path, also appended to it as JSON lines."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self.rows: list[CallRecord] = []
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, record: CallRecord) -> None:
        self.rows.append(record)
        if self.path:
            with self.path.open("a") as f:
                f.write(json.dumps(asdict(record), sort_keys=True) + "\n")

    def for_trial(self, trial: str) -> list[CallRecord]:
        return [r for r in self.rows if r.trial == trial]


def load_ledger(path: str | Path) -> list[CallRecord]:
    return [CallRecord(**json.loads(line)) for line in Path(path).read_text().splitlines() if line]
