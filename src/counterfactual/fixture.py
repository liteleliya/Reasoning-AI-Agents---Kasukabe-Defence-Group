"""Toy three-agent recovery fixture (roadmap section 02).

Plan X takes six minutes, Plan Y takes two, and the limit is four. A insists on X; B and C defend Y.
After message #8 the board stalls at X/Y/Y, and replacing A's #6 with a REVISE that accepts the
four-minute limit brings the sandbox to Y/Y/Y (credit -1/3). The same trace drives the scheduler,
sandbox, metrics and viewer tests, so the known answer lives here and nowhere else.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from agents.ledger import call_scope
from agents.llm_client import MockClient
from agents.pex_agent import PEXAgent
from agents.prompts import persona_for
from blackboard import BoardState, EventStore
from counterfactual.recovery import ReplayRecovery
from counterfactual.sandbox import Alternative
from protocol import Event, EventDraft, Tag
from scheduler import Scheduler, SchedulerConfig

CASE_ID = "toy-recovery-xy"
QUESTION = (
    "Service must be restored within a four-minute downtime limit. "
    "Plan X takes six minutes. Plan Y takes two minutes. Which plan, X or Y?"
)
ANSWER = "Y"
OFF_SESSION = f"{CASE_ID}-off"  # stalls at #8, no recovery
ON_SESSION = f"{CASE_ID}-on"  # replays #6, then A answers #7 for real
TARGET_SEQ = 6  # A's reply that gets replayed
CHALLENGER_SEQ = 7  # B's REFUTE of the target
WINDOW = 3  # a deliberately short impasse window; calibrate the model window separately

# (author, tag, reply_to, prediction, explanation) for the exact stalled prefix, messages #0-#8
_PREFIX = (
    ("A", Tag.INIT, None, "X", "Plan X restores full service, though it takes six minutes."),
    ("B", Tag.INIT, None, "Y", "Plan Y restores service in two minutes."),
    ("C", Tag.INIT, None, "Y", "Plan Y fits inside the downtime limit."),
    ("A", Tag.REFUTE, 1, "X", "Plan X is the safe option; Y cuts corners."),
    ("B", Tag.REFUTE, 3, "Y", "X takes six minutes, which exceeds the four-minute limit."),
    ("C", Tag.RATIFY, 4, "Y", "Agreed: Y is the only plan inside four minutes."),
    ("A", Tag.REFUTE, 4, "X", "I still prefer X; the limit is only a guideline."),
    ("B", Tag.REFUTE, 6, "Y", "The four-minute limit is a hard requirement and X cannot meet it."),
    ("C", Tag.RATIFY, 7, "Y", "Agreed: the limit is hard, so the answer is Y."),
)

ALTERNATIVE = Alternative(
    tag=Tag.REVISE,
    prediction=ANSWER,
    explanation=(
        "You are right: the four-minute limit is binding and Plan X needs six minutes, "
        "so Plan Y at two minutes is the only plan that complies."
    ),
)


def adoption_draft(session_id: str) -> EventDraft:
    """A's real reply to the challenger #7 once the replay showed that conceding helps."""
    return EventDraft(
        session_id=session_id,
        author="A",
        tag=ALTERNATIVE.tag,
        reply_to=CHALLENGER_SEQ,
        prediction=ANSWER,
        explanation=(
            "Acknowledged: the four-minute limit is binding and Plan X needs six minutes, "
            "so I switch to Plan Y."
        ),
        meta={"adopted_counterfactual": True},
    )


def prefix_drafts(session_id: str) -> list[EventDraft]:
    """The exact stalled prefix, ready to append to an empty session."""
    return [
        EventDraft(
            session_id=session_id,
            author=author,
            tag=tag,
            reply_to=reply_to,
            prediction=prediction,
            explanation=explanation,
        )
        for author, tag, reply_to, prediction, explanation in _PREFIX
    ]


@dataclass
class RotatingAgent:
    """Scripted policy: speaks only when `len(messages) % 3 == slot` and never changes its answer.

    It RATIFYs the latest message of the agent it listens to when that message agrees with it and
    REFUTEs otherwise. The fixed speaking order makes the normal scheduler reproduce the roadmap's
    prefix exactly. `swap` is (index of own message, alternative) and puts that alternative in
    place of the message the policy would have sent.
    """

    name: str
    slot: int
    answer: str
    listens_to: str
    said: tuple[str, ...]  # explanation of each of its own messages, in order
    swap: tuple[int, Alternative] | None = None
    counterfactual: bool = False  # may the recovery checkpoint replay this agent's replies?

    async def act(self, question: str, board: BoardState) -> EventDraft | None:
        messages = board.messages
        if len(messages) % 3 != self.slot:
            return None
        sent = sum(1 for e in messages if e.author == self.name)
        if sent == 0:
            return self._draft(board, Tag.INIT, None, self.answer, self.said[0])
        heard = [e for e in messages if e.author == self.listens_to]
        if not heard:
            return None
        target = heard[-1]
        if self.swap is not None and self.swap[0] == sent:
            alt = self.swap[1]
            return self._draft(board, alt.tag, target.seq, alt.prediction or "", alt.explanation)
        return self._reply(board, target, sent)

    async def reply_to_target(self, question: str, board: BoardState, target: Event) -> EventDraft:
        """Answer `target` whatever the turn order is; used by the sandbox branches."""
        sent = sum(1 for e in board.messages if e.author == self.name)
        return self._reply(board, target, sent)

    def _reply(self, board: BoardState, target: Event, sent: int) -> EventDraft:
        tag = Tag.RATIFY if target.prediction == self.answer else Tag.REFUTE
        explanation = self.said[min(sent, len(self.said) - 1)]
        return self._draft(board, tag, target.seq, self.answer, explanation)

    def _draft(
        self, board: BoardState, tag: Tag, reply_to: int | None, prediction: str, explanation: str
    ) -> EventDraft:
        return EventDraft(
            session_id=board.session_id,
            author=self.name,
            tag=tag,
            reply_to=reply_to,
            prediction=prediction,
            explanation=explanation,
        )


def agents(fixed: bool = False, enabled: tuple[str, ...] = ()) -> list[RotatingAgent]:
    """A, B and C. With `fixed`, A's third message (#6) is the alternative instead of a REFUTE.

    `enabled` names the agents whose replies the recovery checkpoint may replay.
    """

    def said(name: str) -> tuple[str, ...]:
        return tuple(row[4] for row in _PREFIX if row[0] == name)

    swap = (2, ALTERNATIVE) if fixed else None
    return [
        RotatingAgent("A", 0, "X", "B", said("A"), swap, "A" in enabled),
        RotatingAgent("B", 1, "Y", "A", said("B"), None, "B" in enabled),
        RotatingAgent("C", 2, "Y", "B", said("C"), None, "C" in enabled),
    ]


def scheduler_config() -> SchedulerConfig:
    return SchedulerConfig(impasse_window=WINDOW)


def build_handoff_db(path: str | Path) -> EventStore:
    """Write the two demo sessions to a fresh store, both through the normal scheduler.

    Only the recovery policy differs: the off session stalls at #8 and ends in an impasse, and the
    on session replays #6, adopts the replacement as a real reply to #7 and reaches consensus.
    """
    store = EventStore(path)
    candidate = json.dumps(
        {"tag": "REVISE", "prediction": ANSWER, "explanation": ALTERNATIVE.explanation}
    )
    author = PEXAgent("A", persona_for(0), MockClient(responder=lambda _: candidate), n_agents=3)
    recovery = ReplayRecovery(store, {"A": author}, lambda: [a for a in agents() if a.name != "A"])
    for session_id, policy in ((OFF_SESSION, None), (ON_SESSION, recovery)):
        scheduler = Scheduler(store, agents(enabled=("A",)), scheduler_config(), recovery=policy)
        with call_scope(trial=session_id):
            asyncio.run(scheduler.run(session_id, QUESTION))
    return store


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Write the stalled and recovered fixture sessions."
    )
    parser.add_argument("--db", type=Path, default=Path("results/roadmap_fixture.sqlite"))
    args = parser.parse_args(argv)
    if args.db.exists():
        parser.error(f"{args.db} already exists; delete it or choose another --db")
    args.db.parent.mkdir(parents=True, exist_ok=True)
    build_handoff_db(args.db).close()
    print(f"wrote {OFF_SESSION} and {ON_SESSION} to {args.db}")
    print(f"view: uv run python -m server --db {args.db}")


if __name__ == "__main__":
    main()
