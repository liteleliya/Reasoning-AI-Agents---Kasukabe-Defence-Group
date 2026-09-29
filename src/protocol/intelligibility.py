"""Intelligibility classifier for a session log (spec section 3; paper Def. 1 and Remark 6)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from protocol.schema import REPLY_TAGS, Event, Kind, Tag


class Intelligibility(StrEnum):
    ULTRA_STRONG = "ultra_strong"
    STRONG = "strong"
    FAILED = "failed"


@dataclass(frozen=True)
class PairResult:
    """Tags sent by `sender` in reply to messages of `receiver` (T_mn with m=sender, n=receiver)."""

    sender: str
    receiver: str
    tags: tuple[Tag, ...]

    @property
    def one_way(self) -> bool:
        """Paper Def. 1: at least one RATIFY/REVISE and no REJECT. `receiver` was intelligible."""
        return any(t in (Tag.RATIFY, Tag.REVISE) for t in self.tags) and Tag.REJECT not in self.tags


@dataclass(frozen=True)
class Report:
    label: Intelligibility
    pairs: tuple[PairResult, ...]
    revises: int

    @property
    def two_way_pairs(self) -> list[tuple[str, str]]:
        """Unordered pairs that are one-way intelligible in both directions (paper Def. 2)."""
        ok = {(p.sender, p.receiver) for p in self.pairs if p.one_way}
        return sorted({tuple(sorted(pair)) for pair in ok if pair[::-1] in ok})


def counted(events: Sequence[Event]) -> list[Event]:
    """Events that count: real reply messages (no INIT/TERM, rollbacks or counterfactuals)."""
    return [
        e for e in events if e.kind is Kind.MESSAGE and not e.counterfactual and e.tag in REPLY_TAGS
    ]


def pair_tags(events: Sequence[Event]) -> tuple[PairResult, ...]:
    by_seq = {e.seq: e for e in events}
    tags: dict[tuple[str, str], list[Tag]] = {}
    for e in counted(events):
        target = by_seq.get(e.reply_to) if e.reply_to is not None else None
        if target is None or target.author == e.author:
            continue
        tags.setdefault((e.author, target.author), []).append(e.tag)  # type: ignore[arg-type]
    return tuple(PairResult(m, n, tuple(t)) for (m, n), t in sorted(tags.items()))


def classify(events: Sequence[Event]) -> Report:
    """Strong: >=1 interacting pair, all one-way intelligible. Ultra-Strong: plus a REVISE."""
    pairs = pair_tags(events)
    revises = sum(1 for e in counted(events) if e.tag is Tag.REVISE)
    if not pairs or not all(p.one_way for p in pairs):
        label = Intelligibility.FAILED
    elif revises:
        label = Intelligibility.ULTRA_STRONG
    else:
        label = Intelligibility.STRONG
    return Report(label=label, pairs=pairs, revises=revises)
