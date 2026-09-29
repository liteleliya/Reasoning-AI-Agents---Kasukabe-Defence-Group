"""A4: tag state machine and intelligibility classifier on scripted tag logs."""

import json
from pathlib import Path

import pytest

from protocol import (
    Event,
    Intelligibility,
    Kind,
    Tag,
    choose_tag,
    classify,
    is_compatible,
)

FIXTURES = sorted((Path(__file__).parent / "fixtures" / "pxp_sequences").glob("*.json"))


def to_events(rows: list[dict], **overrides) -> list[Event]:
    return [
        Event(
            seq=i,
            session_id="s",
            author=r["author"],
            tag=r["tag"],
            reply_to=r["reply_to"],
            prediction="p",
            explanation="e",
            **overrides,
        )
        for i, r in enumerate(rows)
    ]


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_scripted_logs(path: Path) -> None:
    fixture = json.loads(path.read_text())
    assert classify(to_events(fixture["events"])).label == fixture["expected"], fixture["source"]


def test_fixture_set_covers_every_class() -> None:
    expected = {json.loads(p.read_text())["expected"] for p in FIXTURES}
    assert expected == {c.value for c in Intelligibility}


def test_report_details() -> None:
    fixture = json.loads((FIXTURES[0].parent / "paper_human_teaching.json").read_text())
    report = classify(to_events(fixture["events"]))
    assert [(p.sender, p.receiver, p.tags, p.one_way) for p in report.pairs] == [
        ("h", "m", (Tag.REFUTE, Tag.RATIFY), True),
        ("m", "h", (Tag.REVISE,), True),
    ]
    assert report.revises == 1
    assert report.two_way_pairs == [("h", "m")]


def test_rollbacks_and_counterfactuals_are_ignored() -> None:
    rows = [
        {"author": "a", "tag": "INIT", "reply_to": None},
        {"author": "b", "tag": "INIT", "reply_to": None},
        {"author": "b", "tag": "RATIFY", "reply_to": 0},
    ]
    events = to_events(rows)
    replay = Event(
        seq=3,
        session_id="s",
        author="a",
        kind=Kind.ROLLBACK_STEP,
        tag=Tag.REJECT,
        counterfactual=True,
    )
    cf_message = Event(
        seq=4,
        session_id="s",
        author="a",
        tag=Tag.REVISE,
        reply_to=2,
        prediction="p",
        explanation="e",
        counterfactual=True,
    )
    report = classify([*events, replay, cf_message])
    assert report.label is Intelligibility.STRONG
    assert report.revises == 0


@pytest.mark.parametrize(
    ("match", "agree", "aligned", "tag"),
    [
        (True, True, False, Tag.RATIFY),
        (False, False, True, Tag.REJECT),
        (True, False, False, Tag.REFUTE),
        (True, False, True, Tag.REVISE),
        (False, True, False, Tag.REFUTE),
        (False, True, True, Tag.REVISE),
    ],
)
def test_choose_tag_follows_paper_guards(match: bool, agree: bool, aligned: bool, tag: Tag) -> None:
    assert choose_tag(match, agree, aligned) is tag


def test_compatible_transitions() -> None:
    assert is_compatible(Tag.REFUTE, Tag.REVISE)
    assert is_compatible(Tag.INIT, Tag.REJECT)
    assert is_compatible(Tag.RATIFY, Tag.RATIFY)
    assert not is_compatible(Tag.RATIFY, Tag.REFUTE)
    assert not is_compatible(Tag.REVISE, Tag.REVISE)
    assert not is_compatible(Tag.REJECT, Tag.RATIFY)
    assert all(is_compatible(t, Tag.TERM) for t in Tag)
