"""Single-agent MedAgentBench harness: the official GET / POST / FINISH loop and refsol grading.

This follows the upstream task server (stanfordmlgroup/MedAgentBench): one agent sees the task
prompt and the FHIR function catalogue, answers with exactly one action per turn, and is scored by
the gated `refsol.py` grader. As upstream, a POST is parsed and recorded but not sent to the
server, so the FHIR state never changes and no per-task reset is needed (recorded as
`reset: not_required`). The multi-agent debate is deliberately not part of this module: this is
the baseline the debate would be compared against.

Neither `refsol.py` nor the upstream checkout lives in this repository. `--upstream` points at a
checkout (for the task file and function catalogue) and `--refsol` at the downloaded grader.
"""

from __future__ import annotations

from urllib.parse import urlsplit
import argparse
import asyncio
import hashlib
import importlib.util
import json
import platform
import subprocess
import sys
import time
import types
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from agents.ledger import call_scope
from agents.llm_client import BaseLLMClient, LLMError, make_client

DEFAULT_FHIR_BASE = "http://localhost:8080/fhir/"
MAX_ROUND = 8  # upstream configs/tasks/medagentbench.yaml
DATA_FILE = "data/medagentbench/test_data_v2.json"
FUNCS_FILE = "data/medagentbench/funcs_v1.json"
CONTINUE_HINT = (
    "Please call FINISH if you have got answers for all the questions and finished all the "
    "requested tasks"
)

PROMPT = """You are an expert in using FHIR functions to assist medical professionals. You are given a question and a set of possible functions. Based on the question, you will need to make one or more function/tool calls to achieve the purpose.

1. If you decide to invoke a GET function, you MUST put it in the format of
GET url?param_name1=param_value1&param_name2=param_value2...

2. If you decide to invoke a POST function, you MUST put it in the format of
POST url
[your payload data in JSON format]

3. If you have got answers for all the questions and finished all the requested tasks, you MUST call to finish the conversation in the format of (make sure the list is JSON loadable.)
FINISH([answer1, answer2, ...])

Your response must be in the format of one of the three cases, and you can call only one function each time. You SHOULD NOT include any other text in the response.

Here is a list of functions in JSON format that you can invoke. Note that you should use {api_base} as the api_base.
{functions}

Context: {context}
Question: {question}"""  # noqa: E501 - the upstream prompt, kept verbatim so scores stay comparable

COMPLETED, INVALID_ACTION, ROUND_LIMIT, TASK_ERROR, MODEL_ERROR = (
    "completed",
    "invalid_action",
    "round_limit",
    "task_error",
    "model_error",
)


class MedAgentError(RuntimeError):
    """The environment or a required file is not usable; never a model failure."""


@dataclass
class Turn:
    """One history entry. `role` is "user" (environment) or "agent", the names refsol reads."""

    role: str
    content: str


@dataclass
class Outcome:
    """What refsol receives: the dialogue and the text inside FINISH(...)."""

    history: list[Turn]
    result: str | None = None


@dataclass
class Action:
    kind: str  # GET | POST | FINISH | INVALID
    text: str


def parse_action(reply: str) -> Action:
    """Mirror the upstream parser: strip code fences, then dispatch on the first word."""
    text = reply.strip().replace("```tool_code", "").replace("```", "").strip()
    if text.startswith("GET"):
        return Action("GET", text)
    if text.startswith("POST"):
        return Action("POST", text)
    if text.startswith("FINISH("):
        return Action("FINISH", text)
    return Action("INVALID", text)

# def validate_action_format(action: Action) -> str | None:
#     """Return a format error, or None when the action matches the expected syntax."""
#     text = action.text.strip()

#     if action.kind == "GET":
#         url = text.removeprefix("GET").strip()
#         parsed = urlsplit(url)
#         if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.path:
#             return "GET must contain a complete HTTP(S) URL"
#         return None

#     if action.kind == "POST":
#         lines = text.splitlines()
#         if len(lines) < 2:
#             return "POST must contain a URL followed by a JSON payload"

#         parsed = urlsplit(lines[0].removeprefix("POST").strip())
#         if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.path:
#             return "POST must contain a complete HTTP(S) URL"

#         payload = "\n".join(lines[1:]).strip()
#         if not payload:
#             return "POST payload is empty"

#         try:
#             value = json.loads(payload)
#         except json.JSONDecodeError:
#             return "POST payload must be valid JSON"

#         if not isinstance(value, dict):
#             return "POST payload must be a JSON object"

#         return None

#     if action.kind == "FINISH":
#         if not (text.startswith("FINISH(") and text.endswith(")")):
#             return "FINISH must use FINISH([...]) syntax"

#         payload = text[len("FINISH("):-1]
#         try:
#             value = json.loads(payload)
#         except json.JSONDecodeError:
#             return "FINISH payload must be valid JSON"

#         if not isinstance(value, list):
#             return "FINISH payload must be a JSON list"

#         return None

#     return "Action must begin with GET, POST, or FINISH"


def _get_request(client: httpx.Client, url: str) -> dict[str, Any]:
    """Same result shape as upstream `send_get_request`: JSON only for a bare application/json."""
    try:
        response = client.get(url)
        response.raise_for_status()
        body = (
            response.json()
            if response.headers.get("Content-Type") == "application/json"
            else response.text
        )
        return {"status_code": response.status_code, "data": body}
    except Exception as err:
        return {"error": str(err)}


class Fhir:
    """The FHIR server as the agent and the grader see it."""

    def __init__(self, base: str = DEFAULT_FHIR_BASE, transport: httpx.BaseTransport | None = None):
        self.base = base if base.endswith("/") else base + "/"
        self._http = httpx.Client(transport=transport, timeout=60.0)

    def get(self, url: str) -> dict[str, Any]:
        return _get_request(self._http, url)

    def healthy(self) -> bool:
        return self.get(f"{self.base}metadata").get("status_code") == 200

    def close(self) -> None:
        self._http.close()


def load_grader(refsol_path: str | Path, fhir: Fhir) -> Callable[[dict, Outcome], bool]:
    """Import the downloaded refsol.py with a small `utils` beside it and return `grade`.

    refsol does `from .utils import *`, so it is loaded as a submodule of a synthetic package
    whose `utils` provides the two helpers the upstream one does.
    """
    path = Path(refsol_path).expanduser()
    if not path.is_file():
        raise MedAgentError(f"refsol.py not found at {path}")
    package = types.ModuleType("medagent_refsol")
    package.__path__ = []  # type: ignore[attr-defined]
    utils = types.ModuleType("medagent_refsol.utils")
    utils.send_get_request = fhir.get  # type: ignore[attr-defined]
    utils.verify_fhir_server = lambda base: fhir.healthy()  # type: ignore[attr-defined]
    sys.modules["medagent_refsol"], sys.modules["medagent_refsol.utils"] = package, utils
    spec = importlib.util.spec_from_file_location("medagent_refsol.refsol", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["medagent_refsol.refsol"] = module
    spec.loader.exec_module(module)

    def grade(case: dict, outcome: Outcome) -> bool:
        grader = getattr(module, case["id"].split("_")[0], None)
        if grader is None:
            raise MedAgentError(f"refsol has no grader for {case['id']}")
        try:
            return grader(case, outcome, fhir.base) is True
        except Exception:
            return False

    return grade


@dataclass
class TaskRun:
    task_id: str
    status: str
    result: str | None
    rounds: int
    history: list[Turn] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    wall_time_s: float = 0.0
    detail: str = ""


async def run_task(
    llm: BaseLLMClient,
    case: dict,
    funcs: list,
    fhir: Fhir,
    *,
    max_round: int = MAX_ROUND,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    seed: int | None = None,
) -> TaskRun:
    """Play one task. Only the question, context and function catalogue reach the model."""
    start = time.monotonic()
    prompt = PROMPT.format(
        api_base=fhir.base,
        functions=json.dumps(funcs),
        context=case.get("context", ""),
        question=case["instruction"],
    )
    history = [Turn("user", prompt)]
    run = TaskRun(case["id"], ROUND_LIMIT, None, 0, history)

    def finish(status: str, detail: str = "") -> TaskRun:
        run.status, run.detail, run.wall_time_s = status, detail, time.monotonic() - start
        return run

    for _ in range(max_round):
        messages = [
            {"role": "assistant" if t.role == "agent" else "user", "content": t.content}
            for t in history
        ]
        try:
            with call_scope(trial=case["id"], phase="debate", agent="solo"):
                reply = await llm.complete(
                    messages, temperature=temperature, max_tokens=max_tokens, seed=seed
                )
        except LLMError as err:
            return finish(MODEL_ERROR, str(err))
        run.rounds += 1
        run.prompt_tokens += reply.usage.prompt
        run.completion_tokens += reply.usage.completion
        history.append(Turn("agent", reply.text.strip()))
        action = parse_action(reply.text)
        # format_error = validate_action_format(action)
        # if format_error:
        #     return finish(INVALID_ACTION, format_error)
        if action.kind == "GET":
            got = fhir.get(action.text[3:].strip() + "&_format=json")
            if "data" in got:
                note = f"Here is the response from the GET request:\n{got['data']}. {CONTINUE_HINT}"
            else:
                note = f"Error in sending the GET request: {got['error']}"
            history.append(Turn("user", note))
        elif action.kind == "POST":
            try:
                json.loads("\n".join(action.text.split("\n")[1:]))
            except ValueError:
                history.append(Turn("user", "Invalid POST request"))
            else:
                history.append(
                    Turn(
                        "user", f"POST request accepted and executed successfully. {CONTINUE_HINT}"
                    )
                )
        elif action.kind == "FINISH":
            run.result = action.text[len("FINISH(") : -1]
            return finish(COMPLETED)
        else:
            return finish(INVALID_ACTION, action.text[:200])
    return finish(ROUND_LIMIT)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _commit(checkout: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def select(cases: list[dict], ids: Iterable[str] | None, per_type: int | None) -> list[dict]:
    """Pick tasks by id, or the first `per_type` of each task type; otherwise all."""
    if ids:
        wanted = list(ids)
        by_id = {c["id"]: c for c in cases}
        missing = [i for i in wanted if i not in by_id]
        if missing:
            raise MedAgentError(f"unknown MedAgentBench task id {missing[0]!r}")
        return [by_id[i] for i in wanted]
    if per_type is None:
        return list(cases)
    seen: dict[str, int] = {}
    chosen = []
    for case in cases:
        kind = case["id"].split("_")[0]
        if seen.get(kind, 0) < per_type:
            seen[kind] = seen.get(kind, 0) + 1
            chosen.append(case)
    return chosen


def _done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {json.loads(line)["task_id"] for line in path.read_text().splitlines() if line.strip()}


async def run_all(
    llm: BaseLLMClient,
    cases: list[dict],
    funcs: list,
    fhir: Fhir,
    grade: Callable[[dict, Outcome], bool],
    out: Path,
    *,
    log: Callable[[str], None] = print,
    **options: Any,
) -> list[dict]:
    """Run tasks serially, appending one JSON line per finished task; resumes where it stopped."""
    out.mkdir(parents=True, exist_ok=True)
    results = out / "results.jsonl"
    finished = _done(results)
    rows: list[dict] = []
    for index, case in enumerate(cases, 1):
        if case["id"] in finished:
            continue
        run = await run_task(llm, case, funcs, fhir, **options)
        correct = run.status == COMPLETED and grade(case, Outcome(run.history, run.result))
        row = {**asdict(run), "correct": correct, "task_type": case["id"].split("_")[0]}
        with results.open("a") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        rows.append(row)
        log(f"[{index}/{len(cases)}] {case['id']}: {run.status}, correct={correct}")
    return rows


def summarize(results: Path) -> dict[str, Any]:
    rows = [json.loads(line) for line in results.read_text().splitlines() if line.strip()]
    by_type: dict[str, list[bool]] = {}
    for row in rows:
        by_type.setdefault(row["task_type"], []).append(row["correct"])
    statuses: dict[str, int] = {}
    for row in rows:
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
    return {
        "tasks": len(rows),
        "correct": sum(row["correct"] for row in rows),
        "success_rate": (sum(row["correct"] for row in rows) / len(rows)) if rows else None,
        "by_type": {k: {"n": len(v), "correct": sum(v)} for k, v in sorted(by_type.items())},
        "statuses": statuses,
        "prompt_tokens": sum(row["prompt_tokens"] for row in rows),
        "completion_tokens": sum(row["completion_tokens"] for row in rows),
    }


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Run the single-agent MedAgentBench baseline.")
    p.add_argument("--upstream", required=True, help="local checkout of MedAgentBench")
    p.add_argument("--refsol", required=True, help="the downloaded refsol.py (kept out of Git)")
    p.add_argument("--out", required=True)
    p.add_argument("--ids", nargs="*", help="task ids such as task1_1 task5_3")
    p.add_argument("--per-type", type=int, help="first N tasks of each of the ten task types")
    p.add_argument("--fhir-base", default=DEFAULT_FHIR_BASE)
    p.add_argument("--backend", help="mock or openai; default from LLM_BACKEND")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--max-tokens", type=int, default=1024)
    p.add_argument("--image-digest", default="", help="docker image digest, for provenance")
    a = p.parse_args(argv)

    upstream, out = Path(a.upstream).expanduser(), Path(a.out)
    refsol = Path(a.refsol).expanduser()
    cases = json.loads((upstream / DATA_FILE).read_text())
    funcs = json.loads((upstream / FUNCS_FILE).read_text())
    chosen = select(cases, a.ids, a.per_type)
    fhir = Fhir(a.fhir_base)
    if not fhir.healthy():
        raise SystemExit(f"FHIR server not answering at {fhir.base}metadata; start the container")
    grade = load_grader(refsol, fhir)
    llm = make_client(a.backend)
    out.mkdir(parents=True, exist_ok=True)
    (out / "run.json").write_text(
        json.dumps(
            {
                "benchmark": "medagentbench",
                "evaluation": "official refsol.py grader, single agent",
                "upstream_commit": _commit(upstream),
                "task_file_sha256": _sha256(upstream / DATA_FILE),
                "function_catalogue_sha256": _sha256(upstream / FUNCS_FILE),
                "refsol_sha256": _sha256(refsol),
                "image_digest": a.image_digest,
                "fhir_base": fhir.base,
                "reset": "not_required",
                "model": llm.model,
                "temperature": a.temperature,
                "max_tokens": a.max_tokens,
                "max_round": MAX_ROUND,
                "tasks": [c["id"] for c in chosen],
                "python": platform.python_version(),
            },
            indent=2,
        )
    )
    try:
        asyncio.run(
            run_all(
                llm,
                chosen,
                funcs,
                fhir,
                grade,
                out,
                temperature=a.temperature,
                max_tokens=a.max_tokens,
            )
        )
    finally:
        fhir.close()
    print(json.dumps(summarize(out / "results.jsonl"), indent=2))


if __name__ == "__main__":
    main()
