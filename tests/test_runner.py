"""D4: resumable runner, end to end on the scripted mock model (no GPU, no network)."""

import argparse
import asyncio
import json
from pathlib import Path

import pytest

from agents.ledger import load_ledger
from bench.cases import load_cases
from bench.metrics import read_metrics
from bench.mscore import Instance
from bench.run import (
    JobConfig,
    build_trials,
    final_answer,
    job_instances,
    judging,
    mock_client,
    parse_shard,
    run_job,
    shard_of,
)
from blackboard import EventStore
from scheduler import FollowerAgent, StubbornAgent


def inst(i: int, ref: str = "B") -> Instance:
    return Instance(
        id=f"Data2/Law/Single-choice/simple#{i}",
        domain="law",
        format="single_choice",
        difficulty="simple",
        stage="",
        question=f"问题 {i}?",
        reference=ref,
        options=(("A", "a"), ("B", "b"), ("C", "c"), ("D", "d")),
    )


JOB = JobConfig(name="tjob", sample={}, seeds=(0, 1), n_counterfactual=(0, 3))
INSTANCES = [inst(i) for i in range(3)]


def go(out: Path, **kw) -> list[dict]:
    kw.setdefault("client", mock_client())
    return asyncio.run(run_job(JOB, out, instances=INSTANCES, log=lambda _: None, **kw))


def test_trials_and_shards() -> None:
    trials = build_trials(JOB, INSTANCES, "m")
    assert len(trials) == 2 * 2 * 3
    keys = [t.meta.key for t in trials]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)
    parts = [shard_of(trials, (i, 3)) for i in (1, 2, 3)]
    assert sorted(t.meta.key for p in parts for t in p) == keys
    assert {t.meta.config for t in trials} == {"tjob-cf0", "tjob-cf3"}
    with pytest.raises(argparse.ArgumentTypeError):
        parse_shard("0/2")
    assert parse_shard("2/4") == (2, 4)


def test_run_writes_rows_board_and_provenance(tmp_path: Path) -> None:
    rows = go(tmp_path, parallel=4)
    assert len(rows) == 12
    saved = read_metrics(tmp_path / "metrics.csv")
    assert len(saved) == 12
    assert {r["stop_reason"] for r in saved} <= {"consensus", "impasse", "cap"}
    assert all(r["answer"] and r["answer"] in "ABCD" for r in saved)
    assert {r["n_counterfactual"] for r in saved} == {"0", "3"}
    store = EventStore(tmp_path / "board.sqlite")
    assert len(store.sessions()) == 12
    info = json.loads((tmp_path / "run.json").read_text())
    run = info["runs"][0]
    assert run["shard"] == "1/1" and run["sessions_run"] == 12 and run["model"] == "mock"
    assert len(run["commit"]) == 40


def test_resume_skips_finished_trials_and_partial_sessions(tmp_path: Path) -> None:
    assert len(go(tmp_path, limit=5)) == 5
    # a crash mid-session leaves a partial session behind for the next trial
    trials = build_trials(JOB, INSTANCES, "mock")
    store = EventStore(tmp_path / "board.sqlite")
    from protocol import EventDraft, Tag

    store.append_sync(
        EventDraft(
            session_id=trials[5].meta.key,
            author="agent_a",
            tag=Tag.INIT,
            prediction="A",
            explanation="half-finished",
        )
    )
    store.close()
    assert len(go(tmp_path)) == 7
    saved = read_metrics(tmp_path / "metrics.csv")
    assert len({r["trial_key"] for r in saved}) == len(saved) == 12
    assert any(r["session_id"].endswith("~r1") for r in saved)
    assert go(tmp_path) == []  # nothing left
    assert len(json.loads((tmp_path / "run.json").read_text())["runs"]) == 3


def test_same_trial_gives_same_transcript(tmp_path: Path) -> None:
    go(tmp_path / "a", limit=2)
    go(tmp_path / "b", limit=2)

    def transcript(d):
        s = EventStore(d / "board.sqlite")
        return [[(e.author, e.tag, e.prediction) for e in s.events(sid)] for sid in s.sessions()]

    assert transcript(tmp_path / "a") == transcript(tmp_path / "b")


def test_judging_and_final_answer() -> None:
    same, correct = judging("single_choice")
    assert same("答案是 B。", "B") and not same("B", "C")
    assert correct("选 B", "B")
    assert final_answer({"a": "B", "b": "C", "c": "答案 B"}, same) == "B"
    assert final_answer({}, same) == ""


def test_run_writes_the_call_ledger_and_reconciled_token_columns(tmp_path: Path) -> None:
    go(tmp_path, parallel=4)
    ledger = load_ledger(tmp_path / "calls.jsonl")
    saved = read_metrics(tmp_path / "metrics.csv")
    assert len(ledger) == sum(int(r["ledger_calls"]) for r in saved) > 0
    assert {r.trial for r in ledger} == {r["trial_key"] for r in saved}
    for r in saved:
        total = int(r["ledger_tokens_in"]) + int(r["ledger_tokens_out"])
        assert int(r["total_tokens"]) == total
        legacy = int(r["tokens_in"]) + int(r["tokens_out"]) + int(r["unposted_tokens"])
        assert total >= legacy  # drafts the store refused are in the ledger but not the old sum
        assert r["stop_detail"] and int(r["decision_seq"]) >= 0


def test_a_wrong_consensus_keeps_both_the_agreement_and_the_verdict(tmp_path: Path) -> None:
    def wrong_but_agreed(trial, client, job, store):
        return [
            StubbornAgent("agent_a", "A"),
            FollowerAgent("agent_b", "C"),
            FollowerAgent("agent_c", "D"),
        ]

    job = JobConfig(name="wrong", sample={}, n_counterfactual=(0,))
    rows = asyncio.run(
        run_job(
            job,
            tmp_path,
            instances=[inst(0, ref="B")],
            client=mock_client(),
            make_agents=wrong_but_agreed,
            log=lambda _: None,
        )
    )
    (row,) = rows
    assert row["stop_reason"] == "consensus" and row["converged"] is True
    assert row["answer"] == "A" and row["correct"] is False
    assert row["ledger_calls"] == 0  # these agents never called the model


def authored_job(**cases) -> JobConfig:
    return JobConfig(name="authored", sample={}, cases={"kinds": ["authored"], **cases})


def test_authored_agreement_runs_through_the_scheduler_and_the_verdict_is_separate(
    tmp_path: Path,
) -> None:
    two_min = "B; downtime=2 min; data_loss=30 s; lag_check=before"
    in_seconds = "B; downtime=120 s; data_loss=30 s; lag_check=before"

    def agents(trial, client, job, store):
        return [
            StubbornAgent("agent_a", two_min),
            FollowerAgent("agent_b", in_seconds),
            FollowerAgent("agent_c", "A; downtime=6 min; data_loss=0 s; lag_check=none"),
        ]

    job = authored_job(split="dev", ids=["restore-p1"])
    rows = asyncio.run(
        run_job(job, tmp_path, client=mock_client(), make_agents=agents, log=lambda _: None)
    )
    (row,) = rows
    assert row["stop_reason"] == "consensus" and row["converged"] is True
    assert row["answer"] == two_min and row["correct"] is True
    saved = read_metrics(tmp_path / "metrics.csv")
    assert saved[0]["benchmark"] == "authored" and saved[0]["instance_id"] == "case:restore-p1"


def test_case_instances_come_from_the_job_without_a_sample() -> None:
    dev = job_instances(authored_job(split="dev"))
    assert sorted(i.id for i in dev) == [
        "case:patch-window",
        "case:refund-window",
        "case:restore-p1",
        "case:restore-p1-unbounded",
    ]
    held = job_instances(authored_job(split="heldout"))
    assert len(held) == 8 and {i.format for i in held} == {"authored"}
    assert [i.id for i in job_instances(authored_job(split="dev", ids=["restore-p1"]))] == [
        "case:restore-p1"
    ]


def test_run_json_records_the_manifest_version(tmp_path: Path) -> None:
    job = authored_job(split="dev", ids=["restore-p1"])
    asyncio.run(
        run_job(
            job,
            tmp_path,
            client=mock_client(),
            make_agents=lambda *_: [StubbornAgent(f"agent_{c}", "A") for c in "abc"],
            log=lambda _: None,
        )
    )
    run = json.loads((tmp_path / "run.json").read_text())["runs"][0]
    assert run["cases"]["version"] == load_cases().version
    assert run["cases"]["split"] == "dev"


def test_unknown_case_id_in_a_job_is_an_error() -> None:
    with pytest.raises(ValueError, match="no-such-case"):
        job_instances(authored_job(split="dev", ids=["no-such-case"]))


def test_rows_label_how_agreement_was_decided(tmp_path: Path) -> None:
    from bench.run import agreement_basis

    assert agreement_basis("single_choice") == "exact"
    assert agreement_basis("judgment") == "exact"
    assert agreement_basis("authored") == "key"
    assert agreement_basis("open_qa") == "approximate"  # lexical overlap, not a verified key
    rows = go(tmp_path, limit=1)
    assert rows[0]["agreement_basis"] == "exact"


def test_a_copied_reference_with_a_flipped_conclusion_fails_despite_overlap() -> None:
    from bench.cases import load_cases
    from bench.correctness import rouge_l_f1

    book = load_cases()
    instance = book.instance("restore-p1")
    _, correct = judging("authored", instance)
    copied = "A; downtime=2 min; data_loss=30 s; lag_check=before"
    right = "B; downtime=2 min; data_loss=30 s; lag_check=before"
    assert rouge_l_f1(copied, right) > 0.8
    assert correct(right, "B") and not correct(copied, "B")
