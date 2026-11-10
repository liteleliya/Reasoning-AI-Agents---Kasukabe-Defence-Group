"""Blinded grading of final responses (roadmap section 07).

`export` writes a sheet a person can score without seeing the condition, the session or the
automatic verdict, plus a private map from a random grading ID back to the trial. Four dimensions
are scored 0, 1 or 2 (conclusion, evidence, constraints, justification); a response passes at
6 of 8 with no critical violation. Scores rejoin the metrics rows through the private map.

    uv run python -m bench.grading export CONFIG --run DIR --out DIR [--seed N] [--double K]
    uv run python -m bench.grading rejoin --run DIR --private FILE --scores FILE --out FILE
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from bench.authored import check
from bench.metrics import read_metrics
from bench.mscore import Instance
from blackboard import EventStore

DIMENSIONS = ("conclusion", "evidence", "constraints", "justification")
PASS_AT = 6
_TRUE, _FALSE = {"1", "true", "yes", "y"}, {"", "0", "false", "no", "n"}
_CITATION = re.compile(r"\bE\d+\b")


class ScoreError(ValueError):
    """A score sheet is incomplete, out of range or inconsistent with the private map."""


# --- export ---------------------------------------------------------------------------------


def _explanation(store: EventStore, session_id: str, answer: str) -> str:
    latest = store.state(session_id).latest
    holders = sorted(a for a, e in latest.items() if e.prediction == answer)
    return latest[holders[0]].explanation if holders else ""


def _auto(instance: Instance, row: Mapping[str, str], answer: str, explanation: str) -> dict:
    """The automatic checks kept in the private map, never on the sheet."""
    case, grading = getattr(instance, "case", None), getattr(instance, "grading", None)
    if case is None or grading is None:
        return {"correct": row.get("correct", "")}
    verdict = check(case, grading, answer)
    text = f"{answer}\n{explanation}"
    cited = set(_CITATION.findall(text))
    known = {e.id for e in case.evidence}
    return {
        "decision_ok": verdict.decision_ok,
        "violations": [v.id for v in verdict.violations],
        "conditions_hit": [
            c.id for c in grading.conditions if any(re.search(p, text, re.I) for p in c.patterns)
        ],
        "missing_evidence": [e for e in grading.evidence_required if e not in cited],
        "unknown_evidence": sorted(cited - known),
    }


def export_for_grading(
    rows: Sequence[Mapping[str, str]],
    store: EventStore,
    instances: Mapping[str, Instance],
    *,
    seed: int,
) -> tuple[list[dict], dict[str, dict]]:
    """(sheet rows in a shuffled order, private map by grading ID); answerless rows are skipped."""
    rng = random.Random(seed)
    graded = [r for r in rows if r.get("answer")]
    rng.shuffle(graded)
    sheet: list[dict] = []
    private: dict[str, dict] = {}
    for row in graded:
        instance = instances[row["instance_id"]]
        answer = row["answer"]
        explanation = _explanation(store, row["session_id"], answer)
        gid = f"g-{rng.getrandbits(32):08x}"
        while gid in private:
            gid = f"g-{rng.getrandbits(32):08x}"
        sheet.append(
            {
                "grading_id": gid,
                "prompt": instance.prompt_text(),
                "answer": answer,
                "explanation": explanation,
                **dict.fromkeys(DIMENSIONS, ""),
                "critical": "",
                "grader": "",
                "notes": "",
            }
        )
        private[gid] = {
            "trial_key": row["trial_key"],
            "session_id": row["session_id"],
            "instance_id": row["instance_id"],
            "benchmark": row["benchmark"],
            "config": row["config"],
            "auto": _auto(instance, row, answer, explanation),
        }
    return sheet, private


def double_score_subset(private: Mapping[str, Mapping[str, Any]], k: int, seed: int) -> list[str]:
    """`k` grading IDs spread evenly over case types, for two people to score independently."""
    by_kind: dict[str, list[str]] = defaultdict(list)
    for gid in sorted(private):
        by_kind[private[gid]["benchmark"]].append(gid)
    rng = random.Random(seed)
    queues = [rng.sample(ids, len(ids)) for _, ids in sorted(by_kind.items())]
    picked: list[str] = []
    while any(queues) and len(picked) < k:
        for queue in queues:
            if queue and len(picked) < k:
                picked.append(queue.pop())
    return picked


# --- scores ---------------------------------------------------------------------------------


def write_sheet(path: str | Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise ValueError("nothing to write")
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _flag(raw: str, gid: str) -> bool:
    value = str(raw).strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ScoreError(f"{gid}: critical must be yes or no, got {raw!r}")


def read_scores(path: str | Path) -> list[dict]:
    """Scores from a filled sheet; every dimension must be 0, 1 or 2."""
    with Path(path).open(encoding="utf-8", newline="") as f:
        raw = list(csv.DictReader(f))
    out = []
    for r in raw:
        gid = r["grading_id"]
        entry: dict[str, Any] = {"grading_id": gid, "grader": r.get("grader", "")}
        for dim in DIMENSIONS:
            text = str(r.get(dim, "")).strip()
            if text not in ("0", "1", "2"):
                raise ScoreError(f"{gid}: {dim} must be 0, 1 or 2, got {text!r}")
            entry[dim] = int(text)
        entry["critical"] = _flag(r.get("critical", ""), gid)
        out.append(entry)
    return out


def rubric_result(score: Mapping[str, Any]) -> dict:
    total = sum(int(score[d]) for d in DIMENSIONS)
    critical = bool(score["critical"])
    return {
        "grading_id": score["grading_id"],
        "total": total,
        "critical": critical,
        "passed": total >= PASS_AT and not critical,
    }


def reconcile(first: Sequence[Mapping[str, Any]], second: Sequence[Mapping[str, Any]]) -> dict:
    """Agreement between two graders on the responses both scored, and what to discuss."""
    a, b = {s["grading_id"]: s for s in first}, {s["grading_id"]: s for s in second}
    both = sorted(a.keys() & b.keys())
    fields = (*DIMENSIONS, "critical")
    differing = {g: [f for f in fields if a[g][f] != b[g][f]] for g in both}
    return {
        "both": len(both),
        "exact": sum(1 for g in both if not differing[g]),
        "disagreements": [
            {"grading_id": g, "dimensions": differing[g]} for g in both if differing[g]
        ],
        "pass_agreement": (
            sum(rubric_result(a[g])["passed"] == rubric_result(b[g])["passed"] for g in both)
            / len(both)
            if both
            else None
        ),
        "dimension_agreement": {
            f: (sum(a[g][f] == b[g][f] for g in both) / len(both) if both else None) for f in fields
        },
    }


def rejoin(
    rows: Sequence[Mapping[str, str]],
    private: Mapping[str, Mapping[str, Any]],
    scores: Sequence[Mapping[str, Any]],
) -> list[dict]:
    """Rows with `rubric_total`, `rubric_pass` and `rubric_critical`; blank where not graded."""
    seen: dict[str, Mapping[str, Any]] = {}
    for s in scores:
        gid = s["grading_id"]
        if gid not in private:
            raise ScoreError(f"unknown grading ID {gid!r}")
        if gid in seen:
            raise ScoreError(f"{gid} was scored twice; reconcile before joining")
        seen[gid] = s
    by_trial = {private[g]["trial_key"]: rubric_result(s) for g, s in seen.items()}
    joined = []
    for row in rows:
        result = by_trial.get(row["trial_key"])
        joined.append(
            {
                **row,
                "rubric_total": result["total"] if result else "",
                "rubric_pass": result["passed"] if result else "",
                "rubric_critical": result["critical"] if result else "",
            }
        )
    return joined


# --- command line ---------------------------------------------------------------------------


def _export(a: argparse.Namespace) -> None:
    from bench.run import JobConfig, job_instances

    run = Path(a.run)
    instances = {i.id: i for i in job_instances(JobConfig.load(a.config))}
    store = EventStore(run / "board.sqlite")
    try:
        sheet, private = export_for_grading(
            read_metrics(run / "metrics.csv"), store, instances, seed=a.seed
        )
    finally:
        store.close()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    write_sheet(out / "sheet.csv", sheet)
    (out / "private.json").write_text(json.dumps(private, indent=2, ensure_ascii=False))
    if a.double:
        ids = double_score_subset(private, a.double, a.seed)
        write_sheet(out / "sheet_double.csv", [s for s in sheet if s["grading_id"] in ids])
    print(f"wrote {len(sheet)} responses to {out}; keep private.json away from graders")


def _rejoin(a: argparse.Namespace) -> None:
    private = json.loads(Path(a.private).read_text(encoding="utf-8"))
    rows = read_metrics(Path(a.run) / "metrics.csv")
    write_sheet(a.out, rejoin(rows, private, read_scores(a.scores)))
    print(f"wrote {a.out}")


def main(argv: Sequence[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    e = sub.add_parser("export", help="write the blinded sheet and the private map")
    e.add_argument("config")
    e.add_argument("--run", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--seed", type=int, default=0)
    e.add_argument("--double", type=int, default=0, help="size of the double-scored subset")
    e.set_defaults(func=_export)
    r = sub.add_parser("rejoin", help="join scores to the metrics rows")
    r.add_argument("--run", required=True)
    r.add_argument("--private", required=True)
    r.add_argument("--scores", required=True)
    r.add_argument("--out", required=True)
    r.set_defaults(func=_rejoin)
    a = p.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
