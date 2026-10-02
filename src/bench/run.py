"""Resumable experiment runner (D4).

    uv run python -m bench.run configs/<job>.json [--shard i/k] [--parallel n] [--limit n]
                                                  [--out DIR] [--mock]

Runs every (counterfactual level x seed x question) trial of a job config, writes one metrics row
per finished session to `<out>/metrics.csv`, every message to `<out>/board.sqlite` and the run's
provenance to `<out>/run.json`. Rerunning the same command skips finished trials. `--shard i/k`
takes every k-th trial starting at i, so k people or Colab sessions can split a job.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import re
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from agents.llm_client import BaseLLMClient, MockClient, make_client
from agents.pex_agent import PEXAgent
from agents.prompts import answer_instructions, persona_for
from bench.metrics import MetricsWriter, TrialMeta, read_metrics, trial_row
from bench.mscore import Instance, sample
from blackboard import EventStore
from scheduler import Scheduler, SchedulerConfig

REPO = Path(__file__).resolve().parents[2]


# --- config -------------------------------------------------------------------------------


@dataclass(frozen=True)
class JobConfig:
    name: str
    sample: dict  # kwargs for bench.mscore.sample: n_per_group, seed, domains, formats, ...
    seeds: tuple[int, ...] = (0,)
    n_agents: int = 3
    n_counterfactual: tuple[int, ...] = (0,)
    temperature: float = 0.7
    max_tokens: int = 400
    scheduler: dict = field(default_factory=dict)  # max_messages, impasse_window, stall_rule
    counterfactual: dict = field(default_factory=dict)  # sandbox settings (jobs-v2)

    @classmethod
    def load(cls, path: str | Path) -> JobConfig:
        raw = json.loads(Path(path).read_text())
        raw["seeds"] = tuple(raw.get("seeds", (0,)))
        raw["n_counterfactual"] = tuple(raw.get("n_counterfactual", (0,)))
        return cls(**raw)


def parse_shard(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d+)/(\d+)", text)
    if not m or not 1 <= int(m.group(1)) <= int(m.group(2)):
        raise argparse.ArgumentTypeError(f"--shard must look like 1/4, got {text!r}")
    return int(m.group(1)), int(m.group(2))


# --- judging --------------------------------------------------------------------------------

_LETTERS = re.compile(r"(?<![A-Za-z])[A-H](?![A-Za-z])")


def _fallback_same(fmt: str) -> Callable[[str, str], bool]:
    def key(text: str) -> str:
        if fmt in ("single_choice", "multi_choice"):
            return "|".join(sorted(set(_LETTERS.findall(text.upper()))))
        return " ".join(text.lower().split()).rstrip("。.!")

    return lambda a, b: bool(key(a)) and key(a) == key(b)


def judging(fmt: str) -> tuple[Callable[[str, str], bool], Callable[[str, str], bool]]:
    """(same_answer, is_correct) for a format: Package 3's rules if merged, else exact match."""
    try:
        from bench import correctness  # Package 3, lands Sat 3 Oct
    except ImportError:
        same = _fallback_same(fmt)
        return same, same
    return correctness.same_answer(fmt), lambda pred, ref: correctness.is_correct(fmt, pred, ref)


def groups(predictions: Mapping[str, str], same: Callable[[str, str], bool]) -> list[list[str]]:
    """Greedy grouping in sorted agent order, so it is deterministic."""
    out: list[list[str]] = []
    for agent in sorted(predictions):
        for g in out:
            if same(predictions[g[0]], predictions[agent]):
                g.append(agent)
                break
        else:
            out.append([agent])
    return out


def scheduler_config(fmt: str, job: JobConfig) -> SchedulerConfig:
    same, _ = judging(fmt)

    def consensus(preds: Mapping[str, str]) -> bool:
        return bool(preds) and len(groups(preds, same)) == 1

    def distance(preds: Mapping[str, str]) -> float:
        if not preds:
            return 1.0
        return 1 - max(len(g) for g in groups(preds, same)) / len(preds)

    return SchedulerConfig(consensus=consensus, distance=distance, **job.scheduler)


def final_answer(predictions: Mapping[str, str], same) -> str:
    """The largest group's prediction (ties: the group containing the first agent by name)."""
    if not predictions:
        return ""
    best = max(groups(predictions, same), key=len)
    return predictions[best[0]]


# --- trials ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Trial:
    meta: TrialMeta
    instance: Instance


def build_trials(job: JobConfig, instances: Sequence[Instance], model: str) -> list[Trial]:
    trials = [
        Trial(
            TrialMeta(
                config=f"{job.name}-cf{cf}",
                benchmark="mscore",
                instance_id=inst.id,
                seed=seed,
                n_agents=job.n_agents,
                n_counterfactual=cf,
                domain=inst.domain,
                model=model,
            ),
            inst,
        )
        for cf in job.n_counterfactual
        for seed in job.seeds
        for inst in instances
    ]
    return sorted(trials, key=lambda t: t.meta.key)


def shard_of(trials: Sequence[Trial], shard: tuple[int, int]) -> list[Trial]:
    i, k = shard
    return [t for n, t in enumerate(trials) if n % k == i - 1]


def question_text(inst: Instance) -> str:
    return f"{inst.prompt_text()}\n\n{answer_instructions(inst.format)}"


AgentFactory = Callable[[Trial, BaseLLMClient, JobConfig], list]


def default_agents(trial: Trial, client: BaseLLMClient, job: JobConfig) -> list[PEXAgent]:
    """3 agents with fixed personas; the first n_counterfactual of them are counterfactual."""
    n, cf = trial.meta.n_agents, trial.meta.n_counterfactual
    return [
        PEXAgent(
            f"agent_{chr(ord('a') + i)}",
            persona_for(i),
            client,
            counterfactual=i < cf,
            temperature=job.temperature,
            max_tokens=job.max_tokens,
            seed=trial.meta.seed * 1000 + i,
            n_agents=n,
        )
        for i in range(n)
    ]


def fresh_session_id(store: EventStore, key: str) -> str:
    """The trial key, or key~r<n> if a crashed attempt left a partial session behind."""
    sid, n = key, 1
    while store.state(sid).seq >= 0:
        sid, n = f"{key}~r{n}", n + 1
    return sid


async def run_trial(
    trial: Trial,
    store: EventStore,
    client: BaseLLMClient,
    job: JobConfig,
    make_agents: AgentFactory,
) -> dict:
    start = time.perf_counter()
    fmt = trial.instance.format
    agents = make_agents(trial, client, job)
    sid = fresh_session_id(store, trial.meta.key)
    result = await Scheduler(store, agents, scheduler_config(fmt, job)).run(
        sid, question_text(trial.instance)
    )
    same, correct = judging(fmt)
    answer = final_answer(result.state.predictions, same)
    unposted = sum(
        a.unposted.prompt + a.unposted.completion for a in agents if hasattr(a, "unposted")
    )
    return trial_row(
        result.state,
        trial.meta,
        answer=answer,
        correct=correct(answer, trial.instance.reference) if answer else False,
        wall_time_s=time.perf_counter() - start,
        rejected=len(result.rejected),
        failed_replies=sum(getattr(a, "failures", 0) for a in agents),
        unposted_tokens=unposted,
    )


# --- provenance -----------------------------------------------------------------------------


def _git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _gpu() -> str:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def provenance(job: JobConfig, shard: tuple[int, int], client: BaseLLMClient) -> dict:
    return {
        "job": asdict(job),
        "shard": f"{shard[0]}/{shard[1]}",
        "commit": _git("rev-parse", "HEAD"),
        "tag": _git("describe", "--tags", "--exact-match"),
        "dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "model": getattr(client, "model", ""),
        "base_url": os.environ.get("LLM_BASE_URL", ""),
        "machine": platform.platform(),
        "python": platform.python_version(),
        "gpu": _gpu(),
    }


# --- main loop ------------------------------------------------------------------------------


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


async def run_job(
    job: JobConfig,
    out: Path,
    *,
    shard: tuple[int, int] = (1, 1),
    parallel: int = 1,
    limit: int | None = None,
    client: BaseLLMClient | None = None,
    make_agents: AgentFactory = default_agents,
    instances: Sequence[Instance] | None = None,
    log: Callable[[str], None] = print,
) -> list[dict]:
    """Run the job's unfinished trials for this shard; returns the rows written this time."""
    out.mkdir(parents=True, exist_ok=True)
    client = client or make_client()
    instances = instances if instances is not None else sample(**job.sample)
    trials = shard_of(build_trials(job, instances, getattr(client, "model", "")), shard)
    if limit is not None:
        trials = trials[:limit]
    writer = MetricsWriter(out / "metrics.csv")
    done = writer.done()
    todo = [t for t in trials if t.meta.key not in done]
    store = EventStore(out / "board.sqlite")

    info_path = out / "run.json"
    info = json.loads(info_path.read_text()) if info_path.exists() else {}
    info.setdefault("runs", []).append(
        {"started": datetime.now(UTC).isoformat(), **provenance(job, shard, client)}
    )
    info_path.write_text(json.dumps(info, indent=2))

    log(
        f"{job.name} shard {shard[0]}/{shard[1]}: {len(trials)} trials, "
        f"{len(trials) - len(todo)} already done, {len(todo)} to run"
    )
    sem = asyncio.Semaphore(max(1, parallel))
    finished = len(trials) - len(todo)
    durations: list[float] = []
    rows: list[dict] = []
    started = time.perf_counter()

    async def one(trial: Trial) -> None:
        nonlocal finished
        async with sem:
            t0 = time.perf_counter()
            row = await run_trial(trial, store, client, job, make_agents)
        writer.write(row)
        rows.append(row)
        finished += 1
        durations.append(time.perf_counter() - t0)
        rate = (time.perf_counter() - started) / len(durations)  # wall seconds per session
        eta = rate * (len(trials) - finished)
        log(
            f"done {finished}/{len(trials)} · last session {durations[-1]:.0f} s · "
            f"{row['stop_reason']} · eta {_fmt_duration(eta)}"
        )

    try:
        await asyncio.gather(*(one(t) for t in todo))
    finally:
        info = json.loads(info_path.read_text())
        info["runs"][-1].update(
            finished=datetime.now(UTC).isoformat(),
            sessions_run=len(rows),
            mean_session_s=(sum(durations) / len(durations) if durations else None),
        )
        info_path.write_text(json.dumps(info, indent=2))
        store.close()
        await client.aclose()

    if rows or finished == len(trials):
        all_rows = read_metrics(out / "metrics.csv")
        stops = {
            r: sum(1 for x in all_rows if x["stop_reason"] == r)
            for r in ("consensus", "impasse", "cap")
        }
        log(
            f"stop reasons: consensus {stops['consensus']}, impasse {stops['impasse']}, "
            f"cap {stops['cap']}"
        )
    return rows


# --- offline smoke test ----------------------------------------------------------------------


def mock_client() -> MockClient:
    """A scripted model for `--mock`: opens with a letter from a hash, then follows what it is
    shown half of the time. Lets the whole pipeline run with no GPU."""
    import hashlib

    def respond(messages) -> str:
        user = messages[-1].content
        h = hashlib.sha256((messages[0].content + user).encode()).digest()
        if "board is empty" in user:
            return json.dumps(
                {
                    "tag": "INIT",
                    "prediction": "ABCD"[h[0] % 4],
                    "explanation": "first reading of the options",
                }
            )
        shown = user.split("Reply to message [", 1)[1].split(": ", 1)[1].split(" |")[0]
        mine = user.split("Your current prediction: ", 1)[1].split("\n", 1)[0]
        if shown == mine:
            return json.dumps({"tag": "RATIFY", "prediction": mine, "explanation": "agreed"})
        if h[1] % 2:
            return json.dumps({"tag": "REVISE", "prediction": shown, "explanation": "convinced"})
        return json.dumps({"tag": "REFUTE", "prediction": mine, "explanation": "not convinced"})

    return MockClient(responder=respond, model="mock")


def main(argv: Sequence[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Run (or resume) one shard of an experiment job.")
    p.add_argument("config", help="configs/<job>.json")
    p.add_argument("--shard", type=parse_shard, default=(1, 1), help="i/k, e.g. 2/4")
    p.add_argument("--parallel", type=int, default=1, help="sessions run at once")
    p.add_argument("--limit", type=int, help="run only the first n trials of the shard")
    p.add_argument("--out", help="output folder (default results/runs/<job>/shard-i-of-k)")
    p.add_argument("--mock", action="store_true", help="scripted model, no GPU (pipeline test)")
    a = p.parse_args(argv)
    job = JobConfig.load(a.config)
    i, k = a.shard
    out = Path(a.out) if a.out else REPO / "results" / "runs" / job.name / f"shard-{i}-of-{k}"
    if a.out:
        out = out / f"shard-{i}-of-{k}"
    asyncio.run(
        run_job(
            job,
            out,
            shard=a.shard,
            parallel=a.parallel,
            limit=a.limit,
            client=mock_client() if a.mock else None,
        )
    )


if __name__ == "__main__":
    main()
