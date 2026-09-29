"""D3: per-trial metrics rows and resumable CSV."""

import asyncio
from pathlib import Path

import pytest

from bench.metrics import COLUMNS, MetricsWriter, TrialMeta, read_metrics, trial_row
from blackboard import EventStore
from protocol import EventDraft, Kind, Tag
from scheduler import FollowerAgent, Scheduler, StubbornAgent

META = TrialMeta(
    config="cf-0",
    benchmark="toy",
    instance_id="q1",
    seed=7,
    n_agents=3,
    n_counterfactual=1,
    domain="math",
    model="mock",
)


def consensus_state():
    store = EventStore()
    agents = [StubbornAgent("a", "x"), FollowerAgent("b", "y"), FollowerAgent("c", "z")]
    asyncio.run(Scheduler(store, agents).run("s", "q"))
    return store


def test_row_for_consensus_session() -> None:
    row = trial_row(consensus_state().state("s"), META, correct=True, wall_time_s=1.23456)
    assert tuple(row) == COLUMNS
    assert row["trial_key"] == "cf-0|toy|q1|7"
    assert row["converged"] is True and row["stop_reason"] == "consensus"
    assert (row["messages"], row["refute"], row["revise"]) == (6, 1, 2)
    assert row["cycles"] == 1.0
    assert row["intelligibility"] == "failed"  # a REFUTEs c and never ratifies
    assert row["cf_share"] == 0.3333
    assert row["wall_time_s"] == 1.235


def test_rollback_tokens_are_in_total() -> None:
    store = EventStore()
    for name in ("a", "b"):
        store.append_sync(
            EventDraft(
                session_id="s",
                author=name,
                tag=Tag.INIT,
                prediction=name,
                explanation="e",
                tokens={"in": 10, "out": 1},
            )
        )
    store.append_sync(
        EventDraft(
            session_id="s", author="a", kind=Kind.ROLLBACK_START, reply_to=0, counterfactual=True
        )
    )
    store.append_sync(
        EventDraft(
            session_id="s",
            author="b",
            kind=Kind.ROLLBACK_STEP,
            tag=Tag.RATIFY,
            counterfactual=True,
            tokens={"in": 5, "out": 2},
        )
    )
    store.append_sync(
        EventDraft(session_id="s", author="a", kind=Kind.ROLLBACK_END, counterfactual=True)
    )
    row = trial_row(store.state("s"), META)
    assert row["rollbacks"] == 1
    assert (row["total_tokens"], row["rollback_tokens_in"], row["rollback_tokens_out"]) == (
        29,
        5,
        2,
    )
    assert row["correct"] == "" and row["intelligibility"] == "failed"


def test_writer_is_resumable(tmp_path: Path) -> None:
    path = tmp_path / "results" / "metrics.csv"
    state = consensus_state().state("s")
    w = MetricsWriter(path)
    w.write(trial_row(state, META))
    assert MetricsWriter(path).done() == {"cf-0|toy|q1|7"}
    # a crash mid-write leaves a partial line; it is ignored and the next run appends cleanly
    with path.open("a") as f:
        f.write("cf-0|toy|q2|7,cf-0,toy")
    rows = read_metrics(path)
    assert [r["trial_key"] for r in rows] == ["cf-0|toy|q1|7"]
    assert rows[0]["converged"] == "True"


def test_writer_refuses_mismatched_header(tmp_path: Path) -> None:
    path = tmp_path / "old.csv"
    path.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match="different columns"):
        MetricsWriter(path)
