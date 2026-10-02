"""Correctness and answer-equivalence rules for MSCoRe (D2).

`is_correct` judges a session's answer against the reference; `same_answer` decides whether two
agents hold the same answer, and `consensus_fn` / `distance_fn` plug that into the scheduler.

Formats: `single_choice` (reference "B"), `multi_choice` ("A|B|D"), `judgment` ("是" / "否") and
`open_qa` (a long reference answer, judged by ROUGE-L; the threshold is decision #27).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

CHOICE_FORMATS = ("single_choice", "multi_choice")

# A letter A-H counts when no Latin letter touches it: "B", "A|C", "选 B 和 D", "(C).", "答案是B。"
_LETTER = re.compile(r"(?<![A-Za-z])[A-H](?![A-Za-z])")

_NEGATIVE = (
    "不对",
    "不正确",
    "错误",
    "否",
    "错",
    "不是",
    "false",
    "no",
    "\u00d7",
    "✗",
    "incorrect",
    "wrong",
)
_POSITIVE = ("正确", "是", "对", "true", "yes", "√", "✓", "correct", "right")
_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_WORD = re.compile(r"[a-z0-9]+")


def choice_letters(text: str) -> frozenset[str]:
    """Option letters A-H standing alone in `text` (upper case only; 'a' is an English word)."""
    return frozenset(_LETTER.findall(text or ""))


def judgment_value(text: str) -> bool | None:
    """True / False for a judgment answer, None if unclear. Negative forms are checked first,
    so '不对' is False, and a text containing both a positive and a negative cue is unclear only
    when no negative form is found."""
    t = (text or "").strip().lower()
    if not t:
        return None
    for cue in _NEGATIVE:
        if _has_cue(t, cue):
            return False
    for cue in _POSITIVE:
        if _has_cue(t, cue):
            return True
    return None


def _has_cue(text: str, cue: str) -> bool:
    if cue.isascii() and cue.isalpha():
        return re.search(rf"(?<![a-z]){re.escape(cue)}(?![a-z])", text) is not None
    return cue in text


def tokens(text: str) -> list[str]:
    """Each CJK character is a token; other text splits into lower-case words; punctuation goes."""
    out: list[str] = []
    for chunk in re.split(r"(" + _CJK.pattern + r")", (text or "").lower()):
        if not chunk:
            continue
        if _CJK.fullmatch(chunk):
            out.append(chunk)
        else:
            out.extend(_WORD.findall(chunk))
    return out


def rouge_l_f1(candidate: str, reference: str) -> float:
    """ROUGE-L F1 (beta = 1) over `tokens`; pure-Python LCS."""
    c, r = tokens(candidate), tokens(reference)
    if not c or not r:
        return 0.0
    prev = [0] * (len(r) + 1)
    for x in c:
        cur = [0] * (len(r) + 1)
        for j, y in enumerate(r, 1):
            cur[j] = prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1])
        prev = cur
    lcs = prev[-1]
    if lcs == 0:
        return 0.0
    precision, recall = lcs / len(c), lcs / len(r)
    return 2 * precision * recall / (precision + recall)


def _key_equal(fmt: str, a: str, b: str, rouge_threshold: float) -> bool:
    if fmt in CHOICE_FORMATS:
        la, lb = choice_letters(a), choice_letters(b)
        return bool(la) and la == lb
    if fmt == "judgment":
        va, vb = judgment_value(a), judgment_value(b)
        return va is not None and va == vb
    return rouge_l_f1(a, b) >= rouge_threshold


def is_correct(fmt: str, prediction: str, reference: str, *, rouge_threshold: float = 0.3) -> bool:
    """Choice: letter sets equal and non-empty; judgment: same value; open_qa: ROUGE-L >= t."""
    return _key_equal(fmt, prediction, reference, rouge_threshold)


def same_answer(fmt: str, *, rouge_threshold: float = 0.5) -> Callable[[str, str], bool]:
    """Whether two agents hold the same answer (same rules as `is_correct`)."""
    return lambda a, b: _key_equal(fmt, a, b, rouge_threshold)


def _groups(predictions: Mapping[str, str], same: Callable[[str, str], bool]) -> list[list[str]]:
    groups: list[list[str]] = []
    for agent in sorted(predictions):
        for g in groups:
            if same(predictions[g[0]], predictions[agent]):
                g.append(agent)
                break
        else:
            groups.append([agent])
    return groups


def consensus_fn(fmt: str, **kw) -> Callable[[Mapping[str, str]], bool]:
    """True when there is at least one prediction and all are pairwise the same answer."""
    same = same_answer(fmt, **kw)

    def consensus(predictions: Mapping[str, str]) -> bool:
        values = list(predictions.values())
        return (
            bool(values)
            and all(same(values[0], v) for v in values[1:])
            and same(values[0], values[0])
        )

    return consensus


def distance_fn(fmt: str, **kw) -> Callable[[Mapping[str, str]], float]:
    """1 - largest group / number of agents, grouping greedily in sorted agent order. {} -> 1.0."""
    same = same_answer(fmt, **kw)

    def distance(predictions: Mapping[str, str]) -> float:
        if not predictions:
            return 1.0
        return 1 - max(len(g) for g in _groups(predictions, same)) / len(predictions)

    return distance
