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
    normalise,
)
from scheduler.mock_agents import ConfusedAgent, FollowerAgent, StubbornAgent

__all__ = [
    "CAP",
    "CONSENSUS",
    "IMPASSE",
    "Agent",
    "ConfusedAgent",
    "FollowerAgent",
    "Scheduler",
    "SchedulerConfig",
    "SessionResult",
    "StubbornAgent",
    "exact_consensus",
    "normalise",
]
