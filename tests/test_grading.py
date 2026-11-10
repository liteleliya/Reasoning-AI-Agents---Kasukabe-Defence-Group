"""Roadmap section 07: blinded grading export, the rubric rule and the rejoin to trial rows."""

import csv
import json
from pathlib import Path

import pytest

from bench.cases import load_cases
from bench.grading import (
    DIMENSIONS,
    PASS_AT,
    ScoreError,
    double_score_subset,
    export_for_grading,
    read_scores,
    reconcile,
    rejoin,
    rubric_result,
    write_sheet,
)
from bench.mscore import Instance
from blackboard import EventStore
from protocol import EventDraft, Tag

BOOK = load_cases()
P1 = BOOK.instance("restore-p1")
GOOD = "B; downtime=2 min; data_loss=30 s; lag_check=before"


def session(store: EventStore, sid: str, prediction: str, explanation: str) -> None:
    for author in ("agent_a", "agent_b"):
        store.append_sync(
            EventDraft(
                session_id=sid,
                author=author,
                tag=Tag.INIT,
                prediction=prediction,
                explanation=explanation,
            )
        )


def row(n: int, instance: Instance, answer: str, config: str = "job-cf2") -> dict:
    return {
        "trial_key": f"{config}|authored|{instance.id}|{n}",
        "session_id": f"{config}|authored|{instance.id}|{n}",
        "config": config,
        "benchmark": "authored",
        "instance_id": instance.id,
        "seed": str(n),
        "answer": answer,
        "correct": "True",
        "stop_reason": "consensus",
    }


@pytest.fixture
def exported():
    store = EventStore()
    rows = []
    for n, (answer, why) in enumerate(
        [
            (GOOD, "E1 and E2: 2 min is under the 4 min limit, 30 s under 60 s; check lag first."),
            (GOOD, "It is the faster plan."),
            ("A; downtime=6 min; data_loss=0 s; lag_check=none", "E1 loses nothing."),
        ]
    ):
        r = row(n, P1, answer)
        session(store, r["session_id"], answer, why)
        rows.append(r)
    sheet, private = export_for_grading(rows, store, {P1.id: P1}, seed=3)
    return rows, sheet, private


def test_sheet_shows_the_public_prompt_the_answer_and_its_explanation(exported) -> None:
    _, sheet, _ = exported
    assert len(sheet) == 3
    first = next(s for s in sheet if "check lag first" in s["explanation"])
    assert "How should service be restored" in first["prompt"]
    assert "[E1] Plan A needs six minutes" in first["prompt"]
    assert first["answer"] == GOOD
    assert len({s["grading_id"] for s in sheet}) == 3
    assert all(s["grading_id"].startswith("g-") for s in sheet)
    assert all(not s[d] for s in sheet for d in DIMENSIONS)  # blank for the grader


def test_sheet_is_blind_to_condition_session_and_the_automatic_verdict(exported) -> None:
    rows, sheet, private = exported
    text = json.dumps(sheet)
    for r in rows:
        assert r["config"] not in text and r["session_id"] not in text
    assert "consensus" not in text and "cf2" not in text
    assert "rubric" not in text.lower() and "acceptable" not in text.lower()
    assert set(private) == {s["grading_id"] for s in sheet}


def test_private_map_ties_each_id_to_its_trial_with_the_automatic_checks(exported) -> None:
    rows, _, private = exported
    by_key = {p["trial_key"]: p for p in private.values()}
    assert set(by_key) == {r["trial_key"] for r in rows}
    good, evidence_free, fatal = (by_key[r["trial_key"]] for r in rows)
    assert good["auto"]["decision_ok"] and not good["auto"]["violations"]
    assert good["auto"]["missing_evidence"] == []
    assert evidence_free["auto"]["missing_evidence"] == ["E1", "E2"]  # cites nothing
    assert fatal["auto"]["violations"] == ["chose_a", "assumed_zero_loss"]
    assert not fatal["auto"]["decision_ok"]


def test_export_is_reproducible_for_a_seed_and_differs_for_another(exported) -> None:
    rows, sheet, _ = exported
    store = EventStore()
    for r in rows:
        session(store, r["session_id"], r["answer"], "x")
    again, _ = export_for_grading(rows, store, {P1.id: P1}, seed=3)
    assert [s["grading_id"] for s in again] == [s["grading_id"] for s in sheet]
    other, _ = export_for_grading(rows, store, {P1.id: P1}, seed=4)
    assert [s["grading_id"] for s in other] != [s["grading_id"] for s in sheet]


def test_rows_without_an_answer_are_left_out(exported) -> None:
    rows, _, _ = exported
    store = EventStore()
    for r in rows:
        session(store, r["session_id"], r["answer"], "x")
    empty = {**rows[0], "answer": ""}
    sheet, private = export_for_grading([empty], store, {P1.id: P1}, seed=0)
    assert sheet == [] and private == {}


def score(grading_id, c, e, k, j, critical=False, grader="p1") -> dict:
    return {
        "grading_id": grading_id,
        "grader": grader,
        "conclusion": c,
        "evidence": e,
        "constraints": k,
        "justification": j,
        "critical": critical,
    }


def test_pass_needs_six_of_eight_and_no_critical_violation() -> None:
    assert PASS_AT == 6
    assert rubric_result(score("g", 2, 2, 1, 1))["passed"]
    assert not rubric_result(score("g", 2, 1, 1, 1))["passed"]  # 5 of 8
    result = rubric_result(score("g", 2, 2, 2, 2, critical=True))
    assert result["total"] == 8 and not result["passed"]


def test_same_decision_with_unsupported_evidence_can_agree_yet_fail_the_rubric() -> None:
    from bench.authored import judge

    same, _ = judge(P1.case, P1.grading)
    assert same(GOOD, GOOD.replace("2 min", "120 s"))  # agreement passes
    assert not rubric_result(score("g", 2, 0, 1, 1))["passed"]  # the rubric still fails it


def test_scores_are_read_from_csv_and_checked(tmp_path: Path) -> None:
    path = tmp_path / "scores.csv"
    write_sheet(path, [score("g-1", 2, 1, 2, 0), score("g-2", 1, 1, 1, 1, critical=True)])
    read = read_scores(path)
    assert [r["conclusion"] for r in read] == [2, 1]
    assert read[1]["critical"] is True and read[0]["critical"] is False
    bad = tmp_path / "bad.csv"
    write_sheet(bad, [score("g-1", 3, 1, 2, 0)])
    with pytest.raises(ScoreError, match="conclusion"):
        read_scores(bad)
    blank = tmp_path / "blank.csv"
    write_sheet(blank, [score("g-1", "", 1, 2, 0)])
    with pytest.raises(ScoreError, match="g-1"):
        read_scores(blank)


def test_double_scoring_lists_what_to_reconcile() -> None:
    a = [score("g-1", 2, 2, 2, 2), score("g-2", 1, 1, 1, 1), score("g-3", 0, 0, 0, 0)]
    b = [score("g-1", 2, 2, 2, 2, grader="p2"), score("g-2", 2, 1, 1, 1, grader="p2")]
    out = reconcile(a, b)
    assert out["both"] == 2 and out["exact"] == 1
    assert out["disagreements"] == [{"grading_id": "g-2", "dimensions": ["conclusion"]}]
    assert out["pass_agreement"] == 1.0  # 5 vs 4 of 8: both fail
    assert out["dimension_agreement"]["conclusion"] == 0.5


def test_the_double_scored_subset_is_balanced_over_case_types() -> None:
    private = {
        f"g-{i}": {"benchmark": kind, "instance_id": f"{kind}{i}"}
        for i, kind in enumerate(["authored"] * 6 + ["mscore"] * 6)
    }
    picked = double_score_subset(private, k=4, seed=1)
    kinds = [private[g]["benchmark"] for g in picked]
    assert len(picked) == 4 and kinds.count("authored") == kinds.count("mscore") == 2
    assert picked == double_score_subset(private, k=4, seed=1)


def test_scores_rejoin_the_trial_rows_through_the_private_map(exported) -> None:
    rows, _, private = exported
    ids = {p["trial_key"]: g for g, p in private.items()}
    scores = [
        score(ids[rows[0]["trial_key"]], 2, 2, 2, 1),
        score(ids[rows[2]["trial_key"]], 0, 0, 0, 0),
    ]
    joined = rejoin(rows, private, scores)
    assert [r["rubric_total"] for r in joined] == [7, "", 0]
    assert [r["rubric_pass"] for r in joined] == [True, "", False]
    assert joined[0]["correct"] == rows[0]["correct"]  # the automatic verdict stays alongside


def test_rejoin_refuses_unknown_ids_and_unreconciled_duplicates(exported) -> None:
    rows, _, private = exported
    gid = next(iter(private))
    with pytest.raises(ScoreError, match="unknown"):
        rejoin(rows, private, [score("g-nope", 1, 1, 1, 1)])
    with pytest.raises(ScoreError, match="reconcile"):
        rejoin(rows, private, [score(gid, 1, 1, 1, 1), score(gid, 2, 2, 2, 2, grader="p2")])


def test_csv_round_trip_keeps_non_ascii_text(tmp_path: Path) -> None:
    path = tmp_path / "s.csv"
    write_sheet(path, [{"grading_id": "g-1", "prompt": "为什么?", "answer": "是"}])
    with path.open(encoding="utf-8", newline="") as f:
        assert next(csv.DictReader(f))["prompt"] == "为什么?"


def test_command_line_export_then_rejoin_round_trip(tmp_path: Path) -> None:
    import asyncio

    from bench.grading import main
    from bench.metrics import read_metrics
    from bench.run import JobConfig, mock_client, run_job
    from scheduler import FollowerAgent, StubbornAgent

    config = tmp_path / "job.json"
    config.write_text(
        json.dumps(
            {
                "name": "gj",
                "sample": {},
                "cases": {"split": "dev", "kinds": ["authored"], "ids": ["restore-p1"]},
                "seeds": [0, 1],
            }
        )
    )
    run = tmp_path / "run"
    asyncio.run(
        run_job(
            JobConfig.load(config),
            run,
            client=mock_client(),
            make_agents=lambda *_: [
                StubbornAgent("agent_a", GOOD),
                FollowerAgent("agent_b", "A; downtime=6 min; data_loss=0 s; lag_check=none"),
                FollowerAgent("agent_c", GOOD),
            ],
            log=lambda _: None,
        )
    )
    out = tmp_path / "grading"
    main(["export", str(config), "--run", str(run), "--out", str(out), "--double", "1"])
    with (out / "sheet.csv").open(encoding="utf-8", newline="") as f:
        sheet = list(csv.DictReader(f))
    assert len(sheet) == 2 and "trial_key" not in sheet[0]
    with (out / "sheet_double.csv").open(encoding="utf-8", newline="") as f:
        assert len(list(csv.DictReader(f))) == 1
    for s in sheet:
        s.update(conclusion=2, evidence=2, constraints=2, justification=1, grader="p1")
    write_sheet(tmp_path / "scores.csv", sheet)
    joined = tmp_path / "joined.csv"
    main(
        [
            *("rejoin", "--run", str(run), "--private", str(out / "private.json")),
            *("--scores", str(tmp_path / "scores.csv"), "--out", str(joined)),
        ]
    )
    rows = read_metrics(joined)
    assert [r["rubric_total"] for r in rows] == ["7", "7"]
    assert {r["rubric_pass"] for r in rows} == {"True"}
