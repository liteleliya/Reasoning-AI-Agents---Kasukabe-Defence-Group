"""Tables, paired comparison and figures from a saved paired run (roadmap section 09).

    uv run python -m bench.paired_analysis <run dir> --out <dir> [--grades joined.csv]

Terms, each on its own: the prefix is *eligible* when the shared checkpoint opened; an arm
*recovered* when the prefix was eligible and the arm ended in a consensus that grades correct.
Grades come from the rubric (`rubric_pass`, added by `bench.grading rejoin`) when present, else from
the automatic verdict; rows with neither are counted as missing, never as correct.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from bench.arms import ARMS
from bench.metrics import read_metrics

Row = Mapping[str, str]
SMALL = 10  # fewer eligible pairs than this are reported as raw counts only
SERIES = {"standard": "#2a78d6", "forward": "#eb6834", "replay": "#1baf7a"}
DECLINED = ("not_helpful", "incomplete", "candidate_failed")
STAGES = ("eligible", "attempted", "completed", "helpful", "adopted", "correct_recovery")


# --- row predicates -------------------------------------------------------------------------


def _flag(text: str | None) -> bool | None:
    return {"True": True, "False": False}.get((text or "").strip())


def graded(row: Row) -> bool | None:
    """The verdict on the row's final answer: rubric first, else automatic, else unknown."""
    rubric = _flag(row.get("rubric_pass"))
    return rubric if rubric is not None else _flag(row.get("correct"))


def eligible(row: Row) -> bool:
    return row.get("checkpoint") == "opened"


def consensus(row: Row) -> bool:
    return row.get("stop_reason") == "consensus"


def recovered(row: Row) -> bool:
    return eligible(row) and consensus(row) and graded(row) is True


def _number(text: str | None) -> float | None:
    try:
        return float(text) if text not in (None, "") else None
    except ValueError:
        return None


# --- verification ---------------------------------------------------------------------------


def verify(rows: Sequence[Row]) -> dict[str, Any]:
    """Checks before plotting: row count, duplicates, unpaired units, token totals, grades."""
    keys = Counter(r["trial_key"] for r in rows)
    units: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in rows:
        units[(r["instance_id"], r["seed"])].add(r["arm"])
    grades = Counter(
        "rubric"
        if _flag(r.get("rubric_pass")) is not None
        else "automatic"
        if _flag(r.get("correct")) is not None
        else "missing"
        for r in rows
    )
    return {
        "rows": len(rows),
        "duplicates": sorted(k for k, n in keys.items() if n > 1),
        "unpaired": [
            {"case": case, "seed": seed, "missing": [a for a in ARMS if a not in arms]}
            for (case, seed), arms in sorted(units.items())
            if set(ARMS) - arms
        ],
        "tokens_posted": sum(int(r["tokens_in"] or 0) + int(r["tokens_out"] or 0) for r in rows),
        "tokens_full": sum(int(r["total_tokens"] or 0) for r in rows),
        "grades": {k: grades.get(k, 0) for k in ("rubric", "automatic", "missing")},
    }


# --- tables ---------------------------------------------------------------------------------


def outcome_table(rows: Sequence[Row]) -> list[dict[str, Any]]:
    """One line per arm. Correct recovery uses the same eligible prefixes in every arm."""
    out = []
    for arm in ARMS:
        mine = [r for r in rows if r["arm"] == arm]
        done = [r for r in mine if consensus(r)]
        costs = [c for r in mine if (c := _number(r.get("total_tokens"))) is not None]
        walls = [w for r in mine if (w := _number(r.get("wall_time_s"))) is not None]
        out.append(
            {
                "arm": arm,
                "trials": len(mine),
                "eligible": sum(eligible(r) for r in mine),
                "consensus": len(done),
                "correct_consensus": sum(graded(r) is True for r in done),
                "wrong_consensus": sum(graded(r) is False for r in done),
                "ungraded_consensus": sum(graded(r) is None for r in done),
                "correct_recovery": sum(recovered(r) for r in mine),
                "median_cost": statistics.median(costs) if costs else None,
                "median_wall_s": statistics.median(walls) if walls else None,
            }
        )
    return out


def funnel(rows: Sequence[Row], arm: str, *, reasons: bool = False) -> Any:
    """eligible → attempted → completed → helpful → adopted → correct recovery for one arm.

    With `reasons`, the recovery outcomes of eligible rows and the skip reasons of the rest.
    """
    mine = [r for r in rows if r["arm"] == arm]
    elig = [r for r in mine if eligible(r)]
    credit = [_number(r.get("credit_delta")) for r in elig]
    counts = {
        "eligible": len(elig),
        "attempted": sum(bool(r.get("recovery_outcome")) for r in elig),
        "completed": sum(c is not None for c in credit),
        "helpful": sum(c is not None and c < 0 for c in credit),
        "adopted": sum(r.get("recovery_outcome") == "reply_accepted" for r in elig),
        "correct_recovery": sum(recovered(r) for r in elig),
    }
    if not reasons:
        return [{"stage": s, "count": counts[s]} for s in STAGES]
    return {
        "outcomes": dict(Counter(r["recovery_outcome"] for r in elig if r.get("recovery_outcome"))),
        "skipped": dict(
            Counter(r["skip_reason"] for r in mine if not eligible(r) and r.get("skip_reason"))
        ),
    }


# --- paired comparison ----------------------------------------------------------------------


def _percentile_ci(values: list[float]) -> tuple[float, float]:
    ordered = sorted(values)
    lo = ordered[int(0.025 * (len(ordered) - 1))]
    hi = ordered[math.ceil(0.975 * (len(ordered) - 1))]
    return lo, hi


def _bootstrap(by_case: Mapping[str, list[Any]], stat, reps: int, seed: int):
    """Percentile CI of `stat(units)`, resampling whole cases so a case's seeds stay together."""
    cases = sorted(by_case)
    if len(cases) < 2:
        return None
    rng = random.Random(seed)
    draws = []
    for _ in range(reps):
        picked = [u for c in rng.choices(cases, k=len(cases)) for u in by_case[c]]
        draws.append(stat(picked))
    return _percentile_ci(draws)


def compare_arms(
    rows: Sequence[Row], arm: str, other: str, *, reps: int = 2000, seed: int = 0
) -> dict[str, Any]:
    """`arm` against `other` on cases and seeds both ran from an eligible prefix."""
    by_unit: dict[tuple[str, str], dict[str, Row]] = defaultdict(dict)
    for r in rows:
        by_unit[(r["instance_id"], r["seed"])][r["arm"]] = r
    pairs = [
        (case, a[arm], a[other])
        for (case, _), a in sorted(by_unit.items())
        if arm in a and other in a and eligible(a[arm]) and eligible(a[other])
    ]
    by_case: dict[str, list[tuple[Row, Row]]] = defaultdict(list)
    for case, x, y in pairs:
        by_case[case].append((x, y))

    def rate(units) -> float:
        return sum(recovered(x) - recovered(y) for x, y in units) / len(units)

    def mean_diff(field: str):
        def stat(units) -> float:
            diffs = [d for x, y in units if (d := _diff(x, y, field)) is not None]
            return sum(diffs) / len(diffs) if diffs else 0.0

        return stat

    flat = [(x, y) for _, x, y in pairs]
    out: dict[str, Any] = {
        "arm": arm,
        "other": other,
        "pairs": len(pairs),
        "cases": len(by_case),
        "wins": sum(recovered(x) and not recovered(y) for x, y in flat),
        "losses": sum(recovered(y) and not recovered(x) for x, y in flat),
        "small": len(pairs) < SMALL,
    }
    out["ties"] = len(pairs) - out["wins"] - out["losses"]
    out["rate_difference"] = rate(flat) if flat else None
    out["ci"] = _bootstrap(by_case, rate, reps, seed) if flat else None
    out["differences"] = {}
    for field in ("total_tokens", "intervention_tokens", "tokens_in", "tokens_out", "wall_time_s"):
        diffs = [d for x, y in flat if (d := _diff(x, y, field)) is not None]
        out["differences"][field] = {
            "n": len(diffs),
            "mean": sum(diffs) / len(diffs) if diffs else None,
            "ci": _bootstrap(by_case, mean_diff(field), reps, seed) if diffs else None,
        }
    return out


def _diff(x: Row, y: Row, field: str) -> float | None:
    a, b = _number(x.get(field)), _number(y.get(field))
    return None if a is None or b is None else a - b


# --- examples and output --------------------------------------------------------------------


def trace_examples(rows: Sequence[Row], per_kind: int = 3) -> dict[str, list[str]]:
    """Session ids to open in the explorer: a recovery, a declined branch, a wrong consensus."""
    replay = [r for r in rows if r["arm"] == "replay"]
    return {
        "successful_recovery": [r["session_id"] for r in replay if recovered(r)][:per_kind],
        "declined_branch": [
            r["session_id"] for r in replay if r.get("recovery_outcome") in DECLINED
        ][:per_kind],
        "wrong_consensus": [r["session_id"] for r in rows if consensus(r) and graded(r) is False][
            :per_kind
        ],
    }


def _figures(table, steps, comparisons, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    for i, t in enumerate(table):
        parts = [t["correct_consensus"], t["wrong_consensus"] + t["ungraded_consensus"]]
        parts.append(max(0, t["trials"] - sum(parts)))
        left = 0
        for value, color, label in zip(
            parts,
            ("#1baf7a", "#d03b3b", "#c9c9c9"),
            ("correct consensus", "wrong or ungraded", "no consensus"),
            strict=True,
        ):
            ax.barh(i, value, left=left, color=color, label=label if i == 0 else None)
            if value:
                ax.text(left + value / 2, i, str(value), ha="center", va="center", fontsize=8)
            left += value
    ax.set_yticks(range(len(table)), [t["arm"] for t in table])
    ax.set_xlabel("trials")
    ax.legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    fig.savefig(out / "outcomes.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    names = [s["stage"].replace("_", " ") for s in steps]
    ax.barh(range(len(steps)), [s["count"] for s in steps], color=SERIES["replay"])
    for i, s in enumerate(steps):
        ax.text(s["count"], i, f" {s['count']}", va="center", fontsize=8)
    ax.set_yticks(range(len(steps)), names)
    ax.invert_yaxis()
    ax.set_xlabel("prefixes (replay arm)")
    fig.tight_layout()
    fig.savefig(out / "funnel.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    for i, c in enumerate(comparisons.values()):
        d = c["rate_difference"]
        if d is None:
            continue
        ax.plot([d], [i], "o", color=SERIES["replay"])
        if c["ci"]:
            ax.plot(list(c["ci"]), [i, i], "-", color=SERIES["replay"])
        ax.text(
            1.02,
            i,
            f"{c['wins']}W {c['losses']}L {c['ties']}T of {c['pairs']}",
            transform=ax.get_yaxis_transform(),
            va="center",
            fontsize=8,
        )
    ax.axvline(0, color="#888", lw=0.8)
    ax.set_yticks(range(len(comparisons)), list(comparisons))
    ax.set_ylim(len(comparisons) - 0.5, -0.5)
    ax.set_xlim(-1, 1)
    ax.set_xlabel("difference in correct-recovery rate (shared eligible prefixes)")
    fig.tight_layout()
    fig.savefig(out / "paired.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analyse(
    run_dir: str | Path, out_dir: str | Path, *, grades: str | Path | None = None, reps: int = 2000
) -> dict[str, Any]:
    """Write the verification report, tables, figures and the exact input manifest."""
    run, out = Path(run_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    source = Path(grades) if grades else run / "metrics.csv"
    rows = [r for r in read_metrics(source) if r.get("arm")]
    table = outcome_table(rows)
    steps = funnel(rows, "replay")
    comparisons = {
        f"replay_vs_{other}": compare_arms(rows, "replay", other, reps=reps)
        for other in ("forward", "standard")
    }
    report = {
        "verification": verify(rows),
        "outcomes": table,
        "funnel": {"replay": steps, "reasons": funnel(rows, "replay", reasons=True)},
        "comparisons": comparisons,
        "trace_examples": trace_examples(rows),
        "note": "J3 is the historical pilot: its zero rollbacks give no estimate of replay.",
    }
    (out / "analysis.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    with (out / "outcome_table.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    _figures(table, steps, comparisons, out)
    files = {
        source.name: {"path": str(source), "sha256": _sha256(source), "rows": len(rows)},
    }
    for name in ("run.json", "opportunities.jsonl", "calls.jsonl"):
        if (run / name).exists():
            files[name] = {"path": str(run / name), "sha256": _sha256(run / name)}
    (out / "inputs.json").write_text(json.dumps({"files": files}, indent=2))
    return report


def main(argv: Sequence[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Tables and figures from a paired run.")
    p.add_argument("run", help="folder with metrics.csv from bench.run")
    p.add_argument("--out", required=True)
    p.add_argument("--grades", help="metrics rows rejoined with rubric scores (bench.grading)")
    p.add_argument("--reps", type=int, default=2000, help="bootstrap resamples")
    a = p.parse_args(argv)
    report = analyse(a.run, a.out, grades=a.grades, reps=a.reps)
    v = report["verification"]
    print(
        f"{v['rows']} rows, {len(v['duplicates'])} duplicates, {len(v['unpaired'])} unpaired units"
    )
    print(f"wrote tables and figures to {a.out}")


if __name__ == "__main__":
    main()
