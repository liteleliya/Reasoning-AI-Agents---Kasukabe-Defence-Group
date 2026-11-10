"""Describe a session for the session list: its case, condition, seed and, if known, its outcome.

Trial sessions are named by their trial key (`config|benchmark|instance_id|seed`, with `~r<n>`
after a crashed attempt). The fixture sessions are named `<case>-off` and `<case>-on`. A run's
metrics file, when given, is the better source and overrides what the name says.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bench.labels import case_label

_TRIAL = re.compile(r"^(?P<config>[^|]+)\|[^|]+\|(?P<case>.+)\|(?P<seed>\d+)(?:~r\d+)?$")
_ARM = re.compile(r"^(?P<case>.+)-(?P<arm>off|on)$")


def describe_session(
    session_id: str, metrics: Mapping[str, str] | None = None, source: str = ""
) -> dict[str, Any]:
    case_id, condition, seed = session_id, None, None
    if m := _TRIAL.match(session_id):
        case_id, condition, seed = m["case"], m["config"], int(m["seed"])
    elif m := _ARM.match(session_id):
        case_id, condition = m["case"], m["arm"]
    out: dict[str, Any] = {
        "case_id": case_id,
        "label": case_label(case_id),
        "condition": condition,
        "seed": seed,
        "source": source,
        "enabled_agents": None,
        "n_agents": None,
        "correct": None,
    }
    if metrics:
        out["case_id"] = metrics["instance_id"]
        out["label"] = case_label(metrics["instance_id"])
        out["condition"] = metrics.get("config") or condition
        out["seed"] = int(metrics["seed"]) if metrics.get("seed") else seed
        out["enabled_agents"] = _int(metrics.get("n_counterfactual"))
        out["n_agents"] = _int(metrics.get("n_agents"))
        out["correct"] = {"True": True, "False": False}.get(metrics.get("correct", ""))
    return out


def _int(text: str | None) -> int | None:
    return int(text) if text else None


def load_metrics_index(path: str | Path) -> dict[str, dict[str, str]]:
    """The rows of a run's `metrics.csv`, keyed by session id."""
    with Path(path).open(newline="") as f:
        return {row["session_id"]: row for row in csv.DictReader(f)}
