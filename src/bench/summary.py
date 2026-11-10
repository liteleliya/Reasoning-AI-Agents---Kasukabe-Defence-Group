"""Aggregate a run's metrics rows for the results view.

The numbers shown in the UI come from here: the UI never recomputes correctness or decides which
cases count. A figure the export does not record is None, never 0, so the UI can say
"unavailable" instead of showing a count that looks measured.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from server.catalog import case_label

KINDS = ("historical", "controlled", "model")  # what the run is evidence of

# recovery funnel, in order: stage -> (label, column the export must have to count it)
STAGES = (
    ("eligible", "Eligible checkpoints", "eligible"),
    ("attempted", "Replays attempted", "replay_attempted"),
    ("completed", "Comparisons completed", "replay_completed"),
    ("helpful", "Replacements that helped", "replay_helpful"),
    ("adopted", "Adopted as a real reply", "adopted"),
    ("recovered", "Correct recovery", "correct_recovery"),
)
EXAMPLES_PER_KIND = 3

Row = Mapping[str, str]


def _yes(value: str | None) -> bool:
    return (value or "").strip().lower() in ("true", "1")


def _count(rows: Sequence[Row], column: str) -> int | None:
    """Rows where a boolean column is true, or None if the export has no such column."""
    if not any(column in r for r in rows):
        return None
    return sum(_yes(r.get(column)) for r in rows)


def _median(values: list[int]) -> float | int | None:
    if not values:
        return None
    m = statistics.median(values)
    return int(m) if m == int(m) else m


def _tokens(rows: Sequence[Row]) -> list[int]:
    return [int(r["total_tokens"]) for r in rows if r.get("total_tokens")]


def _condition(config: str, rows: Sequence[Row]) -> dict[str, Any]:
    consensus = [r for r in rows if r["stop_reason"] == "consensus"]
    return {
        "condition": config,
        "enabled_agents": int(rows[0]["n_counterfactual"])
        if rows[0].get("n_counterfactual")
        else None,
        "n_agents": int(rows[0]["n_agents"]) if rows[0].get("n_agents") else None,
        "trials": len(rows),
        "consensus": len(consensus),
        "correct_consensus": sum(_yes(r.get("correct")) for r in consensus),
        "wrong_consensus": sum(r.get("correct") == "False" for r in consensus),
        "eligible": _count(rows, "eligible"),
        "median_tokens": _median(_tokens(rows)),
    }


def _examples(rows: Sequence[Row]) -> list[dict[str, Any]]:
    picks = {
        "wrong_consensus": (
            "Consensus on a wrong answer",
            lambda r: r["stop_reason"] == "consensus" and r.get("correct") == "False",
        ),
        "impasse": ("Stopped in an impasse", lambda r: r["stop_reason"] == "impasse"),
        "recovery": (
            "Recovered after a replay",
            lambda r: _yes(r.get("adopted")) and _yes(r.get("correct_recovery")),
        ),
    }
    out = []
    for kind, (title, test) in picks.items():
        for r in [r for r in rows if test(r)][:EXAMPLES_PER_KIND]:
            out.append(
                {
                    "kind": kind,
                    "title": title,
                    "session_id": r["session_id"],
                    "case_id": r["instance_id"],
                    "label": case_label(r["instance_id"]),
                    "condition": r["config"],
                    "outcome": r["stop_reason"],
                }
            )
    return out


def summarize_run(
    rows: Sequence[Row], *, label: str = "", kind: str | None = None
) -> dict[str, Any]:
    if kind is not None and kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    by_config: dict[str, list[Row]] = {}
    for r in rows:
        by_config.setdefault(r["config"], []).append(r)
    conditions = [_condition(config, rs) for config, rs in by_config.items()]
    conditions.sort(
        key=lambda c: (c["enabled_agents"] is None, c["enabled_agents"] or 0, c["condition"])
    )

    recorded = sum(int(r.get("rollbacks") or 0) > 0 for r in rows)
    recovery = [{"stage": "recorded", "label": "Replays logged on the board", "count": recorded}]
    recovery += [
        {"stage": stage, "label": text, "count": _count(rows, column)}
        for stage, text, column in STAGES
    ]
    return {
        "run": {
            "label": label,
            "kind": kind,
            "model": ", ".join(sorted({r["model"] for r in rows if r.get("model")})),
            "trials": len(rows),
            "cases": len({r["instance_id"] for r in rows}),
            "conditions": len(by_config),
            "seeds": sorted({int(r["seed"]) for r in rows if r.get("seed")}),
        },
        "totals": {
            "trials": len(rows),
            "consensus": sum(r["stop_reason"] == "consensus" for r in rows),
            "correct_consensus": sum(
                r["stop_reason"] == "consensus" and _yes(r.get("correct")) for r in rows
            ),
            "recorded_replays": recorded,
        },
        "conditions": conditions,
        "recovery": recovery,
        "examples": _examples(rows),
    }
