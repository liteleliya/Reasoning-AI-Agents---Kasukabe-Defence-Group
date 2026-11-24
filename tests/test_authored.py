"""Roadmap section 07: the comparison key for authored cases, and the scorer fixtures."""

from pathlib import Path

import pytest

from bench.authored import canonical_prediction, check, judge, parse_prediction
from bench.cases import load_cases

ROOT = Path(__file__).resolve().parents[1] / "data" / "cases"
BOOK = load_cases(ROOT)
P1 = BOOK.public["restore-p1"]
P1_UNBOUNDED = BOOK.public["restore-p1-unbounded"]
SAME_P1, _ = judge(P1, BOOK.grading["restore-p1"])
SAME_UNBOUNDED, _ = judge(P1_UNBOUNDED, BOOK.grading["restore-p1-unbounded"])

B = "B; downtime=2 min; data_loss=30 s; lag_check=before"


def test_prediction_is_read_into_decision_and_canonical_values() -> None:
    parsed = parse_prediction(P1, B)
    assert parsed is not None
    assert parsed.decision == "B"
    assert parsed.values == {"downtime": 120.0, "data_loss": 30.0, "lag_check": "before"}


def test_two_minutes_and_120_seconds_are_the_same_answer() -> None:
    assert SAME_P1(B, "B; downtime=120 seconds; data_loss=0.5 minutes; lag_check=before")


def test_the_decision_and_wording_of_the_decision_are_normalized() -> None:
    assert SAME_P1(B, " b ; downtime = 2 minutes ; data_loss = 30 sec ; lag_check = Before.")


def test_labelled_decisions_and_human_field_labels_canonicalize_at_the_agent_boundary() -> None:
    case = BOOK.public["contractor-access"]
    text = "decision: exception; total days = 95 days; exception signed: yes"
    parsed = parse_prediction(case, text)
    assert parsed is not None and parsed.decision == "exception"
    assert canonical_prediction(case, text) == (
        "exception; total_days=95 days; exception_signed=yes"
    )


def test_the_parser_does_not_silently_correct_an_unknown_action() -> None:
    case = BOOK.public["rollback-release"]
    assert parse_prediction(case, "rollbak; time_to_fix=6 min; drain=before") is None


def test_a_different_decision_is_a_different_answer() -> None:
    assert not SAME_P1(B, "A; downtime=6 min; data_loss=0 s; lag_check=none")


def test_a_required_condition_makes_otherwise_equal_choices_differ() -> None:
    plain = "B; downtime=2 min; lag_check=none"
    conditional = "B; downtime=2 min; lag_check=before"
    assert not SAME_UNBOUNDED(plain, conditional)
    assert SAME_UNBOUNDED(conditional, conditional.replace("2 min", "120 s"))


def test_a_missing_decisive_value_is_unresolved_even_against_itself() -> None:
    text = "B; downtime=2 min; lag_check=before"  # data_loss is decisive in P1 and missing
    assert parse_prediction(P1, text) is None
    assert not SAME_P1(text, text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "C; downtime=2 min; data_loss=30 s; lag_check=before",
        "B; downtime=2; data_loss=30 s; lag_check=before",
        "B; downtime=soon; data_loss=30 s; lag_check=before",
        "B; downtime=2 min; data_loss=30 s; lag_check=maybe",
        "just do B",
    ],
)
def test_invalid_predictions_are_unresolved(text) -> None:
    assert parse_prediction(P1, text) is None
    assert not SAME_P1(text, B)


def test_values_outside_the_decisive_set_do_not_split_agreement() -> None:
    case = BOOK.public["vendor-select"]
    same, _ = judge(case, BOOK.grading["vendor-select"])
    a = "X; total_cost=$49,000; warranty=12 months; delivery=30"
    b = "X; total_cost=49000 USD; warranty=12; delivery=28"
    assert same(a, b)  # delivery is not decisive
    assert not same(a, "X; total_cost=$46,000; warranty=6 months; delivery=30")


def test_semicolon_pipe_and_newline_separators_all_work() -> None:
    assert parse_prediction(P1, "B | downtime=2 min | data_loss=30 s | lag_check=before")
    assert parse_prediction(P1, "B\ndowntime=2 min\ndata_loss=30 s\nlag_check=before")


def test_decision_check_and_fatal_errors() -> None:
    _, correct = judge(P1, BOOK.grading["restore-p1"])
    assert correct(B, "B")
    assert not correct("A; downtime=6 min; data_loss=0 s; lag_check=none", "B")
    zero_loss = "B; downtime=2 min; data_loss=0 s; lag_check=before"
    assert not correct(zero_loss, "B")  # assumes Plan B loses nothing
    assert [v.id for v in check(P1, BOOK.grading["restore-p1"], zero_loss).violations] == [
        "assumed_zero_loss"
    ]


def test_unbounded_variant_accepts_a_conditional_recommendation_only() -> None:
    _, correct = judge(P1_UNBOUNDED, BOOK.grading["restore-p1-unbounded"])
    assert correct("B; downtime=2 min; lag_check=before", "B")
    assert not correct("B; downtime=2 min; lag_check=none", "B")


def test_numeric_bounds_in_fatal_rules() -> None:
    case, grading = BOOK.public["vendor-select"], BOOK.grading["vendor-select"]
    short = check(case, grading, "X; total_cost=46000; warranty=6; delivery=30")
    assert [v.id for v in short.violations] == ["short_warranty"]
    assert not check(case, grading, "X; total_cost=49000; warranty=12; delivery=30").violations


def test_every_case_accepts_its_own_acceptable_answer_shape() -> None:
    for cid, case in BOOK.public.items():
        grading = BOOK.grading[cid]
        decision = grading.acceptable_decisions[0]
        assert decision in case.decisions, cid
