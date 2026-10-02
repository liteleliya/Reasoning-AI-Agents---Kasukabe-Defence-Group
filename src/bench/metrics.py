"""Per-trial metrics rows and a crash-safe CSV writer (D3). Columns: docs/metrics.md."""

from __future__ import annotations

import csv
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from blackboard import BoardState
from protocol import Kind, Tag, classify

COLUMNS = (
    "trial_key",
    "config",
    "benchmark",
    "domain",
    "instance_id",
    "seed",
    "model",
    "n_agents",
    "n_counterfactual",
    "cf_share",
    "session_id",
    "stop_reason",
    "converged",
    "answer",
    "correct",
    "messages",
    "cycles",
    "ratify",
    "refute",
    "revise",
    "reject",
    "rollbacks",
    "incompatible",
    "rejected",
    "failed_replies",
    "intelligibility",
    "tokens_in",
    "tokens_out",
    "rollback_tokens_in",
    "rollback_tokens_out",
    "unposted_tokens",
    "total_tokens",
    "wall_time_s",
)


@dataclass(frozen=True)
class TrialMeta:
    """What identifies a trial: one instance, under one config, with one seed."""

    config: str
    benchmark: str
    instance_id: str
    seed: int
    n_agents: int
    n_counterfactual: int
    domain: str = ""
    model: str = ""

    @property
    def key(self) -> str:
        return f"{self.config}|{self.benchmark}|{self.instance_id}|{self.seed}"


def trial_row(
    state: BoardState,
    meta: TrialMeta,
    *,
    answer: str = "",
    correct: bool | None = None,
    wall_time_s: float | None = None,
    rejected: int = 0,
    failed_replies: int = 0,
    unposted_tokens: int = 0,
) -> dict[str, Any]:
    """One CSV row for a finished session.

    `answer` is the session's final answer and `correct` the benchmark judge's verdict on it.
    `unposted_tokens` are tokens spent on replies that never reached the board (unparseable
    after the retry); they still count towards `total_tokens` (H3).
    """
    msgs = [e for e in state.messages if e.author != "system"]
    counts = {t: sum(1 for e in msgs if e.tag is t) for t in Tag}
    replies = sum(1 for e in msgs if e.tag is not Tag.INIT)
    row = {
        "trial_key": meta.key,
        "config": meta.config,
        "benchmark": meta.benchmark,
        "domain": meta.domain,
        "instance_id": meta.instance_id,
        "seed": meta.seed,
        "model": meta.model,
        "n_agents": meta.n_agents,
        "n_counterfactual": meta.n_counterfactual,
        "cf_share": round(meta.n_counterfactual / meta.n_agents, 4),
        "session_id": state.session_id,
        "stop_reason": state.stop_reason or "",
        "converged": state.stop_reason == "consensus",
        "answer": answer,
        "correct": "" if correct is None else correct,
        "messages": len(msgs),
        "cycles": round(replies / meta.n_agents, 4),
        "ratify": counts[Tag.RATIFY],
        "refute": counts[Tag.REFUTE],
        "revise": counts[Tag.REVISE],
        "reject": counts[Tag.REJECT],
        "rollbacks": sum(1 for e in state.events if e.kind is Kind.ROLLBACK_START),
        "incompatible": sum(1 for e in msgs if e.meta.get("warnings")),
        "rejected": rejected,
        "failed_replies": failed_replies,
        "intelligibility": classify(state.events).label.value,
        "tokens_in": state.tokens_in,
        "tokens_out": state.tokens_out,
        "rollback_tokens_in": state.rollback_tokens_in,
        "rollback_tokens_out": state.rollback_tokens_out,
        "unposted_tokens": unposted_tokens,
        "total_tokens": state.total_tokens + unposted_tokens,
        "wall_time_s": "" if wall_time_s is None else round(wall_time_s, 3),
    }
    assert tuple(row) == COLUMNS
    return row


class MetricsWriter:
    """Appends one row per finished trial and fsyncs, so a Colab disconnect loses at most one row.

    `done()` returns the trial keys already written, for resuming a run (D4).
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists() or self.path.stat().st_size == 0:
            with self.path.open("w", newline="") as f:
                csv.writer(f).writerow(COLUMNS)
        else:
            with self.path.open(newline="") as f:
                header = next(csv.reader(f), [])
            if tuple(header) != COLUMNS:
                raise ValueError(f"{self.path} has different columns; write to a new file")

    def done(self) -> set[str]:
        return {r["trial_key"] for r in read_metrics(self.path)}

    def write(self, row: dict[str, Any]) -> None:
        with self.path.open("a", newline="") as f:
            csv.DictWriter(f, fieldnames=COLUMNS).writerow(row)
            f.flush()
            os.fsync(f.fileno())


def read_metrics(path: str | Path) -> list[dict[str, str]]:
    """Rows as strings; drops a trailing partial line left by a crash mid-write."""
    with Path(path).open(newline="") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r.get(COLUMNS[-1]) is not None]


def write_all(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    writer = MetricsWriter(path)
    for row in rows:
        writer.write(row)
