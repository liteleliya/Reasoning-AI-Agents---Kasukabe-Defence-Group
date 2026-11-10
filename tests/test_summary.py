"""The results view shows numbers computed here; the UI never decides what counts."""

import csv
from pathlib import Path

import pytest

from bench.summary import summarize_run

J3 = Path("results/runs/j3_prelim_hot/shard-1-of-1/metrics.csv")
CASE = "Data2/Law/Single-choice/complex#{}"


def row(
    config="run-cf0", enabled="0", case=1, stop="consensus", correct="True", tokens="3000", **kw
):
    return {
        "config": config,
        "n_counterfactual": enabled,
        "n_agents": "3",
        "instance_id": CASE.format(case),
        "seed": "0",
        "model": "qwen",
        "session_id": f"{config}|mscore|{CASE.format(case)}|0",
        "stop_reason": stop,
        "correct": correct,
        "rollbacks": "0",
        "total_tokens": tokens,
        **kw,
    }


def test_counts_each_condition_apart_and_orders_them_by_enabled_agents() -> None:
    rows = [
        row("run-cf2", "2", 1, "consensus", "True", "100"),
        row("run-cf0", "0", 1, "consensus", "False", "300"),
        row("run-cf0", "0", 2, "consensus", "True", "100"),
        row("run-cf0", "0", 3, "impasse", "False", "200"),
    ]
    out = summarize_run(rows, label="J3", kind="historical")
    assert [c["condition"] for c in out["conditions"]] == ["run-cf0", "run-cf2"]
    zero = out["conditions"][0]
    assert (zero["trials"], zero["consensus"], zero["correct_consensus"]) == (3, 2, 1)
    assert (zero["wrong_consensus"], zero["median_tokens"]) == (1, 200)
    assert (zero["enabled_agents"], zero["n_agents"]) == (0, 3)
    assert out["totals"] == {
        "trials": 4,
        "consensus": 3,
        "correct_consensus": 2,
        "recorded_replays": 0,
    }
    assert out["run"]["cases"] == 3
    assert (out["run"]["label"], out["run"]["kind"], out["run"]["model"]) == (
        "J3",
        "historical",
        "qwen",
    )


def test_what_the_export_does_not_record_is_none_not_zero() -> None:
    out = summarize_run([row()])
    assert out["conditions"][0]["eligible"] is None
    stages = {s["stage"]: s["count"] for s in out["recovery"]}
    assert stages["eligible"] is None and stages["recovered"] is None
    assert stages["recorded"] == 0  # replays logged on the board is known


def test_recovery_stages_are_counted_when_the_export_has_them() -> None:
    rows = [
        row(eligible="True", replay_attempted="True", adopted="True", correct_recovery="True"),
        row(
            case=2,
            eligible="True",
            replay_attempted="True",
            adopted="False",
            correct_recovery="False",
        ),
        row(
            case=3,
            eligible="False",
            replay_attempted="False",
            adopted="False",
            correct_recovery="False",
        ),
    ]
    out = summarize_run(rows)
    stages = {s["stage"]: s["count"] for s in out["recovery"]}
    assert (stages["eligible"], stages["attempted"], stages["adopted"], stages["recovered"]) == (
        2,
        2,
        1,
        1,
    )
    assert stages["completed"] is None  # that column was not exported
    assert out["conditions"][0]["eligible"] == 2


def test_examples_point_at_sessions_and_say_why_they_were_picked() -> None:
    rows = [
        row(case=1, stop="consensus", correct="False"),
        row(case=2, stop="impasse", correct="False"),
        row(case=3, stop="consensus", correct="True"),
    ]
    examples = {e["kind"]: e for e in summarize_run(rows)["examples"]}
    assert examples["wrong_consensus"]["session_id"] == rows[0]["session_id"]
    assert examples["impasse"]["session_id"] == rows[1]["session_id"]
    assert examples["impasse"]["label"] == "Law complex #2"
    assert "recovery" not in examples  # nothing recovered


def test_an_empty_run_summarizes_to_empty() -> None:
    out = summarize_run([])
    assert out["totals"]["trials"] == 0 and out["conditions"] == [] and out["examples"] == []


@pytest.mark.skipif(not J3.exists(), reason="the J3 results are not in this checkout")
def test_j3_reports_117_of_120_consensus_93_correct_and_no_replays() -> None:
    with J3.open(newline="") as f:
        rows = list(csv.DictReader(f))
    out = summarize_run(rows, label="J3", kind="historical")
    assert out["totals"] == {
        "trials": 120,
        "consensus": 117,
        "correct_consensus": 93,
        "recorded_replays": 0,
    }
    by = {c["enabled_agents"]: c for c in out["conditions"]}
    assert sorted(by) == [0, 1, 2, 3]  # the 0/1/2/3 conditions are preserved
    assert [by[n]["consensus"] for n in range(4)] == [29, 30, 29, 29]
    assert [by[n]["correct_consensus"] for n in range(4)] == [23, 24, 23, 23]
    assert all(c["eligible"] is None for c in out["conditions"])
    assert out["run"]["model"] == "qwen2.5:7b-instruct" and out["run"]["conditions"] == 4
