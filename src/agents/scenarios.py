"""Scripted deadlock scenarios (T11 / Package 3.2).

Each scenario is a handful of deterministic agents that react only to the board, plus the one
changed message (`Fix`) that would have avoided the deadlock. Standard agents deadlock
(impasse or cap); with the fix applied they reach consensus on the scenario's answer. Credit
assignment (B6) is validated against these: replaying the fix in the sandbox must score as
helpful (negative credit delta).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from blackboard import BoardState
from protocol import Event, EventDraft, Tag
from scheduler.mock_agents import unanswered

# A policy answers one target message given this agent's current prediction:
# returns (tag, prediction, explanation).
Policy = Callable[[str, Event], tuple[Tag, str, str]]


@dataclass(frozen=True)
class Fix:
    author: str  # whose message to change
    index: int  # which of that author's messages: 0 = its INIT, 1 = its first reply, ...
    tag: str
    prediction: str
    explanation: str


class ScriptedAgent:
    """Opens with `initial`, then answers with `policy`; optionally swaps in one `fix` message."""

    def __init__(
        self,
        name: str,
        initial: tuple[str, str],
        policy: Policy,
        fix: Fix | None = None,
        prefer: str | None = None,
    ):
        self.name = name
        self.initial = initial  # (prediction, explanation)
        self.policy = policy
        self.fix = fix if fix is not None and fix.author == name else None
        self.prefer = prefer  # answer this author's unanswered messages first

    async def act(self, question: str, board: BoardState) -> EventDraft | None:
        sent = sum(1 for e in board.messages if e.author == self.name)
        fixing = self.fix is not None and self.fix.index == sent
        if sent == 0:
            pred, expl = self.initial
            if fixing:
                pred, expl = self.fix.prediction, self.fix.explanation
            return self._draft(board, Tag.INIT, None, pred, expl)
        target = self._preferred(board) or unanswered(board, self.name)
        if target is None:
            return None
        if fixing:
            return self._draft(
                board, Tag(self.fix.tag), target.seq, self.fix.prediction, self.fix.explanation
            )
        tag, pred, expl = self.policy(board.latest[self.name].prediction, target)
        return self._draft(board, tag, target.seq, pred, expl)

    def _preferred(self, board: BoardState) -> Event | None:
        if self.prefer is None:
            return None
        answered = {e.reply_to for e in board.messages if e.author == self.name}
        for e in reversed(board.messages):
            if e.author == self.prefer and e.seq not in answered and e.tag is not Tag.RATIFY:
                return e
        return None

    def _draft(self, board, tag, reply_to, prediction, explanation) -> EventDraft:
        return EventDraft(
            session_id=board.session_id,
            author=self.name,
            tag=tag,
            reply_to=reply_to,
            prediction=prediction,
            explanation=explanation,
        )


# --- policies -------------------------------------------------------------------------------


def stubborn(me: str, t: Event) -> tuple[Tag, str, str]:
    """Keeps its answer: RATIFY agreement, REFUTE everything else."""
    if t.prediction == me:
        return Tag.RATIFY, me, f"agreed, {me}"
    return Tag.REFUTE, me, f"no: the answer is {me}"


def follower(me: str, t: Event) -> tuple[Tag, str, str]:
    """Adopts whatever it answers."""
    if t.prediction == me:
        return Tag.RATIFY, me, f"agreed, {me}"
    return Tag.REVISE, t.prediction, f"convinced: {t.prediction}"


def needs_term(term: str) -> Policy:
    """REJECTs any differing answer whose explanation lacks `term`; with it, it is convinced."""

    def policy(me: str, t: Event) -> tuple[Tag, str, str]:
        if t.prediction == me:
            return Tag.RATIFY, me, f"agreed, {me}"
        if term in t.explanation:
            return Tag.REVISE, t.prediction, f"with {term} explained, {t.prediction}"
        return Tag.REJECT, me, f"I cannot follow this without {term}"

    return policy


def anchored_on(leader: str) -> Policy:
    """Follows `leader` whatever it says; holds firm against everyone else."""

    def policy(me: str, t: Event) -> tuple[Tag, str, str]:
        if t.author == leader:
            return follower(me, t)
        return stubborn(me, t)

    return policy


# --- scenarios ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    name: str
    question: str
    answer: str
    why: str
    fix: Fix | None
    roster: tuple[tuple, ...]  # (name, (pred, expl), policy[, preferred author])

    def agents(self, fixed: bool = False) -> list[ScriptedAgent]:
        fix = self.fix if fixed else None
        return [ScriptedAgent(r[0], r[1], r[2], fix, *r[3:]) for r in self.roster]


SCENARIOS: dict[str, Scenario] = {
    s.name: s
    for s in [
        Scenario(
            name="mutual_refute",
            question="Which reading of the clause is right, x, y or z?",
            answer="y",
            why="a and b each defend their own answer and refute the other forever, while c "
            "adopts whoever spoke last, so the board oscillates and never converges.",
            fix=Fix("a", 1, "REVISE", "y", "y holds: here is the derivation from the clause"),
            roster=(
                ("a", ("x", "x fits the clause"), stubborn),
                ("b", ("y", "y follows from the clause"), stubborn),
                ("c", ("z", "z at first sight"), follower),
            ),
        ),
        Scenario(
            name="jargon_reject",
            question="Is the claim barred, x or y?",
            answer="x",
            why="b rejects every argument that does not explain estoppel, and nobody does, so "
            "b and a exchange REJECT and REFUTE until the impasse window closes.",
            fix=Fix("a", 1, "REFUTE", "x", "x, by estoppel: the party's earlier conduct bars it"),
            roster=(
                ("a", ("x", "x because the claim is barred"), stubborn),
                ("b", ("y", "y because nothing bars it"), needs_term("estoppel")),
                ("c", ("x", "x seems right"), stubborn),
            ),
        ),
        Scenario(
            name="wrong_anchor",
            question="Which stage sets the cost ceiling, w or r?",
            answer="r",
            why="b anchors on a's confident but wrong opening answer; c alone holds the right "
            "answer and is refuted every time, so two agents hold w against one holding r.",
            fix=Fix("a", 0, "INIT", "r", "r: the design stage fixes the cost ceiling"),
            roster=(
                ("a", ("w", "w: procurement sets it, obviously"), stubborn),
                ("b", ("v", "not sure yet"), anchored_on("a"), "a"),
                ("c", ("r", "r: the design stage fixes the cost ceiling"), stubborn),
            ),
        ),
        Scenario(
            name="control",
            question="Which option is right, x, y or z?",
            answer="x",
            why="One agent is sure and the other two follow, so standard agents agree quickly.",
            fix=None,
            roster=(
                ("a", ("x", "x is right"), stubborn),
                ("b", ("y", "y maybe"), follower),
                ("c", ("z", "z maybe"), follower),
            ),
        ),
    ]
}
