"""PEX agent (B3): reads the board, asks the model for one PXP message, returns an EventDraft."""

from __future__ import annotations

import logging

from agents.ledger import call_scope
from agents.llm_client import BaseLLMClient, LLMError, TokenUsage
from agents.parsing import PXPParseError, parse_pxp, repair_messages
from agents.prompts import Persona, init_messages, reply_messages
from blackboard import BoardState
from protocol import Event, EventDraft, Tag
from scheduler.mock_agents import unanswered
from scheduler.recovery import TurnReason, TurnResult

log = logging.getLogger(__name__)


class PEXAgent:
    """An LLM-backed agent for the scheduler.

    INIT first; afterwards it answers the latest real message by another agent that it has not
    replied to (RATIFYs are skipped). One repair retry on an unparseable reply, then it passes.
    """

    def __init__(
        self,
        name: str,
        persona: Persona,
        client: BaseLLMClient,
        *,
        counterfactual: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 400,
        seed: int | None = None,
        n_agents: int | None = None,
    ) -> None:
        self.name = name
        self.persona = persona
        self.client = client
        self.counterfactual = counterfactual
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.seed = seed
        self.n_agents = n_agents
        self.failures = 0  # replies that stayed unparseable after the retry
        self.errors = 0  # turns lost to a model error
        self.unposted = TokenUsage()  # tokens spent on those replies (still count for H3)
        self.notes: list[str] = []  # lessons carried into the next prompts (credit assignment)

    async def act(self, question: str, board: BoardState) -> EventDraft | None:
        return (await self.take_turn(question, board)).draft

    async def take_turn(self, question: str, board: BoardState) -> TurnResult:
        """Like `act`, but says why no message came out and which model calls were made."""
        if self.name not in board.latest:
            msgs = init_messages(self.persona, self.name, question, self.n_agents)
            return await self._ask(board, msgs, Tag.INIT, None, ("INIT",))
        target = unanswered(board, self.name)
        if target is None:
            return TurnResult(None, TurnReason.NO_TARGET)
        return await self.reply_to_target(question, board, target)

    async def reply_to_target(
        self, question: str, board: BoardState, target: Event, *, rethink: bool = False
    ) -> TurnResult:
        """Answer `target` itself instead of the message the normal picker would choose.

        With `rethink`, the prompt says the agent's earlier reply was challenged (forward repair).
        """
        msgs = reply_messages(
            self.persona,
            self.name,
            question,
            board.events,
            target,
            board.latest[self.name].prediction,
            self.n_agents,
            notes=self.notes,
            rethink=rethink,
        )
        return await self._ask(board, msgs, None, target, ("RATIFY", "REVISE", "REFUTE", "REJECT"))

    async def _ask(
        self,
        board: BoardState,
        msgs: list[dict],
        force_tag: Tag | None,
        target: Event | None,
        allowed: tuple[str, ...],
    ) -> TurnResult:
        label = f"{board.session_id}/{self.name}"
        usage = TokenUsage()
        call_ids: list[str] = []
        for attempt in range(2):
            try:
                with call_scope(
                    session_id=board.session_id,
                    agent=self.name,
                    parent_seq=None if target is None else target.seq,
                    repair=attempt == 1,
                ):
                    response = await self.client.complete(
                        msgs,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        seed=None if self.seed is None else self.seed + board.seq + 1,
                        json_mode=True,
                        label=label,
                    )
            except LLMError as err:
                self.errors += 1
                self.unposted = self.unposted + usage
                log.warning("%s: model error (%s)", label, err)
                return TurnResult(None, TurnReason.MODEL_ERROR, str(err), tuple(call_ids))
            usage = usage + response.usage
            call_ids.append(response.call_id)
            try:
                parsed = parse_pxp(response.text, allowed_tags=allowed)
            except PXPParseError as err:
                if attempt == 0:
                    msgs = [*msgs, *repair_messages(response.text, err)]
                    continue
                self.failures += 1
                self.unposted = self.unposted + usage
                log.warning("%s: unusable reply after retry (%s)", label, err.reason)
                return TurnResult(None, TurnReason.PARSE_FAILURE, err.reason, tuple(call_ids))
            draft = EventDraft(
                session_id=board.session_id,
                author=self.name,
                tag=force_tag or Tag(parsed.tag),
                reply_to=None if target is None else target.seq,
                prediction=parsed.prediction,
                explanation=parsed.explanation,
                tokens=usage.as_event(),
                meta={
                    "retried": attempt == 1,
                    "estimated_tokens": usage.estimated,
                    "call_ids": call_ids,
                },
            )
            return TurnResult(draft, TurnReason.OK, call_ids=tuple(call_ids))
        raise AssertionError("unreachable")
