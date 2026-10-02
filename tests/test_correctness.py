"""D2: correctness and same-answer rules for every MSCoRe format."""

import pytest

from bench.correctness import (
    choice_letters,
    consensus_fn,
    distance_fn,
    is_correct,
    judgment_value,
    rouge_l_f1,
    same_answer,
    tokens,
)


@pytest.mark.parametrize(
    ("text", "letters"),
    [
        ("B", {"B"}),
        ("答案是 B。", {"B"}),
        ("答案是B。", {"B"}),
        ("A和C", {"A", "C"}),
        ("A|C", {"A", "C"}),
        ("A, C", {"A", "C"}),
        ("选 B 和 D", {"B", "D"}),
        ("(C).", {"C"}),
        ("Because of rule D", {"D"}),
        ("BAD", set()),
        ("", set()),
        ("I", set()),
    ],
)
def test_choice_letters(text: str, letters: set[str]) -> None:
    assert choice_letters(text) == letters


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("是", True),
        ("否", False),
        ("不对", False),
        ("对", True),
        ("这个说法是错误的", False),
        ("正确", True),
        ("不正确", False),
        ("True", True),
        ("no", False),
        ("Yes, it holds", True),
        ("不是", False),
        ("√", True),
        ("\u00d7", False),
        ("not sure", None),
        ("", None),
    ],
)
def test_judgment_value(text: str, value: bool | None) -> None:
    assert judgment_value(text) is value


def test_tokens_and_rouge() -> None:
    assert tokens("合同法, Article 5!") == ["合", "同", "法", "article", "5"]
    assert rouge_l_f1("合同审查需要法律评估", "合同审查需要法律评估") == 1.0
    assert rouge_l_f1("合同审查", "完全无关的句子") == 0.0
    assert rouge_l_f1("", "x") == 0.0
    # LCS of 合同审查 (4) against 合同的审查流程 (7): P = 4/4, R = 4/7
    assert rouge_l_f1("合同审查", "合同的审查流程") == pytest.approx(2 * 1 * (4 / 7) / (1 + 4 / 7))


@pytest.mark.parametrize(
    ("fmt", "pred", "ref", "ok"),
    [
        ("single_choice", "答案是 B。", "B", True),
        ("single_choice", "C", "B", False),
        ("single_choice", "", "B", False),
        ("single_choice", "B or C", "B", False),
        ("multi_choice", "C|A", "A|C", True),
        ("multi_choice", "A", "A|C", False),
        ("judgment", "这是正确的", "是", True),
        ("judgment", "不对", "是", False),
        ("judgment", "不确定", "否", False),
        ("open_qa", "合同审查需要法律评估", "合同审查需要法律风险评估", True),
        ("open_qa", "无关", "合同审查需要法律风险评估", False),
    ],
)
def test_is_correct(fmt: str, pred: str, ref: str, ok: bool) -> None:
    assert is_correct(fmt, pred, ref) is ok


def test_same_answer_consensus_and_distance() -> None:
    same = same_answer("multi_choice")
    assert same("A|C", "C,A") and not same("A", "A|C") and not same("", "")
    assert consensus_fn("multi_choice")({"a": "A|C", "b": "C,A", "c": "A, C"})
    assert not consensus_fn("single_choice")({"a": "B", "b": "C"})
    assert not consensus_fn("single_choice")({})
    assert not consensus_fn("single_choice")({"a": "no letter"})
    assert consensus_fn("single_choice")({"a": "B"})
    dist = distance_fn("single_choice")
    assert dist({"a": "B", "b": "B", "c": "C"}) == pytest.approx(1 / 3)
    assert dist({"a": "B", "b": "C", "c": "D"}) == pytest.approx(2 / 3)
    assert dist({"a": "B", "b": "B"}) == 0
    assert dist({}) == 1.0
    assert distance_fn("judgment")({"a": "是", "b": "正确", "c": "否"}) == pytest.approx(1 / 3)
