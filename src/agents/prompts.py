"""Personas and prompt templates for PEX agents (B2).

Tag wording follows the paper's guard table (spec section 1) and lives in TAG_RULES only, so it
can change in one place if the spec changes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from protocol import Event, Kind


@dataclass(frozen=True)
class Persona:
    name: str
    style: str


PERSONAS: dict[str, Persona] = {
    p.name: p
    for p in [
        Persona(
            "expert",
            "You are a senior domain practitioner. You trust concrete professional practice and "
            "regulations over general arguments, and you say so when an argument ignores how the "
            "work is actually done.",
        ),
        Persona(
            "sceptic",
            "You are a careful sceptic. You look for the weakest step in every argument, including "
            "your own, and you only accept a claim when its reasoning holds up step by step.",
        ),
        Persona(
            "synthesiser",
            "You are a synthesiser. You look for what the different positions get right and try to "
            "combine them, but you will not agree to an answer you think is wrong.",
        ),
        Persona(
            "literalist",
            "You are a literalist. You read the question and every option word by word and hold "
            "others to exactly what is asked, not to what they think was meant.",
        ),
    ]
}


def persona_for(index: int) -> Persona:
    """Personas assigned in a fixed order, so agent i always gets the same one."""
    names = list(PERSONAS)
    return PERSONAS[names[index % len(names)]]


TAG_RULES = """\
When you reply to a message, compare your own answer and reasoning with it:
- RATIFY: your answer is the same AND you accept their reasoning.
- REVISE: their message changed your mind; you now give an answer and reasoning that agree with theirs.
- REFUTE: you agree with part of it (the answer or the reasoning) but not all; keep your answer and give the corrective information.
- REJECT: your answer differs AND their reasoning does not hold up for you."""

ANSWER_FORMATS = {
    "single_choice": 'Your "prediction" is exactly one option letter, e.g. "B".',
    "multi_choice": 'Your "prediction" lists every correct option letter joined by "|", e.g. "A|C".',
    "judgment": 'Your "prediction" is exactly "是" (true) or "否" (false).',
    "open_qa": 'Your "prediction" is your answer in at most 60 words.',
}


def answer_instructions(fmt: str) -> str:
    return ANSWER_FORMATS.get(fmt, ANSWER_FORMATS["open_qa"])


def system_prompt(persona: Persona, agent_id: str, n_agents: int | None = None) -> str:
    others = f" with {n_agents - 1} other agents" if n_agents else " with other agents"
    return f"""\
You are {agent_id}, one of several agents answering the same question together{others} on a shared board.
{persona.style}

Each turn you post ONE message as a JSON object and nothing else:
{{"tag": "...", "prediction": "...", "explanation": "...", "reply_to": <message number or null>}}

{TAG_RULES}

"explanation" gives your reasoning in at most 80 words. "reply_to" is the number of the message you answer.
Do not copy other agents' wording; think for yourself, and change your answer only when you are convinced."""


def render_event(e: Event) -> str:
    reply = f" (to {e.reply_to})" if e.reply_to is not None else ""
    return f"[{e.seq}] {e.author} {e.tag}{reply}: {e.prediction} | {e.explanation}"


def render_board(events: Sequence[Event], max_events: int = 12) -> str:
    real = [e for e in events if e.kind is Kind.MESSAGE and not e.counterfactual and e.tag]
    real = [e for e in real if e.author != "system"]
    shown = real[-max_events:]
    head = f"(… {len(real) - len(shown)} earlier messages)\n" if len(real) > len(shown) else ""
    return head + "\n".join(render_event(e) for e in shown) if shown else "(empty)"


def init_messages(persona: Persona, agent_id: str, question: str, n_agents: int | None = None):
    return [
        {"role": "system", "content": system_prompt(persona, agent_id, n_agents)},
        {
            "role": "user",
            "content": f"Question:\n{question}\n\nThe board is empty. Post your opening message: "
            'tag "INIT", your prediction and explanation, reply_to null.',
        },
    ]


def reply_messages(
    persona: Persona,
    agent_id: str,
    question: str,
    board: Sequence[Event],
    target: Event,
    own_prediction: str,
    n_agents: int | None = None,
    max_events: int = 12,
    notes: Sequence[str] = (),
):
    lessons = "".join(f"\nNote to yourself: {n}" for n in notes)
    return [
        {"role": "system", "content": system_prompt(persona, agent_id, n_agents)},
        {
            "role": "user",
            "content": f"Question:\n{question}\n\nBoard so far:\n{render_board(board, max_events)}"
            f"\n\nYour current prediction: {own_prediction}{lessons}\n"
            f"Reply to message [{target.seq}] by {target.author}:\n{render_event(target)}\n\n"
            f"Use tag RATIFY, REVISE, REFUTE or REJECT, and reply_to {target.seq}.",
        },
    ]


def counterfactual_messages(
    persona: Persona,
    agent_id: str,
    question: str,
    board_before: Sequence[Event],
    original: Event,
    new_tag: str,
    n_agents: int | None = None,
):
    """Ask the agent to rewrite one of its past messages with a different tag (for the sandbox)."""
    return [
        {"role": "system", "content": system_prompt(persona, agent_id, n_agents)},
        {
            "role": "user",
            "content": f"Question:\n{question}\n\nBoard before your message:\n"
            f"{render_board(board_before)}\n\nYou posted:\n{render_event(original)}\n\n"
            f"That exchange went nowhere. Write a different version of that message with tag "
            f"{new_tag}, replying to message {original.reply_to}. Give a new explanation that "
            "could actually persuade the other agent, rather than repeating your earlier one.",
        },
    ]
