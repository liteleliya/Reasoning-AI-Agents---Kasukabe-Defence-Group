import pytest

from bench.ablation_analysis import analyze


def row(
    level: int, item: int, *, correct: bool, checkpoint: bool, rollbacks: int
) -> dict[str, str]:
    return {
        "trial_key": f"cf{level}|item-{item}|0",
        "n_counterfactual": str(level),
        "instance_id": f"item-{item}",
        "stop_reason": "consensus" if correct else "impasse",
        "correct": str(correct),
        "checkpoint": "opened" if checkpoint else "none",
        "rollbacks": str(rollbacks),
        "total_tokens": "100",
        "wall_time_s": "2",
    }


def test_ablation_analysis_requires_full_paired_density_manifest() -> None:
    rows = [
        row(level, item, correct=item % 2 == level % 2, checkpoint=False, rollbacks=0)
        for level in range(4)
        for item in range(5)
    ]
    result = analyze(rows, expected_per_level=5)
    assert result["total_trials"] == 20 and result["instance_count"] == 5
    assert [c["enabled_agents"] for c in result["conditions"]] == [0, 1, 2, 3]
    assert result["paired_vs_zero"][3]["metric"] == "correct_consensus"


def test_ablation_analysis_rejects_mismatched_conditions() -> None:
    rows = [
        row(level, item, correct=False, checkpoint=False, rollbacks=0)
        for level in range(4)
        for item in range(3)
    ]
    rows.pop()
    with pytest.raises(ValueError, match="expected 3 per level"):
        analyze(rows, expected_per_level=3)


def test_ablation_analysis_rejects_duplicates() -> None:
    rows = [
        row(level, item, correct=False, checkpoint=False, rollbacks=0)
        for level in range(4)
        for item in range(2)
    ]
    rows.append(rows[0])
    with pytest.raises(ValueError, match="duplicate"):
        analyze(rows, expected_per_level=2)
