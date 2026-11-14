"""Roadmap section 08: three arms from one shared prefix, on the scripted toy case."""

import asyncio
import json
from pathlib import Path

import pytest

from agents.llm_client import MockClient
from agents.pex_agent import PEXAgent
from agents.prompts import persona_for
from bench.metrics import read_metrics
from bench.mscore import Instance
from bench.paired import Roster, run_paired
from bench.run import JobConfig
from blackboard import EventStore
from counterfactual.fixture import ALTERNATIVE, QUESTION, agents

CANDIDATE = json.dumps({"tag": "REVISE", "prediction": "Y", "explanation": ALTERNATIVE.explanation})
STUCK = json.dumps({"tag": "REFUTE", "prediction": "X", "explanation": "still X"})


def respond(messages) -> str:
    """The scripted model: replay candidates and rethought replies concede, ordinary ones do not."""
    user = messages[-1].content
    if "Write a different version" in user or "was challenged" in user:
        return CANDIDATE
    return STUCK


INSTANCE = Instance(
    id="toy#0",
    domain="ops",
    format="open_qa",
    difficulty="simple",
    stage="",
    question=QUESTION,
    reference="Y",
)
JOB = JobConfig(
    name="pj",
    sample={},
    seeds=(0, 1),
    n_agents=3,
    scheduler={"impasse_window": 3},
    arms=("standard", "forward", "replay"),
    allowance_calls=6,
)


def scripted_roster(trial, client, job) -> Roster:
    author = PEXAgent("A", persona_for(0), client, n_agents=3)
    return Roster(
        agents=agents(enabled=("A",)),
        authors={"A": author},
        make_peers=lambda: [a for a in agents() if a.name != "A"],
    )


def go(out: Path, **kw) -> list[dict]:
    client = MockClient(responder=respond, model="mock")
    return asyncio.run(
        run_paired(
            JOB,
            out,
            client=client,
            roster=scripted_roster,
            instances=[INSTANCE],
            log=lambda _: None,
            **kw,
        )
    )


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("paired")
    go(out)
    return out


def rows_of(run_dir: Path) -> list[dict]:
    return read_metrics(run_dir / "metrics.csv")


def test_one_row_per_arm_and_seed_each_joined_to_its_own_board(run_dir) -> None:
    rows = rows_of(run_dir)
    assert len(rows) == 6
    assert sorted((r["arm"], r["seed"]) for r in rows) == sorted(
        (arm, str(seed)) for arm in JOB.arms for seed in (0, 1)
    )
    store = EventStore(run_dir / "board.sqlite")
    sessions = {r["session_id"] for r in rows}
    assert len(sessions) == 6 and sessions <= set(store.sessions())
    assert all(f"-{r['arm']}|" in r["trial_key"] for r in rows)


def test_the_prefix_is_identical_in_every_arm(run_dir) -> None:
    store = EventStore(run_dir / "board.sqlite")
    rows = [r for r in rows_of(run_dir) if r["seed"] == "0"]

    def prefix(sid: str):
        return [
            (e.author, e.tag, e.reply_to, e.prediction, e.explanation)
            for e in store.events(sid)[:9]
        ]

    shapes = {prefix(r["session_id"]).__repr__() for r in rows}
    assert len(shapes) == 1
    (prefix_sid,) = [s for s in store.sessions() if "-prefix|" in s and s.endswith("|0")]
    assert prefix(prefix_sid) == prefix(rows[0]["session_id"])


def test_the_arms_differ_only_after_the_trigger(run_dir) -> None:
    by_arm = {r["arm"]: r for r in rows_of(run_dir) if r["seed"] == "0"}
    assert {a: by_arm[a]["stop_reason"] for a in by_arm} == {
        "standard": "impasse",
        "forward": "consensus",
        "replay": "consensus",
    }
    assert {a: by_arm[a]["checkpoint"] for a in by_arm} == dict.fromkeys(by_arm, "opened")
    assert by_arm["replay"]["recovery_outcome"] == "reply_accepted"
    assert float(by_arm["replay"]["credit_delta"]) == pytest.approx(-1 / 3)
    assert by_arm["standard"]["credit_delta"] == ""
    assert by_arm["replay"]["correct"] == "True"


def test_every_arm_stays_inside_the_call_allowance_and_counts_the_prefix(run_dir) -> None:
    for r in rows_of(run_dir):
        assert int(r["intervention_calls"]) <= JOB.allowance_calls
        assert int(r["total_tokens"]) >= int(r["prefix_tokens"])
    controls = [r for r in rows_of(run_dir) if r["arm"] != "replay"]
    assert {r["intervention_calls"] for r in controls} == {"1"}
    replay = next(r for r in rows_of(run_dir) if r["arm"] == "replay")
    assert int(replay["intervention_calls"]) >= 1  # the candidate; scripted peers make no calls


def test_run_files_hold_the_sidecar_ledger_and_provenance(run_dir) -> None:
    sidecar = [json.loads(x) for x in (run_dir / "opportunities.jsonl").read_text().splitlines()]
    assert {o["policy"] for o in sidecar} == {"prefix", "standard", "forward", "replay"}
    assert (run_dir / "calls.jsonl").exists()
    run = json.loads((run_dir / "run.json").read_text())["runs"][0]
    assert run["job"]["arms"] == list(JOB.arms)


def test_resume_after_one_arm_reuses_the_saved_prefix_and_skips_finished_arms(tmp_path) -> None:
    first = go(tmp_path, limit=1)
    assert [r["arm"] for r in first] == ["standard"]
    store = EventStore(tmp_path / "board.sqlite")
    prefixes = [s for s in store.sessions() if "-prefix|" in s]
    assert len(prefixes) == 1
    saved = [e.to_record() for e in store.events(prefixes[0])]
    store.close()
    prefix_calls = sum(1 for _ in (tmp_path / "calls.jsonl").read_text().splitlines())

    rest = go(tmp_path)
    assert sorted(r["arm"] for r in rest if r["seed"] == 0) == ["forward", "replay"]
    rows = rows_of(tmp_path)
    assert len(rows) == 6 and len({r["trial_key"] for r in rows}) == 6
    store = EventStore(tmp_path / "board.sqlite")
    assert [s for s in store.sessions() if "-prefix|" in s and s.endswith("|0")] == prefixes
    assert [e.to_record() for e in store.events(prefixes[0])] == saved
    assert prefix_calls > 0


def test_without_an_eligible_checkpoint_every_arm_shares_the_terminal_outcome(tmp_path) -> None:
    def agreeing(trial, client, job) -> Roster:
        from scheduler import FollowerAgent, StubbornAgent

        team = [StubbornAgent("a", "Y"), FollowerAgent("b", "Y"), FollowerAgent("c", "Y")]
        return Roster(team, {}, lambda: [])

    client = MockClient(responder=respond, model="mock")
    rows = asyncio.run(
        run_paired(
            JOB,
            tmp_path,
            client=client,
            roster=agreeing,
            instances=[INSTANCE],
            log=lambda _: None,
        )
    )
    assert len(rows) == 6
    assert {r["checkpoint"] for r in rows} == {"none"}
    assert {r["stop_reason"] for r in rows} == {"consensus"}
    assert {r["intervention_calls"] for r in rows} == {0}
    assert len({r["answer"] for r in rows}) == 1


def test_the_primary_experiment_is_serial() -> None:
    client = MockClient(responder=respond, model="mock")
    with pytest.raises(ValueError, match="serial"):
        asyncio.run(
            run_paired(
                JOB,
                Path("unused"),
                client=client,
                roster=scripted_roster,
                instances=[INSTANCE],
                parallel=2,
                log=lambda _: None,
            )
        )


def test_a_job_with_arms_runs_through_the_command_line_on_the_mock_model(tmp_path) -> None:
    from bench.run import main

    config = tmp_path / "job.json"
    config.write_text(
        json.dumps(
            {
                "name": "cli",
                "sample": {},
                "cases": {"split": "dev", "kinds": ["authored"], "ids": ["restore-p1"]},
                "arms": ["standard", "replay"],
                "scheduler": {"impasse_window": 3},
            }
        )
    )
    main([str(config), "--mock", "--out", str(tmp_path / "out"), "--limit", "3"])
    rows = read_metrics(tmp_path / "out" / "shard-1-of-1" / "metrics.csv")
    assert [r["arm"] for r in rows] == ["standard", "replay"]
    assert all(r["checkpoint"] in ("opened", "none") for r in rows)


def test_a_job_can_pin_the_persona_set_and_the_model() -> None:
    from bench.paired import model_roster
    from bench.run import Trial, TrialMeta, job_client_args

    job = JobConfig(name="p", sample={}, persona_set="divergent", model="qwen2.5:3b-instruct")
    assert job_client_args(job) == {"model": "qwen2.5:3b-instruct"}
    assert job_client_args(JobConfig(name="p", sample={})) == {}
    meta = TrialMeta("p-prefix", "mscore", "x#0", 0, 3, 3)
    team = model_roster(Trial(meta, INSTANCE), MockClient(), job).agents
    assert [a.persona.name for a in team] == ["contrarian", "risk_averse", "first_principles"]
