"""PXP tag rules from the paper (Appendix A, Def. 5 and Table 4; Prop. 5)."""

from __future__ import annotations

from protocol.schema import Tag

# Replies a *compatible* agent can send to each tag (paper Prop. 5), besides TERM.
# Tags not listed (INIT, REFUTE) may be answered with any reply tag.
COMPATIBLE_REPLIES: dict[Tag, frozenset[Tag]] = {
    Tag.RATIFY: frozenset({Tag.RATIFY}),
    Tag.REVISE: frozenset({Tag.RATIFY}),
    Tag.REJECT: frozenset({Tag.REJECT}),
}


def choose_tag(match: bool, agree: bool, aligned_after_learning: bool = False) -> Tag:
    """The tag the paper's guards select when replying to another agent's message.

    match: own prediction MATCHes theirs. agree: own explanation AGREEs with theirs.
    aligned_after_learning: after LEARNing from their message, the new prediction matches AND the
    new explanation agrees (guard g'). Only used in the mixed cases.
    """
    if match and agree:
        return Tag.RATIFY
    if not match and not agree:
        return Tag.REJECT
    return Tag.REVISE if aligned_after_learning else Tag.REFUTE


def is_compatible(previous: Tag, reply: Tag) -> bool:
    """Whether `reply` to a `previous` message is possible between compatible agents."""
    if reply is Tag.TERM:
        return True
    allowed = COMPATIBLE_REPLIES.get(previous)
    return allowed is None or reply in allowed
