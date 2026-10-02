"""J1: parse check runs end to end on the mock and reports retries."""

import asyncio
import json
from pathlib import Path

from agents.llm_client import MockClient
from bench.parse_check import run, summary
from tests.test_runner import inst


def test_parse_check_counts_first_try_and_retry(tmp_path: Path) -> None:
    calls = []

    def responder(messages):
        calls.append(1)
        user = messages[-1].content
        if "could not be used" in user:  # the repair turn
            tag = "INIT" if "board is empty" in messages[1].content else "REFUTE"
            return json.dumps({"tag": tag, "prediction": "B", "explanation": "fixed"})
        if len(calls) % 3 == 0:
            return "not json"
        tag = "INIT" if "board is empty" in user else "REJECT"
        return json.dumps({"tag": tag, "prediction": "B", "explanation": "e", "reply_to": 1})

    records = asyncio.run(
        run(12, 3, tmp_path, MockClient(responder=responder), [inst(i) for i in range(3)])
    )
    assert len(records) == 12 and all(r["ok"] for r in records)
    assert any(not r["first_try"] for r in records)
    assert {r["kind"] for r in records} == {"init", "reply"}
    assert len((tmp_path / "calls.jsonl").read_text().splitlines()) == 12
    text = summary(records)
    assert "valid after one retry: 12/12 (100%)" in text
