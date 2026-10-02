"""B2/B3: parser, prompts and the PEX agent on the mock client."""

import asyncio
import json

import pytest

from agents.llm_client import MockClient
from agents.parsing import PXPParseError, extract_json, parse_pxp, repair_messages
from agents.pex_agent import PEXAgent
from agents.prompts import (
    PERSONAS,
    TAG_RULES,
    answer_instructions,
    counterfactual_messages,
    init_messages,
    persona_for,
    render_board,
    reply_messages,
)
from blackboard import EventStore
from protocol import EventDraft, Tag
from scheduler import Scheduler, SchedulerConfig

GOOD = '{"tag": "REFUTE", "prediction": "B", "explanation": "because", "reply_to": 3}'


@pytest.mark.parametrize(
    "text",
    [
        GOOD,
        f"Sure! Here you go:\n```json\n{GOOD}\n```\nHope that helps.",
        f"My reply is {GOOD} as requested.",
        GOOD.replace("REFUTE", " refute ").replace('"tag"', '"Tag"'),
        '{"tag": "REFUTE", "prediction": "B", "explanation": "a \\"quoted\\" {brace}", '
        '"reply_to": "3"}',
    ],
)
def test_parse_variants(text: str) -> None:
    m = parse_pxp(text, valid_reply_ids={1, 3})
    assert (m.tag, m.prediction, m.reply_to) == ("REFUTE", "B", 3)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("no json here", "no JSON object"),
        ('{"tag": "REFUTE", "prediction": "B"}', "missing field(s): explanation"),
        ('{"tag": "AGREE", "prediction": "B", "explanation": "x"}', "not one of"),
        ('{"tag": "RATIFY", "prediction": "", "explanation": "x"}', "prediction is empty"),
        ('{"tag": "RATIFY", "prediction": "B", "explanation": "x", "reply_to": 9}', "not one of"),
        (
            '{"tag": "RATIFY", "prediction": "B", "explanation": "x", "reply_to": "abc"}',
            "not a message number",
        ),
        ('{"tag": "RATIFY", "prediction": "B", "explanation": "x"', "no JSON object"),
    ],
)
def test_parse_errors(text: str, reason: str) -> None:
    with pytest.raises(PXPParseError) as exc:
        parse_pxp(text, valid_reply_ids={1, 3})
    assert reason in exc.value.reason


def test_extract_json_and_lists() -> None:
    assert extract_json('[1, 2] then {"a": {"b": 1}}') == {"a": {"b": 1}}
    m = parse_pxp(
        '{"tag": "INIT", "prediction": ["A", "C"], "explanation": "x"}', allowed_tags=("INIT",)
    )
    assert m.prediction == "A|C" and m.reply_to is None


def test_repair_messages_quote_the_error() -> None:
    turns = repair_messages("garbage", PXPParseError("no JSON object found"))
    assert turns[0] == {"role": "assistant", "content": "garbage"}
    assert "no JSON object found" in turns[1]["content"]


def test_prompts() -> None:
    assert len(PERSONAS) == 4 and persona_for(5) == persona_for(1)
    msgs = init_messages(persona_for(0), "a", "Which?", 3)
    system = msgs[0]["content"]
    for tag in ("RATIFY", "REVISE", "REFUTE", "REJECT"):
        assert tag in system
    assert TAG_RULES in system and "2 other agents" in system
    assert "INIT" in msgs[1]["content"]
    assert "A|C" in answer_instructions("multi_choice")
    assert answer_instructions("unknown") == answer_instructions("open_qa")


def board_with(*drafts):
    store = EventStore()
    for d in drafts:
        store.append_sync(d)
    return store.state("s")


def msg(author, tag, reply_to=None, prediction="x", **kw):
    return EventDraft(
        session_id="s",
        author=author,
        tag=tag,
        reply_to=reply_to,
        prediction=prediction,
        explanation="because",
        **kw,
    )


def test_board_rendering_hides_counterfactuals() -> None:
    board = board_with(
        msg("a", Tag.INIT),
        msg("b", Tag.INIT, prediction="y"),
        msg("a", Tag.REFUTE, 1, counterfactual=True),
    )
    text = render_board(board.events)
    assert "[0] a INIT: x | because" in text and "[1] b INIT: y" in text
    assert "REFUTE" not in text
    reply = reply_messages(persona_for(1), "a", "Q", board.events, board.events[1], "x")
    assert "Reply to message [1] by b" in reply[1]["content"]
    cf = counterfactual_messages(
        persona_for(1), "a", "Q", board.events[:1], board.events[1], "REVISE"
    )
    assert "tag REVISE" in cf[1]["content"]


def scripted(*texts):
    """A mock client that returns the given replies in order."""
    queue = list(texts)
    return MockClient(responder=lambda msgs: queue.pop(0))


def test_agent_init_then_reply_forces_tag_and_target() -> None:
    client = scripted(
        '{"tag": "RATIFY", "prediction": "B", "explanation": "opening"}',  # wrong tag for INIT
        '{"tag": "REFUTE", "prediction": "B", "explanation": "no", "reply_to": 0}',
    )
    agent = PEXAgent("a", persona_for(0), client)
    first = asyncio.run(agent.act("Q", board_with(msg("b", Tag.INIT, prediction="C"))))
    assert first is None  # RATIFY is not allowed for an opening message, even after retry
    client = scripted(
        '{"tag": "INIT", "prediction": "B", "explanation": "opening"}',
        '{"tag": "REFUTE", "prediction": "B", "explanation": "no", "reply_to": 0}',
    )
    agent = PEXAgent("a", persona_for(0), client)
    board = board_with(msg("b", Tag.INIT, prediction="C"))
    init = asyncio.run(agent.act("Q", board))
    assert (init.tag, init.reply_to, init.prediction) == (Tag.INIT, None, "B")
    board = board_with(
        msg("b", Tag.INIT, prediction="C"),
        msg("a", Tag.INIT, prediction="B"),
        msg("b", Tag.REJECT, 1, prediction="C"),
    )
    reply = asyncio.run(agent.act("Q", board))
    assert (reply.tag, reply.reply_to) == (Tag.REFUTE, 2)  # target forced to b's latest
    assert reply.tokens.out > 0


def test_agent_retries_once_and_sums_tokens() -> None:
    client = scripted("not json at all", '{"tag": "INIT", "prediction": "A", "explanation": "e"}')
    agent = PEXAgent("a", persona_for(0), client)
    draft = asyncio.run(agent.act("Q", board_with(msg("b", Tag.INIT))))
    assert draft.meta["retried"] is True
    assert draft.tokens.out == 3 + 7  # both calls count
    bad = PEXAgent("a", persona_for(0), scripted("x", "y"))
    assert asyncio.run(bad.act("Q", board_with(msg("b", Tag.INIT)))) is None
    assert bad.failures == 1 and bad.unposted.completion == 2


def test_agent_passes_when_nothing_to_answer() -> None:
    agent = PEXAgent("a", persona_for(0), scripted())
    board = board_with(msg("a", Tag.INIT), msg("b", Tag.INIT), msg("a", Tag.REFUTE, 1))
    assert asyncio.run(agent.act("Q", board)) is None


def follower_model(messages):
    """A fake model: opens with its own letter, then adopts whatever it is shown."""
    user = messages[-1].content
    if "board is empty" in user:
        letter = "ABC"[hash(messages[0].content) % 3]
        return json.dumps({"tag": "INIT", "prediction": letter, "explanation": "first guess"})
    shown = user.split("Reply to message [", 1)[1].split(": ", 1)[1].split(" |")[0]
    return json.dumps({"tag": "REVISE", "prediction": shown, "explanation": "convinced"})


def test_three_pex_agents_finish_a_session_on_the_scheduler() -> None:
    client = MockClient(responder=follower_model)
    agents = [PEXAgent(n, persona_for(i), client, n_agents=3) for i, n in enumerate("abc")]
    store = EventStore()
    result = asyncio.run(Scheduler(store, agents, SchedulerConfig()).run("s", "Pick A, B or C"))
    assert result.stop_reason in ("consensus", "impasse")
    assert result.rejected == []
    assert sum(e.tokens.in_ for e in store.events("s")) == client.total_usage("s/").prompt
