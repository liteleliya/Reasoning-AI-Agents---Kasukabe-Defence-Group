"""D3: per-trial metrics rows and resumable CSV."""

import asyncio
from pathlib import Path

import pytest

from agents.ledger import CallRecord
from bench.metrics import COLUMNS, MetricsWriter, TrialMeta, read_metrics, trial_row
from blackboard import EventStore
from protocol import EventDraft, Kind, Tag
from scheduler import FollowerAgent, Scheduler, StubbornAgent
from tests.test_matched_branches import llm
from tests.test_recovery_policy import build

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


def test_without_a_ledger_the_new_columns_are_blank_and_the_total_is_unchanged() -> None:
    row = trial_row(consensus_state().state("s"), META, unposted_tokens=7)
    for column in ("ledger_calls", "ledger_tokens_in", "ledger_unposted_tokens", "grading_tokens"):
        assert row[column] == ""
    assert row["total_tokens"] == row["tokens_in"] + row["tokens_out"] + 7


def test_the_ledger_total_reconciles_with_the_board_and_unposted_calls_count_once() -> None:
    calls = []

    def flaky(messages) -> str:
        calls.append(1)
        # C's first answer in the original branch is unusable, and so is its repair
        return "garbage" if len(calls) in (3, 4) else llm(messages)

    result, store, client = build(responder=flaky)
    assert result.opportunity.replay["status"] == "incomplete"  # C never answered in one branch
    rows = client.ledger.for_trial("s")
    row = trial_row(result.state, META, ledger=rows)

    posted_ids = {i for e in store.events("s") for i in e.meta.get("call_ids", [])}
    spent = lambda rs: sum((r.prompt_tokens or 0) + (r.completion_tokens or 0) for r in rs)  # noqa: E731
    posted = [r for r in rows if r.call_id in posted_ids]
    unposted = [r for r in rows if r.call_id not in posted_ids]
    assert {r.call_id for r in unposted} == {"call-3", "call-4"}

    board = row["tokens_in"] + row["tokens_out"]
    assert board == spent(posted)  # accepted events add up to the posted subtotal
    assert row["ledger_unposted_tokens"] == spent(unposted) > 0
    assert row["total_tokens"] == board + row["ledger_unposted_tokens"]  # counted once
    assert row["total_tokens"] == row["ledger_tokens_in"] + row["ledger_tokens_out"]
    assert (row["ledger_calls"], row["ledger_missing"]) == (6, 0)


def test_calls_with_unknown_usage_are_marked_missing_and_not_summed() -> None:
    rows = [
        CallRecord("call-1", prompt_tokens=5, completion_tokens=3),
        CallRecord("call-2", status="error", usage="missing"),
        CallRecord("call-3", usage="estimated", prompt_tokens=0, completion_tokens=4),
    ]
    row = trial_row(consensus_state().state("s"), META, ledger=rows)
    assert (row["ledger_calls"], row["ledger_missing"]) == (3, 1)
    assert (row["ledger_tokens_in"], row["ledger_tokens_out"]) == (5, 7)


def test_grading_cost_stop_detail_and_decision_seq_are_kept_apart() -> None:
    plain = trial_row(consensus_state().state("s"), META, ledger=[])
    row = trial_row(
        consensus_state().state("s"),
        META,
        ledger=[],
        grading_tokens=120,
        stop_detail="debate_stall",
        decision_seq=8,
    )
    assert (row["grading_tokens"], row["stop_detail"], row["decision_seq"]) == (
        120,
        "debate_stall",
        8,
    )
    assert row["total_tokens"] == plain["total_tokens"]  # offline grading is not trial cost
