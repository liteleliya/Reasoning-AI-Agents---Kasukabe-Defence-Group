"""Roadmap section 07: a productive revision answers a challenge with a supported change that
lowers the group's distance soon after, kept apart from the legacy Strong/Ultra-Strong labels."""

from blackboard import EventStore
from protocol import EventDraft, Tag
from scheduler import exact_distance

SID = "s"


def board(*rows):
    """rows: (author, tag, reply_to, prediction[, explanation]) appended in order."""
    store = EventStore()
    for n, (author, tag, reply_to, prediction, *rest) in enumerate(rows):
        store.append_sync(
            EventDraft(
                session_id=SID,
                author=author,
                tag=tag,
                reply_to=reply_to,
                prediction=prediction,
                explanation=rest[0] if rest else f"reason {n} from {author}",
            )
        )
    return store.events(SID)


def count(events, **kw) -> int:
    from bench.revision import productive_revisions

    return productive_revisions(events, exact_distance, **kw)


OPEN = [
    ("a", Tag.INIT, None, "X"),
    ("b", Tag.INIT, None, "Y"),
    ("c", Tag.INIT, None, "Y"),
    ("a", Tag.REFUTE, 1, "X"),  # 3: challenges b
    ("b", Tag.REFUTE, 3, "Y"),  # 4: challenges a
]


def test_a_supported_change_after_a_challenge_that_lowers_distance_counts() -> None:
    events = board(*OPEN, ("a", Tag.REVISE, 4, "Y"), ("c", Tag.RATIFY, 5, "Y"))
    assert count(events) == 1


def test_a_revision_that_answers_no_challenge_does_not_count() -> None:
    events = board(*OPEN, ("c", Tag.RATIFY, 1, "Y"), ("a", Tag.REVISE, 2, "Y"))
    assert count(events) == 0  # #2 is an INIT, not a challenge


def test_repeating_the_same_answer_is_not_a_substantive_change() -> None:
    events = board(*OPEN, ("a", Tag.REFUTE, 4, "X"), ("b", Tag.REFUTE, 5, "Y"))
    assert count(events) == 0


def test_a_change_that_repeats_the_old_reasoning_is_not_supported() -> None:
    old = "reason 3 from a"  # what `board` gave a's previous message, #3
    events = board(*OPEN, ("a", Tag.REVISE, 4, "Y", old))
    assert count(events) == 0
    assert count(board(*OPEN, ("a", Tag.REVISE, 4, "Y", "new reasoning from E2"))) == 1


def test_a_change_that_does_not_help_the_group_does_not_count() -> None:
    events = board(
        *OPEN,
        ("a", Tag.REVISE, 4, "Z"),  # a moves to a third answer; b and c still agree
        ("b", Tag.REFUTE, 5, "Y"),
        ("c", Tag.RATIFY, 6, "Y"),
        ("a", Tag.REFUTE, 7, "Z"),
    )
    assert count(events) == 0


def test_help_must_come_within_the_window() -> None:
    late = board(
        ("a", Tag.INIT, None, "X"),
        ("b", Tag.INIT, None, "Y"),
        ("c", Tag.INIT, None, "Z"),
        ("a", Tag.REFUTE, 1, "X"),  # 3: challenges b
        ("c", Tag.REFUTE, 3, "Z"),  # 4: challenges a
        ("b", Tag.REVISE, 4, "W"),  # 5: changes, still three different answers
        ("a", Tag.REFUTE, 5, "X"),  # 6
        ("c", Tag.REFUTE, 5, "Z"),  # 7
        ("a", Tag.REFUTE, 7, "X"),  # 8
        ("c", Tag.REVISE, 8, "X"),  # 9: helps, but it is the 4th message after #5
    )
    assert count(late) == 1  # only #9 itself, which lowers the distance at once
    assert count(late, window=4) == 2  # #5 counts once the window reaches #9


def test_a_consensus_stop_inside_the_window_counts() -> None:
    store = EventStore()
    for d in board(*OPEN, ("a", Tag.REVISE, 4, "Y")):
        store.append_sync(
            EventDraft(
                session_id="t",
                author=d.author,
                tag=d.tag,
                reply_to=d.reply_to,
                prediction=d.prediction,
                explanation=d.explanation,
            )
        )
    store.append_sync(
        EventDraft(session_id="t", author="system", tag=Tag.TERM, explanation="consensus")
    )
    from bench.revision import productive_revisions

    assert productive_revisions(store.events("t"), exact_distance) == 1


def test_counterfactual_messages_are_ignored() -> None:
    store = EventStore()
    for author, tag, reply_to, prediction in OPEN:
        store.append_sync(
            EventDraft(
                session_id=SID,
                author=author,
                tag=tag,
                reply_to=reply_to,
                prediction=prediction,
                explanation="x",
            )
        )
    store.append_sync(
        EventDraft(
            session_id=SID,
            author="a",
            tag=Tag.REVISE,
            reply_to=4,
            prediction="Y",
            explanation="sandbox only",
            counterfactual=True,
        )
    )
    assert count(store.events(SID)) == 0


def test_the_comparator_decides_what_counts_as_a_change() -> None:
    events = board(*OPEN, ("a", Tag.REVISE, 4, "y"), ("c", Tag.RATIFY, 5, "Y"))
    assert count(events, same=lambda p, q: p.lower() == q.lower()) == 1
    stubborn = board(*OPEN, ("a", Tag.REVISE, 4, "x2"), ("c", Tag.RATIFY, 5, "Y"))
    assert count(stubborn, same=lambda p, q: p[0] == q[0]) == 0  # "x2" is still X
