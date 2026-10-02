"""D4: resumable runner, end to end on the scripted mock model (no GPU, no network)."""

import argparse
import asyncio
import json
from pathlib import Path

import pytest

from bench.metrics import read_metrics
from bench.mscore import Instance
from bench.run import (
    JobConfig,
    build_trials,
    final_answer,
    judging,
    mock_client,
    parse_shard,
    run_job,
    shard_of,
)
from blackboard import EventStore


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
