"""D1: MSCoRe ingestor, offline (files are pre-seeded into a temporary cache)."""

import json
from pathlib import Path

import pytest

from bench import mscore
from bench.mscore import JUDGMENT, MANIFEST, MULTI, OPEN_QA, SINGLE, load_ids, sample, select_files

LAW_SINGLE = "Data2/Law/Single-choice/simple"
LAW_MULTI = "Data2/Law/Multi-choice/simple"
CONSTRUCTION = "Data2/Construction/simple/data.json"
AUTO = "Automotive Value Chain/Easy/Design"


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    def put(path: str, records: list[dict]) -> None:
        f = tmp_path / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

    put(
        LAW_SINGLE,
        [{"question": f"q{i}", "options": {"B": "b", "A": "a"}, "answer": "A"} for i in range(10)],
    )
    put(LAW_MULTI, [{"question": "m", "options": {"A": "a", "B": "b"}, "answer": "A|B"}])
    put(CONSTRUCTION, [{"question": "施工可以继续。", "answer": "否"}])
    put(AUTO, [{"instruction": f" 如何{i}? ", "input": "", "output": "答案"} for i in range(4)])
    mscore.load_file.cache_clear()
    return tmp_path


def test_manifest_is_well_formed() -> None:
    assert len({f.path for f in MANIFEST}) == len(MANIFEST)
    assert {f.domain for f in MANIFEST} == {
        "automotive",
        "automotive_energy",
        "ecommerce",
        "pharmaceutical",
        "finance",
        "law",
        "construction",
    }
    assert {f.format for f in select_files(domains=["law"])} == {SINGLE, MULTI}
    assert all(f.format == OPEN_QA for f in select_files(domains=["pharmaceutical"]))


def test_parses_every_format(cache: Path) -> None:
    single = mscore.load_file(LAW_SINGLE, cache)[0]
    assert (single.id, single.format, single.reference) == (f"{LAW_SINGLE}#0", SINGLE, "A")
    assert single.options == (("A", "a"), ("B", "b"))
    assert single.prompt_text() == "q0\nA. a\nB. b"
    assert mscore.load_file(LAW_MULTI, cache)[0].reference == "A|B"
    judged = mscore.load_file(CONSTRUCTION, cache)[0]
    assert (judged.format, judged.reference, judged.options) == (JUDGMENT, "否", ())
    qa = mscore.load_file(AUTO, cache)[1]
    assert (qa.format, qa.question, qa.reference, qa.difficulty) == (
        OPEN_QA,
        "如何1?",
        "答案",
        "simple",
    )


def test_sampling_is_deterministic_and_grouped(cache: Path) -> None:
    kw = {"domains": ["law", "construction"], "difficulties": ["simple"], "cache_dir": cache}
    first = sample(3, seed=1, **kw)
    assert [i.id for i in first] == [i.id for i in sample(3, seed=1, **kw)]
    groups = [(i.domain, i.difficulty) for i in first]
    assert groups.count(("law", "simple")) == 3 and groups.count(("construction", "simple")) == 1
    other = sample(3, seed=2, **kw)
    assert [i.id for i in other] != [i.id for i in first]


def test_ids_round_trip(cache: Path) -> None:
    picked = [mscore.load_file(AUTO, cache)[3], mscore.load_file(LAW_SINGLE, cache)[7]]
    assert load_ids([i.id for i in picked], cache) == picked


def test_cli_writes_jsonl(cache: Path, tmp_path: Path) -> None:
    out = tmp_path / "s.jsonl"
    mscore.main(
        [
            "--n",
            "2",
            "--domains",
            "construction",
            "--difficulties",
            "simple",
            "--cache-dir",
            str(cache),
            "--out",
            str(out),
        ]
    )
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [r["reference"] for r in rows] == ["否"]
