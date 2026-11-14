"""Roadmap section 09: verification, outcome table, recovery funnel and the paired comparison."""

import csv
import json
from pathlib import Path

import pytest

from bench.metrics import COLUMNS
from bench.paired_analysis import (
    analyse,
    compare_arms,
    funnel,
    outcome_table,
    verify,
)

ARMS = ("standard", "forward", "replay")


def row(
    case,
    seed,
    arm,
    *,
    opened=True,
    stop="consensus",
    correct=True,
    outcome="",
    credit="",
    tokens=1000,
    prefix=400,
    calls=1,
    wall=2.0,
    rubric="",
) -> dict:
    return {
        "trial_key": f"j-{arm}|mscore|{case}|{seed}",
        "session_id": f"j-{arm}|mscore|{case}|{seed}",
        "instance_id": case,
        "seed": str(seed),
        "arm": arm,
        "checkpoint": "opened" if opened else "none",
        "skip_reason": "" if opened else "no_full_window",
        "stop_reason": stop,
        "correct": str(correct),
        "rubric_pass": rubric,
        "recovery_outcome": outcome,
        "credit_delta": credit,
        "total_tokens": str(tokens),
        "tokens_in": str(tokens - 100),
        "tokens_out": "100",
        "prefix_tokens": str(prefix),
        "intervention_calls": str(calls),
        "intervention_tokens": str(tokens - prefix),
        "wall_time_s": str(wall),
    }


def case_rows(case, seed, *, standard="fail", forward="fail", replay="win", opened=True):
    """Each arm either recovers (a correct consensus) or does not."""

    def arm_row(arm, result):
        ok = result == "win"
        extra = {}
        if arm == "replay" and opened:
            extra = {
                "outcome": "reply_accepted" if ok else "not_helpful",
                "credit": "-0.3333" if ok else "0.0",
                "tokens": 3000,
                "calls": 5,
            }
        elif opened:
            extra = {"outcome": "reply_accepted"}
        return row(
            case,
            seed,
            arm,
            opened=opened,
            stop="consensus" if ok else "impasse",
            correct=ok,
            **extra,
        )

    return [arm_row("standard", standard), arm_row("forward", forward), arm_row("replay", replay)]


def sample_rows():
    rows = []
    for c in range(8):
        rows += case_rows(f"q{c}", 0, replay="win", forward="win" if c < 2 else "fail")
        rows += case_rows(f"q{c}", 1, replay="win" if c < 6 else "fail")
    rows += case_rows("q8", 0, opened=False, standard="win", forward="win", replay="win")
    return rows


def test_verify_counts_rows_duplicates_and_unpaired_units() -> None:
    rows = sample_rows()
    report = verify(rows)
    assert report["rows"] == len(rows) == 51 and report["duplicates"] == []
    assert report["unpaired"] == []
    broken = [*rows, rows[0], *case_rows("lone", 0)[:2]]
    report = verify(broken)
    assert report["duplicates"] == [rows[0]["trial_key"]]
    assert report["unpaired"] == [{"case": "lone", "seed": "0", "missing": ["replay"]}]


def test_verify_compares_posted_with_full_trial_tokens_and_counts_missing_grades() -> None:
    rows = sample_rows()
    report = verify(rows)
    assert report["tokens_posted"] == sum(int(r["tokens_in"]) + int(r["tokens_out"]) for r in rows)
    assert report["tokens_full"] == sum(int(r["total_tokens"]) for r in rows)
    assert report["grades"] == {"rubric": 0, "automatic": 51, "missing": 0}
    rows[0]["rubric_pass"] = "True"
    rows[1]["correct"] = ""
    assert verify(rows)["grades"] == {"rubric": 1, "automatic": 49, "missing": 1}


def test_outcome_table_uses_the_same_eligible_denominator_in_every_arm() -> None:
    table = {r["arm"]: r for r in outcome_table(sample_rows())}
    assert {a: table[a]["trials"] for a in ARMS} == dict.fromkeys(ARMS, 17)
    assert {a: table[a]["eligible"] for a in ARMS} == dict.fromkeys(ARMS, 16)
    assert table["replay"]["correct_recovery"] == 14
    assert table["forward"]["correct_recovery"] == 2
    assert table["standard"]["correct_recovery"] == 0
    assert table["replay"]["consensus"] == 15 and table["replay"]["wrong_consensus"] == 0
    assert table["replay"]["median_cost"] == 3000 and table["forward"]["median_cost"] == 1000


def test_a_wrong_consensus_is_kept_apart_from_a_correct_one() -> None:
    rows = case_rows("q0", 0, replay="win")
    rows[2] = row("q0", 0, "replay", stop="consensus", correct=False, outcome="reply_accepted")
    replay = next(r for r in outcome_table(rows) if r["arm"] == "replay")
    assert (replay["consensus"], replay["correct_consensus"], replay["wrong_consensus"]) == (
        1,
        0,
        1,
    )
    assert replay["correct_recovery"] == 0


def test_funnel_counts_each_stage_on_its_own() -> None:
    rows = sample_rows()
    steps = {s["stage"]: s["count"] for s in funnel(rows, "replay")}
    assert steps == {
        "eligible": 16,
        "attempted": 16,
        "completed": 16,
        "helpful": 14,
        "adopted": 14,
        "correct_recovery": 14,
    }
    declined = [r for r in rows if r["arm"] == "replay" and r["recovery_outcome"] == "not_helpful"]
    assert len(declined) == 2
    reasons = funnel(rows, "replay", reasons=True)
    assert reasons["outcomes"] == {"reply_accepted": 14, "not_helpful": 2}
    assert reasons["skipped"] == {"no_full_window": 1}


def test_helpful_adopted_and_correct_are_not_assumed_from_each_other() -> None:
    helped = row(
        "q", 0, "replay", outcome="stale_target", credit="-0.3333", stop="impasse", correct=False
    )
    steps = {s["stage"]: s["count"] for s in funnel([helped], "replay")}
    assert steps["helpful"] == 1 and steps["adopted"] == 0 and steps["correct_recovery"] == 0


def test_paired_comparison_counts_wins_losses_and_ties_on_shared_eligible_cases() -> None:
    out = compare_arms(sample_rows(), "replay", "forward", reps=500)
    assert out["pairs"] == 16
    assert (out["wins"], out["losses"], out["ties"]) == (12, 0, 4)
    assert out["rate_difference"] == pytest.approx((14 - 2) / 16)
    lo, hi = out["ci"]
    assert lo <= out["rate_difference"] <= hi and lo > 0
    assert out["small"] is False


def test_the_bootstrap_resamples_cases_with_their_seeds_together() -> None:
    rows = case_rows("a", 0, replay="win") + case_rows("a", 1, replay="win")
    rows += case_rows("b", 0, replay="fail") + case_rows("b", 1, replay="fail")
    out = compare_arms(rows, "replay", "forward", reps=300)
    assert out["cases"] == 2 and out["pairs"] == 4
    assert out["rate_difference"] == pytest.approx(0.5)
    lo, hi = out["ci"]  # a single case is drawn with both of its seeds, so only 0, .5 or 1 occur
    assert {round(lo, 6), round(hi, 6)} <= {0.0, 0.5, 1.0}


def test_a_small_eligible_subset_is_flagged_and_keeps_raw_counts() -> None:
    out = compare_arms(case_rows("q0", 0) + case_rows("q1", 0), "replay", "forward", reps=50)
    assert out["small"] is True and (out["wins"], out["pairs"]) == (2, 2)


def test_unpaired_or_ineligible_units_are_left_out_of_the_comparison() -> None:
    rows = [*case_rows("q0", 0), *case_rows("q1", 0, opened=False), *case_rows("q2", 0)[:2]]
    assert compare_arms(rows, "replay", "forward", reps=20)["pairs"] == 1


def test_token_differences_use_the_same_pairs_and_split_out_the_intervention() -> None:
    out = compare_arms(sample_rows(), "replay", "forward", reps=200)
    tokens = out["differences"]
    assert tokens["total_tokens"]["mean"] == pytest.approx(2000)
    assert tokens["intervention_tokens"]["mean"] == pytest.approx(2000)
    assert tokens["wall_time_s"]["mean"] == pytest.approx(0.0)
    assert len(tokens["total_tokens"]["ci"]) == 2


def test_rubric_grades_win_over_the_automatic_verdict() -> None:
    rows = case_rows("q0", 0, replay="win")
    rows[2]["rubric_pass"] = "False"
    replay = next(r for r in outcome_table(rows) if r["arm"] == "replay")
    assert replay["correct_consensus"] == 0 and replay["correct_recovery"] == 0


def test_analyse_writes_tables_figures_and_the_input_manifest(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    with (run / "metrics.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in sample_rows():
            w.writerow({k: r.get(k, "") for k in COLUMNS})
    out = tmp_path / "out"
    analyse(run, out, reps=100)
    report = json.loads((out / "analysis.json").read_text())
    assert report["verification"]["rows"] == 51
    assert report["comparisons"]["replay_vs_forward"]["wins"] == 12
    assert (out / "outcome_table.csv").read_text().startswith("arm,")
    for name in ("outcomes.png", "funnel.png", "paired.png"):
        assert (out / name).stat().st_size > 1000
    manifest = json.loads((out / "inputs.json").read_text())
    assert manifest["files"]["metrics.csv"]["rows"] == 51
    assert len(manifest["files"]["metrics.csv"]["sha256"]) == 64
    assert report["trace_examples"]["successful_recovery"]
    assert report["trace_examples"]["declined_branch"]
