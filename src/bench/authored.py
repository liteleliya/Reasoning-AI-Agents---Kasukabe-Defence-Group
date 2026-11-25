"""Agreement and decision checks for authored cases (roadmap section 07).

An agent's prediction is `decision; name=value; ...`. The decision is matched against the case's
public action vocabulary, and each value is normalized (durations to seconds, amounts without
currency marks or separators) so "2 min" and "120 s" are the same answer. Two predictions agree
when their decisions and every decisive value match. A missing or invalid required part makes the
prediction unresolved, and an unresolved prediction agrees with nothing, not even itself.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from bench.cases import Field, GradingRecord, PublicCase

_SEPARATORS = re.compile(r"[;|\n]")
_NUMBER = re.compile(r"^\s*([-+]?\d[\d,]*\.?\d*)\s*([^\d\s].*?)?\s*$")
_DECISION_LABEL = re.compile(
    r"^(?:decision|action|recommendation|answer|option)\s*[:=]\s*(.+)$", re.I
)
_NAME = re.compile(r"[^a-z0-9]+")
_SECONDS = {
    **dict.fromkeys(("s", "sec", "secs", "second", "seconds"), 1.0),
    **dict.fromkeys(("m", "min", "mins", "minute", "minutes"), 60.0),
    **dict.fromkeys(("h", "hr", "hrs", "hour", "hours"), 3600.0),
    **dict.fromkeys(("d", "day", "days"), 86400.0),
}
_BOOLEANS = {"yes": True, "true": True, "no": False, "false": False}


@dataclass(frozen=True)
class Parsed:
    decision: str
    values: dict[str, Any]

    def key(self, case: PublicCase) -> tuple:
        decisive = tuple((f.name, _round(self.values[f.name])) for f in case.fields if f.decisive)
        return (self.decision, decisive)


@dataclass(frozen=True)
class Violation:
    id: str
    description: str


@dataclass(frozen=True)
class Check:
    parsed: Parsed | None
    decision_ok: bool
    violations: tuple[Violation, ...]

    @property
    def passed(self) -> bool:
        return self.decision_ok and not self.violations


def _name(text: str) -> str:
    """A field label in a model reply, independent of spaces, hyphens or casing."""
    return _NAME.sub("_", text.lower()).strip("_")


def _round(value: Any) -> Any:
    return round(value, 6) if isinstance(value, float) else value


def _number(text: str) -> tuple[float, str] | None:
    m = _NUMBER.match(text.replace("$", ""))
    if not m:
        return None
    try:
        amount = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return amount, (m.group(2) or "").strip().rstrip(".").lower()


def _value(field: Field, text: str) -> Any:
    """The canonical value of `text` for `field`, or None if it does not fit."""
    text = text.strip().rstrip(".").strip()
    if field.kind == "enum":
        wanted = text.lower().replace(" ", "_")
        return wanted if wanted in {v.lower().replace(" ", "_") for v in field.values} else None
    if field.kind == "bool":
        return _BOOLEANS.get(text.lower())
    parsed = _number(text)
    if parsed is None:
        return None
    amount, unit = parsed
    if field.kind == "duration":
        factor = _SECONDS.get(unit)
        return amount * factor if factor else None
    allowed = {"", field.unit.lower(), field.unit.lower().rstrip("s"), "%", "usd"}
    return amount if unit in allowed else None


def parse_prediction(case: PublicCase, text: str) -> Parsed | None:
    """The decision and canonical values, or None if a decisive part is unresolved.

    Agents are prompted to use ``decision; field=value``.  The parser also accepts the harmless
    labelled variant ``decision: value`` and field labels with spaces or hyphens, because those
    are presentation differences rather than reasoning differences.  It deliberately does not
    guess an action from free prose or silently correct misspellings.
    """
    parts = [p.strip() for p in _SEPARATORS.split(text or "") if p.strip()]
    if not parts:
        return None
    vocabulary = {d.lower(): d for d in case.decisions}
    opening = parts[0].strip(" .")
    if match := _DECISION_LABEL.match(opening):
        opening = match.group(1).strip(" .")
    decision = vocabulary.get(opening.lower())
    if decision is None:
        return None
    fields = {_name(f.name): f for f in case.fields}
    raw: dict[str, str] = {}
    for part in parts[1:]:
        name, sep, value = part.partition("=")
        if not sep:
            name, sep, value = part.partition(":")
        if not sep:
            # Models occasionally say ``lag check is before``.  It is still a structured field
            # when the left side names a public field, and not an inferred value from prose.
            name, sep, value = part.partition(" is ")
        key = _name(name)
        if sep and key in fields:
            raw[key] = value
    values: dict[str, Any] = {}
    for f in case.fields:
        key = _name(f.name)
        value = _value(f, raw[key]) if key in raw else None
        if value is None and f.decisive:
            return None
        if value is not None:
            values[f.name] = value
    return Parsed(decision, values)


def canonical_prediction(case: PublicCase, text: str) -> str:
    """Return the public canonical answer key or raise a repair-friendly validation error.

    Canonicalising at the agent boundary prevents the same valid answer being stored as several
    lexical variants.  The explanation remains untouched, so evidence and reasoning are still
    available for blind human grading.
    """
    parsed = parse_prediction(case, text)
    if parsed is None:
        names = ", ".join(f.name for f in case.fields if f.decisive)
        raise ValueError(
            f"prediction must start with one public decision ({' | '.join(case.decisions)}) "
            f"and give each required field ({names}) as name=value"
        )
    parts = [parsed.decision]
    for field in case.fields:
        if field.name in parsed.values:
            parts.append(f"{field.name}={_render(field, parsed.values[field.name])}")
    return "; ".join(parts)


def _render(field: Field, value: Any) -> str:
    if field.kind == "enum":
        return next(
            (choice for choice in field.values if _name(choice) == _name(str(value))), str(value)
        )
    if field.kind == "bool":
        return "yes" if value else "no"
    number = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
    if field.kind == "duration":
        return f"{number} s"
    return f"{number}{f' {field.unit}' if field.unit else ''}"


def evidence_in_explanation(case: PublicCase, explanation: str) -> str | None:
    """Validate that a replay candidate points to public evidence, where a case has any."""
    known = {e.id.lower() for e in case.evidence}
    if not known:
        return None
    cited = {m.group(0).lower() for m in re.finditer(r"\bE\d+\b", explanation, re.I)}
    if known & cited:
        return None
    return "candidate explanation must cite at least one public evidence ID (for example E1)"


def _holds(expected: Any, actual: Any) -> bool:
    if isinstance(expected, Mapping):
        return isinstance(actual, (int, float)) and all(
            {"lt": actual < b, "gt": actual > b, "le": actual <= b, "ge": actual >= b}[op]
            for op, b in expected.items()
        )
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return math.isclose(actual, expected, abs_tol=1e-6)
    return str(actual).lower() == str(expected).lower().replace(" ", "_")


def check(case: PublicCase, grading: GradingRecord, text: str) -> Check:
    """The automatic part of grading: is the decision acceptable, and which fatal rules fire."""
    parsed = parse_prediction(case, text)
    if parsed is None:
        return Check(None, False, ())
    state = {"decision": parsed.decision, **parsed.values}
    fired = tuple(
        Violation(c.id, c.description)
        for c in grading.critical
        if all(k in state and _holds(v, state[k]) for k, v in c.when.items())
    )
    return Check(parsed, parsed.decision in grading.acceptable_decisions, fired)


def judge(
    case: PublicCase, grading: GradingRecord
) -> tuple[Callable[[str, str], bool], Callable[[str, str], bool]]:
    """(same_answer, is_correct) for an authored case, shaped like `bench.run.judging`."""

    def same(a: str, b: str) -> bool:
        pa, pb = parse_prediction(case, a), parse_prediction(case, b)
        return pa is not None and pb is not None and pa.key(case) == pb.key(case)

    def correct(prediction: str, _reference: str) -> bool:
        return check(case, grading, prediction).passed

    return same, correct
