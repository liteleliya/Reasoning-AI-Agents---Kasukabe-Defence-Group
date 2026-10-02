"""Parse a model's reply into a PXP message, and build the one repair retry (B2/B3)."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel

TAGS = ("INIT", "RATIFY", "REVISE", "REFUTE", "REJECT", "TERM")
REPLY_TAGS = ("RATIFY", "REVISE", "REFUTE", "REJECT")
FIELDS = ("tag", "prediction", "explanation", "reply_to")


class ParsedMessage(BaseModel):
    tag: str
    prediction: str
    explanation: str
    reply_to: int | None = None


class PXPParseError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> dict:
    """First JSON object in `text`: inside ``` fences if any, else the first balanced {...}."""
    candidates = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    for chunk in candidates:
        start = chunk.find("{")
        while start != -1:
            depth, in_str, escaped = 0, False, False
            for i in range(start, len(chunk)):
                c = chunk[i]
                if in_str:
                    if escaped:
                        escaped = False
                    elif c == "\\":
                        escaped = True
                    elif c == '"':
                        in_str = False
                    continue
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            value = json.loads(chunk[start : i + 1])
                        except json.JSONDecodeError:
                            break
                        if isinstance(value, dict):
                            return value
                        break
            start = chunk.find("{", start + 1)
    raise PXPParseError("no JSON object found; reply with one JSON object only")


def parse_pxp(
    text: str,
    *,
    allowed_tags: tuple[str, ...] = REPLY_TAGS,
    valid_reply_ids: set[int] | None = None,
) -> ParsedMessage:
    """Shape checks only (protocol rules are the validator's job). Raises PXPParseError."""
    data = extract_json(text)
    data = {str(k).strip().lower(): v for k, v in data.items()}
    missing = [f for f in ("tag", "prediction", "explanation") if f not in data]
    if missing:
        raise PXPParseError(f"missing field(s): {', '.join(missing)}")
    tag = str(data["tag"]).strip().upper()
    if tag not in allowed_tags:
        raise PXPParseError(f"tag {data['tag']!r} is not one of {', '.join(allowed_tags)}")
    prediction = _as_text(data["prediction"])
    explanation = _as_text(data["explanation"])
    if not prediction:
        raise PXPParseError("prediction is empty")
    if not explanation:
        raise PXPParseError("explanation is empty")
    reply_to = data.get("reply_to")
    if reply_to in ("", "null", "None"):
        reply_to = None
    if reply_to is not None:
        try:
            reply_to = int(reply_to)
        except (TypeError, ValueError):
            raise PXPParseError(f"reply_to {reply_to!r} is not a message number") from None
        if valid_reply_ids is not None and reply_to not in valid_reply_ids:
            raise PXPParseError(f"reply_to {reply_to} is not one of {sorted(valid_reply_ids)}")
    return ParsedMessage(tag=tag, prediction=prediction, explanation=explanation, reply_to=reply_to)


def _as_text(value: object) -> str:
    if isinstance(value, list):
        value = "|".join(str(v) for v in value)
    return "" if value is None else str(value).strip()


def repair_messages(bad_output: str, error: PXPParseError) -> list[dict]:
    """Turns to append for the single retry: the bad reply, then what was wrong."""
    return [
        {"role": "assistant", "content": bad_output[:2000]},
        {
            "role": "user",
            "content": (
                f"That reply could not be used: {error.reason}. Answer again with exactly one "
                'JSON object and nothing else: {"tag": "...", "prediction": "...", '
                '"explanation": "...", "reply_to": <message number or null>}.'
            ),
        },
    ]
