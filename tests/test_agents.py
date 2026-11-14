"""B2/B3: parser, prompts and the PEX agent on the mock client."""

import asyncio
import json

import pytest

from agents.llm_client import LLMError, MockClient
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
from scheduler import Scheduler, SchedulerConfig, TurnReason

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


def test_turn_result_explains_each_way_a_turn_can_end() -> None:
    ok = PEXAgent(
        "a", persona_for(0), scripted('{"tag": "INIT", "prediction": "A", "explanation": "e"}')
    )
    turn = asyncio.run(ok.take_turn("Q", board_with(msg("b", Tag.INIT))))
    assert turn.reason is TurnReason.OK and turn.draft is not None
    assert len(turn.call_ids) == 1

    nothing = PEXAgent("a", persona_for(0), scripted())
    board = board_with(msg("a", Tag.INIT), msg("b", Tag.INIT), msg("a", Tag.REFUTE, 1))
    turn = asyncio.run(nothing.take_turn("Q", board))
    assert (turn.draft, turn.reason, turn.call_ids) == (None, TurnReason.NO_TARGET, ())

    bad = PEXAgent("a", persona_for(0), scripted("x", "y"))
    turn = asyncio.run(bad.take_turn("Q", board_with(msg("b", Tag.INIT))))
    assert turn.draft is None and turn.reason is TurnReason.PARSE_FAILURE
    assert len(turn.call_ids) == 2 and turn.detail  # the first call and the repair
    legacy = PEXAgent("a", persona_for(0), scripted("x", "y"))
    assert asyncio.run(legacy.act("Q", board_with(msg("b", Tag.INIT)))) is None  # act is unchanged


def test_model_error_is_a_turn_reason_and_keeps_spent_tokens() -> None:
    calls = []

    def respond(messages) -> str:
        calls.append(1)
        if len(calls) == 1:
            return "not json"
        raise LLMError("cannot reach the server")

    agent = PEXAgent("a", persona_for(0), MockClient(responder=respond))
    turn = asyncio.run(agent.take_turn("Q", board_with(msg("b", Tag.INIT))))
    assert turn.draft is None and turn.reason is TurnReason.MODEL_ERROR
    assert "cannot reach" in turn.detail and len(turn.call_ids) == 1
    assert agent.errors == 1 and agent.failures == 0
    assert agent.unposted.completion > 0  # the first call's tokens still count


def test_reply_to_target_answers_the_given_message_not_the_picked_one() -> None:
    reply = '{"tag": "REFUTE", "prediction": "B", "explanation": "no"}'
    board = board_with(
        msg("a", Tag.INIT, prediction="B"),
        msg("b", Tag.INIT, prediction="C"),
        msg("c", Tag.INIT, prediction="D"),
    )
    picked = asyncio.run(PEXAgent("a", persona_for(0), scripted(reply)).take_turn("Q", board))
    assert picked.draft.reply_to == 2  # the normal picker takes the latest unanswered message
    forced = asyncio.run(
        PEXAgent("a", persona_for(0), scripted(reply)).reply_to_target("Q", board, board.events[1])
    )
    assert forced.draft.reply_to == 1 and forced.reason is TurnReason.OK


def test_authored_format_asks_for_a_decision_then_named_values() -> None:
    from agents.prompts import answer_instructions

    text = answer_instructions("authored")
    assert "name=value" in text and "evidence IDs" in text


def test_persona_sets_assign_in_a_fixed_order_and_reject_unknown_names() -> None:
    from agents.prompts import DIVERGENT_PERSONAS

    assert persona_for(0).name == "expert"
    assert persona_for(0, "divergent").name == "contrarian"
    assert persona_for(4, "divergent") is persona_for(0, "divergent")
    assert len({persona_for(i, "divergent").style for i in range(3)}) == 3
    assert set(DIVERGENT_PERSONAS).isdisjoint(PERSONAS)
    with pytest.raises(ValueError, match="unknown persona set"):
        persona_for(0, "nope")


def test_the_dissenter_set_has_one_dissenter_and_two_ordinary_agents() -> None:
    names = [persona_for(i, "dissenter").name for i in range(3)]
    assert names == ["dissenter", "expert", "sceptic"]
    assert "Concede only when" in persona_for(0, "dissenter").style
