"""Roadmap section 06: public case records, private grading records and what agents may see."""

import json
import shutil
from pathlib import Path

import pytest

from bench.cases import CaseBook, CaseError, load_cases, question_for
from bench.run import question_text

ROOT = Path(__file__).resolve().parents[1] / "data" / "cases"


@pytest.fixture(scope="module")
def book() -> CaseBook:
    return load_cases(ROOT)


def test_every_case_has_a_public_and_a_grading_record(book) -> None:
    assert set(book.public) == set(book.grading)
    assert len(book.split("heldout")) == 8
    assert len(book.split("dev")) == 4


def test_worked_case_and_its_unbounded_variant_are_in_the_dev_set(book) -> None:
    dev = {c.id for c in book.split("dev")}
    assert {"restore-p1", "restore-p1-unbounded"} <= dev
    assert book.grading["restore-p1"].acceptable_decisions == ("B",)


def test_prompt_shows_question_context_evidence_and_the_response_shape(book) -> None:
    text = question_for(book.public["restore-p1"])
    assert "How should service be restored under policy P1?" in text
    assert "four minutes of downtime" in text
    assert "[E1] Plan A needs six minutes" in text
    assert "[E2] Plan B needs two minutes" in text
    assert "A | B" in text
    assert "downtime" in text and "lag_check" in text and "before | none" in text
    assert "cited evidence" in text.lower()


def test_prompts_carry_no_grading_text(book) -> None:
    for case_id, public in book.public.items():
        prompt = question_for(public)
        grading = book.grading[case_id]
        secrets = [c.description for c in grading.conditions] + [
            c.description for c in grading.critical
        ]
        assert not [s for s in secrets if s in prompt], case_id
        assert "acceptable" not in prompt.lower() and "rubric" not in prompt.lower()


def test_runner_question_never_includes_the_reference(book) -> None:
    case = book.public["restore-p1"]
    inst = book.instance(case.id)
    assert inst.reference == "B"  # kept on the record for the decision check, not shown
    text = question_text(inst)
    assert "rubric" not in text.lower() and "acceptable" not in text.lower()
    assert text.startswith("How should service be restored")


def test_authored_question_includes_its_exact_public_prediction_contract(book) -> None:
    text = question_text(book.instance("contractor-access"))
    assert "extend | exception | revoke" in text
    assert "total_days=<number>" in text
    assert "exception_signed=<yes | no>" in text


def test_instance_matches_the_runner_interface(book) -> None:
    inst = book.instance("vendor-select")
    assert inst.id == "case:vendor-select"
    assert inst.format == "authored" and inst.domain == "procurement"
    assert inst.difficulty == "heldout"


def test_manifest_version_is_stable_and_changes_with_content(book, tmp_path) -> None:
    copy = tmp_path / "cases"
    shutil.copytree(ROOT, copy)
    assert load_cases(copy).version == book.version
    edited = copy / "public" / "restore-p1.json"
    body = json.loads(edited.read_text())
    body["context"] += " Extra."
    edited.write_text(json.dumps(body))
    assert load_cases(copy).version != book.version


def _broken(tmp_path: Path, mutate) -> Path:
    copy = tmp_path / "cases"
    shutil.copytree(ROOT, copy)
    mutate(copy)
    return copy


def _edit(path: Path, change) -> None:
    body = json.loads(path.read_text())
    change(body)
    path.write_text(json.dumps(body))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: (r / "grading" / "restore-p1.json").unlink(), "no grading record"),
        (lambda r: (r / "public" / "restore-p1.json").unlink(), "no public record"),
        (
            lambda r: _edit(
                r / "grading" / "restore-p1.json",
                lambda b: b.update(acceptable_decisions=["C"]),
            ),
            "acceptable decision",
        ),
        (
            lambda r: _edit(
                r / "grading" / "restore-p1.json",
                lambda b: b.update(evidence_required=["E9"]),
            ),
            "unknown evidence",
        ),
        (
            lambda r: _edit(
                r / "grading" / "restore-p1.json",
                lambda b: b["critical"].append({"id": "x", "description": "d", "when": {"zz": 1}}),
            ),
            "unknown field",
        ),
        (
            lambda r: _edit(
                r / "grading" / "restore-p1.json",
                lambda b: b["conditions"].append(
                    {"id": "x", "description": "d", "patterns": ["("]}
                ),
            ),
            "pattern",
        ),
        (
            lambda r: _edit(
                r / "public" / "restore-p1.json",
                lambda b: b["response"]["fields"].append({"name": "q", "kind": "enum"}),
            ),
            "enum",
        ),
        (
            lambda r: _edit(r / "public" / "restore-p1.json", lambda b: b.update(split="train")),
            "split",
        ),
    ],
)
def test_invalid_records_are_rejected_with_a_reason(tmp_path, mutate, message) -> None:
    with pytest.raises(CaseError, match=message):
        load_cases(_broken(tmp_path, mutate))


def test_records_with_mismatched_ids_are_rejected(tmp_path) -> None:
    def mutate(root: Path) -> None:
        _edit(root / "grading" / "restore-p1.json", lambda b: b.update(id="other"))

    with pytest.raises(CaseError, match="id"):
        load_cases(_broken(tmp_path, mutate))


def test_loading_never_touches_the_network(book, monkeypatch) -> None:
    import socket

    def refuse(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "socket", refuse)
    assert len(load_cases(ROOT).public) == 12
