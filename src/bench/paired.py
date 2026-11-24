"""The three-arm paired runner (roadmap section 08).

For each (item, seed) the question is first played to the recovery checkpoint once, with no
intervention: that session is the shared prefix and is saved as it is. Each arm then gets its own
session holding a copy of the prefix (same sequence numbers) and the scheduler's turn loop
continues it under that arm's policy. If the prefix never reached an eligible checkpoint, every arm
shares its ordinary terminal outcome and nothing is spent on interventions. Everything is serial:
agents are asked one at a time and one arm runs at a time.

    uv run python -m bench.run configs/<job>.json --mock    (a job with "arms" runs this way)
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.ledger import CallLedger, call_budget, call_scope
from agents.llm_client import BaseLLMClient, make_client
from agents.pex_agent import PEXAgent
from agents.prompts import persona_for
from bench.arms import ARMS, ControlRecovery
from bench.metrics import MetricsWriter, TrialMeta
from bench.run import (
    JobConfig,
    Trial,
    answer_contract,
    finish_row,
    fresh_session_id,
    job_client_args,
    job_instances,
    provenance,
    question_text,
    scheduler_config,
)
from blackboard import EventStore
from counterfactual.recovery import ReplayRecovery
from protocol import Tag
from scheduler import Opportunity, Scheduler, Sidecar


@dataclass
class Roster:
    """Fresh agents for one session, the model-backed ones that may write a reply, and a source
    of fresh peers for the sandbox branches."""

    agents: list
    authors: Mapping[str, Any]
    make_peers: Callable[[], Sequence]


RosterFactory = Callable[[Trial, BaseLLMClient, JobConfig], Roster]


def model_roster(trial: Trial, client: BaseLLMClient, job: JobConfig) -> Roster:
    n = trial.meta.n_agents
    canonicalize, candidate_explanation = answer_contract(trial.instance)

    def build() -> list[PEXAgent]:
        return [
            PEXAgent(
                f"agent_{chr(ord('a') + i)}",
                persona_for(i, job.persona_set),
                client,
                counterfactual=True,  # every agent may be replayed; the arms differ in policy only
                temperature=job.temperature,
                max_tokens=job.max_tokens,
                seed=trial.meta.seed * 1000 + i,
                n_agents=n,
                prediction_canonicalizer=canonicalize,
                candidate_explanation_validator=candidate_explanation,
            )
            for i in range(n)
        ]

    team = build()
    return Roster(team, {a.name: a for a in team}, build)


class Capture:
    """The prefix run's policy: record the checkpoint and intervene in nothing."""

    name = "prefix"

    async def attempt(self, question, board, opportunity: Opportunity):
        opportunity.outcome = "prefix_only"
        return None


def _trial(job: JobConfig, instance, seed: int, label: str) -> Trial:
    return Trial(
        TrialMeta(
            config=f"{job.name}-{label}",
            benchmark=instance.benchmark,
            instance_id=instance.id,
            seed=seed,
            n_agents=job.n_agents,
            n_counterfactual=job.n_agents,
            domain=instance.domain,
            model="",
        ),
        instance,
    )


def _finished(store: EventStore, key: str) -> str | None:
    """A saved session of this key that ran to its end, if any (crashed attempts are ignored)."""
    for sid in store.sessions():
        if (sid == key or sid.startswith(f"{key}~r")) and store.state(sid).terminated:
            return sid
    return None


def _policy(arm: str, job: JobConfig, store: EventStore, roster: Roster, distance):
    if arm == "replay":
        return ReplayRecovery(
            store,
            roster.authors,
            roster.make_peers,
            distance=distance,
            max_branch_tokens=job.counterfactual.get("max_branch_tokens"),
        )
    return ControlRecovery(store, roster.authors, rethink=arm == "forward")


def _cost(rows) -> tuple[int, int]:
    # A ``skipped`` row documents a local allowance block.  It never reached the model and is
    # deliberately excluded from the paid request count and token total.
    requested = [r for r in rows if r.status != "skipped"]
    return len(requested), sum(r.tokens for r in requested)


async def _prefix(
    unit: Trial,
    store: EventStore,
    client: BaseLLMClient,
    job: JobConfig,
    roster: RosterFactory,
    sidecar: Sidecar,
) -> str:
    key = unit.meta.key
    if (done := _finished(store, key)) is not None:
        return done  # a saved prefix is reused, so every remaining arm starts from the same state
    sid = fresh_session_id(store, key)
    cfg = scheduler_config(unit.instance.format, job, unit.instance)
    team = roster(unit, client, job)
    with call_scope(trial=sid):
        await Scheduler(store, team.agents, cfg, recovery=Capture(), sidecar=sidecar).run(
            sid, question_text(unit.instance)
        )
    return sid


async def run_paired(
    job: JobConfig,
    out: Path,
    *,
    client: BaseLLMClient | None = None,
    roster: RosterFactory = model_roster,
    instances=None,
    parallel: int = 1,
    limit: int | None = None,
    log: Callable[[str], None] = print,
) -> list[dict]:
    """Run the unfinished arms of every (item, seed); returns the rows written this time."""
    if parallel != 1 or job.scheduler.get("concurrency", 1) != 1:
        raise ValueError("the paired experiment is serial: parallel and concurrency must be 1")
    unknown = [a for a in job.arms if a not in ARMS]
    if unknown:
        raise ValueError(f"unknown arm {unknown[0]!r}; arms are {ARMS}")
    out.mkdir(parents=True, exist_ok=True)
    client = client or make_client(**job_client_args(job))
    client.ledger = CallLedger(out / "calls.jsonl")
    items = instances if instances is not None else job_instances(job)
    writer, store = MetricsWriter(out / "metrics.csv"), EventStore(out / "board.sqlite")
    sidecar = Sidecar(out / "opportunities.jsonl")
    done = writer.done()
    units = sorted(
        ((inst, seed) for seed in job.seeds for inst in items), key=lambda u: (u[0].id, u[1])
    )
    info_path = out / "run.json"
    info = json.loads(info_path.read_text()) if info_path.exists() else {}
    info.setdefault("runs", []).append(
        {
            "started": datetime.now(UTC).isoformat(),
            **provenance(job, (1, 1), client, items),
        }
    )
    info_path.write_text(json.dumps(info, indent=2))

    rows: list[dict] = []
    try:
        for inst, seed in units:
            arms = [a for a in job.arms if _trial(job, inst, seed, a).meta.key not in done]
            if limit is not None:
                arms = arms[: max(0, limit - len(rows))]
            if not arms:
                continue
            prefix_trial = _trial(job, inst, seed, "prefix")
            prefix_sid = await _prefix(prefix_trial, store, client, job, roster, sidecar)
            for arm in arms:
                row = await _run_arm(
                    arm,
                    _trial(job, inst, seed, arm),
                    prefix_sid,
                    store,
                    client,
                    job,
                    roster,
                    sidecar,
                )
                writer.write(row)
                rows.append(row)
                log(f"done {row['trial_key']} · {row['stop_reason']} · {row['recovery_outcome']}")
    finally:
        info = json.loads(info_path.read_text())
        info["runs"][-1].update(finished=datetime.now(UTC).isoformat(), sessions_run=len(rows))
        info_path.write_text(json.dumps(info, indent=2))
        store.close()
        await client.aclose()
    return rows


async def _run_arm(
    arm: str,
    trial: Trial,
    prefix_sid: str,
    store: EventStore,
    client: BaseLLMClient,
    job: JobConfig,
    roster: RosterFactory,
    sidecar: Sidecar,
) -> dict:
    start = time.perf_counter()
    term = store.events(prefix_sid)[-1]
    assert term.tag is Tag.TERM
    recovery = term.meta.get("recovery") or {}
    opened = bool(recovery.get("eligible")) and recovery.get("skip_reason") is None
    sid = fresh_session_id(store, trial.meta.key)
    cfg = scheduler_config(trial.instance.format, job, trial.instance)
    prefix_rows = client.ledger.for_trial(prefix_sid)
    paired: dict[str, Any] = {
        "arm": arm,
        "checkpoint": "opened" if opened else "none",
        "skip_reason": recovery.get("skip_reason") or "",
        "prefix_tokens": _cost(prefix_rows)[1],
    }
    if not opened:  # nothing to intervene in: the ordinary terminal outcome is shared
        store.copy_session(prefix_sid, sid, upto=term.seq)
        paired.update(recovery_outcome="", intervention_calls=0, intervention_tokens=0)
        return finish_row(
            trial,
            store.state(sid),
            job,
            client,
            [prefix_sid],
            wall_time_s=time.perf_counter() - start,
            stop_detail=term.meta.get("detail", ""),
            decision_seq=term.meta.get("decision_seq"),
            paired=paired,
        )
    store.copy_session(prefix_sid, sid, upto=term.meta["decision_seq"])
    team = roster(trial, client, job)
    policy = _policy(arm, job, store, team, cfg.distance)
    # One allowance covers every request after the shared prefix: the control reply or replay
    # candidate, sandbox branches, repairs and any bounded live continuation.  The old runner
    # counted these calls but did not stop a continuation from exceeding the configured cap.
    with call_scope(trial=sid), call_budget(job.allowance_calls):
        result = await Scheduler(store, team.agents, cfg, recovery=policy, sidecar=sidecar).resume(
            sid, question_text(trial.instance)
        )
    calls, tokens = _cost(client.ledger.for_trial(sid))
    opp = result.opportunity
    credit = (opp.replay or {}).get("credit_delta") if opp else None
    paired.update(
        recovery_outcome=(opp.outcome or "") if opp else "",
        credit_delta="" if credit is None else credit,
        intervention_calls=calls,
        intervention_tokens=tokens,
    )
    return finish_row(
        trial,
        result.state,
        job,
        client,
        [prefix_sid, sid],
        wall_time_s=time.perf_counter() - start,
        rejected=len(result.rejected),
        failed_replies=sum(getattr(a, "failures", 0) for a in team.agents),
        stop_detail=result.stop_detail,
        decision_seq=result.decision_seq,
        paired=paired,
    )
