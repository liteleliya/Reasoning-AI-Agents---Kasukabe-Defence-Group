"""Event-driven scheduler.

Priority arbiter, concurrency cap, stop on consensus/impasse/iteration cap (A5).
"""

from scheduler.core import (
    CAP,
    CONSENSUS,
    IMPASSE,
    Agent,
    Scheduler,
    SchedulerConfig,
    SessionResult,
    exact_consensus,
    exact_distance,
    normalise,
)
from scheduler.mock_agents import ConfusedAgent, FollowerAgent, StubbornAgent
from scheduler.recovery import (
    Opportunity,
    Recovery,
    Sidecar,
    TurnNote,
    TurnReason,
    TurnResult,
    challenged_reply,
    load_opportunities,
)

__all__ = [
    "CAP",
    "CONSENSUS",
    "IMPASSE",
    "Agent",
    "ConfusedAgent",
    "FollowerAgent",
    "Opportunity",
    "Recovery",
    "Scheduler",
    "SchedulerConfig",
    "SessionResult",
    "Sidecar",
    "StubbornAgent",
    "TurnNote",
    "TurnReason",
    "TurnResult",
    "challenged_reply",
    "exact_consensus",
    "exact_distance",
    "load_opportunities",
    "normalise",
]
