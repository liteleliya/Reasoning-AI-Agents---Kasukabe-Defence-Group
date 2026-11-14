"""Screening a setup for real disagreement: prefix-only runs, never touching held-out items."""

import asyncio
import csv
import json
from pathlib import Path

import pytest

from agents.llm_client import MockClient
from bench.mscore import Instance
from bench.paired import Roster
from bench.run import JobConfig
from bench.screen import heldout_ids, screen
from counterfactual.fixture import QUESTION, agents


def inst(i: str) -> Instance:
    return Instance(i, "ops", "open_qa", "simple", "", QUESTION, "Y")


JOB = JobConfig(name="scr", sample={}, seeds=(0, 1), scheduler={"impasse_window": 3})


def roster(trial, client, job) -> Roster:
    return Roster(agents(enabled=("A",)), {}, lambda: [])


def go(out: Path, items, **kw) -> list[dict]:
    return asyncio.run(
        screen(
            JOB,
            out,
            client=MockClient(model="mock"),
            roster=roster,
            instances=items,
            log=lambda _: None,
            **kw,
        )
    )


def test_each_prefix_row_says_how_much_the_agents_disagreed_and_how_it_ended(tmp_path) -> None:
    rows = go(tmp_path, [inst("toy#0")])
    assert len(rows) == 2
    r = rows[0]
    assert r["init_groups"] == 2  # A says X, B and C say Y
    assert r["init_distance"] == pytest.approx(1 / 3)
    assert r["stop_reason"] == "impasse" and r["checkpoint"] == "opened"
    assert r["challenged_replies"] >= 1 and r["messages"] == 9


def test_rows_are_saved_and_a_rerun_skips_finished_units(tmp_path) -> None:
    go(tmp_path, [inst("toy#0")])
    saved = list(csv.DictReader((tmp_path / "screen.csv").open()))
    assert len(saved) == 2
    assert go(tmp_path, [inst("toy#0")]) == []
    assert len(list(csv.DictReader((tmp_path / "screen.csv").open()))) == 2


def test_heldout_items_are_never_screened(tmp_path) -> None:
    held = sorted(heldout_ids())
    assert "case:rollback-release" in held and len(held) == 24
    rows = go(tmp_path, [inst("case:rollback-release"), inst("toy#0")])
    assert {r["instance_id"] for r in rows} == {"toy#0"}


def test_a_summary_reports_the_three_rates(tmp_path) -> None:
    from bench.screen import summarize

    summary = summarize(go(tmp_path, [inst("toy#0")]))
    assert summary == {
        "prefixes": 2,
        "initial_disagreement": 1.0,
        "consensus": 0.0,
        "checkpoint_opened": 1.0,
    }
    assert json.dumps(summary)
