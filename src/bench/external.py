"""Local task-file adapters for proposal benchmarks outside the MSCoRe corpus.

These loaders preserve benchmark IDs and private reference fields. Loading a task file does not
reproduce either benchmark's official environment or scoring; see
`docs/experiments_and_benchmarks.md`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from bench.mscore import Instance


class ExternalBenchmarkError(ValueError):
    """The downloaded task files do not match the expected benchmark contract."""


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExternalBenchmarkError(f"cannot read benchmark file {path}: {exc}") from exc


def load_kramabench(
    workload_dir: str | Path,
    *,
    domains: Iterable[str] | None = None,
    ids: Iterable[str] | None = None,
    max_items: int | None = None,
) -> list[Instance]:
    """Load KramaBench workload JSON without exposing answer keys to the agents' prompt."""
    root = Path(workload_dir).expanduser().resolve()
    wanted_ids = set(ids) if ids is not None else None
    selected_domains = (
        sorted(set(domains)) if domains else sorted(p.stem for p in root.glob("*.json"))
    )
    output: list[Instance] = []
    for domain in selected_domains:
        path = (root / f"{domain}.json").resolve()
        if root not in path.parents:
            raise ExternalBenchmarkError(f"workload file escapes the workload directory: {domain}")
        records = _read_json(path)
        if not isinstance(records, list):
            raise ExternalBenchmarkError(f"{path} must contain a JSON array of tasks")
        for task in records:
            task_id = str(task.get("id", ""))
            if not task_id or not task.get("query") or "answer" not in task:
                raise ExternalBenchmarkError(f"{path}: task is missing id, query, or answer")
            if wanted_ids is not None and task_id not in wanted_ids:
                continue
            sources = task.get("data_sources", [])
            subtasks = task.get("subtasks", [])
            public_context = [f"Workload domain: {domain}"]
            if sources:
                public_context.append(
                    "Data sources named by the task: " + ", ".join(map(str, sources))
                )
            if subtasks:
                public_context.append(
                    f"The task has {len(subtasks)} reference-pipeline subtask(s); "
                    "solve the requested end-to-end question."
                )
            output.append(
                Instance(
                    id=f"kramabench:{domain}:{task_id}",
                    domain=f"kramabench_{domain}",
                    format="kramabench",
                    difficulty=str(task.get("difficulty", "unspecified")),
                    stage="",
                    question=str(task["query"]).strip(),
                    reference=str(task["answer"]).strip(),
                    context="\n".join(public_context),
                    benchmark="kramabench",
                    metadata={
                        "answer_type": str(task.get("answer_type", "text")),
                        "data_sources": [str(x) for x in sources],
                        "subtask_count": len(subtasks),
                        "evaluation_mode": "reference-answer-proxy",
                    },
                )
            )
            if max_items is not None and len(output) >= max_items:
                return output
    if wanted_ids is not None:
        found = {item.id.rsplit(":", 1)[-1] for item in output}
        missing = wanted_ids - found
        if missing:
            raise ExternalBenchmarkError(f"unknown KramaBench task id {sorted(missing)[0]!r}")
    return output


def load_medagentbench(
    tasks_file: str | Path,
    *,
    ids: Iterable[str] | None = None,
    max_items: int | None = None,
) -> list[Instance]:
    """Load MedAgentBench task definitions while keeping `sol` and `eval_MRN` out of prompts.

    The returned rows are tagged `interactive-environment-required`. They are useful for adapter
    smoke tests and task selection; they must not be reported as official MedAgentBench scores
    unless run through the pinned FHIR environment and authorized task grader.
    """
    path = Path(tasks_file).expanduser().resolve()
    records = _read_json(path)
    if not isinstance(records, list):
        raise ExternalBenchmarkError(f"{path} must contain a JSON array of tasks")
    wanted = set(ids) if ids is not None else None
    output = []
    for task in records:
        task_id = str(task.get("id", ""))
        if not task_id or not task.get("instruction"):
            raise ExternalBenchmarkError(f"{path}: task is missing id or instruction")
        if wanted is not None and task_id not in wanted:
            continue
        task_type = task_id.split("_", 1)[0]
        reference = task.get("sol")
        output.append(
            Instance(
                id=f"medagentbench:{task_id}",
                domain="medagentbench_clinical_workflow",
                format="medagentbench",
                difficulty="unspecified",
                stage=task_type,
                question=str(task["instruction"]).strip(),
                reference=json.dumps(reference, ensure_ascii=False)
                if reference is not None
                else "",
                context=str(task.get("context", "")).strip(),
                benchmark="medagentbench",
                metadata={
                    "task_type": task_type,
                    "evaluation_mode": "interactive-environment-required",
                    "eval_mrn": task.get("eval_MRN"),
                    "has_reference_value": reference is not None,
                },
            )
        )
        if max_items is not None and len(output) >= max_items:
            break
    if wanted is not None:
        found = {item.id.removeprefix("medagentbench:") for item in output}
        missing = wanted - found
        if missing:
            raise ExternalBenchmarkError(f"unknown MedAgentBench task id {sorted(missing)[0]!r}")
    return output


def load_external(spec: dict) -> list[Instance]:
    """Resolve a JSON job-config `external` stanza into task instances."""
    kind = spec.get("kind")
    options = {k: v for k, v in spec.items() if k != "kind"}
    if kind == "kramabench":
        return load_kramabench(**options)
    if kind == "medagentbench":
        return load_medagentbench(**options)
    raise ExternalBenchmarkError(f"unknown external benchmark kind {kind!r}")
