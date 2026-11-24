"""Validate and summarize the 0/33/66/100% counterfactual-agent density ablation."""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

LEVELS = (0, 1, 2, 3)


def _bool(text: str) -> bool | None:
    return {"True": True, "False": False}.get(text)


def _metric(row: dict[str, str], metric: str) -> bool:
    if metric == "correct_consensus":
        return row["stop_reason"] == "consensus" and _bool(row.get("correct", "")) is True
    if metric == "consensus":
        return row["stop_reason"] == "consensus"
    if metric == "checkpoint":
        return row.get("checkpoint") == "opened"
    if metric == "rollback":
        return int(row.get("rollbacks") or 0) > 0
    if metric == "correct_answer":
        return _bool(row.get("correct", "")) is True
    raise ValueError(f"unknown metric {metric!r}")


def _paired_summary(control: dict[str, dict], treatment: dict[str, dict], metric: str) -> dict:
    ids = sorted(set(control) & set(treatment))
    deltas = [int(_metric(treatment[i], metric)) - int(_metric(control[i], metric)) for i in ids]
    return {
        "n": len(ids),
        "treatment_wins": sum(d > 0 for d in deltas),
        "control_wins": sum(d < 0 for d in deltas),
        "ties": sum(d == 0 for d in deltas),
        "difference_pp": 100 * sum(deltas) / len(deltas) if deltas else None,
        "interval_95_pp": _bootstrap_mean(deltas),
    }


def _bootstrap_mean(values: list[int], *, reps: int = 10_000, seed: int = 7319):
    if not values:
        return None
    if len(values) == 1:
        value = 100 * values[0]
        return [value, value]
    rng = random.Random(seed)
    n = len(values)
    means = sorted(100 * sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return [means[int(0.025 * reps)], means[min(reps - 1, int(0.975 * reps))]]


def analyze(rows: list[dict[str, str]], *, expected_per_level: int = 500) -> dict[str, Any]:
    keys = [row["trial_key"] for row in rows]
    duplicates = [key for key, count in Counter(keys).items() if count > 1]
    levels: dict[int, dict[str, dict]] = {level: {} for level in LEVELS}
    for row in rows:
        level = int(row["n_counterfactual"])
        if level not in levels:
            continue
        levels[level][row["instance_id"]] = row
    counts = {str(level): len(group) for level, group in levels.items()}
    if duplicates:
        raise ValueError(f"duplicate trial keys found: {duplicates[:3]}")
    if any(count != expected_per_level for count in counts.values()):
        raise ValueError(
            f"incomplete ablation: expected {expected_per_level} per level, got {counts}"
        )
    id_sets = [set(group) for group in levels.values()]
    if not all(ids == id_sets[0] for ids in id_sets[1:]):
        raise ValueError("ablation conditions do not contain the same benchmark instance IDs")

    summary = []
    for level, group in levels.items():
        n = len(group)
        summary.append(
            {
                "enabled_agents": level,
                "enabled_share": level / 3,
                "trials": n,
                "checkpoints": sum(_metric(r, "checkpoint") for r in group.values()),
                "rollbacks": sum(_metric(r, "rollback") for r in group.values()),
                "consensus": sum(_metric(r, "consensus") for r in group.values()),
                "correct_consensus": sum(_metric(r, "correct_consensus") for r in group.values()),
                "mean_tokens": sum(int(r.get("total_tokens") or 0) for r in group.values()) / n,
                "mean_wall_time_s": sum(float(r.get("wall_time_s") or 0) for r in group.values())
                / n,
            }
        )
    comparisons = []
    for level in LEVELS[1:]:
        for metric in ("checkpoint", "rollback", "consensus", "correct_consensus"):
            comparisons.append(
                {
                    "control_agents": 0,
                    "treatment_agents": level,
                    "metric": metric,
                    **_paired_summary(levels[0], levels[level], metric),
                }
            )
    return {
        "expected_per_level": expected_per_level,
        "total_trials": len(rows),
        "instance_count": len(id_sets[0]),
        "conditions": summary,
        "paired_vs_zero": comparisons,
        "interpretation": (
            "Intervals are descriptive paired case-bootstrap intervals. The agreement-distance "
            "policy memory rewards consensus proximity, not answer correctness. Interpret the "
            "correct-consensus metric as the outcome of interest; do not treat checkpoint or "
            "rollback counts as task success."
        ),
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(data: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    _write_csv(out / "conditions.csv", data["conditions"])
    _write_csv(out / "paired_vs_zero.csv", data["paired_vs_zero"])
    conditions = data["conditions"]
    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
    x = [100 * row["enabled_share"] for row in conditions]
    ax.plot(
        x,
        [100 * row["checkpoints"] / row["trials"] for row in conditions],
        "o-",
        label="Checkpoint rate",
    )
    ax.plot(
        x,
        [100 * row["consensus"] / row["trials"] for row in conditions],
        "o-",
        label="Consensus rate",
    )
    ax.plot(
        x,
        [100 * row["correct_consensus"] / row["trials"] for row in conditions],
        "o-",
        label="Correct consensus",
    )
    ax.set(xlabel="Counterfactual-enabled agents (%)", ylabel="Trials (%)", ylim=(0, 100))
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    fig.savefig(out / "density_outcomes.png", dpi=180)
    plt.close(fig)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="directory containing metrics.csv")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-per-level", type=int, default=500)
    args = parser.parse_args(argv)
    with (args.run_dir / "metrics.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    result = analyze(rows, expected_per_level=args.expected_per_level)
    write_outputs(result, args.out)
    print(f"verified {result['total_trials']} trials across four density conditions")


if __name__ == "__main__":
    main()
