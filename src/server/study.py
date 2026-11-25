"""Read-only research dashboard data for a paired experiment.

The browser is deliberately not allowed to infer correctness, eligibility or a replay effect.  It
receives this small, derived view of saved metrics, the frozen run record and the public answer
schema.  Private grading records and raw prompts never leave this module.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from agents.ledger import load_ledger
from bench import authored
from bench.arms import ARMS
from bench.labels import case_label
from bench.paired_analysis import compare_arms, funnel, outcome_table, trace_examples

Row = Mapping[str, str]


def _bool(value: str | None) -> bool | None:
    return {"True": True, "False": False}.get((value or "").strip())


def _number(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def _latest_run(path: Path | None) -> dict[str, Any]:
    if path is None or not (path / "run.json").exists():
        return {}
    try:
        records = json.loads((path / "run.json").read_text(encoding="utf-8")).get("runs", [])
    except (OSError, json.JSONDecodeError):
        return {}
    return records[-1] if records else {}


def _stored_analysis(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    for candidate in (path / "analysis" / "analysis.json", path / "analysis.json"):
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
    return None


def _quality(rows: Sequence[Row], run_dir: Path | None, job: Mapping[str, Any]) -> dict[str, Any]:
    """Integrity counters that help a presenter state what a run can and cannot support."""
    answer_rows = [r for r in rows if r.get("benchmark") == "authored" and r.get("answer")]
    unresolved = 0
    try:
        from bench.cases import load_cases

        book = load_cases()
        for row in answer_rows:
            case_id = row["instance_id"].removeprefix("case:")
            case = book.public.get(case_id)
            if case is not None and authored.parse_prediction(case, row["answer"]) is None:
                unresolved += 1
    except (OSError, ValueError):
        # An archive should still be viewable if local public case files are unavailable.
        unresolved = 0

    graded = Counter(
        "rubric"
        if _bool(r.get("rubric_pass")) is not None
        else "automatic"
        if _bool(r.get("correct")) is not None
        else "missing"
        for r in rows
    )
    allowance = job.get("allowance_calls")
    violations: list[dict[str, Any]] = []
    if run_dir is not None and allowance is not None and (run_dir / "calls.jsonl").exists():
        calls = load_ledger(run_dir / "calls.jsonl")
        by_trial: dict[str, int] = defaultdict(int)
        for call in calls:
            if call.trial and call.status != "skipped":
                by_trial[call.trial] += 1
        for row in rows:
            trial = row.get("trial_key", "")
            if row.get("arm") and by_trial[trial] > int(allowance):
                violations.append({"trial_key": trial, "calls": by_trial[trial]})
    return {
        "grading": {key: graded.get(key, 0) for key in ("rubric", "automatic", "missing")},
        "authored_answers": {"total": len(answer_rows), "unresolved": unresolved},
        "allowance": {"limit": allowance, "violations": violations},
    }


def _matrix(rows: Sequence[Row]) -> list[dict[str, Any]]:
    """One inspectable paired unit per case and seed, with a linkable session for every arm."""
    units: dict[tuple[str, str], dict[str, Row]] = defaultdict(dict)
    for row in rows:
        if row.get("arm") in ARMS:
            units[(row["instance_id"], row["seed"])][row["arm"]] = row
    out = []
    for (case_id, seed), arms in sorted(units.items()):
        arm_data = {}
        for arm in ARMS:
            row = arms.get(arm)
            if row is None:
                continue
            arm_data[arm] = {
                "session_id": row.get("session_id", ""),
                "stop_reason": row.get("stop_reason", ""),
                "correct": _bool(row.get("rubric_pass"))
                if _bool(row.get("rubric_pass")) is not None
                else _bool(row.get("correct")),
                "recovery_outcome": row.get("recovery_outcome", ""),
                "tokens": _number(row.get("total_tokens")),
            }
        first = next(iter(arms.values()))
        out.append(
            {
                "case_id": case_id,
                "label": case_label(case_id),
                "domain": first.get("domain", ""),
                "seed": int(seed),
                "checkpoint": first.get("checkpoint", "none"),
                "arms": arm_data,
            }
        )
    return out


def build_study_report(
    rows: Sequence[Row], *, run_dir: str | Path | None = None
) -> dict[str, Any] | None:
    """Create the entire paired-study API response from saved local files.

    Returns ``None`` for a non-paired archive, allowing the same server to continue serving J3
    and the controlled fixture without pretending that missing experimental fields are zero.
    """
    paired_rows = [row for row in rows if row.get("arm") in ARMS]
    if not paired_rows:
        return None
    directory = Path(run_dir) if run_dir else None
    saved = _stored_analysis(directory)
    latest = _latest_run(directory)
    job = latest.get("job", {}) if isinstance(latest.get("job", {}), Mapping) else {}
    outcomes = saved.get("outcomes") if saved else outcome_table(paired_rows)
    replay_funnel = (
        saved.get("funnel", {}).get("replay") if saved else funnel(paired_rows, "replay")
    )
    comparisons = (
        saved.get("comparisons")
        if saved
        else {
            f"replay_vs_{other}": compare_arms(paired_rows, "replay", other, reps=400)
            for other in ("standard", "forward")
        }
    )
    examples = saved.get("trace_examples") if saved else trace_examples(paired_rows)
    provenance = {
        "model": latest.get("model") or job.get("model") or "not recorded",
        "persona_set": job.get("persona_set", "not recorded"),
        "temperature": job.get("temperature"),
        "n_agents": job.get("n_agents"),
        "seeds": job.get("seeds", []),
        "analysis_source": "saved" if saved else "derived locally",
    }
    # Activity is reported at two explicit levels: checkpoints are unique shared prefixes,
    # whereas PXP tags and rollback counts are trial-level totals across all three arms.
    # Replay adoption is a separate intervention outcome and is counted only on replay rows.
    units = _matrix(paired_rows)
    replay_rows = [row for row in paired_rows if row.get("arm") == "replay"]
    activity = {
        "prefixes": len(units),
        "checkpoints": sum(unit["checkpoint"] == "opened" for unit in units),
        "trials": len(paired_rows),
        "tags": {
            key: sum(_number(row.get(key)) or 0 for row in paired_rows)
            for key in ("ratify", "refute", "revise", "reject")
        },
        "rollbacks": sum(_number(row.get("rollbacks")) or 0 for row in paired_rows),
        "replay_outcomes": dict(
            Counter(
                row.get("recovery_outcome", "")
                for row in replay_rows
                if row.get("recovery_outcome")
            )
        ),
        "replay_attempts": sum(bool(row.get("recovery_outcome")) for row in replay_rows),
        "replay_accepted": sum(
            row.get("recovery_outcome") == "reply_accepted" for row in replay_rows
        ),
    }
    return {
        "provenance": provenance,
        "outcomes": outcomes,
        "funnel": replay_funnel,
        "comparisons": comparisons,
        "examples": examples,
        "integrity": _quality(paired_rows, directory, job),
        "units": units,
        "activity": activity,
        "note": (
            "Correctness uses human rubric scores when present, otherwise the frozen automatic "
            "check. A checkpoint is a property of the shared prefix, not of an individual arm."
        ),
    }
