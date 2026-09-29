"""Event schema for the blackboard log (spec section 2, "Event record")."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

SYSTEM = "system"


class Tag(StrEnum):
    INIT = "INIT"
    RATIFY = "RATIFY"
    REFUTE = "REFUTE"
    REVISE = "REVISE"
    REJECT = "REJECT"
    TERM = "TERM"


REPLY_TAGS = frozenset({Tag.RATIFY, Tag.REFUTE, Tag.REVISE, Tag.REJECT})


class Kind(StrEnum):
    MESSAGE = "message"
    ROLLBACK_START = "rollback_start"
    ROLLBACK_STEP = "rollback_step"
    ROLLBACK_END = "rollback_end"


class Tokens(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    in_: int = Field(default=0, ge=0, alias="in")
    out: int = Field(default=0, ge=0)


class EventDraft(BaseModel):
    """An event before the store assigns its `seq`."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)

    session_id: str = Field(min_length=1)
    author: str = Field(min_length=1)
    kind: Kind = Kind.MESSAGE
    tag: Tag | None = None
    reply_to: int | None = Field(default=None, ge=0)
    prediction: str = ""
    explanation: str = ""
    counterfactual: bool = False
    tokens: Tokens = Field(default_factory=Tokens)
    meta: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _field_rules(self) -> EventDraft:
        if self.kind is Kind.MESSAGE and self.tag is None:
            raise ValueError("message events need a tag")
        if self.kind is Kind.ROLLBACK_STEP and self.tag is None:
            raise ValueError("rollback_step events need a tag")
        if self.kind in (Kind.ROLLBACK_START, Kind.ROLLBACK_END) and self.tag is not None:
            raise ValueError(f"{self.kind} events carry no tag")
        if self.kind is not Kind.MESSAGE and not self.counterfactual:
            raise ValueError("rollback events must have counterfactual=true")
        return self

    def to_record(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class Event(EventDraft):
    """An event as stored in the log."""

    seq: int = Field(ge=0)

    @classmethod
    def from_draft(cls, draft: EventDraft, seq: int) -> Event:
        return cls(seq=seq, **draft.model_dump())
