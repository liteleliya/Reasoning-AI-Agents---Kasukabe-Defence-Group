"""Compare static and adaptive counterfactual tactic policies on a matched density study."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

LEVELS = (0, 1, 2, 3)
METRICS = ("correct_consensus", "checkpoint", "rollback", "consensus")


def _read(path: Path) -> list[dict[str, str]]:
    with (path / "metrics.csv").open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _outcome(row: dict[str, str], metric: str) -> bool:
    if metric == "correct_consensus":
        return row["stop_reason"] == "consensus" and row.get("correct") == "True"
    if metric == "checkpoint":
        return row.get("checkpoint") == "opened"
    if metric == "rollback":
        return int(row.get("rollbacks") or 0) > 0
    if metric == "consensus":
        return row.get("stop_reason") == "consensus"
    raise ValueError(f"unknown metric: {metric}")


def _compare(static: dict[str, dict], adaptive: dict[str, dict], metric: str) -> dict:
    paired = sorted(set(static) & set(adaptive))
    wins = sum(_outcome(adaptive[i], metric) and not _outcome(static[i], metric) for i in paired)
    losses = sum(_outcome(static[i], metric) and not _outcome(adaptive[i], metric) for i in paired)
    ties = len(paired) - wins - losses
    return {
        "metric": metric,
        "paired_cases": len(paired),
        "adaptive_wins": wins,
        "static_wins": losses,
        "ties": ties,
        "adaptive_minus_static_pp": 100 * (wins - losses) / len(paired) if paired else None,
    }


def analyze(
    static_rows: list[dict[str, str]], adaptive_rows: list[dict[str, str]], expected: int = 500
):
    def by_level(rows):
        levels = {level: {} for level in LEVELS}
        keys = [row["trial_key"] for row in rows]
        duplicates = [key for key, count in Counter(keys).items() if count > 1]
        if duplicates:
            raise ValueError(f"duplicate trial keys: {duplicates[:3]}")
        for row in rows:
            level = int(row["n_counterfactual"])
            if level in levels:
                levels[level][row["instance_id"]] = row
        counts = {level: len(levels[level]) for level in LEVELS}
        if any(count != expected for count in counts.values()):
            raise ValueError(f"expected {expected} unique cases at every level, got {counts}")
        return levels

    static = by_level(static_rows)
    adaptive = by_level(adaptive_rows)
    comparisons = []
    for level in LEVELS:
        static_ids, adaptive_ids = set(static[level]), set(adaptive[level])
        if static_ids != adaptive_ids:
            raise ValueError(
                f"static and adaptive runs use different task IDs at density {level}/3"
            )
        for metric in METRICS:
            comparisons.append(
                {
                    "enabled_agents": level,
                    "enabled_share": level / 3,
                    **_compare(static[level], adaptive[level], metric),
                }
            )
    return {
        "expected_cases_per_condition": expected,
        "static_trials": len(static_rows),
        "adaptive_trials": len(adaptive_rows),
        "comparisons": comparisons,
        "interpretation": (
            "Descriptive matched outcomes on the frozen cases. At 0/3 the policy has no active "
            "agent, so that row is a pipeline consistency control. Adaptive updates depend on "
            "order; do not interpret paired case differences as independent randomized evidence."
        ),
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("static_run", type=Path)
    parser.add_argument("adaptive_run", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-per-level", type=int, default=500)
    args = parser.parse_args(argv)
    result = analyze(_read(args.static_run), _read(args.adaptive_run), args.expected_per_level)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "policy_comparison.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    with (args.out / "policy_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result["comparisons"][0]))
        writer.writeheader()
        writer.writerows(result["comparisons"])
    print(
        f"verified {result['static_trials']} static and {result['adaptive_trials']} adaptive trials"
    )


if __name__ == "__main__":
    main()
