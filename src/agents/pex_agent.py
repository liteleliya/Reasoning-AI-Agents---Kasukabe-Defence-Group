"""PEX agent (B3): reads the board, asks the model for one PXP message, returns an EventDraft."""

from __future__ import annotations

import logging

from agents.llm_client import BaseLLMClient, TokenUsage
from agents.parsing import PXPParseError, parse_pxp, repair_messages
from agents.prompts import Persona, init_messages, reply_messages
from blackboard import BoardState
from protocol import Event, EventDraft, Tag
from scheduler.mock_agents import unanswered

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
        self.unposted = TokenUsage()  # tokens spent on those replies (still count for H3)

    async def act(self, question: str, board: BoardState) -> EventDraft | None:
        if self.name not in board.latest:
            msgs = init_messages(self.persona, self.name, question, self.n_agents)
            return await self._ask(board, msgs, Tag.INIT, None, ("INIT",))
        target = unanswered(board, self.name)
        if target is None:
            return None
        msgs = reply_messages(
            self.persona,
            self.name,
            question,
            board.events,
            target,
            board.latest[self.name].prediction,
            self.n_agents,
        )
        return await self._ask(board, msgs, None, target, ("RATIFY", "REVISE", "REFUTE", "REJECT"))

    async def _ask(
        self,
        board: BoardState,
        msgs: list[dict],
        force_tag: Tag | None,
        target: Event | None,
        allowed: tuple[str, ...],
    ) -> EventDraft | None:
        label = f"{board.session_id}/{self.name}"
        usage = TokenUsage()
        for attempt in range(2):
            response = await self.client.complete(
                msgs,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                seed=None if self.seed is None else self.seed + board.seq + 1,
                json_mode=True,
                label=label,
            )
            usage = usage + response.usage
            try:
                parsed = parse_pxp(response.text, allowed_tags=allowed)
            except PXPParseError as err:
                if attempt == 0:
                    msgs = [*msgs, *repair_messages(response.text, err)]
                    continue
                self.failures += 1
                self.unposted = self.unposted + usage
                log.warning("%s: unusable reply after retry (%s)", label, err.reason)
                return None
            return EventDraft(
                session_id=board.session_id,
                author=self.name,
                tag=force_tag or Tag(parsed.tag),
                reply_to=None if target is None else target.seq,
                prediction=parsed.prediction,
                explanation=parsed.explanation,
                tokens=usage.as_event(),
                meta={"retried": attempt == 1, "estimated_tokens": usage.estimated},
            )
        return None
